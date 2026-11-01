# Staging Database Cutover & Smoke Runbook (Before 2026-11-19)

## Scope & Safety Rules

- **Target environment:** Staging only (`foodlogger-staging` / `srv-d6q78f450q8c73f3376g` at `https://foodlogger-staging.onrender.com`, or blueprint alias `biteflow-staging-api` / `srv-dbbiamm1egvs7384stu0` at `https://biteflow-staging-api.onrender.com`).
- **Expiring database:** `dpg-d6q76n5m5p6s73f9k58g-a` (`dpg-dbbhudvavr4c73duk09g-a`, PostgreSQL 17 Free, Frankfurt), expires **2026-11-19 07:58 UTC**.
- **Pre-flight safety gates enforced before any network write:**
  - `hosted-smoke` and `cutover` validate `--origin` / `--staging-url` before sending any HTTP request: `https://` is required, the hostname must match an approved staging host (`foodlogger-staging.onrender.com` or `biteflow-staging-api.onrender.com`, or an explicit `--allow-staging-host` override), and any production identifier (`foodlogger.onrender.com`, `srv-d6q76n5m5p6s73f9k590`, `srv-db3raa3ncjis73bh20p0`, `slnmporlcbqnnkyebdmv`, `supabase.co`, `car_log`) is unconditionally rejected.
  - `cutover` validates `--admin-database-url` and `--app-database-url` before connecting: both must target the exact same replacement `(host, port, dbname)`, authenticate as distinct roles (`admin_user != 'foodlogger_app'` and `app_user == 'foodlogger_app'`), and neither may match the expiring staging DB (`dpg-d6q76n5m5p6s73f9k58g-a` / `dpg-dbbhudvavr4c73duk09g-a`) or any production database.
- **Production boundaries (Hard Limits):**
  - Never modify or run migrations against the shared production Supabase project (`slnmporlcbqnnkyebdmv` / `car_log`).
  - Never trigger a production deploy on `foodlogger` (`srv-d6q76n5m5p6s73f9k590` / `srv-db3raa3ncjis73bh20p0`). `render.yaml` sets `autoDeployTrigger: 'off'`.
  - Keep the old staging database and its `ai_attempts` / `ai_projects` ledger intact until the replacement is verified and Project Lead approves removal.
  - Never place connection strings, passwords, tokens, or API keys in committed files or chat.

---

## 1. Local Offline Pre-Cutover Rehearsal (1 Command, 0 Credentials Required)

`--mode local-verify` runs an **offline SQLite translation + static migration-manifest and contract rehearsal** (not a live PostgreSQL server check):

