"""v2 evaluator: arithmetic on a SYNTHETIC fixture, plus guardrails with a fake provider.

Nothing here calls a provider or measures photo accuracy. Expected values are written
out by hand from the fixture, so they do not depend on the code they check.
"""

import hashlib
import importlib.util
import json
import socket
from pathlib import Path

import pytest
from PIL import Image

from foodlogger.analysis_schemas import VisionFood, VisionMeal
from foodlogger.nutrition_reference import ReferenceCatalog
from foodlogger.vision import VisionQuotaExceeded, VisionUnavailable

REPO = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "meal_eval_v2", REPO / "scripts" / "evaluate_meal_analysis.py"
)
evaluation = importlib.util.module_from_spec(spec)
spec.loader.exec_module(evaluation)

FIXTURE = REPO / "evaluations" / "meal_analysis" / "synthetic" / "v2_scoring_fixture.json"
REPORTS = [
    "baseline-report.json",
    "gemini-3.8-attempt-report.json",
    "gemini-flash-report.json",
    "gemini-lite-recheck-report.json",
    "gemini-lite-report.json",
    "local-experiment-report.json",
    "vision-report.json",
]


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def refuse(*_args, **_kwargs):
        raise AssertionError("Evaluator tests must not open a network connection.")

    monkeypatch.setattr(socket.socket, "connect", refuse)


def load_fixture():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def fixture_rows():
    rows = []
    for case in load_fixture()["cases"]:
        row = {"id": case["id"], "expected_food_count": evaluation.expected_count(case)}
        if case["synthetic_result"] is None:
            row["status"] = "failed"
        else:
            row.update(evaluation.score_case(case, case["synthetic_result"]))
            row.update(status="ok", elapsed_ms=10)
        rows.append(row)
    return rows


def test_fixture_is_labeled_synthetic_and_grounded_in_the_reference():
    manifest = load_fixture()
    assert manifest["synthetic"] is True
    assert evaluation.validate_manifest_v2(manifest, ReferenceCatalog()) == []


def test_proposal_example_passes_the_validator():
    document = (REPO / "docs" / "photo-benchmark-proposal.md").read_text(encoding="utf-8")
    example = json.loads(document.split("```json\n")[1].split("```")[0])
    assert evaluation.validate_manifest_v2({"cases": [example]}, ReferenceCatalog()) == []


def test_hand_checked_detection_and_status_metrics():
    summary = evaluation.summarize(fixture_rows())
    assert summary["completed"] == 8
    assert summary["failed_or_blocked"] == 2
    assert (summary["tp"], summary["fp"], summary["fn"]) == (7, 3, 2)
    assert summary["precision"] == pytest.approx(7 / 10)
    assert summary["recall"] == pytest.approx(7 / 9)
    assert summary["f1"] == pytest.approx(14 / 19)  # 2*7 / (2*7 + 3 + 2)
    # A failed image counts against end-to-end recall: 2+2+2+0+0+1+1+1+2+0 = 11 expected.
    assert summary["end_to_end_recall"] == pytest.approx(7 / 11)
    # False alarm and food reported as no_food are wrong, 6 of 8 completed are right.
    assert summary["status_accuracy"] == pytest.approx(6 / 8)
    # One abstained and one false alarm. The blocked no_food case earns no credit.
    assert summary["non_food_abstention_rate"] == pytest.approx(1 / 2)
    assert summary["v2_sample_counts"]["non_food"] == 2


def test_hand_checked_reference_metrics():
    summary = evaluation.summarize(fixture_rows())
    # Schnitzel, rice, shakshuka right; rice wrong; rice missing; sabich false reference.
    assert summary["usda_reference_counts"] == {
        "correct": 3,
        "wrong": 1,
        "missing": 1,
        "false_reference": 1,
    }
    assert summary["usda_reference_accuracy"] == pytest.approx(3 / 6)
    assert summary["v2_sample_counts"]["matched_items"] == 7  # Hummus is unannotated.


