# LLM layer

## Purpose

Every model call goes through one interface, and code asks for a *role*, never a model. Simple tasks
run locally on the M4 Pro, the rest through APIs.

## Responsibilities

| Role | Used for | Where |
|---|---|---|
| `planner` | The orchestrator: understanding a request and choosing tools | API, strong model (for now `claude-sonnet-5-5`, [ADR-0003](../adr/0003-llm-layer.md)) |
| `writer` | Email drafts and summaries | API |
| `classifier` | Classifying emails and events by importance | Local |
| `embeddings` | Semantic search in memory and email | Local, multilingual model |
| `memory` | Proposing facts to remember | Local or a cheap API |

- **Local models:** Ollama or MLX, running native and not inside Docker (to get GPU access). With
  24GB of memory, only small models.
- **Hebrew:** small local models are weaker in Hebrew. Every local role is tested against an eval
  set, and moves to an API if it doesn't meet the bar.
- **Model choice:** an eval set of 20–30 real Hebrew examples per role, run when the role is
  introduced and against current prices ([evals](evals.md)).
- **Costs:** every call is logged with cost, role and module. The budget is set after two weeks of
  measurement; until then there is a temporary daily cap in config.
- **Providers:** adding a model or provider, local or API, means implementing the provider interface
  and mapping a role to it in config ([extension points](../architecture.md#extension-points)).

**Not responsible for:** voice, which is not a role: it goes only through `VoiceProvider`
([voice](voice.md)); where the cost log is stored ([infra](infra.md#storage)).

## Contracts

| Contract | Kind | Definition |
|---|---|---|
| `Role` | enum | `planner`, `writer`, `classifier`, `embeddings`, `memory` |
| `Message`, `ToolCall`, `ToolResult` | models | Conversation content sent to and from a provider |
| `LLMRequest`, `LLMResponse` | models | One provider call, including tool calls |
| `Usage` | model | Token usage of one call |
| `LLMProvider` | Protocol | One implementation per provider |
| `PrefixMismatchError` | exception | A provider rejected a request because history before a thinking block changed ([ADR-0003](../adr/0003-llm-layer.md)); `FakeProvider` raises it too |
| `ModelRouter` | class | Role → provider, from `RoleModelConfig` |
| `UsageRecord` | model | Cost, role, module, run id, `user_id`; computed from `Usage` and per-model prices |
| `CostLedger` | Protocol | Where `UsageRecord`s are written |
| `DailyBudgetGuard` | class | Refuses a new run once the daily cap is reached |

## Config keys

- `RoleModelConfig`: role → provider and model.
- `BudgetSettings` (`budget` in config): `daily_cap_usd`, the temporary daily cap (default 3.0, finite and > 0).
- Per-model prices, since anything changeable without code is config.
- Open question: key names for `RoleModelConfig` and prices are not specified yet.

## Decisions

- [ADR-0003](../adr/0003-llm-layer.md) — LLM layer: roles, `ModelRouter`, and the first `planner`
  provider: Anthropic, `claude-sonnet-5-5` (Accepted).

## Open questions

- Models per role, local or API: see [open decisions](../design.md#open-decisions).
- Monthly budget: see [open decisions](../design.md#open-decisions).

## Introduced in phase

- [Phase 2](../plan/phase-2-core-cli.md): contracts, `ModelRouter`, the first real provider (`planner`), cost tracking.
- [Phase 4](../plan/README.md#phase-4--approvals--actions): `writer`, with email drafts.
- Local roles (`classifier`, `embeddings`, `memory`) arrive with the phases that use them
  ([Phase 7](../plan/README.md#phase-7--memory), [Phase 8](../plan/README.md#phase-8--events--notifications)).
