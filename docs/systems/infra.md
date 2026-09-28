# Infrastructure

## Purpose

Everything runs on the Mac as background services that start on their own, structured so the core
can move to an always-on machine without a rewrite. This file covers config, secrets, storage,
observability, CI and updates. The processes themselves are in
[architecture](../architecture.md#processes).

## Responsibilities

### Config

- Anything that can change without code lives in config, with defaults.
- `config/default.yaml` is committed and holds generic defaults; `config/local.yaml` is gitignored,
  holds personal values, and is deep-merged over the defaults. Unknown keys are rejected.
- Every field has a safe default, so the app and tests work without `local.yaml` (as in CI).
- The profile has a `timezone` field, which every calendar and scheduling tool uses.

### Secrets

- OAuth tokens and API keys live in the macOS Keychain (via `keyring`), never in code or env files.

### Storage

- **Postgres with pgvector**, in Docker (OrbStack) or from Homebrew. Every table has `user_id`.
- **File-based stores until Postgres:** the cost log (Phase 2) and accounts (Phase 3) are files
  behind the same Protocols. Every record already carries `user_id`, and `account_id` where relevant,
  and uses the same fields as the future tables, so the move to Postgres in Phase 7 is mechanical.
- **Backups:** a daily, encrypted Postgres dump to external storage.

### Observability

- **Langfuse:** every run is traced: prompts, tool calls, model, time and cost.

### CI and updates

- **Git and GitHub Actions:** tests on every push. Evals have their own trigger ([evals](evals.md)).
- **Update:** pull and restart the services, in one script.
- **Moving to the cloud or an always-on machine:** see [extension points](../architecture.md#extension-points).

**Not responsible for:** what is stored in memory ([memory](memory.md)); cost calculation ([LLM](llm.md)).

## Contracts

| Contract | Kind | Definition |
|---|---|---|
| `Settings` | settings | Root config model; includes `UserSettings`, `BudgetSettings` ([LLM](llm.md)), `AgentLimits` ([orchestrator](orchestrator.md)), `RoleModelConfig` ([LLM](llm.md)) |
| `UserSettings` | settings | Personal values, including `timezone` |
| `SecretStore` | Protocol | Keyring implementation, and an in-memory fake for tests |
| `Tracer` | Protocol | Langfuse implementation and a no-op implementation |

## Config keys

- The `Settings` tree above; `UserSettings.timezone`.
- Open question: key names beyond these are not specified yet.

## Decisions

- ADR-0001 — Src layout: packages live under `src/jarvis/` (planned backfill, Phase 1).
- ADR-0005 — File-based stores until Postgres (planned, Phase 2).
- ADR-0006 — Langfuse deployment, Cloud or self-hosted (planned, Phase 2).

## Open questions

- Langfuse Cloud or self-hosted, Postgres in Docker or Homebrew, when and how to run 24/7: see
  [open decisions](../design.md#open-decisions).
- Langfuse must be decided before Phase 3, because email content starts reaching traces then. No
  email content reaches traces before Phase 3, so Cloud is safe until then.

## Introduced in phase

- [Phase 0](../plan/README.md#overview): tooling, CI, config files.
- [Phase 2](../plan/phase-2-core-cli.md): config loader, `SecretStore`, `Tracer`, file-based cost log.
- [Phase 5](../plan/README.md#phase-5--api--tauri-app): `launchd` service, update script.
- [Phase 7](../plan/README.md#phase-7--memory): Postgres with pgvector, backups.
