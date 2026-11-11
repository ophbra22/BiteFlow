# BiteFlow development guide

[Project overview](../README.md) · [Documentation index](README.md)

This guide covers the existing web application. See the project overview for the separate native beta and its current release gates.


**A little more insight into every bite.**

A food-recognition and nutrition journal built with **Python, TensorFlow,
FastAPI, LiteRT and PostgreSQL/SQLite**. Create a private account, photograph food or a product
barcode, review its nutrition, and track the portions you eat. The responsive
website supports phone cameras, uploaded photos and manual nutrition entries.

[מדריך התחלה בעברית](START_HERE_HE.md) · [Model card](MODEL_CARD.md) ·
[Third-party resources](THIRD_PARTY.md) · [Render deployment](DEPLOYMENT.md) ·
[Mobile app (Android and iPhone)](https://github.com/ophbra22/BiteFlow/blob/codex/biteflow-testflight-rc12-15/mobile/README.md) ·
[BiteFlow multi-food analysis: setup, evaluation and release status](MEAL_ANALYSIS.md)

![BiteFlow dashboard](images/dashboard.png)

## Features

- **Private accounts:** Argon2id password hashing, opaque HttpOnly sessions,
  CSRF protection and one-time recovery codes. Every journal operation is scoped
  to the signed-in account.
- **Barcode nutrition:** decode GTIN/EAN/UPC barcodes from camera photos or uploads,
  or enter the digits. Open Food Facts supplies available product nutrients.
  Review and correct values before saving; missing nutrients stay missing.
- **Nutrition labels:** enter custom products, choose grams or millilitres, and
  preserve calories, macros, sugars, saturated fat, fibre, salt, sodium and
  additional source data alongside each saved portion.
- **Real inference:** a cached MobileNetV2 checkpoint, 23 supported ImageNet food
  categories, top suggestions, and an explicit uncertain state.
- **Mobile meal analysis:** server-side Gemini, when enabled with a suitable provider configuration, identifies
  multiple components with editable estimated portions. An actual USDA reference
  extract supplies nutrition. Setup, quotas and limitations are documented above;
  this feature requires deployment and is separate from the legacy classifier.
- **Human confirmation:** manually correct the food and supply grams. A photo
  does not determine mass, ingredients or a recipe.
- **A complete journal:** add/delete meals, browse dates, view calorie and macro
  totals, and export a day's entries to CSV. Data persists in PostgreSQL on the
  hosted service, or SQLite for local development.
- **A clean backend:** typed validation, bounded image uploads, an OpenAPI API,
  dependency injection, and tests independent of model downloads.
- **A trainable pipeline:** stratified train/validation split, a separate test
  set, frozen-backbone transfer learning, fine-tuning, model checkpoints and
  reproducible model/label/metric exports.
- **A responsive web UI:** no frontend build tool or analytics. The new mobile
  analysis sends photos to Gemini with an explicit privacy notice; photos are
  decoded in memory and are not stored by the analysis backend.

The legacy pretrained classifier is an ImageNet baseline, **not a model trained on
Food-101 by this project**. Its `foods.json` nutrition values are illustrative.
The separate `usda_reference.json` used by the new meal-analysis flow contains
13,225 actual USDA records with provenance and reproducible source checksums.

## Run locally

Use **Python 3.11 or 3.12**. Linux, Windows and Apple Silicon have TensorFlow 2.20
wheels; this project was exercised on Linux CPU. Intel macOS users can use the
Docker option or run the journal without the ML extra.

```bash
git clone https://github.com/ophbra22/BiteFlow.git BiteFlow
cd BiteFlow
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[ml,dev]"
foodlogger download-model
foodlogger
```

On Windows, use `python` instead of `python3` and activate with
`.venv\Scripts\Activate.ps1` in PowerShell.

Open **[http://127.0.0.1:8000](http://127.0.0.1:8000)**. Interactive API docs are at
[http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs).

The weights are about 14 MB and are cached under `~/.keras/models/`, with SHA-256
verification. The first inference loads TensorFlow and takes longer. A GPU and
API keys are not required. After installation and weight download, inference
works offline. `pip install -e ".[dev]"` runs the journal without TensorFlow;
photo recognition then returns an explicit setup message instead of fake results.

The default journal is `runtime/journal.sqlite3`, relative to your launch
directory. Launch from the same directory, or set `FOODLOGGER_DB` to an absolute
path. Register an account in the browser and save the recovery code shown once.
There is no email recovery. Accounts and journals share this database; keep a
consistent backup with SQLite's backup API. Older anonymous journal entries are
retained as unowned legacy data and are never assigned to newly registered users.

For the lighter Linux runtime, install `pip install -e ".[lite,dev]"` and run
`FOODLOGGER_INFERENCE=lite foodlogger`. Its verified model is bundled; TensorFlow
is not required. Training/custom `.keras` models use the TensorFlow backend.

## Usage

1. Create an account, save your recovery code, and select a journal date.
2. Choose **Photo / Catalog**, **Barcode**, or **Enter values**.
3. For food photos, confirm the suggested food and its measured weight. For a
   product, photograph its barcode or enter its digits; review the label values
   per 100 g or 100 ml and set the amount you consumed. You can fill missing data
   manually if a product is absent or incomplete in Open Food Facts.
4. Add the confirmed portion. Your account's daily totals update immediately.
5. Browse dates, expand saved nutrition details, export CSV or delete entries.

The camera controls use the device's native photo picker/camera. Availability
varies by browser and device; file upload and barcode digits remain available.
The app decodes barcode **photos**, rather than continuously streaming video.

## Architecture

```text
Browser upload → size/format/pixel validation → RGB crop → LiteRT / TensorFlow
                                                         ↓
                                   original model scores + food candidates
                                                         ↓
                           user confirms food + measured weight in grams
                                                         ↓
                  per-100g catalog → nutrient estimate → database snapshot
                                                         ↓
                                         daily summary / CSV export
```

```text
src/foodlogger/
  app.py           FastAPI factory and HTTP endpoints
  auth.py          password hashing, sessions and account recovery
  products.py      barcode decoding and Open Food Facts normalization
  security.py      deployment settings and bounded request rate limits
  classifier.py    lazy model loading, inference, probability postprocessing
  images.py        upload and image validation
  nutrition.py     catalog lookup and portion scaling
  schemas.py       request validation
  storage.py       private journal with nutrient snapshots
  database.py      SQLite / verified-TLS PostgreSQL connections
  lite_classifier.py  lightweight inference using the bundled model
  training.py      training, fine-tuning, test evaluation and export
  cli.py           local server and model download commands
  data/foods.json  inspectable illustrative nutrition catalog
  static/          responsive CSS and browser behavior
  templates/       application HTML
scripts/           Food-101 split conversion
mobile/            Android and iPhone app (Expo, React Native, TypeScript)
tests/             domain, API, inference policy and dataset tests
```

| Endpoint | Purpose |
|---|---|
| `GET /api/health` | Server health; does not preload or claim model readiness |
| `GET /api/foods` | Foods and nutrition provenance |
| `POST /api/auth/register`, `/login`, `/recover` | Account access; requires `X-FoodLogger-Request: 1` |
| `GET /api/auth/me`, `POST /api/auth/logout` | Current account/CSRF token and session revocation |
| `GET /api/products/{barcode}` | Validated barcode lookup; account required |
| `POST /api/barcode/scan` | Decode a barcode photo; account and CSRF required |
| `POST /api/meals/custom` | Save reviewed product/manual nutrition and quantity |
| `POST /api/predict` | Multipart `file`; JPEG/PNG/WebP, up to 8 MiB and 20 MP |
| `GET /api/nutrition?food_id=banana&grams=150` | Portion estimate |
| `POST /api/meals` | Save confirmed food, grams, date and meal type |
| `GET /api/meals?day=2026-10-08` | Meals and consistent totals for one date |
| `DELETE /api/meals/{id}` | Remove a journal entry |
| `GET /api/export?day=2026-10-08` | Download one day as CSV |

Native clients (the app in [`mobile/`](https://github.com/ophbra22/BiteFlow/blob/codex/biteflow-testflight-rc12-15/mobile/README.md)) send `X-FoodLogger-Client: mobile`
when signing in. They receive the opaque session token in the response as `session_token`
instead of a cookie and send it as `Authorization: Bearer <token>`; those requests need no
CSRF token, because a browser never attaches that header by itself. Cookie sessions are
unchanged. `POST /api/meals` and `POST /api/meals/custom` accept an optional
`Idempotency-Key` header (16–64 URL-safe characters): repeating a key returns the entry
saved the first time with status 200, so a retry after a lost response cannot create a
duplicate.

All journal, prediction and product endpoints require the session cookie.
Mutating authenticated requests also require `X-CSRF-Token`, returned by the
account endpoints. The website handles both automatically. Cross-origin writes
are rejected; authentication responses and private API data use `Cache-Control:
no-store`. JSON body validation never echoes passwords.

## Deploy the Python website on Render

The [Render Blueprint](../render.yaml) uses **Render Free** and an external
**Supabase Free PostgreSQL database**. The original Python server runs with a
bundled 7 MB LiteRT model; TensorFlow remains available for training and local
inference. The Blueprint creates no paid disk or Render database. Set the
private `DATABASE_URL` secret after applying the isolated database migration.

[Deploy this repository on Render](https://render.com/deploy?repo=https%3A%2F%2Fgithub.com%2Fophbra22%2FBiteFlow)

See [deployment and operations](DEPLOYMENT.md) for database setup, free-tier
quotas, backups and live verification. Render Free sleeps after inactivity;
Supabase may pause inactive projects. Accounts persist outside Render's disposable
filesystem. Deployment configuration alone does not mean a public service exists.

## Train your own classifier

Prepare separate `train/<class>` and `test/<class>` directories with at least two
classes. Each class needs at least two training photos and one test photo.
Images must be JPG, PNG or BMP. Class names become the ordered output labels.

```text
datasets/my-foods/
  train/pizza/*.jpg
  train/ice_cream/*.jpg
  test/pizza/*.jpg
  test/ice_cream/*.jpg
```

For [Food-101](https://data.vision.ee.ethz.ch/cvl/datasets_extra/food-101/), obtain
and extract the dataset separately under its terms. This helper preserves the
official train/test partition and copies only the selected classes:

```bash
python scripts/prepare_food101.py \
  --source datasets/food-101 \
  --destination datasets/food101-small \
  --classes pizza ice_cream hot_dog

foodlogger-train --data datasets/food101-small --output models/food101-small \
  --epochs 5 --fine-tune-epochs 3 --batch-size 32 --seed 42
```

Validation uses a seeded 20% holdout from each training class. The test set is
not used for checkpoint selection. Fine-tuning unfreezes the last 30 backbone
layers while keeping BatchNorm frozen, at a lower learning rate. The best
validation-loss checkpoint across both stages is exported and evaluated once
on test data. Start with a small class subset; training is substantially faster
on a suitable GPU. Results depend on your dataset, seed and hardware.

Outputs: `model.keras`, `best.keras`, ordered `labels.json`, `split_manifest.json`
and `metrics.json` (sample counts, seed, TF version, loss, top-1 and top-k metrics).
For fewer than four classes, top-k may be trivial; inspect top-1 accuracy and
class balance. Training refuses a nonempty output directory to preserve runs.
`--weights none` is for smoke tests, not a useful pretrained baseline.

Use your exported model:

```bash
export FOODLOGGER_MODEL="$PWD/models/food101-small/model.keras"
foodlogger
```

In PowerShell: `$env:FOODLOGGER_MODEL = "$PWD/models/food101-small/model.keras"`.
The adjacent `labels.json` is loaded automatically. Custom models accept
`float32` RGB pixels in `[0,255]`, input `(None,224,224,3)`, with preprocessing
embedded and one softmax value per label. Only load models you trust.

Labels must match IDs in `data/foods.json` for automatic nutrition matching.
Unknown labels are shown as unmapped and require manual selection; nutrition
is never invented. To extend coverage, add a reviewed nutrition record with the
exact class ID and its provenance. An `imagenet_index` is only needed for the
default classifier. Duplicate paths across splits are rejected; near-duplicate
or copied image contents still need dataset curation.

## Verification

```bash
pytest
ruff check src tests scripts
ruff format --check src tests scripts
python -m build
```

Run the optional TensorFlow training/export/reload test:

```bash
FOODLOGGER_RUN_ML_TESTS=1 pytest -m integration
```

PowerShell: set `$env:FOODLOGGER_RUN_ML_TESTS = "1"` before `pytest -m integration`.
The integration fixture contains synthetic noise and proves pipeline operation,
**not food-recognition accuracy**. GitHub Actions runs ordinary checks on Python
3.11 and 3.12. A separate job tests real PostgreSQL transactions and builds the
free Docker image, then runs native LiteRT inference inside it. A manual workflow
also runs the TensorFlow training smoke test.

Real PostgreSQL tests require a disposable database named with an `_test` suffix
and an administrator connection in `FOODLOGGER_TEST_DATABASE_URL`. They reset only
the test database's BiteFlow schema and test role; never point them at a live
project. Run `pytest -m postgres` with the `postgres` extra installed.

Optional browser tests cover registration, account isolation, barcode photo
decoding, product review, manual labels, save/upload locking, persistence, CSV
export, deletion and mobile overflow:

```bash
python -m pip install -e ".[browser]"
playwright install chromium
FOODLOGGER_RUN_BROWSER_TESTS=1 pytest -m browser
```

Set `FOODLOGGER_CHROMIUM` to an existing Chromium executable if needed.

## Docker

```bash
docker compose up --build
```

Open the same localhost URL. Compose persists the SQLite journal and model cache
in named volumes, and exposes the port on loopback only. Weight download happens
at first inference. The Docker/Compose configuration has not been independently
validated across supported platforms.

## Configuration

| Variable | Default / meaning |
|---|---|
| `DATABASE_URL` | Private PostgreSQL URL; takes priority over `FOODLOGGER_DB` |
| `FOODLOGGER_DB` | `runtime/journal.sqlite3`; production SQLite requires a persistent absolute path |
| `FOODLOGGER_PROFILE` | Set `free` to require PostgreSQL and prohibit ephemeral SQLite |
| `FOODLOGGER_INFERENCE` | `tensorflow` locally; `lite` in the free Docker image |
| `FOODLOGGER_LITE_MODEL` | Optional verified LiteRT export with adjacent JSON manifest |
| `FOODLOGGER_ENV` | `development`; set `production` behind HTTPS |
| `FOODLOGGER_PUBLIC_URL` | Public HTTPS origin; falls back to `RENDER_EXTERNAL_URL` |
| `FOODLOGGER_TRUSTED_PROXY_HOPS` | `0`; Render Blueprint uses `1` for its appended client IP |
| `PORT` | `8000`; Render supplies its service port |
| `FOODLOGGER_WEIGHTS` | Optional local MobileNetV2 ImageNet `.h5` checkpoint |
| `FOODLOGGER_MODEL` | Optional custom `.keras` model, takes priority over weights |
| `FOODLOGGER_LABELS` | Optional labels path; defaults next to custom model |
| `KERAS_HOME` | Keras cache directory; defaults to `~/.keras` |

If recognition is unavailable, run `foodlogger download-model`, verify the ML
extra was installed in the active virtual environment, and inspect server logs.
Manual logging continues to work. To change ports: `foodlogger --port 8001`.

## License

Code is MIT licensed; third-party models and datasets
retain their own terms. See [third-party notes](THIRD_PARTY.md).
