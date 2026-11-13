"""SQLite locally; verified-TLS PostgreSQL in a private schema when configured."""

import logging
import sqlite3
import ssl
import threading
import time
from collections import deque
from contextlib import contextmanager
from pathlib import Path

logger = logging.getLogger(__name__)
SUPABASE_CA = Path(__file__).parent / "data" / "supabase-ca.crt"
# Version 2 records that the Apple sign-in tables exist. Version 1 databases that
# already have them (the migration predates this marker) are still accepted.
SCHEMA_VERSIONS = (1, 2)
# Transaction-local settings do not leak between pooled or reused connections.
# One statement, one round trip; no parameters, so several commands are allowed.
SESSION_SETUP = (
    "SET LOCAL search_path TO foodlogger, pg_catalog; "
    "SET LOCAL statement_timeout = '10s'; "
    "SET LOCAL lock_timeout = '5s'"
)
MAX_IDLE_CONNECTIONS = 4
MAX_IDLE_SECONDS = 60


def _failure_reason(error):
    """Map driver failures to fixed labels; never log SQL, URLs or raw errors."""
    state = getattr(error, "sqlstate", None)
    if state in {"28000", "28P01"}:
        return "authentication"
    if state == "42501":
        return "permissions"
    if state in {"42P01", "3F000"}:
        return "schema"
    message = str(error).lower()
    if "certificate" in message or "root.crt" in message:
        return "tls_certificate"
    if "password authentication failed" in message or "tenant or user not found" in message:
        return "authentication"
    if "timeout" in message or "timed out" in message:
        return "timeout"
    if "could not translate host name" in message or "name or service not known" in message:
        return "dns"
    if "connection refused" in message or "network is unreachable" in message:
        return "network"
    return "database_error"


class DatabaseUnavailable(RuntimeError):
    """A database operation failed without exposing credentials or driver details."""


class PostgresConnection:
    """Adapt our fixed, parameterized SQL statements to psycopg's placeholders."""

    def __init__(self, connection):
        self.connection = connection

    def execute(self, statement, parameters=()):
        # Statements are application constants, never user-supplied SQL.
        return self.connection.execute(statement.replace("?", "%s"), parameters)