def test_hand_checked_portion_and_calorie_metrics():
    summary = evaluation.summarize(fixture_rows())
    # Errors 25, 40, 10, 20, 0, 50. Identification-only hummus has no grams.
    assert summary["v2_sample_counts"]["item_grams"] == 6
    assert summary["item_grams_mae"] == pytest.approx(145 / 6)
    assert summary["item_grams_mape"] == pytest.approx(
        (25 / 145 + 40 / 160 + 10 / 100 + 20 / 200 + 0 / 100 + 50 / 250) / 6
    )
    # Only two meals have both a reference and an estimate: 25.2/651.6 and 193.5/193.5.
    assert summary["v2_sample_counts"]["calorie_mape"] == 2
    assert summary["calorie_mape"] == pytest.approx((25.2 / 651.6 + 1) / 2)
    # Totals 320/305, 340/300, 0/150, 100/100, 300/250 g. Meal-level v1 key, fed by items.
    assert summary["mean_absolute_error"]["grams"] == pytest.approx((15 + 40 + 150 + 0 + 50) / 5)
    assert summary["mean_absolute_error"]["calories"] == pytest.approx((25.2 + 193.5) / 2)


def test_hand_checked_item_nutrient_error_keeps_missing_values_missing():
    summary = evaluation.summarize(fixture_rows())
    # Schnitzel, rice, rice-with-wrong-reference. The missing reference adds no zero error.
    assert summary["item_nutrient_mae"]["calories"] == pytest.approx((76.8 + 51.6 + 208.7) / 3)
    assert summary["item_nutrient_mae"]["protein"] == pytest.approx((4.0 + 1.0 + 14.8) / 3)
    assert summary["item_nutrient_mae"]["carbs"] == pytest.approx((3.7 + 11.2 + 11.6) / 3)
    assert summary["item_nutrient_mae"]["fat"] == pytest.approx((5.1 + 0.2 + 22.1) / 3)
    counts = summary["v2_sample_counts"]
    assert counts["item_nutrient"]["calories"] == 3
    assert counts["item_nutrient_missing"]["calories"] == 1


def test_item_nutrient_error_is_limited_to_gravimetric_cases():
    case = load_fixture()["cases"][0]
    case["ground_truth_tier"] = "decomposition"
    scored = evaluation.score_case(case, case["synthetic_result"])
    assert [score["nutrient_absolute_error"] for score in scored["item_scores"]] == [{}, {}]


def test_no_evidence_gives_no_metric():
    summary = evaluation.summarize([{"status": "failed", "expected_food_count": 1}])
    for key in (
        "f1",
        "status_accuracy",
        "non_food_abstention_rate",
        "usda_reference_accuracy",
        "item_grams_mae",
        "item_grams_mape",
        "calorie_mape",
    ):
        assert summary[key] is None, key
    assert set(summary["item_nutrient_mae"].values()) == {None}


@pytest.mark.parametrize("name", REPORTS)
def test_v1_summary_keys_reproduce_every_committed_report(name):
    report = json.loads((REPO / "evaluations/meal_analysis" / name).read_text(encoding="utf-8"))
    summary = evaluation.summarize(report["results"])
    assert {key: summary[key] for key in report["summary"]} == report["summary"]


def item(name, *aliases):
    return {"name": name, "aliases": list(aliases)}


def food(search_name, name=None):
    return {"search_name": search_name, "name": name or search_name}


def test_item_match_rejects_words_that_only_share_a_prefix():
    assert evaluation.match_items([item("egg")], [food("eggplant")]) == {}
    assert evaluation.match_items([item("grape")], [food("grapefruit")]) == {}
    assert evaluation.match_items([item("egg")], [food("fried egg")]) == {0: 0}


def test_item_match_uses_hebrew_aliases_on_the_display_name():
    assert evaluation.match_items([item("hummus", "חומוס")], [food("dip", "חומוס")]) == {0: 0}


def test_item_match_is_one_to_one_and_finds_the_maximum_pairing():
    items = [item("chicken"), item("rice")]
    assert evaluation.match_items(items, [food("chicken rice"), food("chicken")]) == {0: 1, 1: 0}
    assert evaluation.match_items([item("rice")], [food("rice"), food("rice")]) == {0: 0}


