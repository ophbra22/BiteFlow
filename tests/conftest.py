"""Routine tests may use MockTransport, never a real HTTPX network transport."""

import ssl

import httpx
import pytest


@pytest.fixture
def system_ca_bundle(monkeypatch, tmp_path_factory):
    """Stand in for the OS CA file, which Python reports as absent on Windows.

    Only the path that Database resolves is faked: no connection is made, and tests that
    need real certificate checks use tests/test_database_tls.py.
    """
    bundle = tmp_path_factory.mktemp("system-ca") / "ca.pem"
    bundle.write_text("fixture, never loaded\n", encoding="utf-8")
    paths = ssl.get_default_verify_paths()._replace(cafile=str(bundle))
    monkeypatch.setattr(ssl, "get_default_verify_paths", lambda: paths)
    return bundle


@pytest.fixture
def make_symlink():
    """Create a symlink, or skip when this Windows account cannot."""

    def create(link, target, *, target_is_directory=False):
        try:
            link.symlink_to(target, target_is_directory=target_is_directory)
        except OSError as error:
            if getattr(error, "winerror", None) != 1314:
                raise
            pytest.skip("Creating symlinks needs Windows Developer Mode or admin (WinError 1314)")

    return create


@pytest.fixture(autouse=True)
def no_real_httpx_transport(monkeypatch):
    def blocked(*args, **kwargs):
        raise AssertionError("Real HTTP transport is disabled in tests; inject MockTransport.")

    async def async_blocked(*args, **kwargs):
        blocked(*args, **kwargs)

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", blocked)
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", async_blocked)
