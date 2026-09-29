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
- The profile has a `default_account_id` field, used when a request names no account
  ([accounts](modules.md#accounts)).

### Secrets

- OAuth tokens and API keys live in the macOS Keychain (via `keyring`), never in code or env files.
- **Keychain naming:** service `jarvis`, account = the secret's name (the provider name for an API
  key, for example `anthropic`). To add or replace one by hand:
  `security add-generic-password -U -s jarvis -a <name> -w` (it prompts for the value). `-U`
  updates an item that already exists, including one that exists but wasn't readable (after "Deny"
  on the access prompt); without it, `security` fails with "already exists".
- `SecretStore` (`jarvis.core.secret_store`): `get(name)`, `set(name, value)`, `delete(name)`.
  `set` and `delete` are for OAuth tokens (Phase 3). A missing secret raises `SecretNotFoundError`,
  whose message is the `security` command above ([behavior](../behavior.md) R3). Deleting a missing
  secret is not an error. An empty name (any method) or an empty value (`set`) raises `ValueError`:
  an empty stored API key would otherwise pass as valid and fail only later, as a 401.
- A secret value never appears in a repr, a log line or an error message.
- Tests never touch the real Keychain: an autouse fixture (`tests/conftest.py`) gives every test an
  in-memory keyring backend. Linux CI has no keyring backend anyway. The one exception is the live
  API tests (`-m live` AND `JARVIS_LIVE=1`, never in CI), which restore the real macOS backend
  deliberately to read the API key.

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
| `UserSettings` | settings | Personal values, including `timezone`, `week_start` and `default_account_id` |
| `SecretStore` | Protocol | Keyring implementation, and an in-memory fake for tests |
| `Tracer` | Protocol | Langfuse implementation and a no-op implementation |

## Config keys

- The `Settings` tree above, loaded by `jarvis.core.config.load_settings()`.
- `user` (`UserSettings`): `id` (non-empty), `name`, `timezone` (an IANA name, default `UTC`), `language`
  (default `he`), `week_start` (default `sunday`; used by `resolve_date`, see
  [orchestrator](orchestrator.md#time-and-date-tools)), `default_account_id` (none or non-empty; default none).
- `budget` (`BudgetSettings`, [LLM](llm.md#config-keys)): `daily_cap_usd` (finite, > 0).
- `models` (role → `RoleModelConfig`, [LLM](llm.md#config-keys)): for each role, `provider` and
  `model` (both non-empty). Empty in code; `default.yaml` maps `planner`.
- Validation is strict: no type coercion (a quoted `"3"` is not a number), and unknown keys are
  errors. The error names the file and the dotted key.
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
