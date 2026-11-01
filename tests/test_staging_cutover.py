"""Stage 0 regressions for render.yaml, 16-migration cutover, and staging smoke safety gates."""

import importlib.util
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
        "http://foodlogger-staging.onrender.com",
        "http://biteflow-staging-api.onrender.com",
        "https://foodlogger.onrender.com",
        "https://srv-d6q76n5m5p6s73f9k590.onrender.com",
        "https://slnmporlcbqnnkyebdmv.supabase.co",
        "https://evil.example.com",
        "https://user:pass@foodlogger-staging.onrender.com",
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
            "postgresql://owner:pw@dpg-d6q76n5m5p6s73f9k58g-a.frankfurt-postgres.render.com/biteflow_staging_db",
            "postgresql://foodlogger_app:pw@dpg-d6q76n5m5p6s73f9k58g-a.frankfurt-postgres.render.com/biteflow_staging_db",
            "expiring staging database",
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

    with pytest.raises(AssertionError, match=expected_error):
        module.apply_postgres_cutover(owner_dsn, app_dsn, "apppass", root=ROOT)

    assert configure_calls == []


def test_cutover_resume_post_migration_succeeds_after_owner_migrations_committed(monkeypatch):
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
    report = module.apply_postgres_cutover(
        owner_dsn,
        app_dsn,
        "apppass",
        resume_post_migration=True,
        root=ROOT,
    )
    assert report["status"] == "passed"
    assert report["migration_transaction"] == "resumed_existing_16_migration_schema"
    assert len(configure_calls) == 1


def test_hosted_smoke_rejects_mismatched_commit_sha_before_any_writes():
    module = _load_cutover_module()
    requests_sent: list[str] = []

    class _FakeResponse:
        status_code = 200
        headers = {}

        def json(self):
            return {"status": "ok", "version": "2.1.0", "commit": "deadbeef1234567"}

    class _FakeStagingClient:
        base_url = "https://foodlogger-staging.onrender.com"

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
            "https://foodlogger-staging.onrender.com",
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
            "postgresql://foodlogger_app:pw@dpg-d6q76n5m5p6s73f9k58g-a.frankfurt-postgres.render.com/car_log",
            "forbidden production identifier",
        ),
        (
            "postgresql://foodlogger_app:pw@dpg-unrelated-a.frankfurt-postgres.render.com/biteflow_staging_db",
            "does not match expected expiring staging database",
        ),
        (
            "postgresql://foodlogger_app:pw@dpg-d6q76n5m5p6s73f9k58g-a."
            "frankfurt-postgres.render.com.unapproved.invalid/biteflow_staging_db",
            "does not match expected expiring staging database",
        ),
        (
            "postgresql://foodlogger_app:pw@evil-dpg-d6q76n5m5p6s73f9k58g-a."
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
        "postgresql://foodlogger_app:pw@dpg-d6q76n5m5p6s73f9k58g-a.frankfurt-postgres.render.com:5432/"
        "biteflow_staging_db?sslmode=verify-full"
    )
    validated = module.validate_cutover_database_urls(owner_dsn, app_dsn, old_dsn=valid_old_dsn)
    assert validated["host"] == "dpg-replacement-a.frankfurt-postgres.render.com"


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

    app = create_app(db_path=tmp_path / "health.sqlite3", settings=Settings())
    with TestClient(app) as client:
        resp = client.get("/api/health")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert body["commit"] == expected_sha
        assert module.verify_deployed_commit_sha(body, expected_sha, root=ROOT) == expected_sha
        with pytest.raises(AssertionError, match="Deployed commit SHA mismatch"):
            module.verify_deployed_commit_sha(body, "deadbeef1234567", root=ROOT)
