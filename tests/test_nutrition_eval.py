"""Deterministic offline evaluation benchmark for USDA nutrition reference retrieval.

This test suite evaluates Hebrew and English food query retrieval against the
bundled USDA FoodData Central catalog (`src/foodlogger/data/usda_reference.json`).
It measures reference retrieval and query normalization only; it does NOT claim
multimodal photo recognition accuracy.
"""

import json
from pathlib import Path

import pytest

from foodlogger.nutrition_reference import ALIASES, ReferenceCatalog

REPO_ROOT = Path(__file__).resolve().parents[1]
BENCHMARK_PATH = (
    REPO_ROOT / "evaluations" / "nutrition_reference" / "hebrew_retrieval_benchmark.json"
)
REPORT_PATH = REPO_ROOT / "evaluations" / "nutrition_reference" / "retrieval_eval_report.json"


@pytest.fixture(scope="module")
def catalog() -> ReferenceCatalog:
    return ReferenceCatalog()


@pytest.fixture(scope="module")
def benchmark_data() -> dict:
    return json.loads(BENCHMARK_PATH.read_text(encoding="utf-8"))


def _is_acceptable(food_name: str, acceptable_prefixes: list[str]) -> bool:
    lowered = food_name.lower()
    return any(lowered.startswith(prefix.lower()) for prefix in acceptable_prefixes)


def test_benchmark_fixture_schema_and_provenance(
    catalog: ReferenceCatalog, benchmark_data: dict
) -> None:
    """Verify benchmark structure, case counts, and that all expected IDs exist in USDA."""
    assert benchmark_data["benchmark_id"] == "biteflow-nutrition-retrieval-he-en-v1"
    cases = benchmark_data["cases"]
    assert len(cases) >= 150
    assert len(cases) == benchmark_data["total_cases"]

    seen_ids = set()
    match_cases = [c for c in cases if c["expected_mode"] == "match"]
    abstain_cases = [c for c in cases if c["expected_mode"] == "abstain"]

    assert len(match_cases) == benchmark_data["match_cases_count"]
    assert len(abstain_cases) == benchmark_data["abstain_cases_count"]
    assert len(abstain_cases) >= 15

    # Ensure both Hebrew and English queries are well represented
    he_cases = [c for c in cases if c["language"] == "he"]
    en_cases = [c for c in cases if c["language"] == "en"]
    assert len(he_cases) >= 120
    assert len(en_cases) >= 35

    for case in cases:
        case_id = case["id"]
        assert case_id not in seen_ids, f"Duplicate benchmark case id: {case_id}"
        seen_ids.add(case_id)
        assert case["query"].strip()
        assert case["preparation"] in {
            "unknown",
            "raw",
            "cooked",
            "fried",
            "grilled",
            "roasted",
            "boiled",
            "steamed",
            "baked",
        }
        if case["expected_mode"] == "match":
            assert case["acceptable_prefixes"], f"Match case {case_id} missing acceptable_prefixes"
            expected_id = case["expected_top1_id"]
            assert expected_id in catalog.records, (
                f"Expected USDA ID {expected_id} for {case_id} does not exist in bundled catalog"
            )
            ref = catalog.get(expected_id)
            assert ref.source == "USDA FoodData Central"
            assert ref.nutrition.calories is not None


def test_hebrew_and_english_retrieval_benchmark_accuracy(
    catalog: ReferenceCatalog, benchmark_data: dict
) -> None:
    """Verify top-1 accuracy, top-5 hit rate, and zero false-positive abstentions."""
    cases = benchmark_data["cases"]
    match_cases = [c for c in cases if c["expected_mode"] == "match"]
    abstain_cases = [c for c in cases if c["expected_mode"] == "abstain"]

    top1_correct = 0
    top5_hits = 0
    missing_matches = []
    wrong_top1 = []

    for case in match_cases:
        results = catalog.search(case["query"], case["preparation"], limit=5)
        if not results:
            missing_matches.append(case["id"])
            continue
        if _is_acceptable(results[0].name, case["acceptable_prefixes"]):
            top1_correct += 1
        else:
            wrong_top1.append((case["id"], case["query"], results[0].id, results[0].name))
        if any(_is_acceptable(r.name, case["acceptable_prefixes"]) for r in results):
            top5_hits += 1

    false_positives = []
    for case in abstain_cases:
        results = catalog.search(case["query"], case["preparation"], limit=5)
        if results:
            false_positives.append((case["id"], case["query"], results[0].id, results[0].name))

    top1_accuracy = top1_correct / len(match_cases)
    top5_hit_rate = top5_hits / len(match_cases)

    assert not missing_matches, f"Missing matches for benchmark cases: {missing_matches}"
    assert not wrong_top1, f"Wrong top-1 matches: {wrong_top1}"
    assert not false_positives, (
        f"Unresolved dishes must abstain instead of fabricating matches: {false_positives}"
    )
    assert top1_accuracy >= 0.95
    assert top5_hit_rate >= 0.98


