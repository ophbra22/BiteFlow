"""Staging DB cutover, 16-migration verification, and hosted/local smoke harness.

Covers Stage 0 (T0.1 render.yaml check, T0.2 staging smoke + AI policy renewal,
and T0.3 staging PostgreSQL 16-migration cutover; confirm the database expiry on Render).
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
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import parse_qsl, unquote, urlsplit

import httpx
from fastapi.testclient import TestClient

import foodlogger
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

# (query, preparation, required top reference, forbidden reference). Each commit's
# rows were checked to fail on that commit's parent and pass on the commit itself.
NUTRITION_FIX_CONTRACTS: dict[str, tuple[tuple[str, str, str | None, str | None], ...]] = {
    "089f789": (
        ("omelette", "fried", "fdc:172185", None),
        ("חביתה", "fried", "fdc:172185", None),
    ),
    "3658a17": (
        ("egg", "cooked", "fdc:2707153", None),
        ("flaxseed", "unknown", "fdc:169414", None),
        ("walnut", "raw", "fdc:170187", None),
    ),
    "4a9d6b6": (
        ("squid", "fried", "fdc:171982", None),
        ("omelette with tomatoes and dark green vegetables", "fried", None, "fdc:2707236"),
    ),
}

# Runs in an isolated interpreter (-I ignores PYTHONPATH and the working directory) with the
# target's src first on sys.path, and reports every foodlogger file it actually used.
CATALOG_CONTRACT_RUNNER = """
import json, sys
from importlib.resources import files
from pathlib import Path

import pydantic  # Dependencies keep their normal caches; only foodlogger must skip them.

sys.pycache_prefix = sys.argv[3]
sys.path.insert(0, str(Path(sys.argv[1]).parent))
from foodlogger.nutrition_reference import ReferenceCatalog

catalog = ReferenceCatalog()
results = [
    [row.id for row in catalog.search(query, preparation, limit=8)]
    for query, preparation in json.loads(sys.argv[2])
]
used = [
    getattr(module, "__file__", None)
    for name, module in sys.modules.items()
    if name == "foodlogger" or name.startswith("foodlogger.")
]
used.append(str(files("foodlogger").joinpath("data/usda_reference.json")))
print(json.dumps({"results": results, "used": used}))
"""
STAGING_PROJECT_ID = "gen-lang-client-0101662511"
DEFAULT_STAGING_ORIGIN = "https://biteflow-staging-api.onrender.com"
# Recorded in docs/biteflow/release-readiness/testflight-rc12-15.md. Whether this is still the
# active staging database must be confirmed on Render (runbook Step 2.0).
EXPIRING_STAGING_DB_IDS: tuple[str, ...] = ("dpg-dbbhudvavr4c73duk09g-a",)
# No repository evidence ties this ID to staging or to an expiry date. It is never accepted as
# the old database, and is refused as a replacement target in case it is in use.
UNVERIFIED_STAGING_DB_IDS: tuple[str, ...] = ("dpg-d6q76n5m5p6s73f9k58g-a",)
APPROVED_STAGING_HOSTS: tuple[str, ...] = ("biteflow-staging-api.onrender.com",)
# Refused everywhere. srv-d6q76n5m5p6s73f9k590 has no repository evidence, and stays blocked only
# as a precaution; the production service recorded in the repository is srv-db3raa3ncjis73bh20p0.
FORBIDDEN_PRODUCTION_IDENTIFIERS: tuple[str, ...] = (
    "foodlogger.onrender.com",
    "srv-d6q76n5m5p6s73f9k590",
    "srv-db3raa3ncjis73bh20p0",
    "slnmporlcbqnnkyebdmv",
    "supabase.co",
    "supabase.com",
    "car_log",
)

ROLE_VERIFICATION_SQL = """
SELECT
    current_user AS current_user,
    session_user AS session_user,
    rolname,
    rolsuper,
    rolcreatedb,
    rolcreaterole,
    rolbypassrls,
    rolinherit,
    (
        SELECT count(*)
        FROM pg_tables
        WHERE schemaname = 'public' AND tableowner = current_user
    ) AS public_owned_tables,
    (
        SELECT count(*)
        FROM pg_tables
        WHERE schemaname IN ('public', 'foodlogger') AND tableowner = current_user
    ) AS total_owned_tables
FROM pg_roles
WHERE rolname = current_user
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


