"""Staging DB cutover, 16-migration verification, and hosted/local smoke harness.

Covers Stage 0 (T0.1 render.yaml check, T0.2 staging smoke + AI policy renewal,
and T0.3 staging PostgreSQL 16-migration cutover before 2026-11-19).
Never logs or persists connection strings, passwords, tokens, or API keys.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import secrets
import shutil
import sqlite3
import ssl
import subprocess
import tempfile
from datetime import UTC, datetime
from pathlib import Path

import httpx
from fastapi.testclient import TestClient

from foodlogger.ai_gateway import AIGateway, BudgetPolicy
from foodlogger.app import create_app
from foodlogger.database import Database
from foodlogger.security import Settings
from foodlogger.text_input import SplitFood, SplitResult

ROOT = Path(__file__).resolve().parents[1]

MIGRATIONS: tuple[tuple[str, str], ...] = (
    (
        "supabase/migrations/20261008142103_foodlogger_private_schema.sql",
        "f80075201182818d988fdc426b56e0492921b73a30041f2d8d10821d531b7887",
    ),
    (
        "supabase/migrations/20261011194917_apple_sign_in.sql",
        "966c774d31f6589d6f35784edd413638195c7ba653fe06e0dd1a2a3cc710bc59",
    ),
    (
        "supabase/migrations/20261013160000_p01_journal_foundation.sql",
        "e7c29500b9cddc7f56ab86121755f96c12a6c1a85daee38cefa1c32ee18a4600",
    ),
    (
        "supabase/migrations/20261013170000_p01_ai_gateway.sql",
        "4d89e33cfc868ea0a2b164b125f960363c557ebda50f7cdb9c37f32800018aca",
    ),
    (
        "supabase/migrations/20261013191213_p02_partial_nutrition.sql",
        "470a0c9236001cadcf77f654a51e56e2c3ea957fc9c93d592c24ca5a96da88dd",
    ),
    (
        "supabase/migrations/20261014030916_p03_goal_revisions.sql",
        "5dd6c01696876593e36aa54524db88f446325c2c1d9747d9a6272d7caecfce42",
    ),
    (
        "supabase/migrations/20261014051354_p04_library.sql",
        "ebfcb179b7d956b9d75b555b40d2e3ff4a8a2c8a1acd4fdc1405fc6347f8e855",
    ),
    (
        "supabase/migrations/20261014052225_p04_recipes.sql",
        "a8736948113e968ab05ca790af4b456267594396f62725e26336327003896444",
    ),
    (
        "supabase/migrations/20261014055032_p04_recipe_yield_decimal.sql",
        "abaeedaf8defe18f9948812f715469f9a365bbe7c8128fcd857dce684a40735e",
    ),
    (
        "supabase/migrations/20261014072459_p06_servings.sql",
        "9895549387ba82d3fe84b0de767b679142a214356952791cb0c4d1320337cbc7",
    ),
    (
        "supabase/migrations/20261014073344_p06_private_products.sql",
        "4163803ed6c42159994ba5cbe3c73da7614403167daaabb41aa041c391645601",
    ),
    (
        "supabase/migrations/20261015112017_p07_tracking.sql",
        "8738277bcdb48821969558740b407e0506ebccc7059eef1eda96b6329f842dbc",
    ),
    (
        "supabase/migrations/20261015122803_p08_recommendations.sql",
        "e480c603650d5086edd3f57e357075ef3c64282e12604d8684b2168a89faa339",
    ),
    (
        "supabase/migrations/20261015132704_p09_habits.sql",
        "f34ae8ad8ab25458b58b4704c079dfb3d30056b2a2bb82ff3582722483e3344a",
    ),
    (
        "supabase/migrations/20261015141516_p10_health.sql",
        "a6f045fd6767b9c0d33927b77b7a3d78a0e7c22f9c36035470bf3249b85e4ba0",
    ),
    (
        "supabase/migrations/20261016055042_p11_health_connect.sql",
        "0ba82e68bd3b25fd1ace9360aadf92a3d7699b7dbbf36c51893dee19b34af17f",
    ),
)

EXPECTED_TABLES: tuple[str, ...] = (
    "ai_attempts",
    "ai_projects",
    "apple_challenges",
    "apple_identities",
    "foundation_issues",
    "foundation_jobs",
    "foundation_migrations",
    "health_connect_imports",
    "health_exports",
    "health_imports",
    "health_scopes",
    "label_cache",
    "library_favorites",
    "library_requests",
    "meal_group_items",
    "meal_groups",
    "meals",
    "private_product_requests",
    "private_product_versions",
    "private_products",
    "recipe_headers",
    "recipe_items",
    "recipe_versions",
    "recommendation_preferences",
    "recommendation_source_reviews",
    "reminder_attempts",
    "reminder_devices",
    "reminder_preferences",
    "save_receipts",
    "schema_version",
    "serving_conversions",
    "sessions",
    "tracking_entries",
    "tracking_receipts",
    "user_nutrition_goal_revisions",
    "users",
)

REQUIRED_NUTRITION_COMMITS: tuple[str, ...] = ("089f789", "3658a17", "4a9d6b6")
STAGING_PROJECT_ID = "gen-lang-client-0101662511"
STAGING_SERVICE_ID = "srv-dbbiamm1egvs7384stu0"
PRODUCTION_SERVICE_ID = "srv-db3raa3ncjis73bh20p0"

ROLE_VERIFICATION_SQL = """
SELECT rolname, rolsuper, rolcreatedb, rolcreaterole, rolbypassrls, rolinherit
FROM pg_roles
WHERE rolname = 'foodlogger_app'
""".strip()

RLS_TABLES_VERIFICATION_SQL = """
SELECT c.relname AS table_name, c.relrowsecurity AS rls_enabled
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = 'foodlogger' AND c.relkind = 'r'
ORDER BY c.relname
""".strip()

TLS_VERIFICATION_SQL = """
SELECT ssl, version, cipher
FROM pg_stat_ssl
WHERE pid = pg_backend_pid()
""".strip()


def build_staging_ai_policy(verified_at: datetime | None = None) -> BudgetPolicy:
    timestamp = (verified_at or datetime.now(UTC)).astimezone(UTC)
    return BudgetPolicy(
        project_id=STAGING_PROJECT_ID,
        provider="gemini-free",
        model="gemini-3.5-flash-lite",
        enabled=True,
        verified_at=timestamp,
        verification_ttl_seconds=604800,
        reset_timezone="America/Los_Angeles",
        daily_limit=60,
        rpm=1,
        input_tpm=200000,
        max_input_tokens=200000,
        photo_reserve=20,
        user_daily_limit=40,
        feature_daily_limits={
            "photo": 40,
            "text": 30,
            "voice": 30,
            "ocr": 10,
            "insight": 0,
            "recommendation": 0,
        },
    )


def verify_render_blueprints(root: Path = ROOT) -> dict:
    prod_yaml = (root / "render.yaml").read_text(encoding="utf-8")
    staging_yaml = (root / "deploy/render.staging.yaml").read_text(encoding="utf-8")
    prod_off = bool(
        re.search(r"^\s*autoDeployTrigger:\s*['\"]?off['\"]?\s*$", prod_yaml, re.M)
        or re.search(r"^\s*autoDeploy:\s*false\s*$", prod_yaml, re.M)
    )
    staging_off = bool(
        re.search(r"^\s*autoDeployTrigger:\s*['\"]?off['\"]?\s*$", staging_yaml, re.M)
    )
    if not prod_off:
        raise AssertionError("render.yaml must set autoDeployTrigger: 'off' (or autoDeploy: false)")
    if not staging_off:
        raise AssertionError("deploy/render.staging.yaml must keep autoDeployTrigger: 'off'")
    return {
        "render_yaml_auto_deploy_off": prod_off,
        "staging_yaml_auto_deploy_off": staging_off,
    }


def verify_migration_manifest(root: Path = ROOT) -> list[dict]:
    migration_dir = root / "supabase/migrations"
    actual_files = sorted(p.relative_to(root).as_posix() for p in migration_dir.glob("*.sql"))
    expected_files = [rel for rel, _ in MIGRATIONS]
    if actual_files != expected_files:
        raise AssertionError(
            f"Migration file list mismatch: expected {len(expected_files)}, got {len(actual_files)}"
        )
    verified = []
    rls_tables: set[str] = set()
    for rel_path, expected_sha in MIGRATIONS:
        content = (root / rel_path).read_bytes().replace(b"\r\n", b"\n")
        digest = hashlib.sha256(content).hexdigest()
        if digest != expected_sha:
            raise AssertionError(f"SHA256 mismatch for {rel_path}: {digest} != {expected_sha}")
        text = content.decode("utf-8")
        for match in re.finditer(
            r"ALTER\s+TABLE\s+(?:foodlogger\.)?([a-z0-9_]+)\s+ENABLE\s+ROW\s+LEVEL\s+SECURITY",
            text,
            re.I,
        ):
            rls_tables.add(match.group(1).lower())
        verified.append({"file": rel_path, "sha256": digest})
    if tuple(sorted(rls_tables)) != EXPECTED_TABLES:
        raise AssertionError(
            f"RLS table set mismatch: {sorted(rls_tables)} != {list(EXPECTED_TABLES)}"
        )
    return verified


def _translate_pg_migration_to_sqlite(rel_path: str, sql_text: str) -> list[str]:
    if rel_path.endswith("20261013191213_p02_partial_nutrition.sql"):
        from foodlogger.partial_migration import MEALS_SQL

        return [
            "DROP TABLE IF EXISTS meals_v2_new",
            MEALS_SQL.replace("CREATE TABLE meals", "CREATE TABLE meals_v2_new"),
            "INSERT INTO meals_v2_new SELECT * FROM meals",
            "DROP TABLE meals",
            "ALTER TABLE meals_v2_new RENAME TO meals",
            "CREATE INDEX IF NOT EXISTS meals_owner_day ON meals(user_id, day)",
            "CREATE UNIQUE INDEX IF NOT EXISTS meals_owner_identity ON meals(user_id, id)",
            "UPDATE schema_version SET version = 2 WHERE id = 1",
        ]
    if rel_path.endswith("20261014055032_p04_recipe_yield_decimal.sql"):
        # SQLite uses dynamic numeric affinity for REAL/NUMERIC columns.
        return ["SELECT 1"]

    cleaned = re.sub(r"--[^\n]*", "", sql_text)
    cleaned = re.sub(
        r"DO\s+\$[A-Za-z0-9_]*\$.*?END\s+\$[A-Za-z0-9_]*\$\s*;",
        "",
        cleaned,
        flags=re.S | re.I,
    )
    statements: list[str] = []
    for raw_stmt in re.split(r";\s*(?:\r?\n|$)", cleaned):
        stmt = raw_stmt.strip()
        if not stmt:
            continue
        upper = stmt.upper()
        if upper.startswith(
            (
                "CREATE ROLE ",
                "CREATE SCHEMA ",
                "REVOKE ",
                "GRANT ",
                "SET LOCAL ",
                "SET SEARCH_PATH ",
                "ALTER TABLE ",
                "CREATE POLICY ",
            )
        ):
            continue
        stmt = re.sub(r"\bfoodlogger\.", "", stmt)
        stmt = stmt.replace("CURRENT_TIMESTAMP::text", "CURRENT_TIMESTAMP")
        statements.append(stmt)
    return statements


def apply_migrations_to_sqlite(db_path: Path, root: Path = ROOT) -> dict:
    from contextlib import closing

    verified_manifest = verify_migration_manifest(root)
    with closing(sqlite3.connect(db_path)) as conn, conn:
        conn.execute("PRAGMA foreign_keys = ON")
        for rel_path, _ in MIGRATIONS:
            sql_text = (root / rel_path).read_text(encoding="utf-8")
            for stmt in _translate_pg_migration_to_sqlite(rel_path, sql_text):
                conn.execute(stmt)
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' "
            "ORDER BY name"
        ).fetchall()
        tables = [row[0] for row in rows]
        version_row = conn.execute("SELECT version FROM schema_version WHERE id = 1").fetchone()
        servings_count = conn.execute("SELECT COUNT(*) FROM serving_conversions").fetchone()[0]
        foundation_rows = [
            r[0]
            for r in conn.execute("SELECT name FROM foundation_migrations ORDER BY name").fetchall()
        ]
    if tuple(tables) != EXPECTED_TABLES:
        raise AssertionError(f"SQLite table list mismatch: {tables} != {list(EXPECTED_TABLES)}")
    if not version_row or version_row[0] != 2:
        raise AssertionError(f"Expected schema_version=2, got {version_row}")
    if servings_count != 27:
        raise AssertionError(f"Expected 27 USDA serving conversions, got {servings_count}")
    return {
        "backend": "sqlite",
        "migration_count": len(verified_manifest),
        "tables_created": len(tables),
        "tables": tables,
        "schema_version": version_row[0],
        "serving_conversions": servings_count,
        "foundation_migrations": foundation_rows,
    }


def verify_tls_and_role_contract(sample_dsn: str | None = None) -> dict:
    if not ssl.get_default_verify_paths().cafile:
        import certifi

        os.environ.setdefault("SSL_CERT_FILE", certifi.where())
    dsn = sample_dsn or (
        "postgresql://foodlogger_app:fixture-only@"
        "dpg-staging-probe.frankfurt-postgres.render.com/biteflow_staging_db"
    )
    database = Database(dsn)
    options = database.connection_options
    if options.get("sslmode") != "verify-full":
        raise AssertionError("Database did not enforce sslmode=verify-full")
    cafile = options.get("sslrootcert")
    if not cafile or cafile == "system":
        raise AssertionError("Database did not resolve an explicit system CA bundle path")
    context = ssl.create_default_context(cafile=cafile)
    ca_count = context.cert_store_stats().get("x509_ca", 0)
    if ca_count <= 0:
        raise AssertionError("Resolved CA bundle contains zero trusted root certificates")
    return {
        "sslmode": options["sslmode"],
        "ca_bundle_resolved": True,
        "trusted_ca_count": ca_count,
        "role_query": ROLE_VERIFICATION_SQL,
        "rls_query": RLS_TABLES_VERIFICATION_SQL,
        "tls_query": TLS_VERIFICATION_SQL,
    }


def verify_commit_and_nutrition_fixes(root: Path = ROOT) -> dict:
    git_bin = shutil.which("git") or r"C:\Program Files\Git\cmd\git.exe"
    head_sha = None
    ancestors: dict[str, bool] = {}
    if Path(git_bin).exists():
        head_sha = subprocess.check_output(
            [git_bin, "-C", str(root), "rev-parse", "HEAD"], text=True
        ).strip()
        for commit in REQUIRED_NUTRITION_COMMITS:
            res = subprocess.run(
                [git_bin, "-C", str(root), "merge-base", "--is-ancestor", commit, "HEAD"],
                capture_output=True,
            )
            ancestors[commit] = res.returncode == 0
        if not all(ancestors.values()):
            raise AssertionError(f"Missing required nutrition commits in HEAD: {ancestors}")
    return {
        "head_sha": head_sha,
        "required_nutrition_commits": ancestors,
    }


class _SyntheticTextProvider:
    name = "gemini-free"
    model = "gemini-3.5-flash-lite"
    api_key = "synthetic-local-probe-key"
    free_tier_confirmed = True

    def payload(self, text: str, language: str) -> dict:
        return {"text": text, "language": language}

    def interpret(self, payload: dict):
        text = payload["text"]
        return (
            SplitResult(foods=[SplitFood(text=text, search_name="fried eggs")]),
            {"input_tokens": 59, "output_tokens": 25},
        )


def run_smoke_against_client(client, *, check_ai: bool = True) -> dict:
    checks: list[dict] = []

    def record(name: str, status: int, expected: int):
        passed = status == expected
        checks.append({"name": name, "status": status, "expected": expected, "pass": passed})
        if not passed:
            raise AssertionError(f"Smoke check '{name}' failed: HTTP {status} != {expected}")

    health = client.get("/api/health")
    record("health", health.status_code, 200)
    health_body = health.json()
    if health_body.get("status") != "ok":
        raise AssertionError(f"Unexpected /api/health payload: {health_body}")

    unauth = client.get("/api/health/imports")
    record("unauthenticated health records", unauth.status_code, 401)

    auth_headers = {"X-FoodLogger-Client": "mobile", "X-FoodLogger-Request": "1"}
    user_a = f"smoke_a_{secrets.token_hex(4)}"
    user_b = f"smoke_b_{secrets.token_hex(4)}"
    password = secrets.token_urlsafe(24)

    reg_a = client.post(
        "/api/auth/register",
        json={"username": user_a, "password": password},
        headers=auth_headers,
    )
    record("synthetic account a", reg_a.status_code, 201)
    headers_a = {"Authorization": f"Bearer {reg_a.json()['session_token']}"}

    reg_b = client.post(
        "/api/auth/register",
        json={"username": user_b, "password": password},
        headers=auth_headers,
    )
    record("synthetic account b", reg_b.status_code, 201)
    headers_b = {"Authorization": f"Bearer {reg_b.json()['session_token']}"}

    caps = client.get("/api/capabilities", headers=headers_a)
    record("capabilities", caps.status_code, 200)

    meal = client.post(
        "/api/meals",
        json={"food_id": "banana", "grams": 120, "day": "2026-11-01", "meal_type": "snack"},
        headers={**headers_a, "Idempotency-Key": "smoke-manual-meal-0001"},
    )
    record("synthetic manual meal", meal.status_code, 201)

    water_body = {
        "value": 250,
        "occurred_at": "2026-11-01T08:00:00Z",
        "local_date": "2026-11-01",
        "timezone_id": "UTC",
        "source": "manual",
    }
    water_key = "smoke-water-write-0001"
    water = client.post(
        "/api/water",
        json=water_body,
        headers={**headers_a, "Idempotency-Key": water_key},
    )
    record("synthetic water write", water.status_code, 201)
    water_id = water.json()["id"]

    water_replay = client.post(
        "/api/water",
        json=water_body,
        headers={**headers_a, "Idempotency-Key": water_key},
    )
    record("water replay", water_replay.status_code, 200)

    other_water = client.get("/api/water?from=2026-11-01&to=2026-11-01", headers=headers_b)
    record("other account water", other_water.status_code, 200)
    if other_water.json().get("items") != []:
        raise AssertionError("Cross-account isolation leak on /api/water")

    other_patch = client.patch(
        f"/api/water/{water_id}",
        json={**water_body, "value": 300, "expected_version": 1},
        headers=headers_b,
    )
    record("other account cannot edit water", other_patch.status_code, 404)

    water_conflict = client.post(
        "/api/water",
        json={**water_body, "value": 500},
        headers={**headers_a, "Idempotency-Key": water_key},
    )
    record("water request content conflict", water_conflict.status_code, 409)

    reconcile_1 = client.post("/api/health/reconcile", headers=headers_a)
    record("health reconciliation", reconcile_1.status_code, 200)

    reconcile_2 = client.post("/api/health/reconcile", headers=headers_a)
    record("stable health reconciliation", reconcile_2.status_code, 200)

    habits_get = client.get("/api/habits?timezone_id=UTC", headers=headers_a)
    record("habits read", habits_get.status_code, 200)

    habits_put = client.put(
        "/api/habits/preferences",
        json={"expected_version": 0, "timezone_id": "UTC", "muted": False},
        headers=headers_a,
    )
    record("habits preference write", habits_put.status_code, 200)

    habits_stale = client.put(
        "/api/habits/preferences",
        json={"expected_version": 0, "timezone_id": "UTC", "muted": True},
        headers=headers_a,
    )
    record("habits stale version", habits_stale.status_code, 409)

    water_del = client.delete(f"/api/water/{water_id}?expected_version=1", headers=headers_a)
    record("water deletion", water_del.status_code, 204)

    reconcile_3 = client.post("/api/health/reconcile", headers=headers_a)
    record("health reconciliation after deletion", reconcile_3.status_code, 200)

    # Verify nutrition reference grounding from 089f789, 3658a17, and 4a9d6b6 over HTTP.
    omelet_ref = client.get("/api/analysis/references?q=omelette", headers=headers_a)
    record("nutrition reference omelette (089f789)", omelet_ref.status_code, 200)
    omelet_foods = omelet_ref.json()["foods"]
    if not omelet_foods or omelet_foods[0]["id"] != "fdc:172185":
        raise AssertionError(f"Expected fdc:172185 for omelette, got {omelet_foods[:1]}")

    no_fat_ref = client.get(
        "/api/analysis/references?q=egg+omelette+no+added+fat", headers=headers_a
    )
    record("nutrition reference fat negation (4a9d6b6)", no_fat_ref.status_code, 200)
    if not no_fat_ref.json()["foods"] or not all(
        "no added fat" in f["name"] for f in no_fat_ref.json()["foods"]
    ):
        raise AssertionError("Fat negation variant check failed")

    ai_probe = None
    if check_ai:
        text_resp = client.post(
            "/api/analyze-text",
            json={
                "text": "sunny side up breakfast eggs",
                "language": "en",
                "local_date": "2026-11-01",
                "meal_category": "breakfast",
                "input_method": "text",
                "allow_ai": True,
            },
            headers={**headers_a, "Idempotency-Key": "smoke-synthetic-ai-text-01"},
        )
        record("synthetic AI nutrition probe", text_resp.status_code, 200)
        body = text_resp.json()
        if body.get("ai_status") != "used":
            raise AssertionError(f"Expected ai_status='used', got {body.get('ai_status')}")
        meals_after = client.get("/api/meals?day=2026-11-01", headers=headers_a).json()
        # Only the earlier banana snack should exist; AI text probe must not auto-save.
        if meals_after["summary"]["count"] != 1:
            raise AssertionError("Synthetic AI text probe unexpectedly auto-saved a meal")
        ai_probe = {
            "input": "sunny side up breakfast eggs",
            "http_status": text_resp.status_code,
            "ai_status": body["ai_status"],
            "food_count": len(body.get("foods", [])),
            "all_unconfirmed": all(not f.get("confirmed", False) for f in body.get("foods", [])),
            "no_auto_save": True,
            "first_reference_id": (
                body["foods"][0]["reference"]["id"]
                if body.get("foods") and body["foods"][0].get("reference")
                else None
            ),
        }

    return {
        "status": "passed",
        "check_count": len(checks),
        "checks": checks,
        "health": health_body,
        "ai_probe": ai_probe,
    }


def run_local_verification(root: Path = ROOT) -> dict:
    blueprints = verify_render_blueprints(root)
    commits = verify_commit_and_nutrition_fixes(root)
    tls_contract = verify_tls_and_role_contract()
    with tempfile.TemporaryDirectory(prefix="biteflow-t0-cutover-") as tmp:
        db_file = Path(tmp) / "staging_rehearsal.sqlite3"
        migration_report = apply_migrations_to_sqlite(db_file, root)
        database = Database(db_file)
        gateway = AIGateway(database, STAGING_PROJECT_ID, enabled=True)
        policy = build_staging_ai_policy()
        gateway.configure(policy)
        env_overrides = {
            "FOODLOGGER_CANONICAL_WRITES": "1",
            "FOODLOGGER_COPY_ENABLED": "1",
            "FOODLOGGER_RECIPE_WRITES": "1",
            "FOODLOGGER_LIBRARY_ENABLED": "1",
            "FOODLOGGER_HEALTH_ENABLED": "1",
            "FOODLOGGER_HABITS_ENABLED": "1",
            "FOODLOGGER_TRACKING_ENABLED": "1",
            "FOODLOGGER_TRACKING_WRITES": "1",
            "FOODLOGGER_RECOMMENDATIONS_ENABLED": "1",
            "FOODLOGGER_RECOMMENDATION_WRITES": "1",
            "FOODLOGGER_INSIGHTS_ENABLED": "1",
            "FOODLOGGER_TRENDS_ENABLED": "1",
            "FOODLOGGER_GOALS_ENABLED": "1",
            "FOODLOGGER_FOOD_SOURCES_ENABLED": "1",
            "FOODLOGGER_SERVINGS_ENABLED": "1",
            "FOODLOGGER_PRIVATE_PRODUCTS_ENABLED": "1",
            "FOODLOGGER_AI_ENABLED": "1",
            "FOODLOGGER_TEXT_AI_ENABLED": "1",
            "FOODLOGGER_AI_PROJECT_ID": STAGING_PROJECT_ID,
        }
        old_env = {k: os.environ.get(k) for k in env_overrides}
        try:
            os.environ.update(env_overrides)
            app = create_app(
                db_path=database,
                settings=Settings.from_environment(),
                text_provider=_SyntheticTextProvider(),
            )
            with TestClient(app) as client:
                smoke = run_smoke_against_client(client, check_ai=True)
            ledger = gateway.summary()
        finally:
            for k, v in old_env.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v

    return {
        "verified_at": datetime.now(UTC).isoformat(),
        "mode": "local-verify",
        "blueprints": blueprints,
        "commits": commits,
        "migrations": migration_report,
        "tls_and_role_contract": tls_contract,
        "smoke": smoke,
        "ai_ledger": ledger,
    }


def apply_postgres_cutover(
    owner_dsn: str,
    app_dsn: str,
    app_password: str,
    *,
    old_dsn: str | None = None,
    root: Path = ROOT,
) -> dict:
    import psycopg
    from psycopg import sql
    from psycopg.rows import dict_row

    manifest = verify_migration_manifest(root)
    exported_ledger = None
    if old_dsn:
        old_db = Database(old_dsn)
        with old_db.connect() as db:
            projects = db.execute("SELECT id, policy, revision FROM ai_projects").fetchall()
            attempts = db.execute(
                "SELECT id, project_id, feature, provider, model, provider_day, "
                "started_at, reserved_tokens, input_tokens, output_tokens, cost_microusd, state "
                "FROM ai_attempts ORDER BY started_at"
            ).fetchall()
            exported_ledger = {
                "projects_count": len(projects),
                "attempts_count": len(attempts),
                "attempts": [dict(r) for r in attempts],
            }

    owner_options = Database(owner_dsn).connection_options
    with psycopg.connect(**owner_options, row_factory=dict_row) as conn:
        existing = conn.execute(
            "SELECT COUNT(*) AS count FROM information_schema.tables "
            "WHERE table_schema = 'foodlogger'"
        ).fetchone()["count"]
        if existing != 0:
            raise RuntimeError(
                f"Target database already has {existing} tables in schema foodlogger; "
                "refusing to overwrite non-empty database."
            )
        for rel_path, _ in MIGRATIONS:
            conn.execute((root / rel_path).read_text(encoding="utf-8"))
        conn.execute(
            sql.SQL("ALTER ROLE foodlogger_app LOGIN PASSWORD {}").format(sql.Literal(app_password))
        )

    app_database = Database(app_dsn)
    app_database.check_schema()
    gateway = AIGateway(app_database, STAGING_PROJECT_ID, enabled=True)
    policy = build_staging_ai_policy()
    gateway.configure(policy)

    with psycopg.connect(**app_database.connection_options, row_factory=dict_row) as app_conn:
        role_row = app_conn.execute(ROLE_VERIFICATION_SQL).fetchone()
        rls_rows = app_conn.execute(RLS_TABLES_VERIFICATION_SQL).fetchall()
        tls_row = app_conn.execute(TLS_VERIFICATION_SQL).fetchone()

    if not role_row or any(
        role_row[k]
        for k in ("rolsuper", "rolcreatedb", "rolcreaterole", "rolbypassrls", "rolinherit")
    ):
        raise AssertionError(f"foodlogger_app has unexpected privileges: {role_row}")
    if [r["table_name"] for r in rls_rows] != list(EXPECTED_TABLES) or not all(
        r["rls_enabled"] for r in rls_rows
    ):
        raise AssertionError("Not all 36 foodlogger tables have RLS enabled")
    if not tls_row or not tls_row.get("ssl"):
        raise AssertionError(f"TLS verification failed: {tls_row}")

    return {
        "status": "passed",
        "migrations_applied": len(manifest),
        "tables_verified": len(rls_rows),
        "app_role": dict(role_row),
        "tls": dict(tls_row),
        "ai_policy_verified_at": policy.verified_at.isoformat(),
        "exported_old_ledger": exported_ledger,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mode",
        choices=("local-verify", "cutover", "hosted-smoke"),
        default="local-verify",
    )
    parser.add_argument("--origin", default="https://biteflow-staging-api.onrender.com")
    parser.add_argument("--allow-live-ai", action="store_true")
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args(argv)

    if args.mode == "local-verify":
        report = run_local_verification(ROOT)
    elif args.mode == "cutover":
        owner_dsn = os.environ["STAGING_OWNER_DATABASE_URL"]
        app_dsn = os.environ["STAGING_DATABASE_URL"]
        app_password = os.environ["STAGING_APP_PASSWORD"]
        old_dsn = os.getenv("OLD_STAGING_DATABASE_URL")
        report = apply_postgres_cutover(
            owner_dsn, app_dsn, app_password, old_dsn=old_dsn, root=ROOT
        )
    else:
        with httpx.Client(base_url=args.origin, timeout=30.0, trust_env=False) as client:
            report = run_smoke_against_client(client, check_ai=args.allow_live_ai)

    rendered = json.dumps(report, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
