# Held-Out Multimodal Photo Evaluation Benchmark Proposal (G58)

## 1. Objective & Scope Boundary
This document specifies the design, dataset schema, licensing gates, ground-truth protocol, metrics, and quota/cost guardrails for BiteFlow's held-out multimodal meal-photo evaluation benchmark (**G58**).

- **Zero Live API Calls in CI / Offline Suites:** All automated tests (`tests/test_nutrition_eval.py`, `tests/test_meal_analysis_evaluation.py`) run strictly offline without calling live vision providers. Currently, `scripts/evaluate_meal_analysis.py` exposes `--mode {baseline,vision}`, `--output`, and `--interval-seconds` (default `13.0`); under this proposal, live multimodal evaluation (`--mode vision`) will be gated behind explicit opt-in flags (`--allow-live-api` and hard budget/case caps) before any full held-out run.
- **No Extrapolation from Retrieval Benchmarks:** Offline USDA reference retrieval metrics (`evaluations/nutrition_reference/`) measure deterministic text normalization and lookup only; they must never be reported as photo recognition or portion estimation accuracy.

---

## 2. Dataset Sourcing, Licensing & Provenance Gates

Every image in the held-out photo benchmark must satisfy strict provenance and licensing requirements before inclusion in `evaluations/meal_analysis/`:

1. **Permitted Sources & Licenses:**
   - **First-Party Weighed Meal Photos (Primary Israeli & Home-Cooked Tier):** Original photos captured by team members or consenting testers where each component is weighed on a digital kitchen scale (`±1 g` precision) prior to plating, released under **CC0-1.0** or **CC-BY-4.0** with signed contributor consent and EXIF location/PII stripped.
   - **Nutrition5k (Google Research):** Overhead/multi-angle cafeteria plates with gravimetric component weights and USDA-linked macronutrients (permitted for non-commercial research benchmarking; images must be fetched locally on-demand via manifest checksums rather than redistributed in binary builds).
   - **FoodRecognition / Open-Access Subsets (CC0 / CC-BY-4.0 / Pexels / Wikimedia Commons):** Publicly licensed meal photos used strictly for **component identification and negative-control/abstention** cases where exact gram ground truth is marked `null` (`evaluation_tier: "identification_only"`), or paired with standardized packaged unit weights.
2. **Prohibited Sources:**
   - Scraped social media, restaurant delivery menus, or copyrighted food blogs without an explicit open license.
   - Any image containing faces, readable license plates, personal documents, or unconsented bystanders.
   - Any image used in few-shot prompt examples or development prompt tuning (strict train/eval separation).

---

## 3. Dataset Stratification & Target Composition (`n = 60` Held-Out Cases)

To stay within free-tier API quotas while covering real-world failure modes, the held-out benchmark is stratified into **60 cases** across four cohorts:

| Cohort | Cases | Description | Ground-Truth Tier |
| :--- | :---: | :--- | :--- |
| **A. Gravimetric Single & Multi-Item Plates** | 25 | Everyday plates (eggs, chicken breast, rice, salad, salmon, pasta, fruits) weighed per component on a kitchen scale (`±1 g`). | `gravimetric` (ID + grams + kcal/macros) |
| **B. Israeli & Middle Eastern Dishes** | 15 | Hummus, falafel, schnitzel, pita, cottage cheese, Israeli salad, plus composite dishes (`שקשוקה`, `סביח`, `בורקס`, `מלאווח`) that test decomposition vs. USDA abstention. | `gravimetric` / `decomposition` |
| **C. Packaged & Ambiguous Preparation Cases** | 10 | Visually ambiguous items (fried vs. baked, skinless vs. skin-on, dressing on side vs. mixed, obscure sauces) testing clarification questions (`needs_clarification`). | `clarification_and_id` |
| **D. Negative Controls & Abstention Cases** | 10 | Empty plates, non-food objects, severely blurred/dark frames, closed opaque containers, and pets/landscapes (`expected_status: "no_food"`). | `abstention` |

---

## 4. Benchmark Manifest Schema (Current v1 vs. Proposed v2 Extension)

Currently, `scripts/evaluate_meal_analysis.py` reads `evaluations/meal_analysis/manifest.json` with meal-level fields (`id`, `file`, `sha256`, `source_url`, `license`, `expected_status`, `visible_food_labels`, `reference_total`, and `ground_truth_tier`).

