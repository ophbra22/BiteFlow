"""Multi-user HTTP application with private journals and server-side inference."""

import asyncio
import csv
import logging
import os
import re
import secrets
import sqlite3
import threading
from datetime import datetime
from io import StringIO
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import urlsplit
from uuid import uuid4
from zoneinfo import ZoneInfo

import httpx
from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Query, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool
from starlette.middleware.trustedhost import TrustedHostMiddleware

from foodlogger.ai_gateway import AIGateway
from foodlogger.analysis_journal import AnalysisSaveConflict, save_analyzed
from foodlogger.analysis_schemas import AnalysisOptions, AnalysisResult, AnalyzedMealCreate
from foodlogger.apple_auth import AppleAuth, AppleUnavailable
from foodlogger.auth import AccountExists, AuthStore, InvalidAccountInput, InvalidCredentials
from foodlogger.classifier import Classifier, ModelUnavailable
from foodlogger.copying import Copying, CopyRequest
from foodlogger.database import Database, DatabaseUnavailable
from foodlogger.domain import MealDraft, MealLogCreate, MealLogPatch
from foodlogger.foundation import Foundation
from foodlogger.goals import GoalConflict, Goals, GoalUpdate
from foodlogger.habits import DeviceBody, HabitPreferences, Habits
from foodlogger.health import Health, HealthImport, ensure_sqlite_health
from foodlogger.health_connect import ConnectImport, HealthConnect, ensure_sqlite_health_connect
from foodlogger.images import MAX_UPLOAD_BYTES, InvalidImage, decode_image
from foodlogger.insights import Insights
from foodlogger.label_input import LabelService, LabelTextRequest, normalize_label, parse_label_text
from foodlogger.library import Favorite, Library
from foodlogger.meal_analysis import AnalysisService
from foodlogger.meal_service import MealConflict, MealService
from foodlogger.nutrition import Catalog
from foodlogger.private_products import PrivateProducts, ProductBody
from foodlogger.products import (
    InvalidBarcode,
    LookupUnavailable,
    OpenFoodFactsClient,
    ProductNotFound,
    decode_barcode,
    validate_barcode,
)
from foodlogger.recipes import RecipeBody, RecipeDuplicate, RecipePatch, Recipes
from foodlogger.recommendations import PreferenceBody, Recommendations, SourceReview
from foodlogger.schemas import (
    AccountDeletionRequest,
    AppleChallengeRequest,
    AppleDeletionRequest,
    AppleProof,
    Credentials,
    CustomMealCreate,
    JournalDate,
    MealCreate,
    RecoveryRequest,
)
from foodlogger.security import RateLimiter, Settings
from foodlogger.storage import Journal
from foodlogger.text_input import TextRequest, TextService
from foodlogger.tracking import Tracking, TrackingBody, TrackingConflict, TrackingPatch
from foodlogger.trends import Trends
from foodlogger.vision import VisionQuotaExceeded, VisionUnavailable
from foodlogger.wording import Wording, WordingRequest

logger = logging.getLogger(__name__)
PACKAGE = Path(__file__).parent
COOKIE = "foodlogger_session"
IDEMPOTENCY_KEY = re.compile(r"[A-Za-z0-9_-]{16,64}")
GIT_SHA = re.compile(r"[0-9a-fA-F]{7,40}")


def _resolve_git_head(repo_root: Path | None = None) -> str | None:
    root = repo_root or PACKAGE.parents[1]
    git_dir = root / ".git"
    head_file = git_dir / "HEAD"
    try:
        if not head_file.is_file():
            return None
        head_text = head_file.read_text(encoding="utf-8").strip()
        if head_text.startswith("ref: "):
            ref = head_text[5:].strip()
            ref_file = git_dir / ref
            if ref_file.is_file():
                candidate = ref_file.read_text(encoding="utf-8").strip()
                if GIT_SHA.fullmatch(candidate):
                    return candidate.lower()
            packed = git_dir / "packed-refs"
            if packed.is_file():
                for line in packed.read_text(encoding="utf-8").splitlines():
                    if not line or line.startswith(("#", "^")):
                        continue
                    parts = line.split(" ", 1)
                    if len(parts) == 2 and parts[1].strip() == ref and GIT_SHA.fullmatch(parts[0]):
                        return parts[0].lower()
        elif GIT_SHA.fullmatch(head_text):
            return head_text.lower()
    except OSError:
        return None
    return None


_DEFAULT_GIT_COMMIT = _resolve_git_head()


def _deployed_commit_sha() -> str | None:
    for env_key in ("RENDER_GIT_COMMIT", "FOODLOGGER_GIT_COMMIT", "GIT_COMMIT"):
        value = (os.getenv(env_key) or "").strip()
        if GIT_SHA.fullmatch(value):
            return value.lower()
    return _DEFAULT_GIT_COMMIT


def resolve_session(auth, request: Request) -> tuple[dict | None, bool]:
    """Return the session and whether it relies on an ambient browser cookie.

    Native clients send the opaque session token as ``Authorization: Bearer``.
    Browsers never attach that header on their own, so only cookie sessions
    need the CSRF token. A bearer header is never mixed with a cookie.
    """
    scheme, _, value = request.headers.get("authorization", "").partition(" ")
    if scheme:
        token = value.strip() if scheme.lower() == "bearer" else None
        return auth.get_session(token), False
    return auth.get_session(request.cookies.get(COOKIE)), True


class BodyLimitMiddleware:
    """Bound raw bodies before parsing, including requests with chunked encoding."""

    def __init__(self, app, auth=None):
        self.app = app
        self.auth = auth
        self.body_timeout = 30
        self.upload_slot = threading.BoundedSemaphore(1)

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] not in {"POST", "PUT", "PATCH"}:
            return await self.app(scope, receive, send)
        upload = scope["path"] in {
            "/api/predict",
            "/api/barcode/scan",
            "/api/analyze-meal",
            "/api/labels/extract",
        }
        if upload and self.auth is not None:
            request = Request(scope)
            try:
                session, ambient = await run_in_threadpool(resolve_session, self.auth, request)
            except DatabaseUnavailable:
                return await JSONResponse(
                    {"detail": "The journal database is temporarily unavailable."}, 503
                )(scope, receive, send)
            if not session:
                return await JSONResponse({"detail": "Sign in to access your journal."}, 401)(
                    scope, receive, send
                )
            if ambient and not secrets.compare_digest(
                request.headers.get("x-csrf-token", ""), session["csrf_token"]
            ):
                return await JSONResponse(
                    {"detail": "Your session changed. Refresh and try again."}, 403
                )(scope, receive, send)
        if upload and not self.upload_slot.acquire(blocking=False):
            response = JSONResponse(
                {"detail": "Image processing is busy. Please try again shortly."},
                429,
                headers={"Retry-After": "3"},
            )
            return await response(scope, receive, send)
        try:
            return await self.bounded_request(scope, receive, send)
        finally:
            if upload:
                self.upload_slot.release()

    async def bounded_request(self, scope, receive, send):
        limit = (
            2 * MAX_UPLOAD_BYTES + 65536
            if scope["path"] == "/api/analyze-meal"
            else (
                MAX_UPLOAD_BYTES + 65536
                if scope["path"]
                in {
                    "/api/predict",
                    "/api/barcode/scan",
                    "/api/labels/extract",
                }
                else (524288 if scope["path"] in {"/api/meals/copy", "/api/days/copy"} else 65536)
            )
        )
        chunks, total = [], 0
        try:
            async with asyncio.timeout(self.body_timeout):
                while True:
                    message = await receive()
                    if message["type"] == "http.disconnect":
                        return
                    total += len(message.get("body", b""))
                    if total > limit:
                        response = JSONResponse(
                            {"detail": "Request is too large. Photos must be under 8 MiB."}, 413
                        )
                        return await response(scope, receive, send)
                    chunks.append(message)
                    if not message.get("more_body", False):
                        break
        except TimeoutError:
            return await JSONResponse({"detail": "Upload timed out. Please try again."}, 408)(
                scope, receive, send
            )
        iterator = iter(chunks)

        async def replay():
            try:
                return next(iterator)
            except StopIteration:
                return await receive()

        await self.app(scope, replay, send)