@pytest.mark.parametrize(
    "mutate, message",
    [
        (lambda c: c["expected_items"][0]["scaled_nutrients"].update(calories=1.0), "differ"),
        (lambda c: c["reference_total"].update(calories=1.0), "not the sum"),
        (lambda c: c["expected_items"][0].update(usda_reference_id="fdc:0"), "unknown reference"),
        (lambda c: c["expected_items"][0].update(usda_reference_name="Other"), "is not"),
        (lambda c: c["expected_items"][0].update(grams=None), "needs grams"),
        (lambda c: c["expected_items"][0].update(grams=0), "1-2000"),
        (lambda c: c.update(license="CC-BY-NC-4.0"), "license"),
        (lambda c: c.update(file="../secret.jpg"), "relative path"),
        (lambda c: c.update(sha256="abc"), "sha256"),
        (lambda c: c.update(expected_status="needs_clarification"), "expected_status"),
        (lambda c: c.update(ground_truth_tier="guess"), "ground_truth_tier"),
        (lambda c: c.update(expected_status="no_food"), "no_food"),
        (lambda c: c.update(expected_items=[]), "needs expected_items"),
    ],
)
def test_validator_rejects_ungrounded_or_unlicensed_cases(mutate, message):
    manifest = load_fixture()
    mutate(manifest["cases"][0])
    errors = evaluation.validate_manifest_v2(manifest, ReferenceCatalog())
    assert any(message in error for error in errors), errors


def test_validator_allows_published_totals_without_usda_recomputation():
    manifest = load_fixture()
    case = manifest["cases"][0]
    case["reference_total_source"] = "published_dataset"
    case["reference_total"] = {"calories": 1.0, "protein": 1.0, "carbs": 1.0, "fat": 1.0}
    case["expected_items"][0]["scaled_nutrients"]["calories"] = 1.0
    assert evaluation.validate_manifest_v2(manifest, ReferenceCatalog()) == []


class FakeProvider:
    name = "gemini-free"
    model = "gemini-3.5-flash-lite"

    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def recognize(self, images, options):
        self.calls.append((images, options))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response, {"total_tokens": 1000}


def vision_food(name="apple"):
    return VisionFood(
        id="a",
        name=name,
        search_name=name,
        preparation="raw",
        region="center",
        dish_type="single",
        visible_ingredients=[],
        estimated_weight_g=100,
        weight_min_g=90,
        weight_max_g=110,
        confidence="medium",
        alternatives=[],
        question=None,
    )


def meal(name="apple"):
    return VisionMeal(meal_name="meal", status="food", foods=[vision_food(name)], warnings=[])


def unavailable():
    return VisionUnavailable("Meal analysis is unavailable.")


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)  # No local .env is read and no default report is overwritten.
    return tmp_path


def write_manifest(directory, count=2, *, schema_version=2, locale="en-US", synthetic=True):
    images = directory / "images"
    images.mkdir(exist_ok=True)
    cases = []
    for index in range(count):
        path = images / f"case{index}.png"
        Image.new("RGB", (256, 256), (index * 20 + 10, 90, 40)).save(path)
        case = {
            "id": f"case{index}",
            "file": f"images/case{index}.png",
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "source_url": "synthetic://generated-in-test",
            "license": "CC0-1.0",
            "ground_truth_tier": "identification_only",
            "expected_status": "food",
            "locale": locale,
            "visible_food_labels": ["apple"],
            "expected_items": [{"name": "apple", "aliases": ["תפוח"], "grams": None}],
            "reference_total": None,
        }
        if schema_version != 2:
            del case["expected_items"]
        cases.append(case)
    manifest = {"cases": cases, "coverage_gaps": []}
    if schema_version == 2:
        manifest["schema_version"] = 2
    if synthetic:
        manifest["synthetic"] = True
    path = directory / "manifest.json"
    path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    return path


def run(monkeypatch, provider, manifest, *flags):
    monkeypatch.setattr(evaluation, "configured_vision", lambda: provider)
    output = manifest.parent / "report.json"
    evaluation.main(
        [
            "--mode",
            "vision",
            "--manifest",
            str(manifest),
            "--output",
            str(output),
            "--interval-seconds",
            "0",
            *flags,
        ]
    )
    return json.loads(output.read_text())


def test_vision_refuses_a_remote_provider_without_explicit_permission(workspace, monkeypatch):
    provider = FakeProvider(meal())
    with pytest.raises(SystemExit) as refused:
        run(monkeypatch, provider, write_manifest(workspace))
    assert refused.value.code == 2
    assert provider.calls == []


def test_local_provider_keeps_working_without_the_permission_flag(workspace, monkeypatch):
    provider = FakeProvider(meal(), meal())
    provider.name = "ollama-local"
    report = run(monkeypatch, provider, write_manifest(workspace))
    assert report["live_provider_calls"] == 2


