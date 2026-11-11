# Contributing to BiteFlow

## Choose the right branch

- `main` serves the existing web application. It is connected to deployment automation.
- `codex/biteflow-testflight-rc12-15` contains the current native beta and its release evidence.
- Make focused changes on a topic branch; do not merge the entire beta into `main` as part of
  a documentation, branding or unrelated maintenance change.

Follow the [development guide](docs/DEVELOPMENT.md). Native contributors should also read
`mobile/AGENTS.md` and `mobile/README.md` on the beta branch.

## Keep changes reviewable

1. Describe the behavior being changed and the relevant branch.
2. Preserve missing nutrient values, source provenance and account isolation.
3. Use mocked providers and synthetic fixtures; never use live AI or production data in tests.
4. Run the relevant tests and formatting checks. Report skipped or unrun checks explicitly.
5. Include migrations and a reversible rollout plan when storage contracts change.

Keep credentials, `.env` files, databases, personal data and generated build outputs out of Git.
Do not rename existing cookies, API headers, storage keys or native bundle identifiers as part
of a visual branding update. Do not uninstall or downgrade the mobile beta with pending local
meal changes; follow its documented synchronization and recovery checks first.

## Pull requests

Explain the problem, final behavior, tests actually run, remaining limits and rollback path.
Link existing phase evidence rather than copying raw logs into the project overview.
Production readiness requires the documented external and device gates as well as local tests.
