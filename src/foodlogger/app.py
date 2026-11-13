"""Multi-user HTTP application with private journals and server-side inference."""

import asyncio
import csv
import logging
import os
import re
import secrets
import sqlite3
import threading
import time
from io import StringIO
from pathlib import Path
from typing import Annotated
from urllib.parse import urlsplit

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Query, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool
from starlette.middleware.trustedhost import TrustedHostMiddleware

from foodlogger.analysis_journal import AnalysisSaveConflict, save_analyzed
from foodlogger.analysis_schemas import AnalysisOptions, AnalysisResult, AnalyzedMealCreate
from foodlogger.apple_auth import AppleAuth, AppleUnavailable
from foodlogger.auth import AccountExists, AuthStore, InvalidAccountInput, InvalidCredentials
from foodlogger.classifier import Classifier, ModelUnavailable
from foodlogger.database import Database, DatabaseUnavailable
from foodlogger.images import MAX_UPLOAD_BYTES, InvalidImage, decode_image
from foodlogger.meal_analysis import AnalysisService
from foodlogger.nutrition import Catalog
from foodlogger.products import (
    InvalidBarcode,
    LookupUnavailable,
    OpenFoodFactsClient,
    ProductNotFound,
    decode_barcode,
    validate_barcode,
)
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
from foodlogger.vision import VisionQuotaExceeded, VisionUnavailable

logger = logging.getLogger(__name__)
PACKAGE = Path(__file__).parent
COOKIE = "foodlogger_session"
IDEMPOTENCY_KEY = re.compile(r"[A-Za-z0-9_-]{16,64}")


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


UPLOAD_PATHS = {"/api/predict", "/api/barcode/scan", "/api/analyze-meal"}
# Per-account requests per minute, checked before an upload reserves a slot.
UPLOAD_LIMITS = {
    "/api/predict": ("predict", 12),
    "/api/barcode/scan": ("scan", 20),
    "/api/analyze-meal": ("analyze", 6),
}
# Seconds one account may spend sending upload bodies per window. A slot is held
# while its body arrives, so this bounds how long a slow sender can occupy one.
UPLOAD_SECONDS, UPLOAD_WINDOW = 90, 300


def _reply(detail, status, headers=None):
    return JSONResponse({"detail": detail}, status, headers=headers)