def validate_staging_origin(
    origin: str,
    *,
    allow_staging_host: str | None = None,
) -> str:
    """Validate that a hosted target URL uses HTTPS and points only to staging."""
    if not origin or not isinstance(origin, str):
        raise ValueError("Staging origin URL must be a non-empty string")
    parsed = urlsplit(origin.strip())
    if parsed.scheme.lower() != "https":
        raise ValueError(f"Staging origin must use https:// (got scheme={parsed.scheme!r})")
    if parsed.username or parsed.password:
        raise ValueError("Staging origin must not embed credentials")
    hostname = (parsed.hostname or "").strip().lower()
    if not hostname:
        raise ValueError("Staging origin must include a hostname")

    for forbidden in FORBIDDEN_PRODUCTION_IDENTIFIERS:
        if forbidden in hostname or forbidden in origin.lower():
            raise ValueError(
                f"Refusing to run staging smoke/cutover against production identifier: {forbidden}"
            )

    allowed_hosts = set(APPROVED_STAGING_HOSTS)
    if allow_staging_host:
        override = allow_staging_host.strip().lower()
        for forbidden in FORBIDDEN_PRODUCTION_IDENTIFIERS:
            if forbidden in override:
                raise ValueError(
                    f"--allow-staging-host cannot override production identifier: {forbidden}"
                )
        allowed_hosts.add(override)

    if hostname not in allowed_hosts:
        raise ValueError(
            f"Unapproved staging host {hostname!r}; expected one of {sorted(allowed_hosts)}"
        )
    return f"https://{parsed.netloc}"


ALLOWED_DSN_QUERY_KEYS: frozenset[str] = frozenset({"sslmode", "sslrootcert"})
ALLOWED_CONNINFO_KEYS: frozenset[str] = frozenset(
    {"host", "port", "dbname", "user", "password", "sslmode", "sslrootcert"}
)


def _parse_postgres_dsn(dsn: str, label: str) -> dict:
    if not dsn or not isinstance(dsn, str):
        raise ValueError(f"{label} must be a non-empty PostgreSQL URL")
    raw = dsn.strip()
    parsed = urlsplit(raw)
    if parsed.scheme.lower() not in ("postgresql", "postgres"):
        raise ValueError(f"{label} must use postgresql:// scheme")
    if parsed.fragment:
        raise ValueError(f"{label} must not contain a URL fragment")

    for key, value in parse_qsl(parsed.query, keep_blank_values=True):
        norm_key = key.strip().lower()
        if norm_key not in ALLOWED_DSN_QUERY_KEYS:
            raise ValueError(
                f"{label} contains forbidden DSN query parameter {key!r}; "
                "only sslmode and sslrootcert are permitted"
            )
        if norm_key == "sslmode" and value.strip() != "verify-full":
            raise ValueError(f"{label} requires sslmode=verify-full (got {value!r})")

    host = unquote(parsed.hostname or "").strip().lower()
    port = int(parsed.port or 5432)
    dbname = unquote(parsed.path.lstrip("/").strip())
    username = unquote(parsed.username) if parsed.username is not None else ""
    password = unquote(parsed.password) if parsed.password is not None else ""
    if not host or not dbname or "/" in dbname:
        raise ValueError(f"{label} must include both hostname and database name")
    if not username:
        raise ValueError(f"{label} must specify a username")

    if not ssl.get_default_verify_paths().cafile:
        import certifi

        os.environ.setdefault("SSL_CERT_FILE", certifi.where())

    from psycopg.conninfo import conninfo_to_dict

    try:
        conninfo = conninfo_to_dict(raw)
    except Exception as exc:
        raise ValueError(f"{label} is not a valid PostgreSQL conninfo URL") from exc

    extra_keys = set(conninfo.keys()) - ALLOWED_CONNINFO_KEYS
    if extra_keys:
        raise ValueError(
            f"{label} contains forbidden libpq conninfo parameters: {sorted(extra_keys)}"
        )

    db_options = Database(raw).connection_options
    conn_tuple = (
        str(conninfo.get("host") or "").strip().lower(),
        int(conninfo.get("port") or 5432),
        str(conninfo.get("dbname") or "").strip(),
        str(conninfo.get("user") or ""),
        str(conninfo.get("password") or ""),
    )
    db_tuple = (
        str(db_options.get("host") or "").strip().lower(),
        int(db_options.get("port") or 5432),
        str(db_options.get("dbname") or "").strip(),
        str(db_options.get("user") or ""),
        str(db_options.get("password") or ""),
    )
    url_tuple = (host, port, dbname, username, password)
    if url_tuple != conn_tuple or url_tuple != db_tuple:
        raise ValueError(
            f"{label} URL components do not match parsed Database/libpq connection options"
        )

    return {
        "host": host,
        "port": port,
        "dbname": dbname,
        "username": username,
        "password": password,
        "connection_options": dict(db_options),
    }


