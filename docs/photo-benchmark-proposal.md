# Held-Out Multimodal Photo Evaluation Benchmark Proposal (G58)

## 1. Objective & Scope Boundary
This document specifies the design, dataset schema, licensing gates, ground-truth protocol, metrics, and quota/cost guardrails for BiteFlow's held-out multimodal meal-photo evaluation benchmark (**G58**).

- **Zero Live API Calls in CI / Offline Suites:** All automated tests (`tests/test_nutrition_eval.py`, `tests/test_meal_analysis_evaluation.py`) run strictly offline without calling live vision providers. Live multimodal evaluation via `scripts/evaluate_meal_analysis.py` is gated behind explicit manual invocation (`--allow-live-api`) and hard budget caps.
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
| **D. Negative Controls & Abstention Cases** | 10 | Empty plates, non-food objects, severely blurred/dark frames, closed opaque containers, and pets/landscapes (`expected_outcome: "abstain"`). | `abstention` |

---

## 4. Benchmark Manifest Schema

Each case in `evaluations/meal_analysis/benchmark.heldout.json` follows the schema consumed by `scripts/evaluate_meal_analysis.py`, extended with provenance and gravimetric metadata:

```json
{
  "id": "il_gravimetric_schnitzel_rice_01",
  "title": "Weighed chicken schnitzel, cooked white rice, and chopped cucumber-tomato salad",
  "cohort": "israeli_dishes",
  "ground_truth_tier": "gravimetric",
  "expected_outcome": "match",
  "image_sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
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
      "usda_reference_id": "fdc:2706039"
    },
    {
      "name": "white rice",
      "aliases": ["אורז", "אורז לבן", "cooked rice"],
      "preparation": "cooked",
      "grams": 160.0,
      "usda_reference_id": "fdc:168878"
    }
  ],
  "expected_totals": {
    "calories": 584.2,
    "protein_g": 41.8,
    "carbs_g": 62.4,
    "fat_g": 17.1
  }
}
```

---

## 5. Ground-Truth Annotation Protocol

1. **Gravimetric Weighing (`ground_truth_tier: "gravimetric"`):**
   - Tare the plate/bowl on a digital scale (`±1 g` resolution).
   - Add each component sequentially, recording net edible mass in grams (`grams`) and photographing both intermediate and final plated states.
   - Cooking method (`raw`, `boiled`, `fried`, `grilled`, `baked`, `steamed`, `roasted`) and added cooking fats/oils (`grams`) must be logged explicitly.
2. **Canonical USDA Reference Binding:**
   - Each weighed component is mapped by two independent reviewers to its exact `fdc:*` ID in `src/foodlogger/data/usda_reference.json` (or flagged as `usda_reference_id: null` when the dish is absent from USDA and requires component decomposition or abstention).
   - Ground-truth `expected_totals` are computed deterministically via `scale_nutrients` and `aggregate` (`src/foodlogger/nutrition_reference.py`) from the weighed grams and canonical USDA per-100g values—never estimated by eye or LLM.
3. **Inter-Annotator Agreement:**
   - Any case where two reviewers disagree on component identity, cooking method, or USDA reference mapping is either resolved by recipe logs or excluded from the gravimetric tier.

---

## 6. Evaluation Metrics & Acceptance Thresholds

`scripts/evaluate_meal_analysis.py` computes six primary metrics across the held-out set, separating **end-to-end metrics** (all cases) from **completed-run metrics** (excluding network/image-fetch failures):

1. **Component Precision, Recall & $F_1$:**
   - Greedy bipartite matching between predicted components and `expected_items` using canonical normalized aliases (where qualifier mismatches like `"sweet potato"` vs. `"potato"` are rejected).
   - $\text{Precision} = \frac{\text{TP}}{\text{TP} + \text{FP}}$, $\quad \text{Recall} = \frac{\text{TP}}{\text{TP} + \text{FN}}$.
2. **Portion Estimation Error (Gram MAE & MAPE):**
   - Evaluated on matched true-positive components in `gravimetric` cases:
   $$\text{Portion MAE (g)} = \frac{1}{M} \sum_{i=1}^{M} \left| \hat{g}_i - g_i \right|, \qquad \text{Portion MAPE (\%)} = \frac{100}{M} \sum_{i=1}^{M} \frac{\left| \hat{g}_i - g_i \right|}{g_i}$$
3. **Meal Calorie & Macronutrient Error (Calorie MAE & MAPE):**
   - Evaluated on gravimetric plates with complete USDA reference coverage:
   $$\text{Calorie MAE (kcal)} = \frac{1}{N_{\text{grav}}} \sum_{j=1}^{N_{\text{grav}}} \left| \widehat{\text{kcal}}_j - \text{kcal}_j \right|$$
4. **USDA Grounding Coverage & Reference Accuracy:**
   - Fraction of predicted components that resolve to an auditable `fdc:*` record matching the ground-truth component's food identity and preparation.
5. **Abstention & Negative-Control Specificity:**
   - On Cohort D (`expected_outcome: "abstain"`), percentage of runs that return `abstained = true` with `0` fabricated food items (target: **100%**).
6. **Failure Accounting:**
   - Any HTTP/provider error, timeout, or schema validation failure is recorded under `failed_cases` and penalized as `0` recall in end-to-end metrics—never silently dropped or counted as a successful abstention.

---

## 7. Cost, Quota & Rate-Limit Guardrails

Because the active Gemini API key operates on the **free tier**, live benchmark execution must enforce strict quota controls:

1. **Explicit Opt-In & Max-Cases Cap:**
   - `scripts/evaluate_meal_analysis.py` must require `--max-cases` (default `10` for smoke runs, max `60` for full release-candidate gate) and `--rpm-limit 10` (minimum 6.5 s pacing between requests) to prevent `429 RESOURCE_EXHAUSTED` failures.
2. **Content-Addressable Response Caching (Eval Mode Only):**
   - Keyed by `(image_sha256, prompt_version_sha256, model_id)` in a local gitignored directory (`.eval_cache/`) so re-scoring after deterministic USDA retrieval changes (`nutrition_reference.py`) costs **0 API calls**.
3. **Hard Budget Circuit Breaker:**
   - Abort the evaluation run immediately if consecutive provider errors exceed `3` or if total token usage exceeds the configured run ceiling (`--max-total-tokens 150000`).
