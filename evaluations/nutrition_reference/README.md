# Offline Nutrition Reference Retrieval Benchmark (`biteflow-nutrition-retrieval-he-en-v1`)

## Overview & Scope
This directory contains the deterministic offline evaluation benchmark for BiteFlow's USDA nutrition reference retrieval (`src/foodlogger/nutrition_reference.py`).

- **Fixture:** [`hebrew_retrieval_benchmark.json`](hebrew_retrieval_benchmark.json) (200 test cases: 184 positive match queries across 8 food categories in Hebrew and English + 16 abstention/negative-control queries).
- **Recorded Metrics:** [`retrieval_eval_report.json`](retrieval_eval_report.json)
- **Automated Test Suite:** `tests/test_nutrition_eval.py`

> **Scope Boundary:** This benchmark evaluates **deterministic text/alias retrieval and ranking against the bundled 13,225-record USDA FoodData Central table only**. It does **not** measure multimodal photo recognition or portion estimation accuracy (see `docs/photo-benchmark-proposal.md` for the held-out multimodal photo benchmark design).

## Baseline vs. Post-Improvement Metrics

Evaluated against the 200-case benchmark before (`4a9d6b60c9304254136dd1eb7fb15f0b57968155`) and after expanding `ALIASES` (from 34 to 348 entries) and refining subject/category/recipe ranking in `src/foodlogger/nutrition_reference.py`:

| Metric | Unmodified Baseline (`4a9d6b6`) | Post-Improvement | Delta |
| :--- | :---: | :---: | :---: |
| **Positive Match Top-1 Accuracy** (`n = 184`) | `22 / 184` (**12.0%**) | `184 / 184` (**100.0%**) | **+88.0 pp** |
| **Positive Match Top-5 Hit Rate** (`n = 184`) | `38 / 184` (**20.7%**) | `184 / 184` (**100.0%**) | **+79.3 pp** |
| **Missing Matches** (`n = 184`) | `135 / 184` (**73.4%**) | `0 / 184` (**0.0%**) | **-73.4 pp** |
| **Wrong Top-1 Match Rate** (`n = 184`) | `27 / 184` (**14.7%**) | `0 / 184` (**0.0%**) | **-14.7 pp** |
| **Abstention Accuracy** (`n = 16`) | `16 / 16` (**100.0%**) | `16 / 16` (**100.0%**) | **0.0 pp (0 false positives)** |
| **Overall Benchmark Accuracy** (`n = 200`) | `38 / 200` (**19.0%**) | `200 / 200` (**100.0%**) | **+81.0 pp** |

## Provenance & Abstention Rules
1. **No Invented Nutrition Data:** Every positive match maps exclusively to a verified `fdc:*` record inside `src/foodlogger/data/usda_reference.json` (USDA SR Legacy, Foundation Foods, or FNDDS 2021–2023).
2. **Strict Abstention on Missing Regional Dishes:** Composite Israeli dishes and snacks that have no verified entry in the bundled USDA reference table (`שקשוקה`, `סביח`, `בורקס`, `מלאווח`, `ג׳חנון`, `קובה`, `במבה`, `לבנה`, `שווארמה`, `קבב`, `פתיתים`, `פיתה כוסמין`, `פיתה עם זעתר`) explicitly translate to distinct tokens and return `[]` rather than silently substituting an unrelated food's macronutrients.

## Running the Benchmark
```bash
pytest tests/test_nutrition_eval.py tests/test_nutrition_matching.py -v
```
