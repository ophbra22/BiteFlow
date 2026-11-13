# Deploy and operate BiteFlow

The [Render Blueprint](../render.yaml) runs the Python application on **Render
Free** with a **Supabase Free PostgreSQL database**. Food recognition uses the
bundled MobileNetV2 model through LiteRT, without loading TensorFlow on the web
server. Barcode decoding, private accounts and journals remain in Python.
Legacy classifier photos are processed in memory; barcode digits go to Open Food
Facts. The new mobile meal-analysis flow sends photos/context to Google's free
vision API and uses a bundled USDA extract. Its required server secrets, privacy
notice, quotas and rollout checks are in [meal analysis](MEAL_ANALYSIS.md).

## Prepare the database

Use an existing Supabase Free project or create one within your account's free
project allowance. Sharing a project shares its storage and connection quotas.
BiteFlow uses the private `foodlogger` schema and the dedicated
`foodlogger_app` role; existing applications' schemas are not changed.

1. Run [the schema migration](../supabase/migrations/20261008142103_foodlogger_private_schema.sql)
   once using the Supabase SQL editor as the database owner. It intentionally
   refuses an existing schema/role instead of overwriting them. Do not rerun the
   whole migration on an already configured project.
   Then run the later files in `supabase/migrations/` in order, also once and as
   the owner: [Apple sign-in](../supabase/migrations/20261011194917_apple_sign_in.sql)
   and [schema version 2](../supabase/migrations/20261113120000_schema_version_2.sql).
   The server checks at startup that the Apple sign-in tables exist and refuses to
   start without them.
2. Set a strong, unique password for the new role through a private SQL-editor
   query: `ALTER ROLE foodlogger_app LOGIN PASSWORD '<new-random-password>';`.
   Never save that query, password or connection URL in this repository.
   This is a dedicated application credential, not the project's owner password.
3. In **Connect → Transaction pooler**, copy the exact host and port for the
   selected project. Use the username `foodlogger_app.<project-ref>`, database
   `postgres`, and the role password from step 2. URL-encode the password.

```text
postgresql://foodlogger_app.<project-ref>:<encoded-password>@<pooler-host>:6543/postgres?sslmode=verify-full
```

