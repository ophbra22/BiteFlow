"""Exercise the offline command as a user; all inputs here are synthetic."""

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/report_release_metrics.py"


def synthetic():
    return {
        "schema_version": 1,
        "evidence_kind": "synthetic",
        "window": {"start": "2026-01-01T00:00:00Z", "end": "2026-01-08T00:00:00Z"},
        "release_commit": None,
        "source_sha256": None,
        "metrics": {
            "photo_to_save_rate": {"coverage": "complete", "numerator": 3, "denominator": 4}
        },
    }


def run(tmp_path, data=None, destination=None):
    output = destination or tmp_path / "report"
    command = [sys.executable, str(SCRIPT), "--output", str(output)]
    if data is not None:
        source = tmp_path / "input.json"
        source.write_bytes(data if isinstance(data, bytes) else json.dumps(data).encode())
        command.extend(["--input", str(source)])
    result = subprocess.run(
        command,
        cwd=tmp_path,
        env={**os.environ, "PYTHONPATH": str(ROOT / "src")},
        capture_output=True,
        text=True,
        timeout=10,
    )
    return result, output


def test_default_report_is_empty_and_standalone(tmp_path):
    result, out = run(tmp_path)
    assert result.returncode == 0, result.stderr
    assert sorted(p.name for p in out.iterdir()) == ["backlog.md", "dashboard.html", "report.json"]
    report = json.loads((out / "report.json").read_text())
    assert report["evidence_kind"] == "none"
    assert report["input_sha256"] is None
    assert report["acceptance"] == "BLOCKED"
    assert all(r["value"] is None for r in report["metrics"])
    html = (out / "dashboard.html").read_text()
    assert "No observations supplied" in html
    assert "BLOCKED" in html
    assert "<script" not in html
    assert "https://" not in html and "http://" not in html
    assert "Content-Security-Policy" in html
    assert "photo_to_save_rate" in (out / "backlog.md").read_text()


def test_synthetic_report_keeps_label_and_input_hash(tmp_path):
    data = json.dumps(synthetic()).encode()
    result, out = run(tmp_path, data)
    assert result.returncode == 0, result.stderr
    report = json.loads((out / "report.json").read_text())
    assert report["input_sha256"] == hashlib.sha256(data).hexdigest()
    assert report["metrics"][0]["value"] == 75
    for filename in ("dashboard.html", "backlog.md"):
        assert "SYNTHETIC VALIDATION ONLY" in (out / filename).read_text()
    assert "post-release" in report["notice"]


def test_observation_hashes_are_only_declared_evidence(tmp_path):
    data = synthetic()
    data.update(
        evidence_kind="unverified_observation", release_commit="a" * 40, source_sha256="b" * 64
    )
    result, out = run(tmp_path, data)
    assert result.returncode == 0, result.stderr
    report = json.loads((out / "report.json").read_text())
    assert report["acceptance"] == "BLOCKED"
    assert report["evidence_kind"] == "unverified_observation"
    assert "UNVERIFIED" in (out / "dashboard.html").read_text()
    assert "verified release" in (out / "backlog.md").read_text()


@pytest.mark.parametrize(
    "data",
    [
        b'{"meal_text":"private-secret"}',
        b'{"schema_version":1,"schema_version":1}',
        b'{"schema_version":NaN}',
        b"[" * 2000 + b"]" * 2000,
        b"1" * 5000,
        b" " * (256 * 1024 + 1),
        b"\xff\xfeprivate-secret",
        b"null",
        b"[]",
        b"{}",
        b"private-secret",
    ],
    # Pytest exports the node ID as PYTEST_CURRENT_TEST to child processes.
    # Raw oversized payloads exceed Linux's per-environment-string limit.
    ids=[
        "unexpected-field",
        "duplicate-key",
        "nonfinite-number",
        "deeply-nested",
        "oversized-integer",
        "oversized-document",
        "invalid-utf8",
        "null",
        "array",
        "empty-object",
        "non-json",
    ],
)
def test_bad_input_is_rejected_without_echo_or_output(tmp_path, data):
    result, out = run(tmp_path, data)
    assert result.returncode == 2
    assert result.stderr == "Cannot create report: invalid input or unavailable output.\n"
    assert "private-secret" not in result.stdout + result.stderr
    assert not out.exists()


@pytest.mark.parametrize("existing", ["file", "directory", "symlink"])
def test_existing_output_is_never_overwritten(tmp_path, existing, make_symlink):
    out = tmp_path / "report"
    target = tmp_path / "kept"
    target.mkdir()
    (target / "important").write_text("preserve me")
    if existing == "file":
        out.write_text("existing")
    elif existing == "directory":
        out.mkdir()
        (out / "report.json").write_text("existing")
    else:
        make_symlink(out, target, target_is_directory=True)
    result, _ = run(tmp_path, synthetic(), out)
    assert result.returncode == 2
    assert result.stderr == "Cannot create report: invalid input or unavailable output.\n"
    assert (target / "important").read_text() == "preserve me"
    if existing == "file":
        assert out.read_text() == "existing"
    elif existing == "directory":
        assert (out / "report.json").read_text() == "existing"
        assert sorted(p.name for p in out.iterdir()) == ["report.json"]
    else:
        assert out.is_symlink()


def test_renderer_escapes_even_internal_labels():
    from foodlogger.measurement import analyze, empty_bundle
    from foodlogger.measurement_report import render_html

    report = analyze(empty_bundle())
    report["input_sha256"] = None
    report["notice"] = '<script>alert("private")</script>'
    report["metrics"][0]["label"] = '<img src="https://private">'
    html = render_html(report)
    assert "<script>" not in html and "<img" not in html
    assert "&lt;script&gt;" in html and "&lt;img" in html


@pytest.mark.parametrize(
    "numerator,denominator,display",
    [
        (999_999_999, 1_000_000_000, "99.9999999"),
        (19_899_999, 20_000_000, "99.499995"),
    ],
)
def test_dashboard_does_not_round_adverse_rates_to_perfect_or_threshold(
    numerator, denominator, display
):
    from foodlogger.measurement import analyze
    from foodlogger.measurement_report import render_html

    data = synthetic()
    data["metrics"] = {
        "crash_free_session_rate": {
            "coverage": "complete",
            "numerator": numerator,
            "denominator": denominator,
        }
    }
    report = analyze(data)
    report["input_sha256"] = None
    html = render_html(report)
    assert f">{display}</td>" in html