def test_permitted_run_reports_provenance_and_sends_no_labels(workspace, monkeypatch):
    provider = FakeProvider(meal(), meal())
    manifest = write_manifest(workspace, locale="he-IL")
    report = run(monkeypatch, provider, manifest, "--allow-live-api")
    assert report["synthetic"] is True
    assert report["limitations"][0].startswith("SYNTHETIC FIXTURE")
    assert report["manifest_schema_version"] == 2
    assert report["live_provider_calls"] == 2
    assert report["summary"]["tp"] == 2
    assert report["summary"]["status_accuracy"] == 1
    for _images, options in provider.calls:
        assert options.language == "he"
        assert options.context == ""
        assert options.plate_diameter_cm is None


def test_invalid_v2_manifest_spends_no_request(workspace, monkeypatch):
    path = write_manifest(workspace)
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest["cases"][0]["license"] = "All rights reserved"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    provider = FakeProvider(meal())
    with pytest.raises(SystemExit):
        run(monkeypatch, provider, path, "--allow-live-api")
    assert provider.calls == []


def test_changed_late_image_spends_no_request(workspace, monkeypatch):
    path = write_manifest(workspace)
    (workspace / "images" / "case1.png").write_bytes(b"changed")
    provider = FakeProvider(meal())
    with pytest.raises(ValueError, match="hash changed: case1"):
        run(monkeypatch, provider, path, "--allow-live-api")
    assert provider.calls == []


def test_quota_stop_blocks_the_rest_and_keeps_failures_in_end_to_end_recall(workspace, monkeypatch):
    provider = FakeProvider(meal(), VisionQuotaExceeded("Quota"), meal())
    report = run(monkeypatch, provider, write_manifest(workspace, 3), "--allow-live-api")
    assert [row["status"] for row in report["results"]] == ["ok", "failed", "blocked"]
    assert report["stop_reason"] == "Quota reached"
    assert report["results"][2]["reason"] == "Quota reached"
    assert len(provider.calls) == 2
    assert report["summary"]["recall"] == 1
    assert report["summary"]["end_to_end_recall"] == pytest.approx(1 / 3)


def test_breaker_stops_after_more_than_three_consecutive_failures(workspace, monkeypatch):
    provider = FakeProvider(*[unavailable() for _ in range(6)])
    report = run(monkeypatch, provider, write_manifest(workspace, 6), "--allow-live-api")
    assert [row["status"] for row in report["results"]] == ["failed"] * 4 + ["blocked"] * 2
    assert report["stop_reason"] == "Repeated provider failures"
    assert len(provider.calls) == 4


def test_a_success_resets_the_breaker(workspace, monkeypatch):
    responses = [unavailable(), unavailable(), unavailable(), meal()] + [unavailable()] * 3
    provider = FakeProvider(*responses)
    report = run(monkeypatch, provider, write_manifest(workspace, 7), "--allow-live-api")
    assert report["stop_reason"] is None
    assert len(provider.calls) == 7


def test_token_budget_stops_after_the_call_that_exceeds_it(workspace, monkeypatch):
    provider = FakeProvider(meal(), meal(), meal())
    report = run(
        monkeypatch,
        provider,
        write_manifest(workspace, 3),
        "--allow-live-api",
        "--max-total-tokens",
        "1500",
    )
    assert [row["status"] for row in report["results"]] == ["ok", "ok", "blocked"]
    assert report["tokens_used"] == 2000
    assert report["stop_reason"] == "Token budget reached"


def test_max_cases_truncates_and_says_so(workspace, monkeypatch):
    provider = FakeProvider(meal())
    report = run(
        monkeypatch, provider, write_manifest(workspace, 3), "--allow-live-api", "--max-cases", "1"
    )
    assert report["cases_in_manifest"] == 3
    assert report["cases_evaluated"] == 1
    assert report["truncated"] is True
    assert any("--max-cases" in note for note in report["limitations"])


@pytest.mark.parametrize(
    "flags",
    [
        ["--max-cases", "61"],
        ["--max-cases", "0"],
        ["--max-total-tokens", "0"],
        ["--interval-seconds", "-1"],
        ["--cache-only"],
    ],
)
def test_invalid_budget_flags_are_rejected(flags):
    with pytest.raises(SystemExit) as refused:
        evaluation.main(["--mode", "vision", *flags])
    assert refused.value.code == 2


