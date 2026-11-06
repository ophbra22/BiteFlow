"""Stage 0 regressions for render.yaml, 16-migration cutover, and staging smoke safety gates."""

import importlib.util
import json
import os
import py_compile
import shutil
import ssl
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/staging_db_cutover.py"


def _load_cutover_module():
    spec = importlib.util.spec_from_file_location("staging_db_cutover", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_render_blueprints_disable_auto_deploy():
    module = _load_cutover_module()
    result = module.verify_render_blueprints(ROOT)
    assert result == {
        "render_yaml_auto_deploy_off": True,
        "staging_yaml_auto_deploy_off": True,
    }


def test_all_16_migrations_apply_cleanly_to_fresh_database(tmp_path):
    module = _load_cutover_module()
    report = module.apply_migrations_to_sqlite(tmp_path / "fresh.sqlite3", ROOT)
    assert report["migration_count"] == 16
    assert report["tables_created"] == 36
    assert tuple(report["tables"]) == module.EXPECTED_TABLES
    assert report["schema_version"] == 2
    assert report["serving_conversions"] == 27
    assert report["foundation_migrations"] == ["p01-ai-v1", "p01-journal-v1", "p03-goals-v1"]


def test_local_verification_covers_health_commits_tls_role_and_synthetic_ai():
    module = _load_cutover_module()
    report = module.run_local_verification(ROOT)
    assert report["overall_pass"] is True
    assert report["blueprints"]["render_yaml_auto_deploy_off"] is True
    assert report["migrations"]["migration_count"] == 16
    assert report["migrations"]["tables_created"] == 36
    assert report["tls_and_role_contract"]["sslmode"] == "verify-full"
    assert report["tls_and_role_contract"]["trusted_ca_count"] > 0
    assert "WHERE rolname = current_user" in report["tls_and_role_contract"]["role_query"]
    assert "current_user" in report["tls_and_role_contract"]["role_query"]
    assert "session_user" in report["tls_and_role_contract"]["role_query"]
    assert "tableowner = current_user" in report["tls_and_role_contract"]["role_query"]
    assert report["smoke"]["status"] == "passed"
    assert report["smoke"]["check_count"] == 21
    assert report["smoke"]["health"]["status"] == "ok"
    assert report["smoke"]["ai_probe"]["ai_status"] == "used"
    assert report["smoke"]["ai_probe"]["all_unconfirmed"] is True
    assert report["smoke"]["ai_probe"]["no_auto_save"] is True
    assert report["smoke"]["ai_probe"]["first_reference_id"] == "fdc:173423"
    assert report["ai_ledger"]["used_requests"] == 1
    assert report["ai_ledger"]["features"]["text"] == 1


@pytest.mark.parametrize(
    "bad_origin",
    [
        "http://biteflow-staging-api.onrender.com",
        "https://foodlogger-staging.onrender.com",  # no repository evidence for this host
        "https://foodlogger.onrender.com",
        "https://srv-d6q76n5m5p6s73f9k590.onrender.com",
        "https://slnmporlcbqnnkyebdmv.supabase.co",
        "https://evil.example.com",
        "https://user:pass@biteflow-staging-api.onrender.com",
    ],
)
def test_hosted_smoke_rejects_http_or_non_staging_origin_before_any_request(bad_origin):
    module = _load_cutover_module()
    calls: list[str] = []

    class _RecordingClient:
        base_url = bad_origin

        def get(self, path, **kwargs):
            calls.append(f"GET {path}")
            raise AssertionError("No HTTP request should be sent for an invalid origin")

        def post(self, path, **kwargs):
            calls.append(f"POST {path}")
            raise AssertionError("No HTTP request should be sent for an invalid origin")

    with pytest.raises(ValueError):
        module.run_hosted_smoke(
            bad_origin,
            expected_commit="4a9d6b60c9304254136dd1eb7fb15f0b57968155",
            client=_RecordingClient(),
        )
    assert calls == []


@pytest.mark.parametrize(
    ("owner_dsn", "app_dsn", "match"),
    [
        (
            "postgresql://owner:pw@dpg-new-a.frankfurt-postgres.render.com:5432/biteflow_staging_db",
            "postgresql://foodlogger_app:pw@dpg-other-a.frankfurt-postgres.render.com:5432/biteflow_staging_db",
            "exact same",
        ),
        (
            "postgresql://owner:pw@dpg-new-a.frankfurt-postgres.render.com:5432/biteflow_staging_db",
            "postgresql://foodlogger_app:pw@dpg-new-a.frankfurt-postgres.render.com:5433/biteflow_staging_db",
            "exact same",
        ),
        (
            "postgresql://owner:pw@dpg-new-a.frankfurt-postgres.render.com:5432/biteflow_staging_db",
            "postgresql://foodlogger_app:pw@dpg-new-a.frankfurt-postgres.render.com:5432/other_db",
            "exact same",
        ),
        (
            "postgresql://foodlogger_app:pw@dpg-new-a.frankfurt-postgres.render.com:5432/biteflow_staging_db",
            "postgresql://foodlogger_app:pw@dpg-new-a.frankfurt-postgres.render.com:5432/biteflow_staging_db",
            "distinct roles",
        ),
        (
            "postgresql://owner:pw@dpg-new-a.frankfurt-postgres.render.com:5432/biteflow_staging_db",
            "postgresql://postgres:pw@dpg-new-a.frankfurt-postgres.render.com:5432/biteflow_staging_db",
            "foodlogger_app",
        ),
        (
            "postgresql://owner:pw@dpg-dbbhudvavr4c73duk09g-a.frankfurt-postgres.render.com/biteflow_staging_db",
            "postgresql://foodlogger_app:pw@dpg-dbbhudvavr4c73duk09g-a.frankfurt-postgres.render.com/biteflow_staging_db",
            "expiring staging database",
        ),
        (
            "postgresql://owner:pw@dpg-d6q76n5m5p6s73f9k58g-a.frankfurt-postgres.render.com/biteflow_staging_db",
            "postgresql://foodlogger_app:pw@dpg-d6q76n5m5p6s73f9k58g-a.frankfurt-postgres.render.com/biteflow_staging_db",
            "unverified database",
        ),
        (
            "postgresql://owner:pw@db.slnmporlcbqnnkyebdmv.supabase.co:5432/postgres",
            "postgresql://foodlogger_app:pw@db.slnmporlcbqnnkyebdmv.supabase.co:5432/postgres",
            "forbidden production identifier",
        ),
    ],
)
def test_validate_cutover_database_urls_rejects_mismatched_or_unsafe_targets(
    owner_dsn, app_dsn, match
):
    module = _load_cutover_module()
    with pytest.raises(ValueError, match=match):
        module.validate_cutover_database_urls(owner_dsn, app_dsn)


@pytest.mark.parametrize(
    ("bad_role_row", "expected_error"),
    [
        (
            {
                "current_user": "biteflow_staging_db_user",
                "session_user": "biteflow_staging_db_user",
                "rolname": "biteflow_staging_db_user",
                "rolsuper": False,
                "rolcreatedb": False,
                "rolcreaterole": False,
                "rolbypassrls": False,
                "rolinherit": False,
                "public_owned_tables": 0,
                "total_owned_tables": 0,
            },
            "not authenticated as non-owner role 'foodlogger_app'",
        ),
        (
            {
                "current_user": "foodlogger_app",
                "session_user": "foodlogger_app",
                "rolname": "foodlogger_app",
                "rolsuper": True,
                "rolcreatedb": False,
                "rolcreaterole": False,
                "rolbypassrls": False,
                "rolinherit": False,
                "public_owned_tables": 0,
                "total_owned_tables": 0,
            },
            "unexpected privilege flags",
        ),
        (
            {
                "current_user": "foodlogger_app",
                "session_user": "foodlogger_app",
                "rolname": "foodlogger_app",
                "rolsuper": False,
                "rolcreatedb": False,
                "rolcreaterole": False,
                "rolbypassrls": False,
                "rolinherit": False,
                "public_owned_tables": 2,
                "total_owned_tables": 2,
            },
            "must not own any tables",
        ),
    ],
)
def test_cutover_rejects_bad_app_role_or_owned_tables_before_gateway_configure(
    monkeypatch, bad_role_row, expected_error
):
    module = _load_cutover_module()
    configure_calls: list[object] = []
    monkeypatch.setattr(
        module.AIGateway,
        "configure",
        lambda self, policy: configure_calls.append(policy),
    )
    monkeypatch.setattr(module.Database, "check_schema", lambda self: 2)

    class _Result:
        def __init__(self, one=None, many=None):
            self._one = one
            self._many = many or []

        def fetchone(self):
            return self._one

        def fetchall(self):
            return self._many

    class _FakeOwnerConn:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def execute(self, query):
            text = str(query)
            if "information_schema.tables" in text:
                return _Result(many=[])
            return _Result()

    class _FakeAppConn:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def execute(self, query):
            text = str(query)
            if "pg_stat_ssl" in text:
                return _Result(
                    one={"ssl": True, "version": "TLSv1.3", "cipher": "TLS_AES_256_GCM_SHA384"}
                )
            if "FROM pg_roles" in text:
                return _Result(one=bad_role_row)
            if "relrowsecurity" in text:
                return _Result(
                    many=[
                        {"table_name": name, "rls_enabled": True} for name in module.EXPECTED_TABLES
                    ]
                )
            raise AssertionError(f"Unexpected query: {text}")

    def _fake_connect(**kwargs):
        if kwargs.get("user") == "foodlogger_app":
            return _FakeAppConn()
        return _FakeOwnerConn()

    import psycopg

    monkeypatch.setattr(psycopg, "connect", _fake_connect)

    owner_dsn = (
        "postgresql://owner:ownerpass@dpg-replacement-a.frankfurt-postgres.render.com:5432/"
        "biteflow_staging_db"
    )
    app_dsn = (
        "postgresql://foodlogger_app:apppass@dpg-replacement-a.frankfurt-postgres.render.com:5432/"
        "biteflow_staging_db"
    )

    monkeypatch.setattr(module, "require_proven_ancestry", lambda *args, **kwargs: "fixture")
    with pytest.raises(AssertionError, match=expected_error):
        module.apply_postgres_cutover(
            owner_dsn, app_dsn, "apppass", expected_commit="4a9d6b6", root=ROOT
        )

    assert configure_calls == []


@pytest.mark.parametrize("staging_url", [None, "https://biteflow-staging-api.onrender.com"])
def test_cutover_resume_post_migration_succeeds_after_owner_migrations_committed(
    monkeypatch, staging_url
):
    module = _load_cutover_module()
    configure_calls: list[object] = []
    smoke_calls: list[str] = []

    def _fake_hosted_smoke(origin, **kwargs):
        smoke_calls.append(origin)
        return {"status": "passed"}

    monkeypatch.setattr(module, "run_hosted_smoke", _fake_hosted_smoke)
    monkeypatch.setattr(
        module.AIGateway,
        "configure",
        lambda self, policy: configure_calls.append(policy),
    )
    monkeypatch.setattr(module.Database, "check_schema", lambda self: 2)

    class _Result:
        def __init__(self, one=None, many=None):
            self._one = one
            self._many = many or []

        def fetchone(self):
            return self._one

        def fetchall(self):
            return self._many

    class _FakeOwnerConn:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def execute(self, query):
            text = str(query)
            if "information_schema.tables" in text:
                return _Result(many=[{"table_name": t} for t in module.EXPECTED_TABLES])
            if "foodlogger.schema_version" in text:
                return _Result(one={"version": 2})
            if "foodlogger.serving_conversions" in text:
                return _Result(one={"count": 27})
            return _Result()

    class _FakeAppConn:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def execute(self, query):
            text = str(query)
            if "pg_stat_ssl" in text:
                return _Result(
                    one={"ssl": True, "version": "TLSv1.3", "cipher": "TLS_AES_256_GCM_SHA384"}
                )
            if "FROM pg_roles" in text:
                return _Result(
                    one={
                        "current_user": "foodlogger_app",
                        "session_user": "foodlogger_app",
                        "rolname": "foodlogger_app",
                        "rolsuper": False,
                        "rolcreatedb": False,
                        "rolcreaterole": False,
                        "rolbypassrls": False,
                        "rolinherit": False,
                        "public_owned_tables": 0,
                        "total_owned_tables": 0,
                    }
                )
            if "relrowsecurity" in text:
                return _Result(
                    many=[
                        {"table_name": name, "rls_enabled": True} for name in module.EXPECTED_TABLES
                    ]
                )
            raise AssertionError(f"Unexpected query: {text}")

    def _fake_connect(**kwargs):
        if kwargs.get("user") == "foodlogger_app":
            return _FakeAppConn()
        return _FakeOwnerConn()

    import psycopg

    monkeypatch.setattr(psycopg, "connect", _fake_connect)

    owner_dsn = (
        "postgresql://owner:ownerpass@dpg-replacement-a.frankfurt-postgres.render.com:5432/"
        "biteflow_staging_db"
    )
    app_dsn = (
        "postgresql://foodlogger_app:apppass@dpg-replacement-a.frankfurt-postgres.render.com:5432/"
        "biteflow_staging_db"
    )
    monkeypatch.setattr(module, "require_proven_ancestry", lambda *args, **kwargs: "fixture")
    report = module.apply_postgres_cutover(
        owner_dsn,
        app_dsn,
        "apppass",
        resume_post_migration=True,
        expected_commit="4a9d6b6",
        staging_url=staging_url,
        root=ROOT,
    )
    assert report["migration_transaction"] == "resumed_existing_16_migration_schema"
    assert len(configure_calls) == 1
    # A successful database phase must never read as full verification.
    assert report["status"] != "passed"
    if staging_url is None:
        assert smoke_calls == []
        assert report["status"] == "database_phase_passed"
        assert report["scope"] == "database_phase_only"
        assert report["end_to_end_verification"] == "pending"
        assert report["hosted_smoke"]["status"] == "NOT_RUN"
        assert "old database" in report["hosted_smoke"]["reason"]
        assert [step.split(":")[0] for step in report["outstanding_steps"]] == [
            "Step 2.2",
            "Step 2.3",
        ]
    else:
        assert smoke_calls == [staging_url]
        assert report["status"] == "database_and_hosted_smoke_passed"
        assert report["end_to_end_verification"] == "hosted_smoke_passed"
        assert report["hosted_smoke"] == {"status": "passed"}
        assert "cannot detect" in report["outstanding_steps"][0]


def test_hosted_smoke_rejects_mismatched_commit_sha_before_any_writes(monkeypatch):
    module = _load_cutover_module()
    monkeypatch.setattr(module, "require_proven_ancestry", lambda *args, **kwargs: "fixture")
    requests_sent: list[str] = []

    class _FakeResponse:
        status_code = 200
        headers = {}

        def json(self):
            return {"status": "ok", "version": "2.1.0", "commit": "deadbeef1234567"}

    class _FakeStagingClient:
        base_url = "https://biteflow-staging-api.onrender.com"

        def get(self, path, **kwargs):
            requests_sent.append(f"GET {path}")
            if path == "/api/health":
                return _FakeResponse()
            raise AssertionError(f"Unexpected GET {path} after commit mismatch")

        def post(self, path, **kwargs):
            requests_sent.append(f"POST {path}")
            raise AssertionError(f"Unexpected write POST {path} after commit mismatch")

    with pytest.raises(AssertionError, match="Deployed commit SHA mismatch"):
        module.run_hosted_smoke(
            "https://biteflow-staging-api.onrender.com",
            expected_commit="4a9d6b60c9304254136dd1eb7fb15f0b57968155",
            client=_FakeStagingClient(),
        )
    assert requests_sent == ["GET /api/health"]


@pytest.mark.parametrize(
    "query_override",
    [
        "host=other-target.invalid",
        "hostaddr=198.51.100.10",
        "port=6543",
        "dbname=other_db",
        "user=other_user",
        "password=other_pass",
        "service=prod",
        "options=-csearch_path%3Dpublic",
        "target_session_attrs=read-write",
        "sslmode=disable",
    ],
)
def test_parse_postgres_dsn_rejects_query_parameter_overrides(query_override):
    module = _load_cutover_module()
    dsn = (
        "postgresql://foodlogger_app:pw@dpg-new-a.frankfurt-postgres.render.com:5432/"
        f"biteflow_staging_db?{query_override}"
    )
    with pytest.raises(ValueError):
        module._parse_postgres_dsn(dsn, "app_database_url")


@pytest.mark.parametrize(
    ("bad_old_dsn", "match"),
    [
        (
            "postgresql://foodlogger_app:pw@db.slnmporlcbqnnkyebdmv.supabase.co:5432/postgres",
            "forbidden production identifier",
        ),
        (
            "postgresql://foodlogger_app:pw@dpg-dbbhudvavr4c73duk09g-a.frankfurt-postgres.render.com/car_log",
            "forbidden production identifier",
        ),
        (
            "postgresql://foodlogger_app:pw@dpg-unrelated-a.frankfurt-postgres.render.com/biteflow_staging_db",
            "does not match expected expiring staging database",
        ),
        (
            "postgresql://foodlogger_app:pw@dpg-d6q76n5m5p6s73f9k58g-a.frankfurt-postgres.render.com/biteflow_staging_db",
            "does not match expected expiring staging database",
        ),
        (
            "postgresql://foodlogger_app:pw@dpg-dbbhudvavr4c73duk09g-a."
            "frankfurt-postgres.render.com.unapproved.invalid/biteflow_staging_db",
            "does not match expected expiring staging database",
        ),
        (
            "postgresql://foodlogger_app:pw@evil-dpg-dbbhudvavr4c73duk09g-a."
            "frankfurt-postgres.render.com/biteflow_staging_db",
            "does not match expected expiring staging database",
        ),
    ],
)
def test_validate_cutover_database_urls_enforces_production_and_legacy_checks_on_old_dsn(
    bad_old_dsn, match
):
    module = _load_cutover_module()
    owner_dsn = (
        "postgresql://owner:pw@dpg-replacement-a.frankfurt-postgres.render.com:5432/"
        "biteflow_staging_db"
    )
    app_dsn = (
        "postgresql://foodlogger_app:pw@dpg-replacement-a.frankfurt-postgres.render.com:5432/"
        "biteflow_staging_db"
    )
    with pytest.raises(ValueError, match=match):
        module.validate_cutover_database_urls(owner_dsn, app_dsn, old_dsn=bad_old_dsn)

    valid_old_dsn = (
        "postgresql://foodlogger_app:pw@dpg-dbbhudvavr4c73duk09g-a.frankfurt-postgres.render.com:5432/"
        "biteflow_staging_db?sslmode=verify-full"
    )
    validated = module.validate_cutover_database_urls(owner_dsn, app_dsn, old_dsn=valid_old_dsn)
    assert validated["host"] == "dpg-replacement-a.frankfurt-postgres.render.com"


def test_staging_identity_matches_the_release_readiness_record():
    module = _load_cutover_module()
    record = (ROOT / "docs/biteflow/release-readiness/testflight-rc12-15.md").read_text(
        encoding="utf-8"
    )
    # Empty tuples would pass both loops without checking anything.
    assert module.EXPIRING_STAGING_DB_IDS
    assert module.UNVERIFIED_STAGING_DB_IDS
    assert module.APPROVED_STAGING_HOSTS
    for db_id in module.EXPIRING_STAGING_DB_IDS:
        assert db_id in record
    for db_id in module.UNVERIFIED_STAGING_DB_IDS:
        assert db_id not in record
    for host in module.APPROVED_STAGING_HOSTS:
        assert host in record
    assert module.DEFAULT_STAGING_ORIGIN in record
    assert module.validate_staging_origin(module.DEFAULT_STAGING_ORIGIN)


@pytest.mark.parametrize(
    "origin",
    [
        "https://foodlogger-yfn4.onrender.com",
        "https://FOODLOGGER-YFN4.ONRENDER.COM",
        "https://foodlogger-yfn4.onrender.com.",
        "https://foodlogger-yfn4.onrender.com:443/",
    ],
)
@pytest.mark.parametrize("override", [None, "foodlogger-yfn4.onrender.com", "other.example"])
def test_real_production_host_is_refused_with_or_without_the_override(origin, override):
    module = _load_cutover_module()
    with pytest.raises(ValueError, match="production identifier"):
        module.validate_staging_origin(origin, allow_staging_host=override)


def test_production_host_override_alone_is_refused():
    module = _load_cutover_module()
    with pytest.raises(ValueError, match="cannot override production identifier"):
        module.validate_staging_origin(
            module.DEFAULT_STAGING_ORIGIN, allow_staging_host="FOODLOGGER-YFN4.onrender.com"
        )


def test_production_url_in_the_mobile_build_config_is_refused():
    module = _load_cutover_module()
    eas = json.loads((ROOT / "mobile/eas.json").read_text(encoding="utf-8"))
    production_url = eas["build"]["production"]["env"]["EXPO_PUBLIC_API_URL"]
    with pytest.raises(ValueError, match="production identifier"):
        module.validate_staging_origin(
            production_url, allow_staging_host=production_url.removeprefix("https://")
        )


def test_cli_hosted_smoke_refuses_production_before_opening_a_client(monkeypatch):
    module = _load_cutover_module()

    def no_client(*args, **kwargs):
        raise RuntimeError("no HTTP client may open against production")

    monkeypatch.setattr(module.httpx, "Client", no_client)
    with pytest.raises(ValueError, match="production identifier"):
        module.main(
            [
                "--mode",
                "hosted-smoke",
                "--origin",
                "https://foodlogger-yfn4.onrender.com",
                "--allow-staging-host",
                "foodlogger-yfn4.onrender.com",
                "--expected-commit",
                "4a9d6b6",
            ]
        )


def test_cutover_smoke_refuses_production_before_any_connection(connections, monkeypatch):
    module = _load_cutover_module()
    monkeypatch.setattr(module, "require_proven_ancestry", lambda *args, **kwargs: "fixture")
    with pytest.raises(ValueError, match="production identifier"):
        module.apply_postgres_cutover(
            OWNER_DSN,
            APP_DSN,
            "apppass",
            staging_url="https://foodlogger-yfn4.onrender.com",
            allow_staging_host="foodlogger-yfn4.onrender.com",
            expected_commit="4a9d6b6",
            root=ROOT,
        )
    assert connections == []


NEON_HOST = "ep-fixture-123456.eu-central-1.aws.neon.tech"
NEON_POOLED_HOST = "ep-fixture-123456-pooler.eu-central-1.aws.neon.tech"


def test_direct_neon_urls_pass_the_cutover_target_checks():
    module = _load_cutover_module()
    target = module.validate_cutover_database_urls(
        f"postgresql://neondb_owner:pw@{NEON_HOST}/neondb?sslmode=verify-full",
        f"postgresql://foodlogger_app:pw@{NEON_HOST}/neondb?sslmode=verify-full",
    )
    assert target["host"] == NEON_HOST
    assert target["admin_user"] == "neondb_owner"


@pytest.mark.parametrize(
    "owner_host,app_host",
    [(NEON_POOLED_HOST, NEON_POOLED_HOST), (NEON_HOST, NEON_POOLED_HOST)],
)
def test_pooled_endpoints_are_refused_for_cutover(owner_host, app_host):
    module = _load_cutover_module()
    with pytest.raises(ValueError, match="pooled endpoint"):
        module.validate_cutover_database_urls(
            f"postgresql://neondb_owner:pw@{owner_host}/neondb",
            f"postgresql://foodlogger_app:pw@{app_host}/neondb",
        )


@pytest.mark.parametrize(
    "query,match",
    [
        ("sslmode=require", "verify-full"),
        ("sslmode=verify-full&channel_binding=require", "channel_binding"),
    ],
)
def test_weaker_or_extra_neon_url_parameters_are_refused(query, match):
    module = _load_cutover_module()
    with pytest.raises(ValueError, match=match):
        module.validate_cutover_database_urls(
            f"postgresql://neondb_owner:pw@{NEON_HOST}/neondb?{query}",
            f"postgresql://foodlogger_app:pw@{NEON_HOST}/neondb",
        )


def test_unlisted_staging_host_needs_the_explicit_override():
    module = _load_cutover_module()
    origin = "https://foodlogger-staging.onrender.com"
    with pytest.raises(ValueError, match="Unapproved staging host"):
        module.validate_staging_origin(origin)
    assert module.validate_staging_origin(
        origin, allow_staging_host="foodlogger-staging.onrender.com"
    )


def test_parse_postgres_dsn_unquotes_percent_encoded_password():
    module = _load_cutover_module()
    dsn = (
        "postgresql://foodlogger_app:fixture%40only%231%252@"
        "dpg-replacement-a.frankfurt-postgres.render.com:5432/biteflow_staging_db?sslmode=verify-full"
    )
    parsed = module._parse_postgres_dsn(dsn, "app_database_url")
    assert parsed["password"] == "fixture@only#1%2"
    assert parsed["connection_options"]["password"] == "fixture@only#1%2"


def test_fastapi_health_endpoint_reports_render_git_commit(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from foodlogger.app import create_app
    from foodlogger.security import Settings

    module = _load_cutover_module()
    expected_sha = "4a9d6b60c9304254136dd1eb7fb15f0b57968155"
    monkeypatch.setenv("RENDER_GIT_COMMIT", expected_sha)
    proven: list[str] = []
    monkeypatch.setattr(
        module,
        "verify_commit_and_nutrition_fixes",
        lambda root, target_commit: proven.append(target_commit),
    )

    app = create_app(db_path=tmp_path / "health.sqlite3", settings=Settings())
    with TestClient(app) as client:
        resp = client.get("/api/health")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert body["commit"] == expected_sha
        assert module.verify_deployed_commit_sha(body, expected_sha, root=ROOT) == expected_sha
        assert proven == [expected_sha]
        with pytest.raises(AssertionError, match="Deployed commit SHA mismatch"):
            module.verify_deployed_commit_sha(body, "deadbeef1234567", root=ROOT)


GIT = shutil.which("git") or r"C:\Program Files\Git\cmd\git.exe"
NUTRITION_FILE = "src/foodlogger/nutrition_reference.py"
STAGING_ORIGIN = "https://biteflow-staging-api.onrender.com"
OWNER_DSN = (
    "postgresql://owner:ownerpass@dpg-replacement-a.frankfurt-postgres.render.com:5432/"
    "biteflow_staging_db"
)
APP_DSN = (
    "postgresql://foodlogger_app:apppass@dpg-replacement-a.frankfurt-postgres.render.com:5432/"
    "biteflow_staging_db"
)
OLD_DSN = "postgresql://foodlogger_app:oldpass@dpg-dbbhudvavr4c73duk09g-a/foodlogger"


def _git(cwd: Path, *args: str) -> str:
    identity = ("-c", "user.name=fixture", "-c", "user.email=fixture@example.invalid")
    return subprocess.check_output([GIT, "-C", str(cwd), *identity, *args], text=True).strip()


def _commit_file(repo: Path, relative: str, content: str | None) -> str:
    path = repo / relative
    if content is None:
        path.unlink()
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", f"change {relative}")
    return _git(repo, "rev-parse", "HEAD")


@pytest.fixture
def source_repo(tmp_path) -> Path:
    """A full repository with a working catalog and none of the real nutrition commits."""
    repo = tmp_path / "source"
    repo.mkdir()
    _git(repo, "init", "-q")
    shutil.copytree(
        ROOT / "src/foodlogger",
        repo / "src/foodlogger",
        ignore=shutil.ignore_patterns("__pycache__", "*.tflite", "static", "templates"),
    )
    _commit_file(repo, "marker.txt", "first\n")
    _commit_file(repo, "marker.txt", "second\n")
    return repo


def _shallow_clone(source: Path, target: Path, depth: int = 1) -> Path:
    subprocess.check_call(
        [GIT, "clone", "-q", "--depth", str(depth), source.as_uri(), str(target)],
        stderr=subprocess.DEVNULL,
    )
    assert _git(target, "rev-parse", "--is-shallow-repository") == "true"
    return target


class _ConnectionReached(Exception):
    pass


@pytest.fixture
def connections(monkeypatch) -> list[dict]:
    import psycopg

    opened: list[dict] = []

    def _record(**kwargs):
        opened.append(kwargs)
        raise _ConnectionReached

    monkeypatch.setattr(psycopg, "connect", _record)
    return opened


class _RecordingStagingClient:
    base_url = STAGING_ORIGIN

    def __init__(self):
        self.calls: list[str] = []

    def get(self, path, **kwargs):
        self.calls.append(f"GET {path}")
        raise AssertionError(f"Unexpected GET {path}")

    def post(self, path, **kwargs):
        self.calls.append(f"POST {path}")
        raise AssertionError(f"Unexpected POST {path}")


@pytest.fixture
def no_system_ca(monkeypatch):
    """Report a CA file only through SSL_CERT_FILE, as Python does on Windows."""
    monkeypatch.delenv("SSL_CERT_FILE", raising=False)
    paths = ssl.get_default_verify_paths()
    monkeypatch.setattr(
        ssl,
        "get_default_verify_paths",
        lambda: paths._replace(cafile=os.environ.get("SSL_CERT_FILE")),
    )


def test_ca_fallback_keeps_verify_full_and_does_not_leak(no_system_ca):
    module = _load_cutover_module()
    contract = module.verify_tls_and_role_contract()
    assert contract["sslmode"] == "verify-full"
    assert contract["trusted_ca_count"] > 0
    assert "SSL_CERT_FILE" not in os.environ

    parsed = module._parse_postgres_dsn(APP_DSN, "app_database_url")
    assert parsed["connection_options"]["sslmode"] == "verify-full"
    assert parsed["connection_options"]["sslrootcert"]
    assert "SSL_CERT_FILE" not in os.environ

    module.validate_cutover_database_urls(OWNER_DSN, APP_DSN)
    assert "SSL_CERT_FILE" not in os.environ


def test_ca_fallback_is_restored_when_a_cutover_fails(no_system_ca, connections, monkeypatch):
    module = _load_cutover_module()
    monkeypatch.setattr(module, "require_proven_ancestry", lambda *args, **kwargs: "fixture")
    with pytest.raises(_ConnectionReached):
        module.apply_postgres_cutover(
            OWNER_DSN, APP_DSN, "apppass", expected_commit="4a9d6b6", root=ROOT
        )
    assert connections[0]["sslmode"] == "verify-full"
    assert "SSL_CERT_FILE" not in os.environ


def test_ca_fallback_never_replaces_an_operator_setting(no_system_ca, tmp_path, monkeypatch):
    module = _load_cutover_module()
    operator_bundle = tmp_path / "operator-ca.pem"
    monkeypatch.setenv("SSL_CERT_FILE", str(operator_bundle))
    parsed = module._parse_postgres_dsn(APP_DSN, "app_database_url")
    assert parsed["connection_options"]["sslrootcert"] == str(operator_bundle)
    assert os.environ["SSL_CERT_FILE"] == str(operator_bundle)


def test_nutrition_contracts_cover_every_required_commit():
    module = _load_cutover_module()
    assert set(module.NUTRITION_FIX_CONTRACTS) == set(module.REQUIRED_NUTRITION_COMMITS)


def test_local_fallback_runs_contracts_against_the_target_clone(source_repo, tmp_path):
    module = _load_cutover_module()
    clone = _shallow_clone(source_repo, tmp_path / "clone")
    report = module.verify_commit_and_nutrition_fixes(clone, allow_behavioral_fallback=True)
    assert report["head_sha"] == _git(clone, "rev-parse", "HEAD")
    # Ancestry was not proven, so it must not be reported as proven.
    assert report["required_nutrition_commits"] == {}
    assert report["ancestry_unverifiable"] == list(module.REQUIRED_NUTRITION_COMMITS)
    assert report["behavioral_contract"] == {"089f789": 2, "3658a17": 3, "4a9d6b6": 2}


def test_fallback_is_off_unless_requested(source_repo, tmp_path):
    module = _load_cutover_module()
    clone = _shallow_clone(source_repo, tmp_path / "clone")
    with pytest.raises(AssertionError, match="Unproven ancestry"):
        module.verify_commit_and_nutrition_fixes(clone)


def test_fallback_detects_a_regression_in_the_target_not_the_imported_package(
    source_repo, tmp_path
):
    module = _load_cutover_module()
    regressed = (source_repo / NUTRITION_FILE).read_text(encoding="utf-8") + (
        "\n\nReferenceCatalog.search = lambda self, query, preparation='unknown', limit=8: []\n"
    )
    _commit_file(source_repo, NUTRITION_FILE, regressed)
    clone = _shallow_clone(source_repo, tmp_path / "clone")
    with pytest.raises(AssertionError, match="Nutrition fix 089f789 regressed"):
        module.verify_commit_and_nutrition_fixes(clone, allow_behavioral_fallback=True)


def test_broken_target_fails_while_a_working_package_is_imported_elsewhere(source_repo, tmp_path):
    import foodlogger

    module = _load_cutover_module()
    _commit_file(source_repo, NUTRITION_FILE, 'raise RuntimeError("fixture broken catalog")\n')
    clone = _shallow_clone(source_repo, tmp_path / "clone")
    assert not Path(foodlogger.__file__).is_relative_to(clone)
    with pytest.raises(AssertionError, match="fixture broken catalog"):
        module.verify_commit_and_nutrition_fixes(clone, allow_behavioral_fallback=True)


def test_target_without_a_regular_package_cannot_borrow_an_installed_one(source_repo, tmp_path):
    module = _load_cutover_module()
    _commit_file(source_repo, "src/foodlogger/__init__.py", None)
    clone = _shallow_clone(source_repo, tmp_path / "clone")
    with pytest.raises(AssertionError, match="outside|Catalog contract run failed"):
        module.verify_commit_and_nutrition_fixes(clone, allow_behavioral_fallback=True)


def test_target_without_catalog_data_fails(source_repo, tmp_path):
    module = _load_cutover_module()
    _commit_file(source_repo, "src/foodlogger/data/usda_reference.json", None)
    clone = _shallow_clone(source_repo, tmp_path / "clone")
    with pytest.raises(AssertionError, match="Catalog contract run failed"):
        module.verify_commit_and_nutrition_fixes(clone, allow_behavioral_fallback=True)


def test_fallback_rejects_a_target_other_than_checked_out_head(source_repo, tmp_path):
    module = _load_cutover_module()
    clone = _shallow_clone(source_repo, tmp_path / "clone", depth=2)
    with pytest.raises(AssertionError, match="only exercise the checked-out HEAD"):
        module.verify_commit_and_nutrition_fixes(
            clone, target_commit="HEAD~1", allow_behavioral_fallback=True
        )


@pytest.mark.parametrize(
    "shadow",
    [
        "src/foodlogger/nutrition_reference.py",  # modified tracked file
        "src/foodlogger/nutrition_reference/__init__.py",  # untracked package wins over the module
        "src/foodlogger/ignored_shadow.pyd",  # git-ignored extension module
    ],
)
def test_fallback_rejects_modified_untracked_and_ignored_package_files(
    source_repo, tmp_path, shadow
):
    module = _load_cutover_module()
    _commit_file(source_repo, ".gitignore", "*.pyd\n")
    clone = _shallow_clone(source_repo, tmp_path / "clone")
    target = clone / shadow
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("# locally changed\n", encoding="utf-8")
    with pytest.raises(AssertionError, match="differs from HEAD"):
        module.verify_commit_and_nutrition_fixes(clone, allow_behavioral_fallback=True)


def test_fallback_tolerates_bytecode_caches(source_repo, tmp_path):
    module = _load_cutover_module()
    _commit_file(source_repo, ".gitignore", "__pycache__/\n")
    clone = _shallow_clone(source_repo, tmp_path / "clone")
    cache = clone / "src/foodlogger/__pycache__/nutrition.cpython-312.pyc"
    cache.parent.mkdir()
    cache.write_bytes(b"")
    report = module.verify_commit_and_nutrition_fixes(clone, allow_behavioral_fallback=True)
    assert report["ancestry_unverifiable"] == list(module.REQUIRED_NUTRITION_COMMITS)


def test_cached_bytecode_cannot_replace_broken_committed_source(source_repo, tmp_path):
    module = _load_cutover_module()
    working_source = source_repo / NUTRITION_FILE
    working_copy = tmp_path / "working_nutrition_reference.py"
    working_copy.write_bytes(working_source.read_bytes())
    _commit_file(source_repo, ".gitignore", "__pycache__/\n")
    _commit_file(source_repo, NUTRITION_FILE, 'raise RuntimeError("fixture broken catalog")\n')
    clone = _shallow_clone(source_repo, tmp_path / "clone")
    target = clone / NUTRITION_FILE
    cache = Path(importlib.util.cache_from_source(str(target)))
    cache.parent.mkdir(exist_ok=True)
    py_compile.compile(
        str(working_copy),
        cfile=str(cache),
        doraise=True,
        invalidation_mode=py_compile.PycInvalidationMode.UNCHECKED_HASH,
    )

    # Control: without an isolated cache location this .pyc does replace the broken source.
    plain_import = subprocess.run(
        [
            sys.executable,
            "-I",
            "-B",
            "-c",
            "import sys; sys.path.insert(0, sys.argv[1]); import foodlogger.nutrition_reference",
            str(clone / "src"),
        ],
        capture_output=True,
    )
    assert plain_import.returncode == 0

    with pytest.raises(AssertionError, match="fixture broken catalog"):
        module.verify_commit_and_nutrition_fixes(clone, allow_behavioral_fallback=True)


def test_local_verification_rejects_a_root_other_than_the_imported_checkout(source_repo):
    module = _load_cutover_module()
    with pytest.raises(AssertionError, match="different checkout"):
        module.run_local_verification(source_repo)


def test_full_clone_without_the_commits_fails_without_behavior_fallback(source_repo, monkeypatch):
    module = _load_cutover_module()

    def must_not_run(root, commits):
        raise RuntimeError("catalog contracts must not replace ancestry in a full clone")

    monkeypatch.setattr(module, "verify_nutrition_fix_behavior", must_not_run)
    with pytest.raises(AssertionError, match="Missing required nutrition commits"):
        module.verify_commit_and_nutrition_fixes(source_repo, allow_behavioral_fallback=True)


def test_full_clone_rejects_a_present_commit_that_is_not_an_ancestor(source_repo, monkeypatch):
    module = _load_cutover_module()
    _git(source_repo, "checkout", "-q", "-b", "side")
    side_commit = _commit_file(source_repo, "marker.txt", "side\n")
    _git(source_repo, "checkout", "-q", "-")
    monkeypatch.setattr(module, "REQUIRED_NUTRITION_COMMITS", (side_commit,))
    with pytest.raises(AssertionError, match="Missing required nutrition commits"):
        module.verify_commit_and_nutrition_fixes(source_repo)


def test_shallow_clone_rejects_a_present_commit_that_is_not_an_ancestor(
    source_repo, tmp_path, monkeypatch
):
    module = _load_cutover_module()
    clone = _shallow_clone(source_repo, tmp_path / "clone", depth=2)
    head = _git(clone, "rev-parse", "HEAD")
    monkeypatch.setattr(module, "REQUIRED_NUTRITION_COMMITS", (head,))
    with pytest.raises(AssertionError, match="Missing required nutrition commits"):
        module.verify_commit_and_nutrition_fixes(clone, target_commit="HEAD~1")


def test_full_clone_reports_verified_ancestry(source_repo, monkeypatch):
    module = _load_cutover_module()
    ancestor = _git(source_repo, "rev-parse", "HEAD~1")
    monkeypatch.setattr(module, "REQUIRED_NUTRITION_COMMITS", (ancestor,))
    report = module.verify_commit_and_nutrition_fixes(source_repo)
    assert report["required_nutrition_commits"] == {ancestor: True}
    assert report["ancestry_unverifiable"] == []
    assert report["behavioral_contract"] == {}


def test_deployed_commit_gate_rejects_a_shallow_checkout(source_repo, tmp_path):
    module = _load_cutover_module()
    clone = _shallow_clone(source_repo, tmp_path / "clone")
    head = _git(clone, "rev-parse", "HEAD")
    with pytest.raises(AssertionError, match="Unproven ancestry"):
        module.verify_deployed_commit_sha({"commit": head}, head, root=clone)


def test_deployed_commit_gate_rejects_a_commit_absent_from_the_checkout(source_repo):
    module = _load_cutover_module()
    absent = "ab" * 20
    with pytest.raises(AssertionError, match="is not a commit in"):
        module.verify_deployed_commit_sha({"commit": absent}, absent, root=source_repo)


def test_hosted_smoke_rejects_unproven_ancestry_before_any_request(source_repo, tmp_path):
    module = _load_cutover_module()
    clone = _shallow_clone(source_repo, tmp_path / "clone")
    client = _RecordingStagingClient()
    with pytest.raises(AssertionError, match="Unproven ancestry"):
        module.run_hosted_smoke(
            STAGING_ORIGIN,
            expected_commit=_git(clone, "rev-parse", "HEAD"),
            client=client,
            root=clone,
        )
    assert client.calls == []


@pytest.mark.parametrize("expected_commit", ["", "   "])
def test_hosted_smoke_requires_expected_commit_before_any_request(expected_commit):
    module = _load_cutover_module()
    client = _RecordingStagingClient()
    with pytest.raises(ValueError, match="requires --expected-commit"):
        module.run_hosted_smoke(STAGING_ORIGIN, expected_commit=expected_commit, client=client)
    assert client.calls == []


def test_smoke_against_a_hosted_client_requires_expected_commit():
    module = _load_cutover_module()
    client = _RecordingStagingClient()
    with pytest.raises(ValueError, match="requires expected_commit"):
        module.run_smoke_against_client(client)
    assert client.calls == []


@pytest.mark.parametrize("cli_expected", [False, True])
def test_cli_hosted_smoke_rejects_a_shallow_checkout_before_opening_a_client(
    source_repo, tmp_path, monkeypatch, cli_expected
):
    module = _load_cutover_module()
    clone = _shallow_clone(source_repo, tmp_path / "clone")
    monkeypatch.delenv("EXPECTED_COMMIT", raising=False)
    monkeypatch.setattr(module, "ROOT", clone)

    def no_client(*args, **kwargs):
        raise RuntimeError("no HTTP client may open before ancestry is proven")

    monkeypatch.setattr(module.httpx, "Client", no_client)
    argv = ["--mode", "hosted-smoke"]
    if cli_expected:
        argv += ["--expected-commit", _git(clone, "rev-parse", "HEAD")]
    with pytest.raises(AssertionError, match="Unproven ancestry"):
        module.main(argv)


@pytest.mark.parametrize("expected_commit", [None, ""])
@pytest.mark.parametrize("resume", [False, True])
def test_cutover_requires_expected_commit_before_any_connection(
    connections, expected_commit, resume
):
    module = _load_cutover_module()
    with pytest.raises(ValueError, match="requires --expected-commit"):
        module.apply_postgres_cutover(
            OWNER_DSN,
            APP_DSN,
            "apppass",
            old_dsn=OLD_DSN,
            resume_post_migration=resume,
            expected_commit=expected_commit,
            root=ROOT,
        )
    assert connections == []


def test_cli_cutover_without_expected_commit_opens_no_connection(connections, monkeypatch):
    module = _load_cutover_module()
    monkeypatch.delenv("EXPECTED_COMMIT", raising=False)
    with pytest.raises(ValueError, match="requires --expected-commit"):
        module.main(
            ["--mode", "cutover", "--admin-database-url", OWNER_DSN, "--app-database-url", APP_DSN]
        )
    assert connections == []


@pytest.mark.parametrize("old_dsn", [None, OLD_DSN])
def test_cutover_rejects_unproven_ancestry_before_any_connection(
    source_repo, tmp_path, connections, old_dsn
):
    module = _load_cutover_module()
    clone = _shallow_clone(source_repo, tmp_path / "clone")
    with pytest.raises(AssertionError, match="Unproven ancestry"):
        module.apply_postgres_cutover(
            OWNER_DSN,
            APP_DSN,
            "apppass",
            old_dsn=old_dsn,
            expected_commit=_git(clone, "rev-parse", "HEAD"),
            root=clone,
        )
    assert connections == []


def test_cutover_rejects_a_proven_commit_that_is_not_checked_out(
    source_repo, connections, monkeypatch
):
    module = _load_cutover_module()
    ancestor = _git(source_repo, "rev-parse", "HEAD~1")
    monkeypatch.setattr(module, "REQUIRED_NUTRITION_COMMITS", (ancestor,))
    with pytest.raises(AssertionError, match="not the checked-out HEAD"):
        module.apply_postgres_cutover(
            OWNER_DSN, APP_DSN, "apppass", expected_commit=ancestor, root=source_repo
        )
    assert connections == []


def test_cutover_with_proven_ancestry_reaches_the_owner_connection(
    source_repo, connections, monkeypatch
):
    module = _load_cutover_module()
    ancestor = _git(source_repo, "rev-parse", "HEAD~1")
    monkeypatch.setattr(module, "REQUIRED_NUTRITION_COMMITS", (ancestor,))
    monkeypatch.setattr(module, "verify_migration_manifest", lambda root: [])
    with pytest.raises(_ConnectionReached):
        module.apply_postgres_cutover(
            OWNER_DSN,
            APP_DSN,
            "apppass",
            expected_commit=_git(source_repo, "rev-parse", "HEAD"),
            root=source_repo,
        )
    assert len(connections) == 1


def test_cli_cutover_exits_zero_but_names_outstanding_steps(monkeypatch, capsys):
    module = _load_cutover_module()
    monkeypatch.setattr(
        module,
        "apply_postgres_cutover",
        lambda *args, **kwargs: {
            "status": "database_phase_passed",
            "outstanding_steps": ["Step 2.2: fixture", "Step 2.3: fixture"],
        },
    )
    exit_code = module.main(
        [
            "--mode",
            "cutover",
            "--admin-database-url",
            OWNER_DSN,
            "--app-database-url",
            APP_DSN,
            "--expected-commit",
            "4a9d6b6",
        ]
    )
    assert exit_code == 0
    stderr = capsys.readouterr().err
    assert "database_phase_passed. Still outstanding:" in stderr
    assert "- Step 2.2: fixture" in stderr
    assert "- Step 2.3: fixture" in stderr


@pytest.mark.parametrize(
    "extra,staging_url",
    [([], None), (["--run-hosted-smoke"], "https://biteflow-staging-api.onrender.com")],
)
def test_cli_cutover_runs_hosted_smoke_only_when_asked(monkeypatch, extra, staging_url):
    module = _load_cutover_module()
    received: dict = {}

    def _capture(owner_dsn, app_dsn, app_password, **kwargs):
        received.update(kwargs)
        return {}

    monkeypatch.setattr(module, "apply_postgres_cutover", _capture)
    module.main(
        [
            "--mode",
            "cutover",
            "--admin-database-url",
            OWNER_DSN,
            "--app-database-url",
            APP_DSN,
            "--expected-commit",
            "4a9d6b6",
            *extra,
        ]
    )
    assert received["staging_url"] == staging_url
    assert received["expected_commit"] == "4a9d6b6"