def test_abstention_safety_never_fabricates_israeli_composite_dishes(
    catalog: ReferenceCatalog,
) -> None:
    """Composite Israeli dishes absent from USDA must return empty list rather than guessing."""
    must_abstain = [
        ("שקשוקה", "cooked"),
        ("סביח", "unknown"),
        ("בורקס", "baked"),
        ("מלאווח", "fried"),
        ("ג׳חנון", "baked"),
        ("קובה", "cooked"),
        ("במבה", "unknown"),
        ("לבנה", "unknown"),
        ("שווארמה", "cooked"),
        ("קבב", "grilled"),
        ("פתיתים", "cooked"),
        ("פיתה כוסמין", "baked"),
        ("פיתה עם זעתר", "baked"),
    ]
    for query, prep in must_abstain:
        assert catalog.search(query, prep) == [], (
            f"Query {query!r} ({prep}) should abstain because USDA has no verified record"
        )


def test_fish_species_compound_dishes_and_whitespace_normalization(
    catalog: ReferenceCatalog,
) -> None:
    """Ensure species queries do not break compound dishes and multi-space aliases normalize."""
    for query in ("salmon sushi", "sushi topped with salmon"):
        rows = catalog.search(query)
        assert rows, f"Expected compound dish match for {query!r}"
        assert rows[0].id == "fdc:2708969"

    multi_space_pairs = [
        ("חזה  עוף", "חזה עוף", "grilled"),
        ("ביצה   קשה", "ביצה קשה", "boiled"),
        ("תפוח  אדמה", "תפוח אדמה", "cooked"),
        ("גבינת   קוטג'", "גבינת קוטג'", "unknown"),
    ]
    for spaced_query, clean_query, prep in multi_space_pairs:
        spaced_rows = catalog.search(spaced_query, prep)
        clean_rows = catalog.search(clean_query, prep)
        assert spaced_rows and clean_rows
        assert [r.id for r in spaced_rows] == [r.id for r in clean_rows]


def test_aliases_only_map_to_clean_english_tokens() -> None:
    """Ensure ALIASES contains substantial Hebrew coverage and no fabricated numbers."""
    assert len(ALIASES) == 348
    for key, target in ALIASES.items():
        assert key == key.strip()
        assert target == target.strip()
        assert target.isascii(), f"Alias target for {key!r} must be ASCII English: {target!r}"


def test_recorded_evaluation_report_matches_live_catalog(
    catalog: ReferenceCatalog, benchmark_data: dict
) -> None:
    """Ensure the committed evaluation report exactly matches live evaluation metrics."""
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    assert report["benchmark_id"] == benchmark_data["benchmark_id"]

    cases = benchmark_data["cases"]
    match_cases = [c for c in cases if c["expected_mode"] == "match"]
    abstain_cases = [c for c in cases if c["expected_mode"] == "abstain"]

    top1_correct = 0
    top5_hits = 0
    missing_matches = 0
    wrong_top1 = 0
    for case in match_cases:
        rows = catalog.search(case["query"], case["preparation"], limit=5)
        if not rows:
            missing_matches += 1
        else:
            if _is_acceptable(rows[0].name, case["acceptable_prefixes"]):
                top1_correct += 1
            else:
                wrong_top1 += 1
            if any(_is_acceptable(r.name, case["acceptable_prefixes"]) for r in rows):
                top5_hits += 1

    correct_abstentions = sum(
        1 for c in abstain_cases if not catalog.search(c["query"], c["preparation"], limit=5)
    )
    false_positives = len(abstain_cases) - correct_abstentions

    improved = report["improved_metrics"]
    assert improved["total_cases"] == len(cases)
    assert improved["match_cases"] == len(match_cases)
    assert improved["abstain_cases"] == len(abstain_cases)
    assert improved["positive_top1_correct"] == top1_correct
    assert improved["positive_top1_accuracy"] == round(top1_correct / len(match_cases), 4)
    assert improved["positive_top5_hits"] == top5_hits
    assert improved["positive_top5_hit_rate"] == round(top5_hits / len(match_cases), 4)
    assert improved["missing_matches"] == missing_matches
    assert improved["wrong_top1_matches"] == wrong_top1
    assert improved["correct_abstentions"] == correct_abstentions
    assert improved["false_positive_abstentions"] == false_positives
    assert improved["positive_top1_accuracy"] > report["baseline_metrics"]["positive_top1_accuracy"]