To support per-component portion MAE and canonical USDA reference verification in **G58**, the proposed v2 manifest (`evaluations/meal_analysis/benchmark.heldout.json`) preserves backward-compatible top-level keys while adding `expected_items` with weighed grams and canonical `fdc:*` IDs:

```json
{
  "id": "il_gravimetric_schnitzel_rice_01",
  "title": "Weighed breaded fried chicken schnitzel and cooked white rice",
  "file": "images/il_gravimetric_schnitzel_rice_01.jpg",
  "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
  "source_url": "https://openbot.local/datasets/biteflow-gravimetric-v1/il_gravimetric_schnitzel_rice_01",
  "license": "CC-BY-4.0",
  "cohort": "israeli_dishes",
  "ground_truth_tier": "gravimetric",
  "expected_status": "food",
  "visible_food_labels": ["chicken schnitzel", "white rice"],
  "image_source": {
    "origin": "first_party_weighed",
    "license": "CC-BY-4.0",
    "attribution": "BiteFlow Internal Gravimetric Collection",
    "scale_model": "OXO Good Grips 11lb Food Scale (±1g)",
    "captured_at": "2026-10-15"
  },
  "locale": "he-IL",
  "expected_items": [
    {
      "name": "chicken schnitzel",
      "aliases": ["שניצל", "שניצל עוף", "breaded fried chicken"],
      "preparation": "fried",
      "grams": 145.0,
      "usda_reference_id": "fdc:170718",
      "usda_reference_name": "Fast foods, chicken, breaded and fried, boneless pieces, plain",
      "scaled_nutrients": {
        "calories": 445.2,
        "protein": 23.1,
        "carbs": 21.6,
        "fat": 29.6
      }
    },
    {
      "name": "white rice",
      "aliases": ["אורז", "אורז לבן", "cooked rice"],
      "preparation": "cooked",
      "grams": 160.0,
      "usda_reference_id": "fdc:2708408",
      "usda_reference_name": "Rice, white, cooked, no added fat",
      "scaled_nutrients": {
        "calories": 206.4,
        "protein": 4.3,
        "carbs": 44.8,
        "fat": 0.4
      }
    }
  ],
  "reference_total": {
    "calories": 651.6,
    "protein": 27.4,
    "carbs": 66.4,
    "fat": 30.0
  }
}
```

*(Note: In the example above, `scaled_nutrients` and `reference_total` are computed directly via `scale_nutrients` and `aggregate` in `src/foodlogger/nutrition_reference.py` from `fdc:170718` [307.0 kcal, 15.9 g protein, 14.9 g carbs, 20.4 g fat per 100 g × 145 g] and `fdc:2708408` [129.0 kcal, 2.67 g protein, 28.0 g carbs, 0.28 g fat per 100 g × 160 g].)*

---

## 5. Ground-Truth Annotation Protocol

1. **Gravimetric Weighing (`ground_truth_tier: "gravimetric"`):**
   - Tare the plate/bowl on a digital scale (`±1 g` resolution).
   - Add each component sequentially, recording net edible mass in grams (`grams`) and photographing both intermediate and final plated states.
   - Cooking method (`raw`, `boiled`, `fried`, `grilled`, `baked`, `steamed`, `roasted`) and added cooking fats/oils (`grams`) must be logged explicitly.
2. **Canonical USDA Reference Binding:**
   - Each weighed component is mapped by two independent reviewers to its exact `fdc:*` ID in `src/foodlogger/data/usda_reference.json` (or flagged as `usda_reference_id: null` when the dish is absent from USDA and requires component decomposition or abstention).
   - Ground-truth `reference_total` values are computed deterministically via `scale_nutrients` and `aggregate` (`src/foodlogger/nutrition_reference.py`) from the weighed grams and canonical USDA per-100g values—never estimated by eye or LLM.
3. **Inter-Annotator Agreement:**
   - Any case where two reviewers disagree on component identity, cooking method, or USDA reference mapping is either resolved by recipe logs or excluded from the gravimetric tier.

---

## 6. Evaluation Metrics: Current v1 (`scripts/evaluate_meal_analysis.py`) vs. Proposed v2 Extensions