def test_cache_replay_costs_no_call_regrounds_and_is_labeled(workspace, monkeypatch):
    manifest = write_manifest(workspace)
    cache = workspace / ".eval_cache"
    first = run(
        monkeypatch,
        FakeProvider(meal(), meal()),
        manifest,
        "--allow-live-api",
        "--cache-dir",
        str(cache),
    )
    assert (first["live_provider_calls"], first["cache_hits"]) == (2, 0)
    assert (cache / ".gitignore").read_text(encoding="utf-8") == "*\n"

    untouched = FakeProvider()
    replay = run(monkeypatch, untouched, manifest, "--cache-dir", str(cache), "--cache-only")
    assert untouched.calls == []
    assert (replay["live_provider_calls"], replay["cache_hits"]) == (0, 2)
    assert replay["tokens_used"] == 0
    assert all(row["cached"] for row in replay["results"])
    assert any("replayed from cache" in note for note in replay["limitations"])
    assert replay["summary"]["tp"] == first["summary"]["tp"]
    first_foods = first["results"][0]["output"]["foods"]
    replay_foods = replay["results"][0]["output"]["foods"]
    assert replay_foods[0]["reference"] == first_foods[0]["reference"]


def test_cache_does_not_store_weighed_labels(workspace, monkeypatch):
    manifest = write_manifest(workspace, 1)
    cache = workspace / ".eval_cache"
    run(
        monkeypatch,
        FakeProvider(meal("pear")),
        manifest,
        "--allow-live-api",
        "--cache-dir",
        str(cache),
    )
    stored = [path for path in cache.iterdir() if path.suffix == ".json"]
    assert len(stored) == 1
    assert "תפוח" not in stored[0].read_text(encoding="utf-8")
    assert "apple" not in stored[0].read_text(encoding="utf-8")


def test_cache_only_miss_fails_the_case_without_a_call_or_breaker(workspace, monkeypatch):
    provider = FakeProvider(meal())
    report = run(
        monkeypatch,
        provider,
        write_manifest(workspace, 5),
        "--cache-dir",
        str(workspace / ".eval_cache"),
        "--cache-only",
    )
    assert provider.calls == []
    assert report["stop_reason"] is None
    assert [row["status"] for row in report["results"]] == ["failed"] * 5
    assert report["summary"]["completed"] == 0


def test_requests_are_paced_only_after_a_live_call(workspace, monkeypatch):
    pauses = []
    monkeypatch.setattr(evaluation.time, "sleep", pauses.append)
    manifest = write_manifest(workspace, 3)
    cache = workspace / ".eval_cache"
    monkeypatch.setattr(
        evaluation, "configured_vision", lambda: FakeProvider(meal(), meal(), meal())
    )
    common = [
        "--mode",
        "vision",
        "--manifest",
        str(manifest),
        "--output",
        str(workspace / "r.json"),
    ]
    evaluation.main([*common, "--allow-live-api", "--cache-dir", str(cache)])
    assert pauses == [13, 13]  # Default spacing, between calls and not after the last.
    pauses.clear()
    evaluation.main([*common, "--cache-dir", str(cache), "--cache-only"])
    assert pauses == []


def test_v1_shaped_manifest_keeps_label_detection_and_v1_limitations(workspace, monkeypatch):
    manifest = write_manifest(workspace, 1, schema_version=1, synthetic=False)
    report = run(monkeypatch, FakeProvider(meal("apple")), manifest, "--allow-live-api")
    assert report["manifest_schema_version"] == 1
    assert report["results"][0]["detection"] == {"tp": 1, "fp": 0, "fn": 0}
    assert "item_scores" not in report["results"][0]
    assert report["synthetic"] is False


def test_baseline_mode_needs_no_provider_or_permission(workspace, monkeypatch):
    class FakeClassifier:
        def __init__(self, _catalog):
            pass

        def predict(self, _image):
            return {"status": "recognized", "candidates": [{"name": "apple"}]}

    def no_provider():
        raise AssertionError("Baseline must not configure a vision provider.")

    monkeypatch.setattr(evaluation, "Classifier", FakeClassifier)
    monkeypatch.setattr(evaluation, "configured_vision", no_provider)
    manifest = write_manifest(workspace, 1, schema_version=1, synthetic=False)
    evaluation.main(["--mode", "baseline", "--manifest", str(manifest)])
    report = json.loads((workspace / "manifest-baseline-report.json").read_text())
    assert report["summary"]["tp"] == 1
    assert report["live_provider_calls"] == 0