class BodyLimitMiddleware:
    """Bound raw bodies before parsing, including requests with chunked encoding.

    Uploads reserve a slot before their body is read, so a rejected upload is never
    buffered. Barcode scans have their own slot: a meal analysis that waits on the
    vision provider no longer blocks them. Each account may have one upload in
    flight, and is limited by count and by upload time before it can take a slot.
    """

    def __init__(self, app, auth=None, limiter=None):
        self.app = app
        self.auth = auth
        self.limiter = limiter
        self.body_timeout = 30
        self.upload_slot = threading.BoundedSemaphore(1)
        self.barcode_slot = threading.BoundedSemaphore(1)
        self._uploading = set()
        self._uploading_lock = threading.Lock()

    async def __call__(self, scope, receive, send):
        # Every method that can carry a body is bounded: DELETE takes JSON too.
        if scope["type"] != "http" or scope["method"] in {"GET", "HEAD", "OPTIONS"}:
            return await self.app(scope, receive, send)
        path = scope["path"]
        if path not in UPLOAD_PATHS:
            return await self.bounded_request(scope, receive, send)
        user_id = None
        if self.auth is not None:
            request = Request(scope)
            try:
                session, ambient = await run_in_threadpool(resolve_session, self.auth, request)
            except DatabaseUnavailable:
                return await _reply("The journal database is temporarily unavailable.", 503)(
                    scope, receive, send
                )
            if not session:
                return await _reply("Sign in to access your journal.", 401)(scope, receive, send)
            if ambient and not secrets.compare_digest(
                request.headers.get("x-csrf-token", ""), session["csrf_token"]
            ):
                return await _reply("Your session changed. Refresh and try again.", 403)(
                    scope, receive, send
                )
            user_id = session["user"]["id"]
        if user_id is not None and self.limiter is not None:
            name, per_minute = UPLOAD_LIMITS[path]
            if not self.limiter.allow(
                "upload-time:" + user_id, UPLOAD_SECONDS, UPLOAD_WINDOW, cost=0
            ) or not self.limiter.allow(f"{name}:{user_id}", per_minute, 60):
                return await _reply(
                    "Too many requests. Please try again later.", 429, {"Retry-After": "60"}
                )(scope, receive, send)
        busy = _reply(
            "Image processing is busy. Please try again shortly.", 429, {"Retry-After": "3"}
        )
        if user_id is not None:
            with self._uploading_lock:
                if user_id in self._uploading:
                    return await busy(scope, receive, send)
                self._uploading.add(user_id)
        slot = self.barcode_slot if path == "/api/barcode/scan" else self.upload_slot
        acquired = False
        try:
            acquired = slot.acquire(blocking=False)
            if not acquired:
                return await busy(scope, receive, send)
            return await self.bounded_request(scope, receive, send, user_id)
        finally:
            if acquired:
                slot.release()
            if user_id is not None:
                with self._uploading_lock:
                    self._uploading.discard(user_id)

    async def bounded_request(self, scope, receive, send, user_id=None):
        limit = (
            2 * MAX_UPLOAD_BYTES + 65536
            if scope["path"] == "/api/analyze-meal"
            else (
                MAX_UPLOAD_BYTES + 65536
                if scope["path"]
                in {
                    "/api/predict",
                    "/api/barcode/scan",
                }
                else 65536
            )
        )
        chunks, total = [], 0
        started = time.monotonic()
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
        finally:
            if user_id is not None and self.limiter is not None:
                self.limiter.charge(
                    "upload-time:" + user_id, time.monotonic() - started, UPLOAD_WINDOW
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
) -> FastAPI:
    settings = settings or Settings.from_environment()
    app = FastAPI(title="BiteFlow API", version="2.1.0", description="Private food journals")
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
    limiter = RateLimiter()
    app.add_middleware(BodyLimitMiddleware, auth=auth, limiter=limiter)
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
    image_slot = threading.BoundedSemaphore(1)
    barcode_slot = threading.BoundedSemaphore(1)
    app.state.auth = auth
    apple = AppleAuth(auth)
    app.state.apple = apple
    meal_analyzer = analyzer if analyzer is not None else AnalysisService()
    app.mount("/static", StaticFiles(directory=PACKAGE / "static"), name="static")

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
            raise HTTPException(403, "Use the BiteFlow sign-in form.")
        address = settings.client_address(request)
        limiter.check("auth:" + address, 8, 60)

    def account_limit(name, username, request, limit, seconds, *, ceiling):
        """Throttle guesses per account and client address.

        Keying on the username alone let anyone lock a user out with a few wrong
        passwords. The much higher username-only ceiling still bounds guessing
        spread across many addresses.
        """
        username = username.strip().lower()
        limiter.check(f"{name}:{username}|{settings.client_address(request)}", limit, seconds)
        limiter.check(f"{name}-account:{username}", ceiling, seconds)

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
        return {"status": "ok", "model": predictor.name, "version": "2.1.0"}

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
        account_limit("login", credentials.username, request, 8, 60, ceiling=60)
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
        account_limit("recovery", payload.username, request, 5, 300, ceiling=30)
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
        except ModelUnavailable as error:
            logger.warning("Classifier unavailable", exc_info=True)
            raise HTTPException(503, str(error)) from error
        finally:
            if image is not None:
                image.close()
            image_slot.release()
            await file.close()

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
        if not barcode_slot.acquire(blocking=False):
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
            barcode_slot.release()
            await file.close()

    def save_once(response: Response, user_id: str, key: str | None, save):
        """Save a meal; a repeated Idempotency-Key returns the first saved entry."""
        if key is None:
            return save(None)
        if not IDEMPOTENCY_KEY.fullmatch(key):
            raise HTTPException(422, "Idempotency-Key must be 16–64 URL-safe characters.")
        try:
            return save(key)
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
                lambda key: journal.add(meal, catalog, user_id=user_id, request_key=key),
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
            lambda key: journal.add_custom(meal, user_id=user_id, request_key=key),
        )

    @app.get("/api/meals")
    def meals(day: JournalDate, session: Annotated[dict, Depends(require_user)]):
        entries = journal.list(day, user_id=session["user"]["id"])
        summary = {
            "count": len(entries),
            **{
                key: round(sum(m[key] for m in entries), 1)
                for key in ("calories", "protein", "carbs", "fat")
            },
        }
        return {"day": day, "meals": entries, "summary": summary}

    @app.delete("/api/meals/{meal_id}", status_code=204)
    def delete_meal(meal_id: str, session: Annotated[dict, Depends(require_user)]):
        if not journal.delete(meal_id, user_id=session["user"]["id"]):
            raise HTTPException(404, "Meal no longer exists.")
        return Response(status_code=204)

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
                "Content-Disposition": f'attachment; filename="biteflow-{day}.csv"',
            },
        )

    return app
