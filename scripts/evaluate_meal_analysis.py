"""Measured small-sample baseline/vision evaluation. No fabricated successes.

python scripts/evaluate_meal_analysis.py --mode baseline
python scripts/evaluate_meal_analysis.py --mode vision --allow-live-api  # free Gemini project
python scripts/evaluate_meal_analysis.py --mode vision --manifest m.json --cache-dir .eval_cache
Only licensed manifest images are uploaded. Weighed labels are NEVER sent to vision.
Metrics, CLI changes and manifest v2 are described in evaluations/meal_analysis/README.md.
"""

import argparse
import hashlib
import json
import math
import os
import re
import statistics
import time
from datetime import UTC, datetime
from pathlib import Path

from foodlogger.analysis_schemas import AnalysisOptions, VisionMeal
from foodlogger.classifier import Classifier, ModelUnavailable
from foodlogger.images import decode_image
from foodlogger.meal_analysis import AnalysisService
from foodlogger.nutrition import Catalog
from foodlogger.nutrition_reference import ReferenceCatalog, aggregate, scale_nutrients
from foodlogger.vision import PROMPT, VisionQuotaExceeded, VisionUnavailable, configured_vision

ROOT = Path("evaluations/meal_analysis")
NUTRIENT_KEYS = ("calories", "protein", "carbs", "fat")
STATUSES = {"food", "no_food", "uncertain"}
TIERS = {
    "gravimetric",
    "decomposition",
    "clarification_and_id",
    "abstention",
    "identification_only",
}
PERMITTED_LICENSES = {"CC0-1.0", "CC-BY-4.0"}
TOTAL_SOURCES = {"usda_reference", "published_dataset"}
LOCAL_PROVIDERS = {"ollama-local"}
MAX_CASES_LIMIT = 60
CONSECUTIVE_FAILURE_LIMIT = 3
LABELS = {
    "sausage": ["sausage"],
    "spinach": ["spinach"],
    "almond": ["almond"],
    "apple": ["apple"],
    "yam": ["yam", "sweet potato"],
    "honeydew": ["honeydew"],
    "potato": ["potato"],
    "bacon": ["bacon"],
    "cauliflower": ["cauliflower"],
    "steak": ["steak", "beef"],
    "chicken": ["chicken"],
    "oatmeal": ["oatmeal", "porridge"],
    "cantaloupe": ["cantaloupe", "rockmelon"],
    "grape": ["grape"],
    "blackberry": ["blackberr"],
    "strawberry": ["strawberr"],
    "raspberry": ["raspberr"],
    "egg": ["egg"],
}


def canonical(name):
    text = name.lower().replace("_", " ")
    # Match at word starts so 'grape' does not match a substring in an unrelated word.
    for label, aliases in LABELS.items():
        if any(re.search(r"\b" + re.escape(alias), text) for alias in aliases):
            return label
    return text


def detection(expected, predicted):
    remaining = [canonical(x) for x in expected]
    tp = 0
    for name in predicted:
        label = canonical(name)
        if label in remaining:
            remaining.remove(label)
            tp += 1
    return {"tp": tp, "fp": len(predicted) - tp, "fn": len(remaining)}


def _normalized(text):
    return " ".join(text.casefold().replace("_", " ").split())


def _food_matches_item(food, item):
    """Whole-phrase alias match, so "eggplant" is not "egg" and "grapefruit" is not "grape"."""
    terms = [item["name"], *item.get("aliases", [])]
    names = [_normalized(food[key]) for key in ("search_name", "name") if food.get(key)]
    return any(
        re.search(r"(?<!\w)" + re.escape(_normalized(term)) + r"(?!\w)", name)
        for term in terms
        for name in names
    )


def match_items(items, foods):
    """Maximum one-to-one pairing, returned as {item index: food index}.

    The result does not depend on output order except when two foods compete for
    one item; then the earlier food keeps it and the later one is a false positive.
    """
    candidates = [
        [index for index, item in enumerate(items) if _food_matches_item(food, item)]
        for food in foods
    ]
    owner = {}

    def assign(food_index, seen):
        for item_index in candidates[food_index]:
            if item_index in seen:
                continue
            seen.add(item_index)
            if item_index not in owner or assign(owner[item_index], seen):
                owner[item_index] = food_index
                return True
        return False

    for food_index in range(len(foods)):
        assign(food_index, set())
    return owner


