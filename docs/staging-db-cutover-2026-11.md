# Staging Database Cutover & Smoke Runbook (Before 2026-11-19)

## Scope & Safety Rules

- **Target environment:** Staging only (`biteflow-staging-api` / `srv-dbbiamm1egvs7384stu0` at `https://biteflow-staging-api.onrender.com`).
- **Expiring database:** `biteflow-staging-db` (`dpg-dbbhudvavr4c73duk09g-a`, PostgreSQL 17 Free, Frankfurt), expires **2026-11-19 07:58 UTC**.
- **Production boundaries (Hard Limits):**
  - Never modify or run migrations against the shared production Supabase project (`slnmporlcbqnnkyebdmv` / `car_log`).
  - Never trigger a production deploy on `foodlogger` (`srv-db3raa3ncjis73bh20p0`). `render.yaml` sets `autoDeployTrigger: 'off'`.
  - Keep the old staging database and its `ai_attempts` / `ai_projects` ledger intact until the replacement is verified and Project Lead approves removal.
  - Never place connection strings, passwords, tokens, or API keys in committed files, chat, or command arguments.

---

## 1. Local Pre-Cutover Rehearsal (1 Command, 0 Credentials Required)

Verify that:
1. Both `render.yaml` and `deploy/render.staging.yaml` enforce `autoDeployTrigger: 'off'`.
2. All 16 migrations in `supabase/migrations/` match their expected SHA-256 digests and apply cleanly from scratch on a fresh database (creating all 36 `foodlogger` tables with RLS enabled, `schema_version = 2`, and 27 USDA serving conversions).
3. The smoke harness passes all 19 checks:
   - **(a) `/api/health` & commit SHA check:** HTTP 200 (`status: "ok"`, `version: "2.1.0"`) and verifies nutrition fix commits `089f789`, `3658a17`, and `4a9d6b6` are ancestors of `HEAD` and grounded via `/api/analysis/references`.
   - **(b) TLS & non-owner DB role verification contract:** Enforces `sslmode=verify-full` with a non-empty system CA bundle and verifies `foodlogger_app` has `rolsuper=false`, `rolcreatedb=false`, `rolcreaterole=false`, `rolbypassrls=false`, `rolinherit=false`, and `relrowsecurity=true` on all 36 tables.
   - **(c) Synthetic AI nutrition verification probe:** Renews `verified_at` on `gen-lang-client-0101662511` (`gemini-free` / `gemini-3.5-flash-lite`, 7-day TTL) and executes a synthetic non-personal probe (`"sunny side up breakfast eggs"`), confirming `ai_status: "used"`, `all_unconfirmed: true`, `no_auto_save: true`, and `fdc:173423` reference grounding.

```powershell
$env:PYTHONUTF8 = "1"; & "C:\Users\braud\AppData\Local\Programs\Python\Python312\python.exe" scripts/staging_db_cutover.py --mode local-verify
```

---

## 2. Live Staging DB Cutover (< 2 Minutes When Credentials Are Provided)

### Prerequisites (Environment Variables Only)

Set the following in your local shell session (never commit or echo values):

- `OLD_STAGING_DATABASE_URL`: Existing `foodlogger_app` PostgreSQL URL on `dpg-dbbhudvavr4c73duk09g-a` (to export non-secret AI ledger evidence before cutover).
- `STAGING_OWNER_DATABASE_URL`: Database owner PostgreSQL URL for the new free Frankfurt PostgreSQL 17 instance (`?sslmode=verify-full`).
- `STAGING_APP_PASSWORD`: Strong random password generated for the dedicated `foodlogger_app` role on the new database.
- `STAGING_DATABASE_URL`: Dedicated `foodlogger_app` PostgreSQL URL (`postgresql://foodlogger_app:<PASSWORD>@<HOST>/<DB>?sslmode=verify-full`).

### Step 2.1 — 1-Command Atomic Migration, Role Lockdown, TLS Check & AI Policy Renewal

```powershell
$env:PYTHONUTF8 = "1"; & "C:\Users\braud\AppData\Local\Programs\Python\Python312\python.exe" scripts/staging_db_cutover.py --mode cutover --output runtime/staging-cutover-2026-11/cutover-evidence.json
```

What this command executes atomically:
1. Exports non-secret AI ledger state (`ai_projects` count, `ai_attempts` state/token summary) from `OLD_STAGING_DATABASE_URL` while leaving the old database untouched.
2. Verifies the target database has 0 existing tables in schema `foodlogger`, applies all 16 SQL migrations in `supabase/migrations/` in chronological order, and sets the `foodlogger_app` login password.
3. Reconnects as `foodlogger_app` with `sslmode=verify-full`, verifies `schema_version = 2`, and renews the `gen-lang-client-0101662511` `BudgetPolicy` (`verified_at = now()`, `verification_ttl_seconds = 604800`, `daily_limit = 60`, `rpm = 1`, `input_tpm = 200000`, `photo_reserve = 20`, `user_daily_limit = 40`).
4. Runs `ROLE_VERIFICATION_SQL`, `RLS_TABLES_VERIFICATION_SQL` (36 tables with `rls_enabled = true`), and `TLS_VERIFICATION_SQL` (`ssl = true`, `TLSv1.3`).

### Step 2.2 — Point `biteflow-staging-api` to New `DATABASE_URL` & Deploy `HEAD` (`4a9d6b6`+)

Update `DATABASE_URL` on Render service `biteflow-staging-api` (`srv-dbbiamm1egvs7384stu0`) to the `foodlogger_app` connection string (`sslmode=verify-full`) and deploy `codex/biteflow-testflight-rc12-15` HEAD (which includes `089f789`, `3658a17`, `4a9d6b6`). Confirm production service `foodlogger` (`srv-db3raa3ncjis73bh20p0`) has `autoDeploy: no` and did not redeploy.

### Step 2.3 — 1-Command Hosted Staging Smoke + Bounded Synthetic AI Probe

```powershell
python scripts/staging_db_cutover.py --mode hosted-smoke --origin https://biteflow-staging-api.onrender.com --allow-live-ai --output runtime/staging-cutover-2026-11/hosted-smoke-evidence.json
```

---

## 3. Rollback Notes

- If any migration or smoke check fails on the new staging database, keep `biteflow-staging-api` pointed at the existing `dpg-dbbhudvavr4c73duk09g-a` database (valid until `2026-11-19 07:58 UTC`).
- Do not delete or drop the old staging database until QA & Security Engineer and Project Lead verify the cutover evidence.
