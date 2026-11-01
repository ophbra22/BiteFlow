"""Stage 0 regressions for render.yaml, 16-migration cutover, and staging smoke."""

import importlib.util
from pathlib import Path

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
    assert report["blueprints"]["render_yaml_auto_deploy_off"] is True
    assert report["migrations"]["migration_count"] == 16
    assert report["migrations"]["tables_created"] == 36
    assert report["tls_and_role_contract"]["sslmode"] == "verify-full"
    assert report["tls_and_role_contract"]["trusted_ca_count"] > 0
    assert "foodlogger_app" in report["tls_and_role_contract"]["role_query"]
    assert report["smoke"]["status"] == "passed"
    assert report["smoke"]["health"]["status"] == "ok"
    assert report["smoke"]["ai_probe"]["ai_status"] == "used"
    assert report["smoke"]["ai_probe"]["all_unconfirmed"] is True
    assert report["smoke"]["ai_probe"]["no_auto_save"] is True
    assert report["smoke"]["ai_probe"]["first_reference_id"] == "fdc:173423"
    assert report["ai_ledger"]["used_requests"] == 1
    assert report["ai_ledger"]["features"]["text"] == 1