def _reference_outcome(item, food):
    """Compare only annotated items: an absent key is unannotated, null expects no reference."""
    if "usda_reference_id" not in item:
        return None
    expected = item["usda_reference_id"]
    actual = (food.get("reference") or {}).get("id")
    if expected is None:
        return "correct" if actual is None else "false_reference"
    if actual is None:
        return "missing"
    return "correct" if actual == expected else "wrong"


def score_item(case, item, food):
    expected_grams = item.get("grams")
    actual_grams = food.get("estimated_weight_g")
    known = expected_grams is not None and actual_grams is not None
    score = {
        "expected": item["name"],
        "predicted": food.get("search_name"),
        "grams_absolute_error": abs(actual_grams - expected_grams) if known else None,
        "grams_absolute_percentage_error": (
            abs(actual_grams - expected_grams) / expected_grams if known else None
        ),
        "reference_outcome": _reference_outcome(item, food),
        "nutrient_absolute_error": {},
    }
    expected_nutrients = item.get("scaled_nutrients")
    if case.get("ground_truth_tier") == "gravimetric" and expected_nutrients:
        actual_nutrients = food.get("nutrients") or {}
        # A missing value stays missing. It never becomes a zero error.
        score["nutrient_absolute_error"] = {
            key: None
            if actual_nutrients.get(key) is None or expected_nutrients.get(key) is None
            else abs(actual_nutrients[key] - expected_nutrients[key])
            for key in NUTRIENT_KEYS
        }
    return score


def _reference_with_grams(case):
    reference = dict(case.get("reference_total") or {})
    items = case.get("expected_items") or []
    if "grams" not in reference and items and all(i.get("grams") is not None for i in items):
        reference["grams"] = sum(i["grams"] for i in items)
    return reference


def expected_count(case):
    if case.get("expected_items") is not None:
        return len(case["expected_items"])
    labels = case.get("visible_food_labels")
    return None if labels is None else len(labels)


def score_case(case, result):
    """Row fields for a completed analysis. `result` is `AnalysisResult.model_dump()`."""
    foods = result["foods"]
    predicted = [food["search_name"] for food in foods]
    scored = {
        "predicted": predicted,
        "expected_status": case["expected_status"],
        "predicted_status": result["status"],
        "abstained": result["status"] == "no_food" and not foods,
        "absolute_error": {},
    }
    items = case.get("expected_items")
    if items is not None:
        pairs = match_items(items, foods)
        scored["detection"] = {
            "tp": len(pairs),
            "fp": len(foods) - len(pairs),
            "fn": len(items) - len(pairs),
        }
        scored["item_scores"] = [
            score_item(case, items[item_index], foods[food_index])
            for item_index, food_index in sorted(pairs.items())
        ]
    elif case.get("visible_food_labels") is not None:
        scored["detection"] = detection(case["visible_food_labels"], predicted)
    if case["expected_status"] != "no_food":
        estimate = {
            **result["total"],
            "grams": sum(food["estimated_weight_g"] for food in foods),
        }
        reference = _reference_with_grams(case)
        scored["reference_calories"] = reference.get("calories")
        for key, actual in reference.items():
            scored["absolute_error"][key] = (
                None if estimate[key] is None or actual is None else abs(estimate[key] - actual)
            )
    return scored


def _mean(values):
    return statistics.mean(values) if values else None