1. Verifies both `render.yaml` and `deploy/render.staging.yaml` enforce `autoDeployTrigger: 'off'`.
2. Statically verifies all 16 SQL migrations in `supabase/migrations/` against their pinned SHA-256 digests and confirms the SQL manifest contains `ENABLE ROW LEVEL SECURITY` for all 36 `foodlogger` tables, then applies the SQLite-translated schema from scratch on a temporary SQLite database (creating all 36 tables, `schema_version = 2`, and 27 USDA serving conversions).
3. Verifies the `Database` PostgreSQL connection contract (`sslmode=verify-full` + non-empty system CA bundle) and the SQL definitions for live PostgreSQL role/RLS/TLS verification (`ROLE_VERIFICATION_SQL`, `RLS_TABLES_VERIFICATION_SQL`, `TLS_VERIFICATION_SQL`).
4. Runs all **21 HTTP smoke checks** against an in-process FastAPI `TestClient`:
   - **(a) `/api/health` & commit SHA ancestry check:** HTTP 200 (`status: "ok"`, `version: "2.1.0"`) and verifies nutrition fix commits `089f789`, `3658a17`, and `4a9d6b6` are ancestors of `HEAD` and grounded via `/api/analysis/references`. In a shallow clone (CI uses `fetch-depth: 1`), a commit whose object is absent cannot be checked for ancestry, so it is listed under `commits.ancestry_unverifiable` and its catalog regressions run instead (`commits.behavioral_contract`), only when the target is the checked-out `HEAD` and `src/foodlogger` is unmodified. This proves the fixed behaviour, not the ancestry; use a full clone for live `cutover` and `hosted-smoke` runs.
   - **(b) Auth, owner isolation, idempotency, water, habits & health reconciliation:** 17 HTTP checks verifying unauthenticated rejection (`401`), synthetic account registration, manual meal write, water idempotency/conflict/delete, cross-account isolation (`404` on other user's water), and habit/health reconciliation.
   - **(c) Synthetic AI nutrition verification probe:** Renews `verified_at` on `gen-lang-client-0101662511` (`gemini-free` / `gemini-3.5-flash-lite`, 7-day TTL) and executes a synthetic non-personal probe (`"sunny side up breakfast eggs"`), confirming `ai_status: "used"`, `all_unconfirmed: true`, `no_auto_save: true`, and `fdc:173423` reference grounding.

```powershell
$env:PYTHONUTF8 = "1"; & "C:\Users\braud\AppData\Local\Programs\Python\Python312\python.exe" scripts/staging_db_cutover.py --mode local-verify
```

---

## 2. Live Staging PostgreSQL Cutover (< 2 Minutes When Credentials Are Provided)

Full PostgreSQL catalog, RLS, role privilege, table ownership, and live TLS verification run in `--mode cutover` (and read-only in `--mode postgres-verify`).

### Prerequisites (Environment Variables Only)

Set the following in your local shell session (never commit or echo values):

- `OLD_STAGING_DATABASE_URL`: Existing `foodlogger_app` PostgreSQL URL on `dpg-d6q76n5m5p6s73f9k58g-a` (optional; used for read-only export of non-secret AI ledger evidence before cutover).
- `STAGING_ADMIN_DATABASE_URL` (or `STAGING_OWNER_DATABASE_URL`): Database owner PostgreSQL URL for the new free Frankfurt PostgreSQL 17 instance (`?sslmode=verify-full`).
- `STAGING_APP_PASSWORD`: Strong random password generated for the dedicated `foodlogger_app` role on the new database (optional if embedded in `STAGING_DATABASE_URL`).
- `STAGING_DATABASE_URL`: Dedicated `foodlogger_app` PostgreSQL URL targeting the exact same `(host, port, dbname)` as `STAGING_ADMIN_DATABASE_URL` (`postgresql://foodlogger_app:<PASSWORD>@<HOST>/<DB>?sslmode=verify-full`).

### Step 2.1 — Execute PostgreSQL Cutover, Role/RLS/TLS Verification & AI Policy Renewal

```powershell
$env:PYTHONUTF8 = "1"; & "C:\Users\braud\AppData\Local\Programs\Python\Python312\python.exe" scripts/staging_db_cutover.py --mode cutover --output runtime/staging-cutover-2026-11/cutover-evidence.json
```

#### Transaction & Retry Boundaries in `--mode cutover`

`apply_postgres_cutover` executes in four explicit phases so that no application write ever occurs on an unverified connection and post-migration checks can be safely retried:

1. **Phase 0–1 (Pre-flight validation & read-only old ledger export):** Validates migration SHA-256 digests, verifies `admin_database_url` and `app_database_url` share `(host, port, dbname)` with distinct roles (`owner` vs `foodlogger_app`), rejects expiring/production DB identifiers, and optionally reads `ai_projects` / `ai_attempts` counts from `OLD_STAGING_DATABASE_URL`.
2. **Phase 2 (Single atomic owner DDL transaction on `owner_conn`):** Verifies the target database has `0` existing tables in schema `foodlogger`, applies all 16 SQL migrations in `supabase/migrations/*.sql`, and sets `ALTER ROLE foodlogger_app LOGIN PASSWORD ...` inside one transaction that commits when Phase 2 completes.
3. **Phase 3 (Read-only `app_conn` posture verification — before any app write):** Opens a separate connection using `STAGING_DATABASE_URL` (`sslmode=verify-full`) and verifies:
   - `pg_stat_ssl`: `ssl = true`.
   - `ROLE_VERIFICATION_SQL` (`FROM pg_roles WHERE rolname = current_user`): `current_user = 'foodlogger_app'`, `session_user = 'foodlogger_app'`, `rolname = 'foodlogger_app'`, `rolsuper = false`, `rolcreatedb = false`, `rolcreaterole = false`, `rolbypassrls = false`, `rolinherit = false`, `public_owned_tables = 0` (`pg_tables WHERE schemaname = 'public' AND tableowner = current_user`), and `total_owned_tables = 0`.
   - `RLS_TABLES_VERIFICATION_SQL`: all 36 `foodlogger` tables exist and have `relrowsecurity = true`.
   - If any check in Phase 3 fails, cutover aborts **before** `gateway.configure()` or any write is executed on `app_conn`.
4. **Phase 4 (Idempotent AI policy renewal on verified `app_conn`):** Verifies `schema_version = 2` and upserts the `gen-lang-client-0101662511` `BudgetPolicy` (`verified_at = now()`, `verification_ttl_seconds = 604800`, `daily_limit = 60`, `rpm = 1`, `input_tpm = 200000`, `photo_reserve = 20`, `user_daily_limit = 40`).

#### Re-entry / Retry After Phase 2 Commits (`--resume-post-migration` & `--mode postgres-verify`)

If Phase 3 or Phase 4 fails after Phase 2's owner DDL transaction has already committed (for example, due to a transient network timeout or password mismatch), re-run with `--resume-post-migration` to verify the existing 36-table 16-migration schema (`schema_version = 2`, 27 serving conversions), refresh the `foodlogger_app` password, and re-run Phase 3 and Phase 4 idempotently:

```powershell
$env:PYTHONUTF8 = "1"; & "C:\Users\braud\AppData\Local\Programs\Python\Python312\python.exe" scripts/staging_db_cutover.py --mode cutover --resume-post-migration --output runtime/staging-cutover-2026-11/cutover-evidence.json
```

To run read-only PostgreSQL TLS, role (`current_user = 'foodlogger_app'`), table-ownership (`0` owned tables), and 36-table RLS verification at any time without owner credentials or writes:

```powershell
$env:PYTHONUTF8 = "1"; & "C:\Users\braud\AppData\Local\Programs\Python\Python312\python.exe" scripts/staging_db_cutover.py --mode postgres-verify
```

### Step 2.2 — Point Staging Render Service to New `DATABASE_URL` & Deploy `HEAD` (`4a9d6b6`+)

Update `DATABASE_URL` on Render staging service (`srv-d6q78f450q8c73f3376g` / `srv-dbbiamm1egvs7384stu0`) to the new `foodlogger_app` connection string (`sslmode=verify-full`) and deploy `codex/biteflow-testflight-rc12-15` HEAD (which includes `089f789`, `3658a17`, `4a9d6b6`). Confirm production service `foodlogger` (`srv-d6q76n5m5p6s73f9k590` / `srv-db3raa3ncjis73bh20p0`) has `autoDeploy: no` and did not redeploy.

### Step 2.3 — 1-Command Hosted Staging Smoke + Commit SHA Check + Bounded Synthetic AI Probe

`--mode hosted-smoke` validates the HTTPS staging hostname, checks `/api/health` and verifies the deployed commit SHA matches or descends from `--expected-commit` **before** registering synthetic accounts or writing data, and then runs the 21-check smoke suite (22 checks including `deployed commit sha`):

```powershell
$env:PYTHONUTF8 = "1"; & "C:\Users\braud\AppData\Local\Programs\Python\Python312\python.exe" scripts/staging_db_cutover.py --mode hosted-smoke --origin https://foodlogger-staging.onrender.com --expected-commit $(git rev-parse HEAD) --allow-live-ai --output runtime/staging-cutover-2026-11/hosted-smoke-evidence.json
```

---

## 3. Rollback Notes

- If any migration, role/RLS/TLS check, or hosted smoke check fails on the new staging database, keep staging pointed at the existing `dpg-d6q76n5m5p6s73f9k58g-a` database (valid until `2026-11-19 07:58 UTC`).
- Do not delete or drop the old staging database until QA & Security Engineer and Project Lead verify the cutover evidence.
