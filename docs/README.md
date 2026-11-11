# BiteFlow documentation

[Project overview](../README.md)

## Start here

| Guide | Contents |
| --- | --- |
| [Development](DEVELOPMENT.md) | Installation, API, configuration, training and tests |
| [התחלה בעברית](START_HERE_HE.md) | Hebrew setup and usage guide |
| [Deployment and operations](DEPLOYMENT.md) | Render, database setup, security and backups |
| [Model card](MODEL_CARD.md) | Recognition scope, model origin and limitations |
| [Meal analysis](MEAL_ANALYSIS.md) | Multi-food analysis, reference data and evaluation |
| [Third-party resources](THIRD_PARTY.md) | Licenses and data provenance |

## Current native beta

The mobile work is maintained on the
[`codex/biteflow-testflight-rc12-15` branch](https://github.com/ophbra22/BiteFlow/tree/codex/biteflow-testflight-rc12-15).
These links deliberately target that branch rather than implying its features are deployed from `main`:

- [Mobile setup](https://github.com/ophbra22/BiteFlow/blob/codex/biteflow-testflight-rc12-15/mobile/README.md)
- [Latest local-first checkpoint](https://github.com/ophbra22/BiteFlow/blob/codex/biteflow-testflight-rc12-15/docs/biteflow/local-first-checkpoint.md)
- [Physical-device checklist in Hebrew](https://github.com/ophbra22/BiteFlow/blob/codex/biteflow-testflight-rc12-15/docs/biteflow/local-first-device-checklist-he.md)
- [Release gate register](https://github.com/ophbra22/BiteFlow/blob/codex/biteflow-testflight-rc12-15/docs/biteflow/release-readiness/gate-register.md)
- [Phase checkpoints and evidence](https://github.com/ophbra22/BiteFlow/tree/codex/biteflow-testflight-rc12-15/docs/biteflow)

## Reading the evidence

Phase reports and raw test evidence are retained in their original locations so commit references
and rollback instructions remain usable. They describe the revision and environment tested at
that time; they are not a statement that every later revision or production service passed.

Older reports may use the previous project name or repository URL. Public-facing documentation
uses **BiteFlow**; technical identifiers such as `foodlogger`, `FOODLOGGER_*` and the existing
app bundle IDs remain unchanged to protect compatibility.