def summarize_v2(successful, counts):
    """Metrics added for G58. All rates are fractions, so 0.125 means 12.5%."""
    items = [score for row in successful for score in row.get("item_scores", [])]
    grams = [s["grams_absolute_error"] for s in items if s["grams_absolute_error"] is not None]
    gram_rates = [
        s["grams_absolute_percentage_error"]
        for s in items
        if s["grams_absolute_percentage_error"] is not None
    ]
    calorie_rates = [
        row["absolute_error"]["calories"] / row["reference_calories"]
        for row in successful
        if row.get("absolute_error", {}).get("calories") is not None
        and (row.get("reference_calories") or 0) > 0
    ]
    nutrient_rows = [s["nutrient_absolute_error"] for s in items if s["nutrient_absolute_error"]]
    nutrient_values = {
        key: [row[key] for row in nutrient_rows if row[key] is not None] for key in NUTRIENT_KEYS
    }
    outcomes = [s["reference_outcome"] for s in items if s["reference_outcome"] is not None]
    reference_counts = {
        key: outcomes.count(key) for key in ("correct", "wrong", "missing", "false_reference")
    }
    with_status = [row for row in successful if row.get("predicted_status") is not None]
    non_food = [row for row in with_status if row.get("expected_status") == "no_food"]
    denominator = 2 * counts["tp"] + counts["fp"] + counts["fn"]
    return {
        "f1": 2 * counts["tp"] / denominator if denominator else None,
        "status_accuracy": (
            sum(row["predicted_status"] == row["expected_status"] for row in with_status)
            / len(with_status)
            if with_status
            else None
        ),
        "non_food_abstention_rate": (
            sum(bool(row.get("abstained")) for row in non_food) / len(non_food)
            if non_food
            else None
        ),
        "usda_reference_accuracy": (
            reference_counts["correct"] / len(outcomes) if outcomes else None
        ),
        "usda_reference_counts": reference_counts,
        "item_grams_mae": _mean(grams),
        "item_grams_mape": _mean(gram_rates),
        "calorie_mape": _mean(calorie_rates),
        "item_nutrient_mae": {key: _mean(values) for key, values in nutrient_values.items()},
        "v2_sample_counts": {
            "status": len(with_status),
            "non_food": len(non_food),
            "matched_items": len(items),
            "item_grams": len(grams),
            "calorie_mape": len(calorie_rates),
            "item_nutrient": {key: len(values) for key, values in nutrient_values.items()},
            "item_nutrient_missing": {
                key: len(nutrient_rows) - len(values) for key, values in nutrient_values.items()
            },
        },
    }


def summarize(rows):
    successful = [row for row in rows if row.get("status") == "ok"]
    counts = {
        k: sum(row.get("detection", {}).get(k, 0) for row in successful) for k in ["tp", "fp", "fn"]
    }

    def ratio(a, b):
        return None if b == 0 else a / b

    values = {
        k: [
            row["absolute_error"][k]
            for row in successful
            if row.get("absolute_error", {}).get(k) is not None
        ]
        for k in ["grams", "calories", "protein", "fat", "carbs"]
    }
    return {
        "completed": len(successful),
        "failed_or_blocked": len(rows) - len(successful),
        "completion_rate": ratio(len(successful), len(rows)),
        **counts,
        "precision": ratio(counts["tp"], counts["tp"] + counts["fp"]),
        "recall": ratio(counts["tp"], counts["tp"] + counts["fn"]),
        "end_to_end_recall": (
            ratio(counts["tp"], sum(row["expected_food_count"] for row in rows))
            if rows and all(row.get("expected_food_count") is not None for row in rows)
            else None
        ),
        "missed_item_rate": ratio(counts["fn"], counts["tp"] + counts["fn"]),
        "false_discovery_rate": ratio(counts["fp"], counts["tp"] + counts["fp"]),
        "mean_latency_ms": statistics.mean([r["elapsed_ms"] for r in successful])
        if successful
        else None,
        "mean_absolute_error": {k: statistics.mean(v) if v else None for k, v in values.items()},
        "error_sample_counts": {k: len(v) for k, v in values.items()},
        "paid_api_cost_usd": 0,
        **summarize_v2(successful, counts),
    }


def _same_nutrients(left, right):
    return all(
        (left.get(key) is None) == (right.get(key) is None)
        and (left.get(key) is None or math.isclose(left[key], right[key], abs_tol=1e-6))
        for key in NUTRIENT_KEYS
    )


def _validate_items(case, references, errors):
    """Ground truth must come from canonical USDA records or the published dataset."""
    label = case.get("id", "?")
    usda_totals = case.get("reference_total_source", "usda_reference") == "usda_reference"
    gravimetric = case.get("ground_truth_tier") == "gravimetric"
    for item in case["expected_items"]:
        name = item.get("name")
        if not name:
            errors.append(f"{label}: expected item without a name")
            continue
        grams = item.get("grams")
        if grams is None:
            if gravimetric:
                errors.append(f"{label}/{name}: gravimetric item needs grams")
        elif (
            isinstance(grams, bool) or not isinstance(grams, int | float) or not 1 <= grams <= 2000
        ):
            errors.append(f"{label}/{name}: grams must be 1-2000 or null")
            continue
        reference_id = item.get("usda_reference_id")
        scaled = item.get("scaled_nutrients")
        if reference_id is None:
            if scaled and usda_totals:
                errors.append(f"{label}/{name}: scaled_nutrients without a USDA reference")
            continue
        if reference_id not in references.records:
            errors.append(f"{label}/{name}: unknown reference {reference_id}")
            continue
        record = references.get(reference_id)
        stated_name = item.get("usda_reference_name")
        if stated_name is not None and stated_name != record.name:
            errors.append(f"{label}/{name}: usda_reference_name is not {record.name!r}")
        if scaled and usda_totals:
            if grams is None:
                errors.append(f"{label}/{name}: scaled_nutrients without grams")
            elif not _same_nutrients(scaled, scale_nutrients(record.nutrition.model_dump(), grams)):
                errors.append(f"{label}/{name}: scaled_nutrients differ from {reference_id}")