def _reject_forbidden_production_dsn(label: str, raw_dsn: str, info: dict) -> None:
    lowered = raw_dsn.lower()
    for forbidden in FORBIDDEN_PRODUCTION_IDENTIFIERS:
        if (
            forbidden in info["host"]
            or forbidden in info["dbname"].lower()
            or forbidden in info["username"].lower()
            or forbidden in lowered
        ):
            raise ValueError(f"{label} matches forbidden production identifier {forbidden!r}")


def validate_cutover_database_urls(
    owner_dsn: str,
    app_dsn: str,
    *,
    old_dsn: str | None = None,
) -> dict:
    """Ensure admin and app URLs target the exact same replacement staging database."""
    owner_info = _parse_postgres_dsn(owner_dsn, "admin_database_url")
    app_info = _parse_postgres_dsn(app_dsn, "app_database_url")

    for label, raw_dsn, info in (
        ("admin_database_url", owner_dsn, owner_info),
        ("app_database_url", app_dsn, app_info),
    ):
        _reject_forbidden_production_dsn(label, raw_dsn, info)
        lowered = raw_dsn.lower()
        for old_id in EXPIRING_STAGING_DB_IDS:
            if old_id in info["host"] or old_id in lowered:
                raise ValueError(
                    f"{label} points to expiring staging database {old_id!r}; "
                    "cutover requires a replacement staging database"
                )
        for unverified_id in UNVERIFIED_STAGING_DB_IDS:
            if unverified_id in info["host"] or unverified_id in lowered:
                raise ValueError(
                    f"{label} points to unverified database {unverified_id!r}; "
                    "cutover requires a newly created replacement staging database"
                )

    owner_target = (owner_info["host"], owner_info["port"], owner_info["dbname"])
    app_target = (app_info["host"], app_info["port"], app_info["dbname"])
    if owner_target != app_target:
        raise ValueError(
            "admin_database_url and app_database_url must target the exact same "
            f"(host, port, dbname); got {owner_target} vs {app_target}"
        )

    if app_info["username"] != "foodlogger_app":
        raise ValueError(
            f"app_database_url must authenticate as 'foodlogger_app' (got {app_info['username']!r})"
        )
    if owner_info["username"] == app_info["username"]:
        raise ValueError(
            "admin_database_url and app_database_url must use distinct roles "
            "(owner vs foodlogger_app)"
        )

    if old_dsn:
        old_info = _parse_postgres_dsn(old_dsn, "old_database_url")
        _reject_forbidden_production_dsn("old_database_url", old_dsn, old_info)
        old_target = (old_info["host"], old_info["port"], old_info["dbname"])
        if old_target == owner_target or old_info["host"] == owner_info["host"]:
            raise ValueError(
                "old_database_url and replacement target database must not be the same instance"
            )
        old_host = old_info["host"].lower().rstrip(".")
        valid_old_host = any(
            old_host == old_id
            or bool(
                re.fullmatch(
                    rf"{re.escape(old_id)}\.[a-z0-9-]+-postgres\.render\.com",
                    old_host,
                )
            )
            for old_id in EXPIRING_STAGING_DB_IDS
        )
        if not valid_old_host:
            raise ValueError(
                f"old_database_url host {old_info['host']!r} does not match expected expiring "
                f"staging database identifiers {list(EXPIRING_STAGING_DB_IDS)}. If Render shows "
                "a different active database, stop and report it (runbook Step 2.0)."
            )

    return {
        "host": owner_info["host"],
        "port": owner_info["port"],
        "dbname": owner_info["dbname"],
        "admin_user": owner_info["username"],
        "app_user": app_info["username"],
    }


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
        "rehearsal_mode": "offline_sqlite_translation_plus_static_rls_manifest_contract",
        "migration_count": len(verified_manifest),
        "tables_created": len(tables),
        "static_rls_manifest_table_count": len(EXPECTED_TABLES),
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