class Database:
    def __init__(self, location: str | Path):
        value = str(location)
        self.postgres = value.startswith(("postgresql://", "postgres://"))
        self.path = None
        self.connection_options = {}
        if self.postgres:
            try:
                from psycopg.conninfo import conninfo_to_dict

                options = conninfo_to_dict(value)
            except ImportError:
                raise RuntimeError("Install the postgres extra to use DATABASE_URL.") from None
            except Exception:
                raise ValueError("Invalid PostgreSQL connection URL.") from None
            host = options.get("host", "")
            if not host or not options.get("dbname") or not options.get("user"):
                raise ValueError("PostgreSQL URL requires a host, database and user.")
            if host not in {"localhost", "127.0.0.1", "::1"}:
                if options.get("sslmode", "verify-full") != "verify-full":
                    raise ValueError(
                        "Remote PostgreSQL requires verified TLS (sslmode=verify-full)."
                    )
                options["sslmode"] = "verify-full"
                if "sslrootcert" not in options and host.lower().endswith(".pooler.supabase.com"):
                    # Supabase's shared poolers use its private production CA,
                    # which is not part of the operating system's public roots.
                    options["sslrootcert"] = str(SUPABASE_CA)
                elif options.get("sslrootcert", "system") == "system":
                    # Binary libpq bundles OpenSSL with build-machine trust paths.
                    # Resolve Python's actual OS bundle rather than those paths.
                    ca_bundle = ssl.get_default_verify_paths().cafile
                    if not ca_bundle:
                        raise ValueError(
                            "System CA bundle unavailable. Set sslrootcert to a trusted CA file."
                        )
                    options["sslrootcert"] = ca_bundle
            options.setdefault("connect_timeout", "5")
            options["application_name"] = "foodlogger"
            self.connection_options = options
            # Reusing connections avoids a TCP, TLS and login handshake per query.
            self._idle = deque()
            self._idle_lock = threading.Lock()
        else:
            if "://" in value or not value:
                raise ValueError("Use a PostgreSQL URL or a local SQLite file path.")
            self.path = Path(location)
            self.path.parent.mkdir(parents=True, exist_ok=True)

    def __repr__(self):
        return f"Database(backend={'postgresql' if self.postgres else 'sqlite'})"

    @contextmanager
    def connect(self):
        if not self.postgres:
            db = sqlite3.connect(self.path, timeout=10)
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA foreign_keys=ON")
            try:
                with db:
                    yield db
            finally:
                db.close()
            return
        import psycopg

        stage, connection = "connect", None
        try:
            connection, reused = self._checkout()
            stage = "session_setup"
            try:
                connection.execute(SESSION_SETUP)
            except psycopg.OperationalError:
                if not reused:
                    raise
                # The server or pooler closed an idle connection. Nothing of the
                # caller's has run yet, so a fresh connection is a safe retry.
                self._discard(connection)
                stage, connection = "connect", None
                connection = self._open()
                stage = "session_setup"
                connection.execute(SESSION_SETUP)
            stage = "query"
            yield PostgresConnection(connection)
            stage = "commit"
            connection.commit()
        except psycopg.IntegrityError:
            raise sqlite3.IntegrityError("Database constraint rejected the operation.") from None
        except psycopg.Error as error:
            logger.warning(
                "PostgreSQL operation failed (stage=%s, reason=%s).", stage, _failure_reason(error)
            )
            raise DatabaseUnavailable("The journal database is temporarily unavailable.") from None
        finally:
            if connection is not None:
                self._release(connection)

    def _open(self):
        import psycopg
        from psycopg.rows import dict_row

        # No prepared statements: compatible with Supabase's transaction pooler.
        return psycopg.connect(
            **self.connection_options, row_factory=dict_row, prepare_threshold=None
        )

    def _checkout(self):
        """Return (connection, reused), preferring the most recently used idle one."""
        while True:
            with self._idle_lock:
                if not self._idle:
                    break
                connection, since = self._idle.pop()
            if time.monotonic() - since <= MAX_IDLE_SECONDS and not connection.closed:
                return connection, True
            self._discard(connection)
        return self._open(), False

    def _release(self, connection):
        """Roll back anything uncommitted and keep a healthy connection for reuse."""
        from psycopg.pq import TransactionStatus

        try:
            if not connection.closed and not connection.broken:
                if connection.info.transaction_status != TransactionStatus.IDLE:
                    connection.rollback()
                if connection.info.transaction_status == TransactionStatus.IDLE:
                    with self._idle_lock:
                        if len(self._idle) < MAX_IDLE_CONNECTIONS:
                            self._idle.append((connection, time.monotonic()))
                            return
        except Exception:
            pass
        self._discard(connection)

    @staticmethod
    def _discard(connection):
        try:
            connection.close()
        except Exception:
            pass

    def close(self):
        """Close idle PostgreSQL connections. Later calls simply open new ones."""
        if self.postgres:
            with self._idle_lock:
                idle, self._idle = list(self._idle), deque()
            for connection, _ in idle:
                self._discard(connection)

    def check_schema(self):
        if self.postgres:
            with self.connect() as db:
                row = db.execute("SELECT version FROM schema_version WHERE id = 1").fetchone()
                version = row["version"] if row else None
                if version not in SCHEMA_VERSIONS:
                    raise DatabaseUnavailable("The journal database schema needs setup.")
                if version < 2:
                    tables = db.execute(
                        "SELECT to_regclass('foodlogger.apple_identities') AS identities, "
                        "to_regclass('foodlogger.apple_challenges') AS challenges"
                    ).fetchone()
                    if tables["identities"] is None or tables["challenges"] is None:
                        # Fail at startup instead of on every later sign-in.
                        raise DatabaseUnavailable(
                            "The journal database is missing the Apple sign-in migration."
                        )