def _validate_total(case, errors):
    total = case.get("reference_total")
    if total is None or case.get("reference_total_source", "usda_reference") != "usda_reference":
        return
    label = case.get("id", "?")
    items = case["expected_items"]
    if not items or any(not item.get("scaled_nutrients") for item in items):
        errors.append(f"{label}: reference_total needs scaled_nutrients on every item")
    elif not _same_nutrients(total, aggregate([item["scaled_nutrients"] for item in items])):
        errors.append(f"{label}: reference_total is not the sum of scaled_nutrients")
    extra = set(total) - {*NUTRIENT_KEYS, "grams"}
    if extra:
        errors.append(f"{label}: unknown reference_total keys {sorted(extra)}")


def validate_manifest_v2(manifest, references):
    """Return every problem, so an invalid manifest spends no provider requests."""
    errors = []
    cases = manifest.get("cases")
    if not isinstance(cases, list) or not cases:
        return ["manifest needs a nonempty cases list"]
    ids = [case.get("id") for case in cases]
    if len(set(ids)) != len(ids):
        errors.append("case ids must be unique")
    for case in cases:
        label = case.get("id", "?")
        file = str(case.get("file", ""))
        if not file or Path(file).anchor or ".." in Path(file).parts:
            errors.append(f"{label}: file must be a relative path inside the manifest directory")
        if not re.fullmatch(r"[0-9a-f]{64}", str(case.get("sha256", ""))):
            errors.append(f"{label}: sha256 must be 64 lowercase hex characters")
        if case.get("license") not in PERMITTED_LICENSES:
            errors.append(f"{label}: license must be one of {sorted(PERMITTED_LICENSES)}")
        if not case.get("source_url"):
            errors.append(f"{label}: source_url is required")
        status = case.get("expected_status")
        if status not in STATUSES:
            errors.append(f"{label}: expected_status must be one of {sorted(STATUSES)}")
        if case.get("ground_truth_tier") not in TIERS:
            errors.append(f"{label}: ground_truth_tier must be one of {sorted(TIERS)}")
        if case.get("reference_total_source", "usda_reference") not in TOTAL_SOURCES:
            errors.append(f"{label}: reference_total_source must be one of {sorted(TOTAL_SOURCES)}")
        items = case.get("expected_items")
        if not isinstance(items, list):
            errors.append(f"{label}: expected_items must be a list")
            continue
        if status == "no_food" and (items or case.get("reference_total")):
            errors.append(f"{label}: a no_food case cannot have items or a reference_total")
        if status == "food" and not items:
            errors.append(f"{label}: a food case needs expected_items")
        _validate_items(case, references, errors)
        _validate_total(case, errors)
    return errors


class EvaluationProvider:
    """Counts provider calls and, when asked, replays stored observations.

    Grounding still runs on every replay, so a retrieval change can be re-scored
    without a provider request. Observations are stored, weighed labels are not.
    """

    def __init__(self, provider, cache_dir=None, cache_only=False):
        self.provider = provider
        self.name = provider.name
        self.model = provider.model
        self.cache_dir = Path(cache_dir) if cache_dir else None
        self.cache_only = cache_only
        self.live_calls = 0
        self.cache_hits = 0
        if self.cache_dir:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            (self.cache_dir / ".gitignore").write_text("*\n", encoding="utf-8")

    def _path(self, images, options):
        fingerprint = hashlib.sha256()
        for part in (
            hashlib.sha256(PROMPT.encode()).hexdigest(),
            self.model,
            options.model_dump_json(),
            *(hashlib.sha256(image).hexdigest() for image in images),
        ):
            fingerprint.update(part.encode() + b"\0")
        return self.cache_dir / (fingerprint.hexdigest() + ".json")

    def recognize(self, images, options):
        path = self._path(images, options) if self.cache_dir else None
        if path and path.exists():
            stored = json.loads(path.read_text(encoding="utf-8"))
            self.cache_hits += 1
            return VisionMeal.model_validate(stored["observation"]), stored["usage"]
        if self.cache_only:
            raise VisionUnavailable("No stored observation for this image in --cache-only mode.")
        self.live_calls += 1
        observation, usage = self.provider.recognize(images, options)
        if path:
            temporary = path.with_suffix(".tmp")
            temporary.write_text(
                json.dumps({"observation": observation.model_dump(), "usage": usage}),
                encoding="utf-8",
            )
            temporary.replace(path)
        return observation, usage