This is a PostgreSQL connection string, not the Supabase API URL or API key.
The server requires verified TLS for remote connections. Supabase shared pooler
hosts ending in `.pooler.supabase.com` use the bundled Supabase production CA
roots automatically. These private roots are not included in the operating
system's public CA store. Their source, fingerprints and expiry dates are in
[third-party notes](THIRD_PARTY.md#supabase-database-certificates).

Other database hosts use Python's explicitly resolved system CA bundle, avoiding
the build-machine paths embedded in binary libpq. An explicit
`sslrootcert=/path/to/certificate.pem` overrides the default for any host; use it
for a project-specific or replacement CA. Certificate-chain and hostname
verification remain enabled with `sslmode=verify-full`. Prepared statements are disabled for transaction-pooler
compatibility. Search path and query/lock timeouts are set per transaction.
The server keeps up to four idle database connections for at most 60 seconds and
reuses them, replacing any the pooler has closed.

The schema is not intended for Supabase's public Data API. RLS is enabled and
only the dedicated Python server role has table access. Authenticated server
queries enforce individual account ownership. Keep the role credential private;
it allows the server to manage all BiteFlow accounts and journals. The server
cannot create tables, and does not run migrations at startup.

## Create the free web service

1. Open [Deploy BiteFlow on Render](https://render.com/deploy?repo=https%3A%2F%2Fgithub.com%2Fophbra22%2FBiteFlow)
   and sign in. The link loads this repository's Blueprint from `main`.
2. Confirm **Free**, one Docker web service, and **no persistent disk or Render
   database**. Set `DATABASE_URL` to the private pooler URL. The Blueprint
   requires this secret; it has no SQLite fallback in its free profile.
3. Create the service. The build installs `.[lite,postgres]` and includes the
   verified 7 MB model. No model download occurs on the first public request.
4. Render provides `PORT` and `RENDER_EXTERNAL_URL`, used for the HTTPS origin
   and Secure session cookies. For a custom domain, set `FOODLOGGER_PUBLIC_URL`
   to that exact HTTPS origin and use it consistently.
5. When healthy, open the public HTTPS URL, register and save the recovery code.
   Test a food photo and barcode photo before sharing the URL.

The Blueprint contains **only a free compute resource**, and does not create
Supabase resources. Check [Render's current free limits](https://render.com/docs/free)
and [Supabase pricing](https://supabase.com/pricing) before deployment. Render
Free currently has 512 MB RAM / 0.1 CPU and sleeps after 15 minutes of inactivity;
the next visitor may wait for it to wake. Its free instance hours and bandwidth
are limited. Supabase Free has a 500 MB database limit and may pause inactive
projects after a week. Resume a paused project from its dashboard. Free hosting
is suitable for modest traffic, without an always-on availability guarantee.
Keep both services within their free quotas; upgrading or enabling paid
resources changes the cost.

Render's filesystem is disposable. Accounts and journals survive service
restarts because they live in PostgreSQL. A database outage returns an error;
the application never silently writes a replacement local journal.

## Verify the live service

- Open the site on desktop and phone. Create two accounts and verify separate
  journals, CSV exports and deletion permissions.
- Save a catalog meal, manual nutrition and a photographed barcode product.
  Confirm unknown products can still be entered manually.
- Photograph a supported food and review real classifier suggestions.
- Test sign-out, sign-in and one-time recovery.
- Redeploy and verify the existing account and meal are still present.

`/api/health` checks database connectivity, not model readiness. The model is
loaded lazily; an actual photo request verifies inference. The camera is a
native `capture="environment"` file control, subject to device support.
JPEG, PNG and WebP up to 8 MiB / 20 MP are accepted; barcode digits and file
uploads remain available when native capture is unavailable.

## Resource and proxy limits

Use one instance and one Uvicorn worker. HTTP concurrency is capped at eight.
One authenticated image request at a time reserves memory before buffering;
other image requests receive 429 and can retry. Request-body receipt has a
30-second total deadline. Image decoding and inference share a processing slot,
and password hashing uses at most two concurrent Argon2 operations. The free
image omits TensorFlow; install the `ml` extra separately for training.

A Linux Docker smoke test capped at 512 MiB / 0.1 CPU completed registration,
real food-photo inference, a 20 MP EXIF-oriented barcode photo and nutrition
saving with a measured cgroup memory peak of approximately 330 MiB. This checks
that workload, not arbitrary traffic or every possible image encoding.

The Blueprint trusts **one appended X-Forwarded-For hop**, selected from the
right, for authentication IP limits. Uvicorn does not independently rewrite
client addresses. This assumes all public requests pass through Render's proxy;
do not expose the application port directly with that setting. Use
`FOODLOGGER_TRUSTED_PROXY_HOPS=0` for a direct local server. Rate limits reset on
restart and are not distributed across instances.

## Backups and account behaviour

Export private database backups to storage outside the project on a regular
schedule. Free hosting is not a backup strategy. A database owner can use
`pg_dump --schema=foodlogger` against a direct/session connection; use a protected
password file rather than putting credentials on a command line. Test restoration
in a separate database with the BiteFlow role and grants recreated. Backups
contain private journals, password hashes and session records; never publish
or commit them. User CSV export includes nutrition entries, not account recovery.

Usernames are case-insensitive, passwords require 12–128 characters, and sessions
expire after seven days. Recovery rotates the code and revokes existing sessions.
There is no email reset path. Losing both password and recovery code prevents
recovery through the UI. Photos are not retained. Saved nutrient snapshots do
not change when the catalog or Open Food Facts record changes.

Local development still supports SQLite via `FOODLOGGER_DB`; back it up using
SQLite's online backup API. Existing local accounts/journals are not automatically
copied into a new PostgreSQL database. Older anonymous SQLite entries stay under
the reserved `__legacy__` owner, inaccessible to newly registered accounts.

## References

[Render free services](https://render.com/docs/free) ·
[Blueprint reference](https://render.com/docs/blueprint-spec) ·
[Supabase connections](https://supabase.com/docs/guides/database/connecting-to-postgres) ·
[LiteRT Python](https://ai.google.dev/edge/litert/migration)


## Database startup failures

If a deploy exits with `DatabaseUnavailable`, check the preceding
`PostgreSQL operation failed` line. Its fixed `stage` and `reason` labels identify
TLS certificate, authentication, permissions, missing schema, DNS, network or
timeout failures without printing credentials or SQL. `tls_certificate` means
that the certificate chain or hostname could not be verified: check the CA bundle
and the exact pooler host, keeping `sslmode=verify-full`. `authentication` means
the dedicated role, project suffix or password needs checking. A schema error
means the private migration has not been applied to that database.