def _git_binary() -> str:
    git_bin = shutil.which("git") or r"C:\Program Files\Git\cmd\git.exe"
    if not Path(git_bin).exists():
        raise AssertionError("git is required to verify the nutrition fix commits")
    return git_bin


def _git_ok(root: Path, *args: str) -> bool:
    res = subprocess.run([_git_binary(), "-C", str(root), *args], capture_output=True)
    return res.returncode == 0


def _git_output(root: Path, *args: str) -> str:
    return subprocess.check_output([_git_binary(), "-C", str(root), *args], text=True).strip()


def _require_commit_sha(commit: str | None) -> str:
    sha = (commit or "").strip().lower()
    if not re.fullmatch(r"[0-9a-f]{7,40}", sha):
        raise ValueError(f"expected_commit must be a 7-40 character hex git SHA (got {commit!r})")
    return sha


def verify_nutrition_fix_behavior(root: Path, commits: list[str]) -> dict[str, int]:
    """Run each commit's catalog contract against root's own code and catalog data."""
    package = (root / "src" / "foodlogger").resolve()
    cases = [(commit, *case) for commit in commits for case in NUTRITION_FIX_CONTRACTS[commit]]
    # An empty cache location makes Python compile the verified source: a tolerated
    # __pycache__ entry in the target could otherwise supply different code under the same path.
    with tempfile.TemporaryDirectory(prefix="biteflow-contract-cache-") as empty_cache:
        run = subprocess.run(
            [
                sys.executable,
                "-I",
                "-B",
                "-c",
                CATALOG_CONTRACT_RUNNER,
                str(package),
                json.dumps([[query, preparation] for _, query, preparation, _, _ in cases]),
                empty_cache,
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )
    if run.returncode != 0:
        raise AssertionError(
            f"Catalog contract run failed against {package}: {run.stderr[-500:].strip()}"
        )
    output = json.loads(run.stdout)
    for used in output["used"]:
        if not used or not Path(used).resolve().is_relative_to(package):
            raise AssertionError(f"Catalog contract used {used!r}, outside {package}")
    checked: dict[str, int] = {}
    for (commit, query, preparation, required_top, forbidden), ids in zip(
        cases, output["results"], strict=True
    ):
        if (required_top and ids[:1] != [required_top]) or forbidden in ids:
            raise AssertionError(
                f"Nutrition fix {commit} regressed for {query!r} ({preparation}): {ids[:3]}"
            )
        checked[commit] = checked.get(commit, 0) + 1
    return checked


def verify_commit_and_nutrition_fixes(
    root: Path = ROOT,
    target_commit: str = "HEAD",
    *,
    allow_behavioral_fallback: bool = False,
) -> dict:
    """Require the nutrition fixes in target_commit, by proven git ancestry by default.

    Only local-verify sets allow_behavioral_fallback. A commit absent from a shallow clone
    then falls back to catalog contracts, when they exercise target_commit: the checked-out
    HEAD, with nothing but bytecode caches differing from it under src/foodlogger.
    """
    ancestors: dict[str, bool] = {}
    ancestry_unverifiable: list[str] = []
    behavioral_contract: dict[str, int] = {}
    if not _git_ok(root, "rev-parse", "--verify", "--quiet", f"{target_commit}^{{commit}}"):
        raise AssertionError(
            f"Cannot prove nutrition fix ancestry: {target_commit} is not a commit in {root}. "
            "Fetch full history and retry."
        )
    head_sha = _git_output(root, "rev-parse", "--verify", f"{target_commit}^{{commit}}")
    shallow = _git_output(root, "rev-parse", "--is-shallow-repository") == "true"
    for commit in REQUIRED_NUTRITION_COMMITS:
        if _git_ok(root, "cat-file", "-e", f"{commit}^{{commit}}"):
            ancestors[commit] = _git_ok(root, "merge-base", "--is-ancestor", commit, head_sha)
        elif shallow:
            ancestry_unverifiable.append(commit)
        else:
            ancestors[commit] = False
    if not all(ancestors.values()):
        raise AssertionError(
            f"Missing required nutrition commits in {target_commit} ({head_sha}): {ancestors}"
        )
    if ancestry_unverifiable:
        if not allow_behavioral_fallback:
            raise AssertionError(
                f"Unproven ancestry of {ancestry_unverifiable} in {target_commit} ({head_sha}): "
                "this mode needs full history. Run `git fetch --unshallow` and retry."
            )
        if head_sha != _git_output(root, "rev-parse", "HEAD"):
            raise AssertionError(
                f"Shallow clone cannot verify {ancestry_unverifiable} in {target_commit} "
                f"({head_sha}): catalog contracts only exercise the checked-out HEAD"
            )
        changes = [
            line
            for line in _git_output(
                root,
                "status",
                "--porcelain",
                "--ignored",
                "--untracked-files=all",
                "--",
                "src/foodlogger",
            ).splitlines()
            if "__pycache__" not in line.split("/")
        ]
        if changes:
            raise AssertionError(
                f"Shallow clone cannot verify {ancestry_unverifiable}: src/foodlogger "
                f"differs from HEAD: {changes[:5]}"
            )
        behavioral_contract = verify_nutrition_fix_behavior(root, ancestry_unverifiable)
    return {
        "head_sha": head_sha,
        "required_nutrition_commits": ancestors,
        "ancestry_unverifiable": ancestry_unverifiable,
        "behavioral_contract": behavioral_contract,
    }


def require_proven_ancestry(
    root: Path, commit: str | None, *, must_be_checked_out: bool = False
) -> str:
    """Pre-flight for live modes: run before any connection, request, or write."""
    sha = _require_commit_sha(commit)
    resolved = verify_commit_and_nutrition_fixes(root, target_commit=sha)["head_sha"]
    if must_be_checked_out and resolved != _git_output(root, "rev-parse", "HEAD"):
        raise AssertionError(
            f"expected_commit {sha} is not the checked-out HEAD, which supplies the migrations"
        )
    return resolved


def verify_deployed_commit_sha(
    health_body: dict,
    expected_commit: str,
    *,
    headers: dict | None = None,
    root: Path = ROOT,
) -> str:
    """Verify /api/health reports expected_commit or a descendant, with proven ancestry."""
    expected = _require_commit_sha(expected_commit)
    hdrs = {k.lower(): v for k, v in (headers or {}).items()}
    reported_raw = (
        health_body.get("commit")
        or health_body.get("commit_sha")
        or health_body.get("git_sha")
        or health_body.get("sha")
        or health_body.get("revision")
        or hdrs.get("x-render-git-commit")
        or hdrs.get("x-git-commit")
    )
    if not reported_raw or not isinstance(reported_raw, str):
        raise AssertionError(
            f"/api/health did not report a deployed commit SHA (expected {expected!r}, "
            f"payload={health_body})"
        )
    reported = reported_raw.strip().lower()
    if not re.fullmatch(r"[0-9a-f]{7,40}", reported):
        raise AssertionError(f"/api/health reported an invalid commit SHA: {reported_raw!r}")

    prefix_match = reported.startswith(expected) or expected.startswith(reported)
    if not prefix_match and not _git_ok(root, "merge-base", "--is-ancestor", expected, reported):
        raise AssertionError(
            f"Deployed commit SHA mismatch on /api/health: reported {reported!r} "
            f"does not match or descend from expected {expected!r}"
        )

    verify_commit_and_nutrition_fixes(root, target_commit=reported)
    return reported


def verify_app_connection_posture(app_conn) -> dict:
    """Verify TLS, current_user/session_user, 0 owned tables, and 36 RLS tables."""
    tls_row = app_conn.execute(TLS_VERIFICATION_SQL).fetchone()
    if not tls_row or not tls_row.get("ssl"):
        raise AssertionError(f"TLS verification failed on app connection: {tls_row}")

    role_row = app_conn.execute(ROLE_VERIFICATION_SQL).fetchone()
    if not role_row:
        raise AssertionError("Role verification query returned no rows on app connection")

    current_user = role_row.get("current_user", role_row.get("rolname"))
    session_user = role_row.get("session_user", current_user)
    rolname = role_row.get("rolname")
    if (
        current_user != "foodlogger_app"
        or session_user != "foodlogger_app"
        or rolname != "foodlogger_app"
    ):
        raise AssertionError(
            "App connection is not authenticated as non-owner role 'foodlogger_app': "
            f"current_user={current_user!r}, session_user={session_user!r}, rolname={rolname!r}"
        )

    forbidden_flags = ("rolsuper", "rolcreatedb", "rolcreaterole", "rolbypassrls", "rolinherit")
    if any(bool(role_row.get(k)) for k in forbidden_flags):
        raise AssertionError(f"foodlogger_app has unexpected privilege flags: {role_row}")

    public_owned = int(role_row.get("public_owned_tables", 0) or 0)
    total_owned = int(role_row.get("total_owned_tables", 0) or 0)
    if public_owned != 0 or total_owned != 0 or bool(role_row.get("tableowner")):
        raise AssertionError(
            "foodlogger_app must not own any tables in public or foodlogger schemas: "
            f"public_owned_tables={public_owned}, total_owned_tables={total_owned}, row={role_row}"
        )

    rls_rows = app_conn.execute(RLS_TABLES_VERIFICATION_SQL).fetchall()
    if [r["table_name"] for r in rls_rows] != list(EXPECTED_TABLES) or not all(
        r["rls_enabled"] for r in rls_rows
    ):
        raise AssertionError("Not all 36 foodlogger tables have RLS enabled on app connection")

    return {
        "app_role": dict(role_row),
        "tls": dict(tls_row),
        "rls_tables": [dict(r) for r in rls_rows],
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


def run_smoke_against_client(
    client,
    *,
    check_ai: bool = True,
    expected_commit: str | None = None,
    allow_staging_host: str | None = None,
    root: Path = ROOT,
) -> dict:
    base_url = str(getattr(client, "base_url", "") or "").rstrip("/")
    if base_url != "http://testserver":
        validate_staging_origin(base_url, allow_staging_host=allow_staging_host)
        if not expected_commit:
            raise ValueError("Smoke against a hosted origin requires expected_commit")

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

    verified_commit = None
    if expected_commit is not None:
        verified_commit = verify_deployed_commit_sha(
            health_body,
            expected_commit,
            headers=dict(getattr(health, "headers", {}) or {}),
            root=root,
        )
        checks.append(
            {
                "name": "deployed commit sha",
                "status": 200,
                "expected": expected_commit,
                "reported": verified_commit,
                "pass": True,
            }
        )

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
        "verified_commit": verified_commit,
        "ai_probe": ai_probe,
    }


def run_hosted_smoke(
    origin: str,
    *,
    expected_commit: str,
    allow_live_ai: bool = False,
    allow_staging_host: str | None = None,
    client=None,
    root: Path = ROOT,
) -> dict:
    """Validate staging origin and expected commit SHA before running hosted smoke."""
    validated_origin = validate_staging_origin(origin, allow_staging_host=allow_staging_host)
    if not expected_commit or not expected_commit.strip():
        raise ValueError("hosted-smoke requires --expected-commit to verify /api/health SHA")
    require_proven_ancestry(root, expected_commit)
    if client is not None:
        return run_smoke_against_client(
            client,
            check_ai=allow_live_ai,
            expected_commit=expected_commit,
            allow_staging_host=allow_staging_host,
            root=root,
        )
    with httpx.Client(base_url=validated_origin, timeout=30.0, trust_env=False) as http_client:
        return run_smoke_against_client(
            http_client,
            check_ai=allow_live_ai,
            expected_commit=expected_commit,
            allow_staging_host=allow_staging_host,
            root=root,
        )


def run_local_verification(root: Path = ROOT) -> dict:
    imported = Path(foodlogger.__file__).resolve().parent
    if imported != (root / "src" / "foodlogger").resolve():
        raise AssertionError(
            f"local-verify imported foodlogger from a different checkout: {imported}"
        )
    blueprints = verify_render_blueprints(root)
    commits = verify_commit_and_nutrition_fixes(root, allow_behavioral_fallback=True)
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
        "rehearsal_scope": "offline_sqlite_translation_plus_static_manifest_and_contract_checks",
        "overall_pass": True,
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
    app_password: str | None = None,
    *,
    old_dsn: str | None = None,
    resume_post_migration: bool = False,
    staging_url: str | None = None,
    expected_commit: str | None = None,
    allow_staging_host: str | None = None,
    allow_live_ai: bool = False,
    root: Path = ROOT,
) -> dict:
    import psycopg
    from psycopg import sql
    from psycopg.rows import dict_row

    # Phase 0: Pre-flight ancestry, target identity, TLS contract, and origin before connect/write.
    if not expected_commit:
        raise ValueError("cutover requires --expected-commit, the checked-out HEAD")
    require_proven_ancestry(root, expected_commit, must_be_checked_out=True)
    manifest = verify_migration_manifest(root)
    target_identity = validate_cutover_database_urls(owner_dsn, app_dsn, old_dsn=old_dsn)
    resolved_app_password = (
        app_password or _parse_postgres_dsn(app_dsn, "app_database_url")["password"]
    )
    if not resolved_app_password:
        raise ValueError(
            "An application role password is required via app_password or app_database_url"
        )
    if staging_url:
        validate_staging_origin(staging_url, allow_staging_host=allow_staging_host)

    # Phase 1: Optional read-only export of non-secret AI ledger from expiring staging database.
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

    # Phase 2: Owner DDL transaction (or verified resume when --resume-post-migration is set).
    owner_options = Database(owner_dsn).connection_options
    migration_transaction = "committed"
    with psycopg.connect(**owner_options, row_factory=dict_row) as conn:
        existing_rows = conn.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'foodlogger' ORDER BY table_name"
        ).fetchall()
        existing_tables = [r["table_name"] for r in existing_rows]
        existing = len(existing_tables)

        if existing == 0:
            if resume_post_migration:
                raise RuntimeError(
                    "--resume-post-migration was set, but schema foodlogger has 0 tables"
                )
            for rel_path, _ in MIGRATIONS:
                conn.execute((root / rel_path).read_text(encoding="utf-8"))
            conn.execute(
                sql.SQL("ALTER ROLE foodlogger_app LOGIN PASSWORD {}").format(
                    sql.Literal(resolved_app_password)
                )
            )
        elif resume_post_migration and tuple(existing_tables) == EXPECTED_TABLES:
            ver_row = conn.execute(
                "SELECT version FROM foodlogger.schema_version WHERE id = 1"
            ).fetchone()
            servings_row = conn.execute(
                "SELECT count(*) AS count FROM foodlogger.serving_conversions"
            ).fetchone()
            if not ver_row or ver_row["version"] != 2 or servings_row["count"] != 27:
                raise RuntimeError(
                    "Existing foodlogger schema does not match the completed 16-migration state"
                )
            conn.execute(
                sql.SQL("ALTER ROLE foodlogger_app LOGIN PASSWORD {}").format(
                    sql.Literal(resolved_app_password)
                )
            )
            migration_transaction = "resumed_existing_16_migration_schema"
        else:
            raise RuntimeError(
                f"Target database already has {existing} tables in schema foodlogger; "
                "refusing to overwrite non-empty database. Use --resume-post-migration only "
                "when all 16 migrations (36 tables) were already committed."
            )

    # Phase 3: Verify app_conn TLS, current_user/session_user, 0 owned tables, and 36 RLS tables
    # BEFORE executing gateway.configure() or any app-connection write.
    app_database = Database(app_dsn)
    with psycopg.connect(**app_database.connection_options, row_factory=dict_row) as app_conn:
        posture = verify_app_connection_posture(app_conn)

    # Phase 4: Schema check and idempotent AI policy renewal on verified app_database.
    app_database.check_schema()
    gateway = AIGateway(app_database, STAGING_PROJECT_ID, enabled=True)
    policy = build_staging_ai_policy()
    gateway.configure(policy)

    # Phase 5: Optional hosted smoke verification against staging URL.
    hosted_smoke = None
    if staging_url:
        hosted_smoke = run_hosted_smoke(
            staging_url,
            expected_commit=expected_commit,
            allow_live_ai=allow_live_ai,
            allow_staging_host=allow_staging_host,
            root=root,
        )

    if hosted_smoke is None:
        scope = {
            "status": "database_phase_passed",
            "scope": "database_phase_only",
            "end_to_end_verification": "pending",
            "hosted_smoke": {
                "status": "NOT_RUN",
                "reason": (
                    "Staging still uses the old database until Step 2.2, and the smoke must not "
                    "write to it. --run-hosted-smoke was not set."
                ),
            },
            "outstanding_steps": [
                "Step 2.2: point staging DATABASE_URL at the replacement database and deploy",
                "Step 2.3: run --mode hosted-smoke against staging",
            ],
        }
    else:
        scope = {
            "status": "database_and_hosted_smoke_passed",
            "scope": "database_phase_and_hosted_smoke",
            "end_to_end_verification": "hosted_smoke_passed",
            "hosted_smoke": hosted_smoke,
            "outstanding_steps": [
                "Confirm staging DATABASE_URL uses the replacement database: "
                "the hosted smoke cannot detect which database staging uses",
            ],
        }
    return {
        **scope,
        "target_database": target_identity,
        "migration_transaction": migration_transaction,
        "migrations_applied": len(manifest),
        "tables_verified": len(posture["rls_tables"]),
        "app_role": posture["app_role"],
        "tls": posture["tls"],
        "ai_policy_verified_at": policy.verified_at.isoformat(),
        "exported_old_ledger": exported_ledger,
    }