def _total_tokens(usage):
    total = usage.get("total_tokens")
    if total is not None:
        return total
    return sum(usage.get(key) or 0 for key in ("input_tokens", "output_tokens", "thinking_tokens"))


def _limitations(manifest, default_manifest, cache_hits, truncated):
    notes = []
    if manifest.get("synthetic") is True:
        notes.append(
            "SYNTHETIC FIXTURE: these numbers test the evaluator and are not product accuracy."
        )
    if default_manifest:
        notes += [
            "8-image convenience sample, not representative accuracy.",
            "Presence labels reviewed by implementation agent; no independent human adjudication.",
        ]
    if truncated:
        notes.append("--max-cases stopped before the end of the manifest; cohorts may be missing.")
    if cache_hits:
        notes.append(
            f"{cache_hits} observation(s) replayed from cache: not a new provider measurement, "
            "and their latency is not provider latency."
        )
    return [
        *notes,
        "Alias matching is a transparent label proxy, not an LLM judge.",
        "Precision/recall are conditional on successful responses. End-to-end recall "
        "counts failed/blocked images as missed expected components.",
        "Item gram, nutrient and USDA reference metrics cover matched items only; "
        "missed components count against recall instead.",
        "Baseline provides at most one accepted item and no weight estimate.",
        "Zero paid API calls; electricity and hardware costs are not measured.",
        *manifest.get("coverage_gaps", []),
    ]


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["baseline", "vision"], required=True)
    parser.add_argument("--output")
    parser.add_argument("--interval-seconds", type=float, default=13)
    parser.add_argument("--manifest", help="default: evaluations/meal_analysis/manifest.json")
    parser.add_argument(
        "--allow-live-api",
        action="store_true",
        help="required before --mode vision may call a non-local provider",
    )
    parser.add_argument("--max-cases", type=int, default=10, help="first N cases, at most 60")
    parser.add_argument("--max-total-tokens", type=int, default=150000)
    parser.add_argument("--cache-dir", help="store and replay provider observations here")
    parser.add_argument(
        "--cache-only",
        action="store_true",
        help="replay from --cache-dir; a miss is a failed case and no provider is called",
    )
    args = parser.parse_args(argv)
    if args.interval_seconds < 0:
        parser.error("--interval-seconds must be nonnegative")
    if not 1 <= args.max_cases <= MAX_CASES_LIMIT:
        parser.error(f"--max-cases must be 1-{MAX_CASES_LIMIT}")
    if args.max_total_tokens < 1:
        parser.error("--max-total-tokens must be positive")
    if args.cache_only and not args.cache_dir:
        parser.error("--cache-only needs --cache-dir")
    if args.cache_dir and args.mode != "vision":
        parser.error("--cache-dir applies only to --mode vision")
    env = Path(".env")
    if env.exists():
        for line in env.read_text().splitlines():
            name, sep, value = line.partition("=")
            if sep and name in {"GEMINI_API_KEY", "FOODLOGGER_GEMINI_FREE_TIER_CONFIRMED"}:
                os.environ.setdefault(name, value.strip().strip('"'))
    default_manifest = args.manifest is None
    manifest_path = ROOT / "manifest.json" if default_manifest else Path(args.manifest)
    base = manifest_path.parent
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") == 2:
        errors = validate_manifest_v2(manifest, ReferenceCatalog())
        if errors:
            parser.error("invalid v2 manifest:\n" + "\n".join(errors))
    provider = None
    if args.mode == "vision":
        configured = configured_vision()
        if (
            configured.name not in LOCAL_PROVIDERS
            and not args.cache_only
            and not args.allow_live_api
        ):
            parser.error(
                f"--mode vision would call {configured.name}. Pass --allow-live-api after "
                "approval, or --cache-only to replay stored observations."
            )
        provider = EvaluationProvider(configured, args.cache_dir, args.cache_only)
    cases = manifest["cases"][: args.max_cases]
    truncated = len(cases) < len(manifest["cases"])
    # Check every image first: a late mismatch would waste the requests already spent.
    images = {}
    for case in cases:
        images[case["id"]] = (base / case["file"]).read_bytes()
        if hashlib.sha256(images[case["id"]]).hexdigest() != case["sha256"]:
            raise ValueError("Evaluation image hash changed: " + case["id"])
    engine = Classifier(Catalog()) if args.mode == "baseline" else AnalysisService(provider)
    rows = []
    stop_reason = None
    consecutive_failures = 0
    tokens_used = 0
    previous_call_was_live = False
    for case in cases:
        row = {"id": case["id"], "expected_food_count": expected_count(case)}
        if stop_reason:
            rows.append({**row, "status": "blocked", "reason": stop_reason})
            continue
        if previous_call_was_live:
            time.sleep(args.interval_seconds)
        image = images[case["id"]]
        calls_before = provider.live_calls if provider else 0
        begin = time.perf_counter()
        try:
            if args.mode == "baseline":
                with decode_image(image) as decoded:
                    output = engine.predict(decoded)
                predicted = (
                    [output["candidates"][0]["name"]] if output["status"] == "recognized" else []
                )
                row.update(predicted=predicted, absolute_error={})
                # Baseline has no automatic portion or nutrient estimate.
                if case.get("visible_food_labels") is not None:
                    row["detection"] = detection(case["visible_food_labels"], predicted)
            else:
                language = "he" if str(case.get("locale", "")).startswith("he") else "en"
                result = engine.analyze(
                    [image], AnalysisOptions(language=language), "public-evaluation", case["id"]
                )
                output = result.model_dump()
                row.update(score_case(case, output))
                predicted = row["predicted"]
                consecutive_failures = 0
                if provider.live_calls > calls_before:
                    tokens_used += _total_tokens(result.usage)
                else:
                    row["cached"] = True
                if tokens_used > args.max_total_tokens:
                    stop_reason = "Token budget reached"
            row.update(
                status="ok",
                elapsed_ms=round((time.perf_counter() - begin) * 1000),
                output=output,
            )
            rows.append(row)
            print(case["id"], row["elapsed_ms"], predicted, flush=True)
        except (VisionUnavailable, ModelUnavailable) as error:
            if isinstance(error, VisionQuotaExceeded):
                stop_reason = "Quota reached"
            elif provider and provider.live_calls > calls_before:
                consecutive_failures += 1
                if consecutive_failures > CONSECUTIVE_FAILURE_LIMIT:
                    stop_reason = "Repeated provider failures"
            cause = error.__cause__
            upstream_status = getattr(getattr(cause, "response", None), "status_code", None)
            rows.append(
                {
                    **row,
                    "status": "failed",
                    "reason": str(error),
                    "cause_type": type(cause).__name__ if cause else None,
                    "upstream_status": upstream_status,
                    "elapsed_ms": round((time.perf_counter() - begin) * 1000),
                }
            )
            print(case["id"], "failed", str(error), upstream_status, flush=True)
        previous_call_was_live = bool(provider and provider.live_calls > calls_before)
    report = {
        "evaluator_version": 2,
        "mode": args.mode,
        "evaluated_at": datetime.now(UTC).isoformat(),
        "provider": getattr(getattr(engine, "provider", None), "name", None),
        "model": getattr(getattr(engine, "provider", None), "model", None),
        "manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
        "manifest_schema_version": manifest.get("schema_version", 1),
        "synthetic": manifest.get("synthetic") is True,
        "cases_in_manifest": len(manifest["cases"]),
        "cases_evaluated": len(cases),
        "truncated": truncated,
        "live_provider_calls": provider.live_calls if provider else 0,
        "cache_hits": provider.cache_hits if provider else 0,
        "tokens_used": tokens_used,
        "stop_reason": stop_reason,
        "summary": summarize(rows),
        "results": rows,
        "limitations": _limitations(
            manifest, default_manifest, provider.cache_hits if provider else 0, truncated
        ),
    }
    if args.output:
        path = Path(args.output)
    elif default_manifest:
        path = ROOT / (args.mode + "-report.json")
    else:
        path = base / f"{manifest_path.stem}-{args.mode}-report.json"
    path.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report["summary"], indent=2))


if __name__ == "__main__":
    main()
