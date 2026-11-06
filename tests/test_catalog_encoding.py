"""Packaged Unicode data must load regardless of the process's default encoding."""

import io

import pytest

from foodlogger.nutrition import Catalog


@pytest.mark.parametrize("default_encoding", ["cp1252", "ascii"])
def test_catalog_preserves_unicode_with_a_legacy_default(monkeypatch, default_encoding):
    real_text_encoding = io.text_encoding

    def legacy_text_encoding(encoding, stacklevel=2):
        # Path.read_text resolves a missing encoding here. Keep the file read
        # real while making that default independent of the OS and UTF-8 mode.
        if encoding is None:
            return default_encoding
        return real_text_encoding(encoding, stacklevel)

    monkeypatch.setattr(io, "text_encoding", legacy_text_encoding)
    catalog = Catalog()
    assert catalog.get("banana")["emoji"] == "\U0001f34c"
    assert catalog.get("apple")["name"] == "Apple"