Currently, `scripts/evaluate_meal_analysis.py` implements `detection(expected, predicted)` and `summarize(rows)`, outputting the following exact v1 summary keys:
- `completed`, `failed_or_blocked`, `completion_rate`
- `tp`, `fp`, `fn`, `precision`, `recall`, `end_to_end_recall`, `missed_item_rate`, `false_discovery_rate`
- `mean_latency_ms`
- `mean_absolute_error` (`{"grams": ..., "calories": ..., "protein": ..., "fat": ..., "carbs": ...}` at the meal total level) and `error_sample_counts`
- `paid_api_cost_usd`

For the full **G58** held-out benchmark, `scripts/evaluate_meal_analysis.py` will retain all existing v1 `summarize(rows)` keys and add the following v2 metrics:

| Metric Area | Current v1 Implementation (`detection` / `summarize`) | Proposed v2 Extension for G58 |
| :--- | :--- | :--- |
| **1. Component Detection** | `detection(expected, predicted)` counts `tp`, `fp`, `fn` via `canonical()`; `summarize()` reports `precision`, `recall`, `end_to_end_recall`, `missed_item_rate`, `false_discovery_rate`. | Add `f1` ($\frac{2 \cdot \text{TP}}{2 \cdot \text{TP} + \text{FP} + \text{FN}}$) and expand `LABELS` in `canonical()` to cover the full 60-case benchmark vocabulary. |
| **2. Portion Estimation Error** | Meal-level total gram MAE via `mean_absolute_error["grams"]` on `reference_total["grams"]`. | Add per-component gram MAE (`item_grams_mae`) and MAPE (`item_grams_mape`) matched against `expected_items[i].grams`: $\frac{1}{M} \sum_{i=1}^{M} |\hat{g}_i - g_i|$. |
| **3. Calorie & Macro Error** | Meal-level `mean_absolute_error["calories"]`, `["protein"]`, `["fat"]`, `["carbs"]` and `error_sample_counts` over completed non-`no_food` runs. | Add meal-level calorie MAPE (`calorie_mape`) and per-component nutrient MAE on `gravimetric` cases. |
| **4. USDA Reference Grounding** | Not tracked in v1 `summarize()`. | Add `usda_reference_accuracy`: fraction of matched components whose resolved `reference.id` matches `expected_items[i].usda_reference_id`. |
| **5. Abstention / Negative Controls** | Evaluated via `detection([], predicted)` (`fp` count when `visible_food_labels` is `[]`). | Add explicit `non_food_abstention_rate` and `status_accuracy` over Cohort D (`expected_status == "no_food"` returning `status == "no_food"` and `foods == []`). |
| **6. Failure & Quota Accounting** | Tracks `completed`, `failed_or_blocked`, `completion_rate`, and penalizes failed/blocked cases in `end_to_end_recall`. | Preserve `failed_or_blocked` and `end_to_end_recall` invariants without modification. |

---

## 7. Proposed Cost, Quota & Rate-Limit Guardrails

Because the active Gemini API key operates on the **free tier**, live benchmark execution (`python scripts/evaluate_meal_analysis.py --mode vision`, which currently paces requests using `--interval-seconds` with a default of `13.0` s and stops on `VisionQuotaExceeded`) should be extended with three additional guardrails before running the 60-case held-out set:

1. **Explicit Opt-In & Max-Cases Cap (Proposed CLI Flags):**
   - Require `--allow-live-api` when `--mode vision` is selected, plus `--max-cases` (default `10` for smoke runs, max `60` for full release-candidate gate) while retaining `--interval-seconds` (default `13.0` s pacing between requests) to prevent `429 RESOURCE_EXHAUSTED` failures.
2. **Content-Addressable Response Caching (Proposed Eval-Only Cache):**
   - Keyed by `(sha256, prompt_version_sha256, model_id)` in a local gitignored directory (`.eval_cache/`) so re-scoring deterministic USDA retrieval changes (`nutrition_reference.py`) costs **0 API calls**.
3. **Hard Budget Circuit Breaker:**
   - Complement the existing `VisionQuotaExceeded` stop with a circuit breaker that aborts if consecutive non-quota `VisionUnavailable` errors exceed `3` or if total token usage exceeds `--max-total-tokens 150000`.
