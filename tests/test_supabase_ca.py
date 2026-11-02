import hashlib
import ssl
from pathlib import Path

import pytest


@pytest.mark.parametrize(
    "host",
    [
        "aws-1-ap-northeast-2.pooler.supabase.com",
        "aws-0-eu-central-1.pooler.supabase.com",
        "AWS-1-AP-NORTHEAST-2.POOLER.SUPABASE.COM",
    ],
)
def test_supabase_poolers_use_bundled_production_roots(host):
    pytest.importorskip("psycopg")
    from foodlogger.database import Database

    options = Database(f"postgresql://app:fixture-only@{host}:6543/postgres").connection_options
    assert options["sslmode"] == "verify-full"
    bundle = Path(options["sslrootcert"])
    assert bundle.name == "supabase-ca.crt"
    context = ssl.create_default_context(cafile=str(bundle))
    fingerprints = {
        hashlib.sha256(cert).hexdigest() for cert in context.get_ca_certs(binary_form=True)
    }
    # Public production roots copied from the pinned official Supabase CLI source.
    assert fingerprints == {
        "807025ad50d4ed219d2c9c7d299c004f824eb00cf7f65afef607d07b72e6cafa",
        "5f9b77951a7aa1303f9b58eea9bfa89e358cfdc15f9786ff10d4930a722c9ae2",
    }


@pytest.mark.parametrize(
    "host",
    [
        "database.example",
        "pooler.supabase.com.attacker.example",
        "supabase.com.attacker.example",
    ],
)
def test_supabase_trust_is_not_used_for_other_hosts(host, system_ca_bundle):
    pytest.importorskip("psycopg")
    from foodlogger.database import Database

    options = Database(f"postgresql://app:fixture-only@{host}/postgres").connection_options
    assert options["sslrootcert"] == str(system_ca_bundle)
    assert options["sslmode"] == "verify-full"


def test_supabase_explicit_ca_override_is_preserved():
    pytest.importorskip("psycopg")
    from foodlogger.database import Database

    options = Database(
        "postgresql://app:fixture-only@aws-1-ap-northeast-2.pooler.supabase.com/postgres"
        "?sslrootcert=/operator/ca.pem"
    ).connection_options
    assert options["sslrootcert"] == "/operator/ca.pem"
    assert options["sslmode"] == "verify-full"


def test_supabase_does_not_need_a_system_ca_bundle(monkeypatch):
    pytest.importorskip("psycopg")
    from foodlogger.database import Database

    paths = ssl.get_default_verify_paths()._replace(cafile=None)
    monkeypatch.setattr(ssl, "get_default_verify_paths", lambda: paths)
    options = Database(
        "postgresql://app:fixture-only@aws-1-ap-northeast-2.pooler.supabase.com/postgres"
    ).connection_options
    assert Path(options["sslrootcert"]).is_file()