def create_app(
    db_path: str | Path | Database | None = None,
    classifier=None,
    products=None,
    settings: Settings | None = None,
    analyzer=None,
    text_provider=None,
    label_provider=None,
    wording_provider=None,
) -> FastAPI:
    settings = settings or Settings.from_environment()
    app = FastAPI(title="FoodLogger API", version="2.1.0", description="Private food journals")
    if settings.production:
        app.add_middleware(
            TrustedHostMiddleware,
            allowed_hosts=[
                urlsplit(settings.public_url).hostname,
                "127.0.0.1",
                "localhost",
            ],
        )
    location = (
        db_path
        if db_path is not None
        else (os.getenv("DATABASE_URL") or os.getenv("FOODLOGGER_DB", "runtime/journal.sqlite3"))
    )
    if os.getenv("FOODLOGGER_PROFILE") == "free" and not (
        isinstance(location, Database)
        and location.postgres
        or str(location).startswith(("postgresql://", "postgres://"))
    ):
        raise RuntimeError("The free profile requires a PostgreSQL DATABASE_URL.")
    database = location if isinstance(location, Database) else Database(location)
    catalog, journal, auth = Catalog(), Journal(database), AuthStore(database)
    app.add_middleware(BodyLimitMiddleware, auth=auth)
    if classifier is not None:
        predictor = classifier
    elif os.getenv("FOODLOGGER_INFERENCE", "tensorflow") == "lite":
        from foodlogger.lite_classifier import LiteClassifier

        predictor = LiteClassifier(catalog, os.getenv("FOODLOGGER_LITE_MODEL"))
    elif os.getenv("FOODLOGGER_INFERENCE", "tensorflow") == "tensorflow":
        predictor = Classifier(catalog)
    else:
        raise RuntimeError("FOODLOGGER_INFERENCE must be tensorflow or lite.")
    product_client = products if products is not None else OpenFoodFactsClient()
    limiter = RateLimiter()
    image_slot = threading.BoundedSemaphore(1)
    app.state.auth = auth
    foundation = Foundation(database)
    meal_service = MealService(journal)
    library = Library(database)
    recipes = Recipes(database)
    private_products = PrivateProducts(database)
    goal_service = Goals(database)
    tracking = Tracking(database)
    ensure_sqlite_health(database)
    ensure_sqlite_health_connect(database)
    health_connect = HealthConnect(database)
    health_sync = Health(database)
    app.state.health = health_sync
    habits = Habits(database)
    app.state.habits = habits
    insights = Insights(database)
    recommendations = Recommendations(database)
    apple = AppleAuth(auth)
    app.state.apple = apple
    gateway = AIGateway(database, settings.ai_project_id, enabled=settings.ai_enabled)
    app.state.ai_gateway = gateway
    wording = Wording(gateway, wording_provider, enabled=settings.wording_enabled)
    label_service = LabelService(gateway, label_provider, enabled=settings.label_ai_enabled)
    text_service = TextService(gateway, text_provider, ai_enabled=settings.text_ai_enabled)
    meal_analyzer = analyzer if analyzer is not None else AnalysisService()
    meal_analyzer.gateway = gateway
    app.mount("/static", StaticFiles(directory=PACKAGE / "static"), name="static")

    @app.exception_handler(MealConflict)
    async def meal_conflict(request, error):
        return JSONResponse({"detail": str(error)}, 409)

    @app.exception_handler(AppleUnavailable)
    async def apple_unavailable(request, error):
        return JSONResponse({"detail": str(error)}, 503)

    @app.exception_handler(DatabaseUnavailable)
    async def database_unavailable(request, error):
        return JSONResponse(
            {"detail": "The journal database is temporarily unavailable. Please try again."},
            503,
            headers={"Retry-After": "10"},
        )

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            expected = settings.public_url or str(request.base_url).rstrip("/")
            origin = request.headers.get("origin")
            if origin and origin != expected:
                return JSONResponse({"detail": "Cross-origin requests are not allowed."}, 403)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["Permissions-Policy"] = "camera=(self), microphone=(), geolocation=()"
        if request.url.path not in {"/docs", "/redoc", "/docs/oauth2-redirect"}:
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; script-src 'self'; style-src 'self'; "
                "img-src 'self' data: blob:; connect-src 'self'; "
                "frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
            )
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        if settings.production:
            response.headers["Strict-Transport-Security"] = "max-age=31536000"
        return response

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, error):
        # Avoid echoing password inputs in validation responses.
        return JSONResponse(
            {
                "detail": "Check the supplied values.",
                "fields": [
                    {"field": ".".join(map(str, item["loc"])), "message": item["msg"]}
                    for item in error.errors()
                ],
            },
            422,
        )

    def require_user(request: Request) -> dict:
        session, ambient = resolve_session(auth, request)
        if not session:
            raise HTTPException(401, "Sign in to access your journal.")
        if (
            ambient
            and request.method not in {"GET", "HEAD", "OPTIONS"}
            and not secrets.compare_digest(
                request.headers.get("x-csrf-token", ""),
                session["csrf_token"],
            )
        ):
            raise HTTPException(403, "Your session changed. Refresh and try again.")
        return session

    def auth_request(request: Request):
        if request.headers.get("x-foodlogger-request") != "1":
            raise HTTPException(403, "Use the FoodLogger sign-in form.")
        address = settings.client_address(request)
        limiter.check("auth:" + address, 8, 60)

    def open_session(user, request, response, recovery_code=None, session_tokens=None):
        token, csrf = session_tokens or auth.create_session(user["id"])
        result = {"user": apple.flags(user), "csrf_token": csrf}
        if request.headers.get("x-foodlogger-client") == "mobile":
            # Native apps keep the token in the device keystore and send it as a
            # bearer credential; they receive no cookie.
            result["session_token"] = token
            result["expires_in"] = AuthStore.SESSION_TTL_SECONDS
        else:
            response.set_cookie(
                COOKIE,
                token,
                httponly=True,
                secure=settings.production,
                samesite="lax",
                max_age=AuthStore.SESSION_TTL_SECONDS,
                path="/",
            )
        if recovery_code:
            result["recovery_code"] = recovery_code
        return result

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(PACKAGE / "templates/index.html")

    @app.get("/api/health")
    def health():
        with journal.connect() as db:
            db.execute("SELECT 1").fetchone()
        payload = {"status": "ok", "model": predictor.name, "version": "2.1.0"}
        commit = _deployed_commit_sha()
        if commit:
            payload["commit"] = commit
        return payload

    @app.post("/api/auth/register", status_code=201)
    def register(credentials: Credentials, request: Request, response: Response):
        auth_request(request)
        address = settings.client_address(request)
        limiter.check("register:" + address, 6, 3600)
        try:
            user, recovery = auth.register(credentials.username, credentials.password)
        except AccountExists as error:
            raise HTTPException(409, str(error)) from error
        except InvalidAccountInput as error:
            raise HTTPException(422, str(error)) from error
        return open_session(user, request, response, recovery)

    @app.post("/api/auth/login")
    def login(credentials: Credentials, request: Request, response: Response):
        auth_request(request)
        limiter.check("login-user:" + credentials.username.strip().lower(), 8, 60)
        try:
            user, token, csrf = auth.authenticate_session(
                credentials.username, credentials.password
            )
        except InvalidCredentials as error:
            raise HTTPException(401, str(error)) from error
        return open_session(user, request, response, session_tokens=(token, csrf))

    @app.post("/api/auth/recover")
    def recover(payload: RecoveryRequest, request: Request, response: Response):
        auth_request(request)
        limiter.check("recovery:" + payload.username.strip().lower(), 5, 300)
        try:
            user, code = auth.recover(payload.username, payload.recovery_code, payload.new_password)
        except InvalidCredentials as error:
            raise HTTPException(401, str(error)) from error
        except InvalidAccountInput as error:
            raise HTTPException(422, str(error)) from error
        return open_session(user, request, response, code)

    @app.get("/api/auth/me")
    def me(session: Annotated[dict, Depends(require_user)]):
        return {"user": apple.flags(session["user"]), "csrf_token": session["csrf_token"]}

    @app.post("/api/auth/logout", status_code=204)
    def logout(request: Request, session: Annotated[dict, Depends(require_user)]):
        scheme, _, bearer = request.headers.get("authorization", "").partition(" ")
        auth.revoke_session(bearer.strip() if scheme else request.cookies.get(COOKIE))
        response = Response(status_code=204)
        response.delete_cookie(
            COOKIE, path="/", secure=settings.production, httponly=True, samesite="lax"
        )
        return response

    @app.delete("/api/auth/account", status_code=204)
    def delete_account(
        payload: AccountDeletionRequest,
        session: Annotated[dict, Depends(require_user)],
    ):
        user_id = session["user"]["id"]
        limiter.check("delete-account:" + user_id, 5, 300)
        try:
            auth.delete_account(
                user_id, payload.password, before_delete=apple.revoke_in_transaction
            )
        except InvalidCredentials as error:
            # This is a failed identity check, not an expired session.
            raise HTTPException(403, "Current password is incorrect.") from error
        meal_analyzer.clear_user(user_id)
        insights.cache.forget(user_id)
        wording.cache.forget(user_id)
        response = Response(status_code=204)
        response.delete_cookie(
            COOKIE, path="/", secure=settings.production, httponly=True, samesite="lax"
        )
        return response

    def apple_request(request):
        if request.headers.get("x-foodlogger-request") != "1":
            raise HTTPException(403, "Use the Biteflow sign-in form.")
        limiter.check("apple:" + settings.client_address(request), 30, 60)

    def apple_context(request, purpose):
        if purpose == "login":
            return "", None
        session = require_user(request)
        # Bind linking/deletion to the exact currently authenticated session.
        token = request.headers.get("authorization", "") or request.cookies.get(COOKIE, "")
        return token, session["user"]["id"]

    @app.post("/api/auth/apple/challenge")
    def apple_challenge(payload: AppleChallengeRequest, request: Request):
        apple_request(request)
        token, uid = apple_context(request, payload.purpose)
        return apple.challenge(payload.purpose, token, uid)

    def apple_complete(payload, request, purpose):
        apple_request(request)
        token, uid = apple_context(request, purpose)
        try:
            subject, encrypted = apple.consume(payload, purpose, token, uid)
            if purpose == "delete":
                apple.delete(uid, subject, encrypted)
                return None
            return apple.sign_in(subject, encrypted, uid)
        except InvalidCredentials as error:
            raise HTTPException(403, str(error)) from error
        except AccountExists as error:
            raise HTTPException(409, str(error)) from error

    @app.post("/api/auth/apple/login")
    def apple_login(payload: AppleProof, request: Request, response: Response):
        return open_session(apple_complete(payload, request, "login"), request, response)

    @app.post("/api/auth/apple/link")
    def apple_link(payload: AppleProof, request: Request):
        return {"user": apple.flags(apple_complete(payload, request, "link"))}

    @app.post("/api/auth/apple/delete", status_code=204)
    def apple_delete(payload: AppleDeletionRequest, request: Request):
        user_id = require_user(request)["user"]["id"]
        apple_complete(payload, request, "delete")
        meal_analyzer.clear_user(user_id)
        insights.cache.forget(user_id)
        wording.cache.forget(user_id)
        response = Response(status_code=204)
        response.delete_cookie(
            COOKIE, path="/", secure=settings.production, httponly=True, samesite="lax"
        )
        return response

    @app.get("/api/foods")
    def foods():
        return {"foods": list(catalog.foods.values()), "source": catalog.source}

    @app.get("/api/nutrition")
    def nutrition(food_id: str, grams: Annotated[float, Query(ge=1, le=2000, allow_inf_nan=False)]):
        try:
            return catalog.estimate(food_id, grams)
        except KeyError as error:
            raise HTTPException(404, "Food is not in the nutrition catalog.") from error

    @app.post("/api/predict")
    async def predict(
        file: Annotated[UploadFile, File()], session: Annotated[dict, Depends(require_user)]
    ):
        limiter.check("predict:" + session["user"]["id"], 12, 60)
        if not image_slot.acquire(blocking=False):
            raise HTTPException(
                429,
                "Image processing is busy. Please try again shortly.",
                headers={"Retry-After": "3"},
            )
        image = None
        try:
            data = await file.read(MAX_UPLOAD_BYTES + 1)
            image = await run_in_threadpool(decode_image, data)
            return await run_in_threadpool(predictor.predict, image)
        except InvalidImage as error:
            raise HTTPException(422, str(error)) from error
        except ModelUnavailable:
            logger.warning("Classifier unavailable")
            raise HTTPException(
                503, "Image recognition is unavailable. Manual logging still works."
            ) from None
        finally:
            if image is not None:
                image.close()
            image_slot.release()
            await file.close()

    @app.get("/api/food-sources")
    def food_sources(
        session: Annotated[dict, Depends(require_user)],
        q: str = Query(min_length=1, max_length=160),
        barcode: str | None = None,
    ):
        if not settings.food_sources_enabled:
            raise HTTPException(503, "Additional food sources are disabled.")
        limiter.check("sources:" + session["user"]["id"], 20, 60)
        limiter.check("lookup:global", 90, 60)
        from foodlogger.food_providers import FoodProviders

        try:
            result = FoodProviders(products=product_client).search(q, barcode)
            result["private_products"] = (
                private_products.list(session["user"]["id"], q)
                if settings.private_products_enabled and private_products.available()
                else []
            )
            return result
        except InvalidBarcode as error:
            raise HTTPException(422, str(error)) from error

    @app.get("/api/servings")
    def serving_options(
        session: Annotated[dict, Depends(require_user)],
        food_id: str = Query(min_length=1, max_length=160),
        version: str = Query(min_length=1, max_length=80),
    ):
        if not settings.servings_enabled:
            raise HTTPException(503, "Household conversions are disabled.")
        limiter.check("servings:" + session["user"]["id"], 60, 60)
        from foodlogger.servings import Servings

        return {"conversions": Servings(database).list(food_id, version)}

    @app.get("/api/products/{barcode}")
    def product(barcode: str, session: Annotated[dict, Depends(require_user)]):
        limiter.check("lookup:" + session["user"]["id"], 20, 60)
        limiter.check("lookup:global", 90, 60)
        try:
            return product_client.lookup(barcode)
        except InvalidBarcode as error:
            raise HTTPException(422, str(error)) from error
        except ProductNotFound as error:
            raise HTTPException(
                404, "Product not found. You can enter its nutrition label manually."
            ) from error
        except LookupUnavailable as error:
            raise HTTPException(
                503,
                "Product lookup is temporarily unavailable. Enter the label manually or try again.",
            ) from error

    @app.get("/api/capabilities")
    def capabilities(session: Annotated[dict, Depends(require_user)]):
        from foodlogger.partial_migration import partial_storage_ready

        ready = foundation.ready_for_owner(session["user"]["id"])
        partial_ready = ready and settings.canonical_writes and partial_storage_ready(database)
        ai_photo = False
        if gateway.available():
            try:
                policy = gateway.policy()
                gateway._ready(policy, gateway.now())
                ai_photo = (meal_analyzer.provider.name, meal_analyzer.provider.model) == (
                    policy.provider,
                    policy.model,
                )
            except VisionUnavailable:
                pass
        return {
            "schema_versions": [1, 2],
            "basis_correction_provenance": True,
            "food_sources": settings.food_sources_enabled,
            "servings": settings.servings_enabled,
            "label_ocr": settings.label_ai_enabled and gateway.available(),
            "private_products": settings.private_products_enabled and private_products.available(),
            "canonical_reads": ready,
            "canonical_writes": ready and settings.canonical_writes,
            "partial_core_writes": partial_ready,
            "tiny_portion_writes": partial_ready,
            "ai_photo": ai_photo,
            "text": True,
            "text_ai": settings.text_ai_enabled and settings.ai_enabled,
            "copy": settings.copy_enabled
            and settings.canonical_writes
            and partial_ready
            and ready
            and Copying(meal_service).available(),
            "recipes": settings.library_enabled and ready and recipes.available(),
            "recipe_writes": settings.library_enabled
            and settings.recipe_writes
            and ready
            and recipes.available(),
            "library": settings.library_enabled and ready and library.available(),
            "habits": settings.habits_enabled and habits.available(),
            "health": settings.health_enabled
            and health_sync.available()
            and settings.tracking_enabled
            and settings.tracking_writes,
            "health_connect": settings.health_connect_enabled
            and health_connect.available()
            and health_sync.available()
            and settings.tracking_enabled
            and settings.tracking_writes,
            "tracking": settings.tracking_enabled and tracking.available(),
            "tracking_writes": settings.tracking_enabled
            and settings.tracking_writes
            and tracking.available(),
            "wording": settings.wording_enabled and gateway.available(),
            "recommendations": settings.recommendations_enabled and recommendations.available(),
            "recommendation_writes": settings.recommendations_enabled
            and settings.recommendation_writes
            and recommendations.available(),
            "insights": settings.insights_enabled
            and tracking.available()
            and goal_service.available(),
            "trends": settings.trends_enabled and tracking.available() and goal_service.available(),
            "goals": settings.goals_enabled and goal_service.available(),
        }

    def private_products_ready():
        if not settings.private_products_enabled or not private_products.available():
            raise HTTPException(503, "Private products are disabled or need migration.")

    @app.get("/api/private-products")
    def list_private_products(
        session: Annotated[dict, Depends(require_user)], q: str = Query(default="", max_length=120)
    ):
        private_products_ready()
        return {"products": private_products.list(session["user"]["id"], q)}

    @app.get("/api/private-products/{identity}")
    def get_private_product(
        identity: str,
        session: Annotated[dict, Depends(require_user)],
        version: int | None = Query(default=None, ge=1),
    ):
        private_products_ready()
        try:
            return private_products.get(session["user"]["id"], identity, version)
        except KeyError:
            raise HTTPException(404, "Private product not found.") from None

    @app.put("/api/private-products/{identity}", status_code=201)
    def save_private_product(
        identity: str,
        payload: ProductBody,
        response: Response,
        session: Annotated[dict, Depends(require_user)],
        idempotency_key: Annotated[str | None, Header()] = None,
    ):
        private_products_ready()
        owner = session["user"]["id"]
        limiter.check("private-products:" + owner, 30, 60)
        try:
            result, created = private_products.save(owner, identity, payload, idempotency_key or "")
            if not created:
                response.status_code = 200
            return result
        except KeyError:
            raise HTTPException(404, "Private product not found.") from None
        except ValueError as error:
            raise HTTPException(422, str(error)) from None

    @app.delete("/api/private-products/{identity}", status_code=204)
    def delete_private_product(
        identity: str,
        session: Annotated[dict, Depends(require_user)],
        expected_version: int = Query(ge=1),
    ):
        private_products_ready()
        try:
            private_products.delete(session["user"]["id"], identity, expected_version)
        except KeyError:
            raise HTTPException(404, "Private product not found.") from None

    @app.post("/api/labels/parse")
    def parse_label(payload: LabelTextRequest, session: Annotated[dict, Depends(require_user)]):
        limiter.check("labels:" + session["user"]["id"], 30, 60)
        try:
            return normalize_label(parse_label_text(payload.text, payload.barcode))
        except ValueError as error:
            raise HTTPException(422, str(error)) from None

    @app.post("/api/labels/extract")
    async def extract_label(
        file: Annotated[UploadFile, File()],
        session: Annotated[dict, Depends(require_user)],
        language: Annotated[str, Form()] = "en",
        idempotency_key: Annotated[str | None, Header()] = None,
    ):
        image = None
        acquired = False
        try:
            if not settings.label_ai_enabled:
                raise HTTPException(503, "Label OCR is disabled. Enter the label manually.")
            if language not in {"en", "he"} or not IDEMPOTENCY_KEY.fullmatch(idempotency_key or ""):
                raise HTTPException(422, "Use en/he and a stable label request key.")
            limiter.check("ocr:" + session["user"]["id"], 12, 60)
            acquired = image_slot.acquire(blocking=False)
            if not acquired:
                raise HTTPException(429, "Image processing is busy.")
            image = await run_in_threadpool(decode_image, await file.read(MAX_UPLOAD_BYTES + 1))
            from io import BytesIO

            def encode_label():
                image.thumbnail((2048, 2048))
                output = BytesIO()
                image.save(output, format="JPEG", quality=90)
                return output.getvalue()

            data = await run_in_threadpool(encode_label)
            import hashlib

            fingerprint = hashlib.sha256(b"label-v1:" + language.encode() + data).hexdigest()
            owner = session["user"]["id"]
            cache_ready = private_products.available()
            cached = (
                await run_in_threadpool(private_products.cache_get, owner, fingerprint)
                if cache_ready
                else None
            )
            if cached is not None:
                return {**cached, "cached": True}
            result = await run_in_threadpool(
                label_service.extract, data, language, owner, idempotency_key
            )
            if cache_ready:
                await run_in_threadpool(private_products.cache_put, owner, fingerprint, result)
            return {**result, "cached": False}
        except (InvalidImage, ValueError) as error:
            raise HTTPException(
                422, "The label could not be read. Enter or correct it manually."
            ) from error
        except VisionQuotaExceeded as error:
            raise HTTPException(429, "Label allowance exhausted. Enter it manually.") from error
        except (VisionUnavailable, httpx.HTTPError, KeyError, TypeError) as error:
            raise HTTPException(
                503, "Label extraction is unavailable. Enter it manually."
            ) from error
        finally:
            if image is not None:
                image.close()
            if acquired:
                image_slot.release()
            await file.close()

    @app.post("/api/analyze-text")
    def analyze_text(
        payload: TextRequest,
        session: Annotated[dict, Depends(require_user)],
        idempotency_key: Annotated[str | None, Header()] = None,
    ):
        owner = session["user"]["id"]
        limiter.check("text:" + owner, 30, 60)
        if payload.allow_ai and not IDEMPOTENCY_KEY.fullmatch(idempotency_key or ""):
            raise HTTPException(422, "A stable analysis request key is required.")
        try:
            return text_service.analyze(payload, owner, idempotency_key)
        except ValueError as error:
            raise HTTPException(422, str(error)) from None

    def library_ready(owner):
        if (
            not settings.library_enabled
            or not foundation.ready_for_owner(owner)
            or not library.available()
        ):
            raise HTTPException(503, "Library is not enabled on this server.")

    @app.get("/api/recents")
    @app.get("/api/favorites")
    def list_library(
        request: Request,
        session: Annotated[dict, Depends(require_user)],
        query: Annotated[str, Query(max_length=120)] = "",
        limit: Annotated[int, Query(ge=1, le=20)] = 20,
        offset: Annotated[int, Query(ge=0, le=100000)] = 0,
    ):
        owner = session["user"]["id"]
        library_ready(owner)
        return library.list(
            owner,
            favorites=request.url.path.endswith("favorites"),
            query=query,
            limit=limit,
            offset=offset,
        )

    @app.post("/api/favorites")
    def favorite(payload: Favorite, session: Annotated[dict, Depends(require_user)]):
        owner = session["user"]["id"]
        library_ready(owner)
        limiter.check("write:" + owner, 60, 60)
        try:
            return library.favorite(owner, payload)
        except KeyError:
            raise HTTPException(404, "Source no longer exists.") from None

    @app.delete("/api/favorites/{kind}/{identity}", status_code=204)
    def unfavorite(kind: str, identity: str, session: Annotated[dict, Depends(require_user)]):
        owner = session["user"]["id"]
        library_ready(owner)
        limiter.check("write:" + owner, 60, 60)
        library.unfavorite(owner, kind, identity)
        return Response(status_code=204)

    def recipes_ready(owner, write=False):
        library_ready(owner)
        if not recipes.available() or (write and not settings.recipe_writes):
            raise HTTPException(503, "Recipe editing is not enabled on this server.")
        if write:
            limiter.check("write:" + owner, 60, 60)

    def recipe_call(action):
        try:
            return action()
        except KeyError:
            raise HTTPException(404, "Recipe no longer exists.") from None
        except MealConflict:
            raise
        except ValueError as error:
            raise HTTPException(422, str(error)) from None

    @app.get("/api/saved-recipes")
    def recipe_list(
        session: Annotated[dict, Depends(require_user)],
        query: Annotated[str, Query(max_length=120)] = "",
        limit: Annotated[int, Query(ge=1, le=20)] = 20,
        offset: Annotated[int, Query(ge=0, le=100000)] = 0,
    ):
        owner = session["user"]["id"]
        recipes_ready(owner)
        return recipes.list(owner, query, limit, offset)

    @app.post("/api/saved-recipes", status_code=201)
    def recipe_create(
        payload: RecipeBody,
        response: Response,
        session: Annotated[dict, Depends(require_user)],
        idempotency_key: Annotated[str | None, Header()] = None,
    ):
        owner = session["user"]["id"]
        recipes_ready(owner, True)
        recipe, created = recipe_call(lambda: recipes.create(owner, payload, idempotency_key))
        if not created:
            response.status_code = 200
        return recipe

    @app.get("/api/saved-recipes/{identity}/versions")
    def recipe_versions(identity: str, session: Annotated[dict, Depends(require_user)]):
        owner = session["user"]["id"]
        recipes_ready(owner)
        return recipe_call(lambda: recipes.versions(owner, identity))

    @app.get("/api/saved-recipes/{identity}")
    def recipe_get(identity: str, session: Annotated[dict, Depends(require_user)]):
        owner = session["user"]["id"]
        recipes_ready(owner)
        return recipe_call(lambda: recipes.get(owner, identity))

    @app.patch("/api/saved-recipes/{identity}")
    def recipe_patch(
        identity: str, payload: RecipePatch, session: Annotated[dict, Depends(require_user)]
    ):
        owner = session["user"]["id"]
        recipes_ready(owner, True)
        return recipe_call(lambda: recipes.patch(owner, identity, payload))

    @app.post("/api/saved-recipes/{identity}/duplicate", status_code=201)
    def recipe_duplicate(
        identity: str,
        payload: RecipeDuplicate,
        response: Response,
        session: Annotated[dict, Depends(require_user)],
        idempotency_key: Annotated[str | None, Header()] = None,
    ):
        owner = session["user"]["id"]
        recipes_ready(owner, True)
        recipe, created = recipe_call(
            lambda: recipes.duplicate(owner, identity, payload, idempotency_key)
        )
        if not created:
            response.status_code = 200
        return recipe

    @app.delete("/api/saved-recipes/{identity}", status_code=204)
    def recipe_delete(
        identity: str,
        expected_version: Annotated[int, Query(ge=1)],
        session: Annotated[dict, Depends(require_user)],
    ):
        owner = session["user"]["id"]
        recipes_ready(owner, True)
        recipe_call(lambda: recipes.delete(owner, identity, expected_version))
        return Response(status_code=204)

    def health_ready():
        if (
            not settings.health_enabled
            or not health_sync.available()
            or not settings.tracking_enabled
            or not settings.tracking_writes
        ):
            raise HTTPException(503, "Health sync unavailable.")

    @app.post("/api/health/reconcile")
    def health_reconcile(session: Annotated[dict, Depends(require_user)]):
        health_ready()
        return recipe_call(lambda: health_sync.reconcile(session["user"]["id"]))

    @app.post("/api/health/import")
    def health_import(payload: HealthImport, session: Annotated[dict, Depends(require_user)]):
        health_ready()
        return recipe_call(lambda: health_sync.import_samples(session["user"]["id"], payload))

    @app.get("/api/health/imports")
    def health_imports(session: Annotated[dict, Depends(require_user)]):
        health_ready()
        return health_sync.imports(session["user"]["id"])

    def health_connect_ready():
        if (
            not settings.health_connect_enabled
            or not health_connect.available()
            or not health_sync.available()
            or not settings.tracking_enabled
            or not settings.tracking_writes
        ):
            raise HTTPException(503, "Health Connect unavailable.")

    @app.post("/api/health-connect/reconcile")
    def connect_reconcile(session: Annotated[dict, Depends(require_user)]):
        health_connect_ready()
        return recipe_call(lambda: health_sync.reconcile(session["user"]["id"]))

    @app.post("/api/health-connect/import")
    def connect_import(payload: ConnectImport, session: Annotated[dict, Depends(require_user)]):
        health_connect_ready()
        return recipe_call(lambda: health_connect.import_changes(session["user"]["id"], payload))

    @app.get("/api/health-connect/imports")
    def connect_imports(session: Annotated[dict, Depends(require_user)]):
        health_connect_ready()
        return health_connect.imports(session["user"]["id"])

    def habits_ready():
        if not settings.habits_enabled or not habits.available():
            raise HTTPException(503, "Reminders are unavailable.")

    @app.get("/api/habits")
    def get_habits(session: Annotated[dict, Depends(require_user)], timezone_id: str = "UTC"):
        habits_ready()
        try:
            zone = HabitPreferences(expected_version=0, timezone_id=timezone_id).timezone_id
        except ValueError:
            raise HTTPException(422, "Use an IANA timezone.") from None
        owner = session["user"]["id"]
        return {
            "preferences": habits.preferences(owner),
            "streak": habits.streak(owner, datetime.now(ZoneInfo(zone)).date()),
        }

    @app.put("/api/habits/preferences")
    def put_habits(payload: HabitPreferences, session: Annotated[dict, Depends(require_user)]):
        habits_ready()
        return recipe_call(lambda: habits.put_preferences(session["user"]["id"], payload))

    def bearer_token(request):
        scheme, _, token = request.headers.get("authorization", "").partition(" ")
        if scheme.lower() != "bearer":
            raise HTTPException(422, "Device registration requires a mobile bearer session.")
        return token.strip()

    @app.put("/api/habits/device")
    def put_reminder_device(
        payload: DeviceBody, request: Request, session: Annotated[dict, Depends(require_user)]
    ):
        habits_ready()
        owner = session["user"]["id"]
        limiter.check("reminder-device:" + owner, 30, 60)
        return recipe_call(lambda: habits.register(owner, bearer_token(request), payload))

    @app.post("/api/habits/device/pause", status_code=204)
    def pause_reminder_device(request: Request, session: Annotated[dict, Depends(require_user)]):
        if habits.available():
            habits.pause(session["user"]["id"], bearer_token(request))
        return Response(status_code=204)

    @app.delete("/api/habits/device", status_code=204)
    def delete_reminder_device(request: Request, session: Annotated[dict, Depends(require_user)]):
        # Revocation remains available while the feature is paused.
        if habits.available():
            habits.unregister(session["user"]["id"], bearer_token(request))
        return Response(status_code=204)

    def tracking_ready(write=False):
        if (
            not settings.tracking_enabled
            or not tracking.available()
            or (write and not settings.tracking_writes)
        ):
            raise HTTPException(503, "Tracking is disabled or needs migration.")

    def tracking_call(operation):
        try:
            return operation()
        except TrackingConflict as error:
            raise HTTPException(409, str(error)) from None
        except KeyError:
            raise HTTPException(404, "Measurement not found.") from None
        except ValueError as error:
            raise HTTPException(422, str(error)) from None

    # Separate explicit routes preserve the existing API namespace.
    def register_tracking_routes(kind):
        def list_entries(
            session: Annotated[dict, Depends(require_user)],
            start: Annotated[JournalDate, Query(alias="from")],
            end: Annotated[JournalDate, Query(alias="to")],
            limit: int = Query(default=100, ge=1, le=100),
            offset: int = Query(default=0, ge=0, le=100000),
        ):
            tracking_ready()
            return tracking_call(
                lambda: tracking.list(session["user"]["id"], kind, start, end, limit, offset)
            )

        def create_entry(
            payload: TrackingBody,
            response: Response,
            session: Annotated[dict, Depends(require_user)],
            idempotency_key: Annotated[str, Header(min_length=8, max_length=160)],
        ):
            tracking_ready(True)
            if payload.source != "manual":
                raise HTTPException(422, "Health import is not enabled.")
            limiter.check("write:" + session["user"]["id"], 60, 60)
            row, created = tracking_call(
                lambda: tracking.create(session["user"]["id"], kind, payload, idempotency_key)
            )
            response.status_code = 201 if created else 200
            return row

        def patch_entry(
            identity: str, payload: TrackingPatch, session: Annotated[dict, Depends(require_user)]
        ):
            tracking_ready(True)
            if payload.source != "manual":
                raise HTTPException(422, "Health import is not enabled.")
            limiter.check("write:" + session["user"]["id"], 60, 60)
            return tracking_call(
                lambda: tracking.patch(session["user"]["id"], kind, identity, payload)
            )

        def delete_entry(
            identity: str,
            expected_version: Annotated[int, Query(ge=1)],
            session: Annotated[dict, Depends(require_user)],
        ):
            tracking_ready(True)
            limiter.check("write:" + session["user"]["id"], 60, 60)
            tracking_call(
                lambda: tracking.delete(session["user"]["id"], kind, identity, expected_version)
            )
            return Response(status_code=204)

        app.add_api_route("/api/" + kind, list_entries, methods=["GET"], name=kind + "_list")
        app.add_api_route("/api/" + kind, create_entry, methods=["POST"], name=kind + "_create")
        app.add_api_route(
            "/api/" + kind + "/{identity}", patch_entry, methods=["PATCH"], name=kind + "_patch"
        )
        app.add_api_route(
            "/api/" + kind + "/{identity}", delete_entry, methods=["DELETE"], name=kind + "_delete"
        )

    register_tracking_routes("water")
    register_tracking_routes("weight")

    @app.get("/api/trends")
    def get_trends(
        session: Annotated[dict, Depends(require_user)],
        start: Annotated[JournalDate, Query(alias="from")],
        end: Annotated[JournalDate, Query(alias="to")],
    ):
        if not settings.trends_enabled or not tracking.available() or not goal_service.available():
            raise HTTPException(503, "Trends are disabled or need migration.")
        return tracking_call(lambda: Trends(database).get(session["user"]["id"], start, end))

    @app.get("/api/insights")
    def get_insights(
        week_start: JournalDate,
        session: Annotated[dict, Depends(require_user)],
        language: Literal["en", "he"] = "en",
    ):
        if (
            not settings.insights_enabled
            or not tracking.available()
            or not goal_service.available()
        ):
            raise HTTPException(503, "Insights are disabled or need migration.")
        return tracking_call(lambda: insights.get(session["user"]["id"], week_start, language))

    def recommendations_ready(write=False):
        if (
            not settings.recommendations_enabled
            or not recommendations.available()
            or (write and not settings.recommendation_writes)
        ):
            raise HTTPException(503, "Recommendations are disabled or need migration.")

    @app.get("/api/recommendation-preferences")
    def recommendation_preferences(session: Annotated[dict, Depends(require_user)]):
        recommendations_ready()
        return recommendations.preferences(session["user"]["id"])

    @app.put("/api/recommendation-preferences")
    def put_recommendation_preferences(
        payload: PreferenceBody, session: Annotated[dict, Depends(require_user)]
    ):
        recommendations_ready(True)
        owner = session["user"]["id"]
        limiter.check("write:" + owner, 60, 60)
        return recipe_call(lambda: recommendations.put_preferences(owner, payload))

    @app.delete("/api/recommendation-preferences")
    def clear_recommendation_preferences(
        expected_version: Annotated[int, Query(ge=0)],
        session: Annotated[dict, Depends(require_user)],
    ):
        recommendations_ready(True)
        owner = session["user"]["id"]
        limiter.check("write:" + owner, 60, 60)
        result = recipe_call(
            lambda: recommendations.put_preferences(
                owner, PreferenceBody(expected_version=expected_version), clear=True
            )
        )
        wording.cache.forget(owner)
        return result

    @app.get("/api/recommendation-sources")
    def recommendation_sources(session: Annotated[dict, Depends(require_user)]):
        recommendations_ready()
        return recommendations.sources(session["user"]["id"])

    @app.put("/api/recommendation-sources/{kind}/{identity}")
    def put_recommendation_source(
        kind: Literal["meal", "recipe"],
        identity: str,
        payload: SourceReview,
        session: Annotated[dict, Depends(require_user)],
    ):
        recommendations_ready(True)
        owner = session["user"]["id"]
        limiter.check("write:" + owner, 60, 60)
        return recipe_call(lambda: recommendations.put_review(owner, kind, identity, payload))

    @app.get("/api/recommendations")
    def get_recommendations(
        day: JournalDate,
        session: Annotated[dict, Depends(require_user)],
        language: Literal["en", "he"] = "en",
    ):
        recommendations_ready()
        return recipe_call(lambda: recommendations.get(session["user"]["id"], day, language))

    @app.post("/api/wording/{feature}")
    def optional_wording(
        feature: Literal["insight", "recommendation"],
        payload: WordingRequest,
        session: Annotated[dict, Depends(require_user)],
        idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
    ):
        owner = session["user"]["id"]
        if not IDEMPOTENCY_KEY.fullmatch(idempotency_key):
            raise HTTPException(422, "Invalid wording request key.")
        limiter.check("wording:" + owner, 12, 60)
        if feature == "insight":
            if (
                not settings.insights_enabled
                or not tracking.available()
                or not goal_service.available()
            ):
                raise HTTPException(503, "Insights are disabled or need migration.")
            document = tracking_call(lambda: insights.get(owner, payload.date, payload.language))
        else:
            recommendations_ready()
            document = recipe_call(
                lambda: recommendations.get(owner, payload.date, payload.language)
            )
        if document["revision"] != payload.expected_revision:
            raise HTTPException(409, "Data changed. Refresh before wording.")
        return wording.enhance(owner, feature, idempotency_key, document)

    def goals_ready():
        if not settings.goals_enabled or not goal_service.available():
            raise HTTPException(503, "Goals are not enabled on this server.")

    @app.get("/api/goals")
    def get_goals(session: Annotated[dict, Depends(require_user)]):
        goals_ready()
        return goal_service.get(session["user"]["id"])

    @app.put("/api/goals")
    def put_goals(payload: GoalUpdate, session: Annotated[dict, Depends(require_user)]):
        goals_ready()
        limiter.check("write:" + session["user"]["id"], 60, 60)
        try:
            return goal_service.put(session["user"]["id"], payload)
        except GoalConflict as error:
            raise HTTPException(409, str(error)) from None

    @app.get("/api/daily-summary")
    def daily_summary(date: JournalDate, session: Annotated[dict, Depends(require_user)]):
        goals_ready()
        return goal_service.daily(session["user"]["id"], date)

    @app.get("/api/admin/ai-budget")
    def ai_budget(session: Annotated[dict, Depends(require_user)]):
        if session["user"]["id"] not in settings.admin_user_ids:
            raise HTTPException(403, "Administrator access is required.")
        if gateway.available():
            try:
                return {"configured": True, **gateway.summary()}
            except VisionUnavailable:
                pass
        return {"configured": False, "enabled": False}

    @app.get("/api/analysis/references")
    def analysis_references(
        q: Annotated[str, Query(min_length=2, max_length=160)],
        session: Annotated[dict, Depends(require_user)],
    ):
        limiter.check("reference:" + session["user"]["id"], 60, 60)
        return {"foods": meal_analyzer.references.search(q, limit=8)}

    @app.post("/api/analyze-meal", response_model=AnalysisResult)
    async def analyze_meal(
        file: Annotated[UploadFile, File()],
        session: Annotated[dict, Depends(require_user)],
        second_file: Annotated[UploadFile | None, File()] = None,
        options: Annotated[str, Form(max_length=2048)] = "{}",
        idempotency_key: Annotated[str | None, Header()] = None,
    ):
        uploads = [file] + ([second_file] if second_file is not None else [])
        acquired = False
        try:
            if not idempotency_key or not IDEMPOTENCY_KEY.fullmatch(idempotency_key):
                raise HTTPException(422, "Provide a valid Idempotency-Key for meal analysis.")
            parsed = AnalysisOptions.model_validate_json(options)
            limiter.check("analyze:" + session["user"]["id"], 6, 60)
            acquired = image_slot.acquire(blocking=False)
            if not acquired:
                raise HTTPException(429, "Image processing is busy.", headers={"Retry-After": "3"})
            data = [await upload.read(MAX_UPLOAD_BYTES + 1) for upload in uploads]
            return await run_in_threadpool(
                meal_analyzer.analyze, data, parsed, session["user"]["id"], idempotency_key
            )
        except (InvalidImage, ValidationError) as error:
            raise HTTPException(422, "Check photo format, size and analysis options.") from error
        except VisionQuotaExceeded as error:
            raise HTTPException(429, str(error), headers={"Retry-After": "60"}) from None
        except VisionUnavailable as error:
            # Never log provider responses, user images or API credentials.
            raise HTTPException(503, str(error)) from None
        except ValueError as error:
            raise HTTPException(409, "This analysis key was used for different content.") from error
        finally:
            if acquired:
                image_slot.release()
            for upload in uploads:
                await upload.close()

    @app.post("/api/meals/analyzed", status_code=201)
    def analyzed_meal(
        payload: AnalyzedMealCreate,
        response: Response,
        session: Annotated[dict, Depends(require_user)],
        idempotency_key: Annotated[str | None, Header()] = None,
    ):
        if not idempotency_key or not IDEMPOTENCY_KEY.fullmatch(idempotency_key):
            raise HTTPException(422, "Provide a valid Idempotency-Key for the meal.")
        user_id = session["user"]["id"]
        limiter.check("write:" + user_id, 60, 60)
        try:
            saved, created = save_analyzed(
                journal, payload, meal_analyzer.references, user_id, idempotency_key
            )
        except AnalysisSaveConflict as error:
            raise HTTPException(409, str(error)) from error
        except (ValueError, KeyError) as error:
            raise HTTPException(
                422, "Choose valid nutrition records and confirm each food."
            ) from error
        if not created:
            response.status_code = 200
        return {"meals": saved}

    @app.post("/api/barcode/scan")
    async def scan_barcode(
        file: Annotated[UploadFile, File()], session: Annotated[dict, Depends(require_user)]
    ):
        limiter.check("scan:" + session["user"]["id"], 20, 60)
        if not image_slot.acquire(blocking=False):
            raise HTTPException(
                429,
                "Image processing is busy. Please try again shortly.",
                headers={"Retry-After": "3"},
            )
        image = None
        try:
            image = await run_in_threadpool(decode_image, await file.read(MAX_UPLOAD_BYTES + 1))
            barcode = await run_in_threadpool(decode_barcode, image)
            return {"barcode": barcode}
        except (InvalidImage, InvalidBarcode) as error:
            raise HTTPException(422, str(error)) from error
        finally:
            if image is not None:
                image.close()
            image_slot.release()
            await file.close()

    def save_once(response: Response, user_id: str, key: str | None, prepare):
        if key is not None and not IDEMPOTENCY_KEY.fullmatch(key):
            raise HTTPException(422, "Idempotency-Key must be 16–64 URL-safe characters.")
        key = key or uuid4().hex
        entry = prepare(key)
        if foundation.available():
            saved, created = meal_service.save_entries([entry], user_id, key, None, "legacy")
            if not created:
                response.status_code = 200
            return saved[0]
        # Compatibility with pre-foundation PostgreSQL; activation requires its migration.
        try:
            journal._insert(entry, user_id)
            return entry
        except sqlite3.IntegrityError:
            existing = journal.get_by_request(key, user_id=user_id)
            if existing is None:
                raise
            response.status_code = 200
            return existing

    @app.post("/api/meals", status_code=201)
    def add_meal(
        meal: MealCreate,
        response: Response,
        session: Annotated[dict, Depends(require_user)],
        idempotency_key: Annotated[str | None, Header()] = None,
    ):
        user_id = session["user"]["id"]
        limiter.check("write:" + user_id, 60, 60)
        try:
            return save_once(
                response,
                user_id,
                idempotency_key,
                lambda key: journal.prepare_catalog(
                    meal, catalog, user_id=user_id, request_key=key
                ),
            )
        except KeyError as error:
            raise HTTPException(404, "Choose a food from the catalog.") from error

    @app.post("/api/meals/custom", status_code=201)
    def custom_meal(
        meal: CustomMealCreate,
        response: Response,
        session: Annotated[dict, Depends(require_user)],
        idempotency_key: Annotated[str | None, Header()] = None,
    ):
        user_id = session["user"]["id"]
        limiter.check("write:" + user_id, 60, 60)
        if meal.barcode:
            try:
                validate_barcode(meal.barcode)
            except InvalidBarcode as error:
                raise HTTPException(422, str(error)) from error
        return save_once(
            response,
            user_id,
            idempotency_key,
            lambda key: journal.prepare_custom(meal, user_id=user_id, request_key=key),
        )

    def canonical_ready(owner, write=False):
        if not foundation.ready_for_owner(owner) or (write and not settings.canonical_writes):
            raise HTTPException(503, "Canonical journal is disabled or its backfill is incomplete.")

    @app.get("/api/copy-sources")
    def copy_sources(day: JournalDate, session: Annotated[dict, Depends(require_user)]):
        owner = session["user"]["id"]
        canonical_ready(owner)
        if not settings.copy_enabled:
            raise HTTPException(503, "Copy is not enabled on this server.")
        with database.connect() as db:
            from foodlogger.foundation import lock_owner

            lock_owner(database, db, owner)
            groups = db.execute(
                "SELECT * FROM meal_groups WHERE user_id=? AND local_date=? "
                "AND deleted_at IS NULL ORDER BY id",
                (owner, str(day)),
            ).fetchall()
            items = []
            for raw in groups:
                group = foundation.public(raw)
                item = library.meal(db, owner, group["id"])
                item.update(
                    favorite=False, entry_ids=[m["id"] for m in group["snapshot"].get("meals", [])]
                )
                items.append(item)
            return {"items": items}

    @app.post("/api/meals/copy")
    @app.post("/api/days/copy")
    def copy_logs(
        payload: CopyRequest,
        response: Response,
        session: Annotated[dict, Depends(require_user)],
        idempotency_key: Annotated[str | None, Header()] = None,
    ):
        owner = session["user"]["id"]
        canonical_ready(owner, write=True)
        from foodlogger.partial_migration import partial_storage_ready

        copying = Copying(meal_service)
        if (
            not settings.copy_enabled
            or not copying.available()
            or not partial_storage_ready(journal.database)
        ):
            raise HTTPException(503, "Copy is not enabled on this server.")
        limiter.check("write:" + owner, 60, 60)
        try:
            result, created = copying.run(owner, payload, idempotency_key)
            response.status_code = 201 if created else 200
            return result
        except MealConflict:
            raise
        except KeyError:
            raise HTTPException(404, "A selected meal no longer exists.") from None
        except ValueError as error:
            raise HTTPException(422, str(error)) from None

    @app.post("/api/meal-logs", status_code=201)
    def create_log(
        payload: MealLogCreate,
        response: Response,
        session: Annotated[dict, Depends(require_user)],
        idempotency_key: Annotated[str | None, Header()] = None,
    ):
        canonical_ready(session["user"]["id"], write=True)
        owner = session["user"]["id"]
        limiter.check("write:" + owner, 60, 60)
        try:
            draft = MealDraft.model_validate(payload.model_dump(exclude={"confirmed"}))
            group, created = meal_service.create(draft, owner, idempotency_key)
        except MealConflict:
            raise
        except ValueError as error:
            raise HTTPException(422, str(error)) from None
        if not created:
            response.status_code = 200
        return group

    @app.get("/api/meal-logs")
    def list_logs(day: JournalDate, session: Annotated[dict, Depends(require_user)]):
        canonical_ready(session["user"]["id"])
        return {"groups": foundation.list_groups(session["user"]["id"], str(day))}

    @app.get("/api/meal-logs/{group_id}")
    def get_log(group_id: str, session: Annotated[dict, Depends(require_user)]):
        canonical_ready(session["user"]["id"])
        group = meal_service.get(group_id, session["user"]["id"])
        if not group:
            raise HTTPException(404, "Meal no longer exists.")
        return group

    @app.patch("/api/meal-logs/{group_id}")
    def patch_log(
        group_id: str,
        payload: MealLogPatch,
        session: Annotated[dict, Depends(require_user)],
        idempotency_key: Annotated[str | None, Header()] = None,
    ):
        canonical_ready(session["user"]["id"], write=True)
        limiter.check("write:" + session["user"]["id"], 60, 60)
        try:
            return meal_service.patch(
                group_id,
                payload.draft,
                session["user"]["id"],
                payload.expected_version,
                idempotency_key,
            )
        except MealConflict:
            raise
        except KeyError:
            raise HTTPException(404, "Meal no longer exists.") from None
        except ValueError as error:
            raise HTTPException(422, str(error)) from None

    @app.delete("/api/meal-logs/{group_id}", status_code=204)
    def delete_log(
        group_id: str,
        session: Annotated[dict, Depends(require_user)],
        expected_version: Annotated[int, Query(ge=1)],
    ):
        canonical_ready(session["user"]["id"], write=True)
        try:
            meal_service.delete(group_id, session["user"]["id"], expected_version)
        except KeyError:
            raise HTTPException(404, "Meal no longer exists.") from None
        return Response(status_code=204)

    @app.get("/api/meals")
    def meals(
        day: JournalDate,
        session: Annotated[dict, Depends(require_user)],
        schema_version: Annotated[int, Query(ge=1, le=2)] = 1,
    ):
        from foodlogger.storage import summarize_entries

        entries = journal.list(day, user_id=session["user"]["id"])
        if schema_version == 1 and any(
            m["grams"] < 1 or any(m[k] is None for k in ("calories", "protein", "carbs", "fat"))
            for m in entries
        ):
            raise HTTPException(
                409, "Upgrade required: this day contains partial nutrition or tiny portions."
            )
        summary = summarize_entries(entries)
        if schema_version == 1:
            summary = {
                "count": len(entries),
                **{k: round(summary[k], 1) for k in ("calories", "protein", "carbs", "fat")},
            }
        return {"day": day, "meals": entries, "summary": summary}

    @app.delete("/api/meals/{meal_id}", status_code=204)
    def delete_meal(meal_id: str, session: Annotated[dict, Depends(require_user)]):
        if not journal.delete(meal_id, user_id=session["user"]["id"]):
            raise HTTPException(404, "Meal no longer exists.")
        return Response(status_code=204)

    @app.get("/api/account/export")
    def export_account(session: Annotated[dict, Depends(require_user)]):
        if settings.account_export_disabled:
            raise HTTPException(503, "Account export is temporarily unavailable.")
        from foodlogger.privacy import ArchiveTooLarge, account_archive

        owner = session["user"]["id"]
        limiter.check("account-export:" + owner, 3, 300)
        try:
            archive = account_archive(database, owner)
        except ArchiveTooLarge:
            raise HTTPException(
                413, "Account archive is too large. Contact support for a complete export."
            ) from None
        except LookupError:
            raise HTTPException(401, "Account no longer exists.") from None
        return JSONResponse(
            archive,
            headers={
                "Content-Disposition": 'attachment; filename="biteflow-account.json"',
                "Cache-Control": "no-store",
            },
        )

    @app.get("/api/export")
    def export(day: JournalDate, session: Annotated[dict, Depends(require_user)]):
        output = StringIO(newline="")
        fields = [
            "day",
            "meal_type",
            "name",
            "grams",
            "unit",
            "calories",
            "protein",
            "carbs",
            "fat",
            "sugars",
            "saturated_fat",
            "fiber",
            "salt",
            "sodium",
            "barcode",
        ]
        writer = csv.DictWriter(output, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for entry in journal.list(day, user_id=session["user"]["id"]):
            details = entry["details"]
            row = {
                **entry,
                **details.get("nutrition_total", {}),
                "unit": details.get("basis_unit", "g"),
                "barcode": details.get("barcode"),
            }
            # Product names are user/upstream input: avoid spreadsheet formula execution.
            row["name"] = (
                "'" + row["name"]
                if row["name"].lstrip().startswith(("=", "+", "-", "@"))
                else row["name"]
            )
            writer.writerow(row)
        return Response(
            output.getvalue(),
            media_type="text/csv",
            headers={
                "Content-Disposition": f'attachment; filename="foodlogger-{day}.csv"',
            },
        )

    return app