def run_postgres_verify(app_dsn: str) -> dict:
    """Run read-only PostgreSQL TLS, role, non-owner, and 36-table RLS verification on app_dsn."""
    import psycopg
    from psycopg.rows import dict_row

    app_info = _parse_postgres_dsn(app_dsn, "app_database_url")
    for forbidden in FORBIDDEN_PRODUCTION_IDENTIFIERS:
        if forbidden in app_info["host"] or forbidden in app_dsn.lower():
            raise ValueError(f"Refusing to run postgres-verify against production: {forbidden}")
    if app_info["username"] != "foodlogger_app":
        raise ValueError(
            f"app_database_url must authenticate as 'foodlogger_app' (got {app_info['username']!r})"
        )
    app_database = Database(app_dsn)
    with psycopg.connect(**app_database.connection_options, row_factory=dict_row) as app_conn:
        posture = verify_app_connection_posture(app_conn)
    app_database.check_schema()
    return {
        "status": "passed",
        "mode": "postgres-verify",
        "tables_verified": len(posture["rls_tables"]),
        "app_role": posture["app_role"],
        "tls": posture["tls"],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mode",
        choices=("local-verify", "cutover", "postgres-verify", "hosted-smoke"),
        default="local-verify",
    )
    parser.add_argument(
        "--origin",
        "--staging-url",
        dest="origin",
        default=DEFAULT_STAGING_ORIGIN,
    )
    parser.add_argument("--allow-staging-host", default=None)
    parser.add_argument("--expected-commit", default=None)
    parser.add_argument("--admin-database-url", default=None)
    parser.add_argument("--app-database-url", default=None)
    parser.add_argument("--app-password", default=None)
    parser.add_argument("--old-database-url", default=None)
    parser.add_argument("--resume-post-migration", action="store_true")
    parser.add_argument(
        "--run-hosted-smoke",
        action="store_true",
        help="After cutover, also smoke --origin. Only once staging uses the replacement DB.",
    )
    parser.add_argument("--allow-live-ai", action="store_true")
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args(argv)

    if args.mode == "local-verify":
        report = run_local_verification(ROOT)
    elif args.mode == "cutover":
        owner_dsn = (
            args.admin_database_url
            or os.getenv("STAGING_ADMIN_DATABASE_URL")
            or os.environ["STAGING_OWNER_DATABASE_URL"]
        )
        app_dsn = args.app_database_url or os.environ["STAGING_DATABASE_URL"]
        app_password = args.app_password or os.getenv("STAGING_APP_PASSWORD")
        old_dsn = args.old_database_url or os.getenv("OLD_STAGING_DATABASE_URL")
        report = apply_postgres_cutover(
            owner_dsn,
            app_dsn,
            app_password,
            old_dsn=old_dsn,
            resume_post_migration=args.resume_post_migration,
            staging_url=args.origin if args.run_hosted_smoke else None,
            expected_commit=args.expected_commit or os.getenv("EXPECTED_COMMIT"),
            allow_staging_host=args.allow_staging_host,
            allow_live_ai=args.allow_live_ai,
            root=ROOT,
        )
    elif args.mode == "postgres-verify":
        app_dsn = args.app_database_url or os.environ["STAGING_DATABASE_URL"]
        report = run_postgres_verify(app_dsn)
    else:
        expected_commit = (
            args.expected_commit
            or os.getenv("EXPECTED_COMMIT")
            or verify_commit_and_nutrition_fixes(ROOT)["head_sha"]
        )
        report = run_hosted_smoke(
            args.origin,
            expected_commit=expected_commit or "",
            allow_live_ai=args.allow_live_ai,
            allow_staging_host=args.allow_staging_host,
            root=ROOT,
        )

    rendered = json.dumps(report, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    if report.get("outstanding_steps"):
        print(
            f"{report['status']}. Still outstanding:",
            *report["outstanding_steps"],
            sep="\n- ",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
