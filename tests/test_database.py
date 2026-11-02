import pytest


def test_sqlite_connection_keeps_transactions_and_foreign_keys(tmp_path):
    from foodlogger.database import Database

    database = Database(tmp_path / "data.sqlite3")
    with database.connect() as db:
        db.execute("CREATE TABLE test (id INTEGER PRIMARY KEY)")
    with pytest.raises(RuntimeError), database.connect() as db:
        db.execute("INSERT INTO test VALUES (?)", (1,))
        raise RuntimeError("rollback")
    with database.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM test").fetchone()[0] == 0
        assert db.execute("PRAGMA foreign_keys").fetchone()[0] == 1


def test_database_url_is_not_a_file_and_never_appears_in_repr(
    tmp_path, monkeypatch, system_ca_bundle
):
    pytest.importorskip("psycopg")
    from foodlogger.database import Database

    monkeypatch.chdir(tmp_path)
    secret = "postgresql://user:SECRET@example.com:5432/postgres"
    database = Database(secret)
    assert database.postgres
    assert "SECRET" not in repr(database)
    assert not list(tmp_path.iterdir())


def test_remote_database_requires_verified_tls(system_ca_bundle):
    pytest.importorskip("psycopg")
    from foodlogger.database import Database

    with pytest.raises(ValueError, match="TLS"):
        Database("postgresql://user:SECRET@example.com/postgres?sslmode=disable")
    with pytest.raises(ValueError, match="TLS"):
        Database("postgresql://user:SECRET@example.com/postgres?sslmode=require")
    database = Database("postgresql://user:SECRET@example.com/postgres")
    assert database.connection_options["sslmode"] == "verify-full"
    assert database.connection_options["sslrootcert"] == str(system_ca_bundle)


def test_invalid_database_url_is_rejected_without_echoing_it():
    from foodlogger.database import Database

    with pytest.raises(ValueError) as error:
        Database("https://SECRET.supabase.co")
    assert "SECRET" not in str(error.value)


def test_free_profile_requires_postgres_even_with_sqlite_path(monkeypatch):
    from foodlogger.app import create_app
    from foodlogger.security import Settings

    monkeypatch.setenv("FOODLOGGER_PROFILE", "free")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(RuntimeError, match="PostgreSQL"):
        create_app(db_path="/tmp/free-must-not-use.sqlite3", settings=Settings())


def test_database_url_failure_does_not_fall_back_to_sqlite(monkeypatch, tmp_path):
    pytest.importorskip("psycopg")
    from foodlogger.app import create_app
    from foodlogger.database import DatabaseUnavailable
    from foodlogger.security import Settings

    monkeypatch.setenv("DATABASE_URL", "postgresql://u:SECRET@127.0.0.1:1/test?connect_timeout=1")
    monkeypatch.setenv("FOODLOGGER_DB", str(tmp_path / "must-not-exist.sqlite3"))
    with pytest.raises(DatabaseUnavailable) as error:
        create_app(settings=Settings())
    assert "SECRET" not in str(error.value)
    assert not list(tmp_path.iterdir())


def test_production_accepts_postgres_instead_of_a_disk(monkeypatch):
    from foodlogger.security import Settings

    monkeypatch.setenv("FOODLOGGER_ENV", "production")
    monkeypatch.setenv("FOODLOGGER_PUBLIC_URL", "https://food.example")
    monkeypatch.setenv("DATABASE_URL", "postgresql://app:SECRET@db.example/postgres")
    monkeypatch.delenv("FOODLOGGER_DB", raising=False)
    assert Settings.from_environment().production


def test_health_outage_is_generic_503(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from foodlogger.app import create_app
    from foodlogger.database import Database, DatabaseUnavailable
    from foodlogger.security import Settings

    app = create_app(db_path=tmp_path / "db.sqlite3", settings=Settings())

    def fail(self):
        raise DatabaseUnavailable("The journal database is temporarily unavailable.")

    monkeypatch.setattr(Database, "connect", fail)
    with TestClient(app) as client:
        response = client.get("/api/health")
    assert response.status_code == 503
    assert "temporarily unavailable" in response.text


def test_lite_backend_selection_without_tensorflow(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from foodlogger.app import create_app
    from foodlogger.security import Settings

    monkeypatch.setenv("FOODLOGGER_INFERENCE", "lite")
    with TestClient(create_app(db_path=tmp_path / "db", settings=Settings())) as client:
        assert "LiteRT" in client.get("/api/health").json()["model"]


def test_explicit_database_ca_is_preserved():
    pytest.importorskip("psycopg")
    from foodlogger.database import Database

    database = Database("postgresql://app:SECRET@db.example/postgres?sslrootcert=/custom/ca.pem")
    assert database.connection_options["sslrootcert"] == "/custom/ca.pem"
    assert database.connection_options["sslmode"] == "verify-full"


def test_missing_system_ca_fails_with_setup_message(monkeypatch):
    import ssl

    pytest.importorskip("psycopg")
    from foodlogger.database import Database

    paths = ssl.get_default_verify_paths()._replace(cafile=None)
    monkeypatch.setattr(ssl, "get_default_verify_paths", lambda: paths)
    with pytest.raises(ValueError, match="CA bundle"):
        Database("postgresql://app:SECRET@db.example/postgres")


@pytest.mark.parametrize(
    "message,expected",
    [
        ("SSL error: certificate verify failed SECRET", "tls_certificate"),
        ("FATAL: password authentication failed for user SECRET", "authentication"),
        ("connection timeout expired SECRET", "timeout"),
        ("unspecified SECRET failure", "database_error"),
    ],
)
def test_database_failure_logs_only_safe_reason(
    monkeypatch, caplog, message, expected, system_ca_bundle
):
    psycopg = pytest.importorskip("psycopg")
    from foodlogger.database import Database, DatabaseUnavailable

    def fail(**options):
        raise psycopg.OperationalError(message)

    monkeypatch.setattr(psycopg, "connect", fail)
    with (
        pytest.raises(DatabaseUnavailable) as error,
        Database("postgresql://app:SECRET@db.example/postgres").connect(),
    ):
        pass
    assert expected in caplog.text
    assert "SECRET" not in caplog.text + str(error.value)
    assert "stage=connect" in caplog.text
