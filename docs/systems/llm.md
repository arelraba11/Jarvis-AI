# LLM layer

## Purpose

Every model call goes through one interface, and code asks for a *role*, never a model. Simple tasks
run locally on the M4 Pro, the rest through APIs.

## Responsibilities

| Role | Used for | Where |
|---|---|---|
| `planner` | The orchestrator: understanding a request and choosing tools | API, strong model |
| `writer` | Email drafts and summaries | API |
| `voice` | Live conversation | API, realtime voice model ([voice](voice.md)) |
| `classifier` | Classifying emails and events by importance | Local |
| `embeddings` | Semantic search in memory and email | Local, multilingual model |
| `memory` | Proposing facts to remember | Local or a cheap API |

- **Local models:** Ollama or MLX, running native and not inside Docker (to get GPU access). With
  24GB of memory, only small models.
- **Hebrew:** small local models are weaker in Hebrew. Every local role is tested against an eval
  set, and moves to an API if it doesn't meet the bar.
- **Model choice:** an eval set of 20–30 real Hebrew examples per role, at the start of development
  and against current prices ([evals](evals.md)).
- **Costs:** every call is logged with cost, role and module. The budget is set after two weeks of
  measurement; until then there is a temporary daily cap in config.
- **Providers:** adding a model or provider, local or API, means implementing the provider interface
  and mapping a role to it in config ([extension points](../architecture.md#extension-points)).

**Not responsible for:** the voice session itself ([voice](voice.md)); where the cost log is
stored ([infra](infra.md#storage)).

## Contracts

| Contract | Kind | Definition |
|---|---|---|
| `Role` | enum | `planner`, `writer`, `voice`, `classifier`, `embeddings`, `memory` |
| `Message`, `ToolCall`, `ToolResult` | models | Conversation content sent to and from a provider |
| `LLMRequest`, `LLMResponse` | models | One provider call, including tool calls |
| `Usage` | model | Token usage of one call |
| `LLMProvider` | Protocol | One implementation per provider |
| `ModelRouter` | class | Role → provider, from `RoleModelConfig` |
| `UsageRecord` | model | Cost, role, module, run id, `user_id`; computed from `Usage` and per-model prices |
| `CostLedger` | Protocol | Where `UsageRecord`s are written |
| `DailyBudgetGuard` | class | Refuses a new run once the daily cap is reached |

## Config keys

- `RoleModelConfig`: role → provider and model.
- `BudgetSettings`: the temporary daily cap.
- Per-model prices, since anything changeable without code is config.
- Open question: exact key names are not specified yet.

## Decisions

- ADR-0003 — LLM layer: roles, `ModelRouter`, and the first `planner` provider (planned, Phase 2).

## Open questions

- Models per role, local or API: see [open decisions](../design.md#open-decisions).
- Monthly budget: see [open decisions](../design.md#open-decisions).
- Which API provider and model for `planner` in Phase 2: choose one for now; the eval set decides later.

## Introduced in phase

- [Phase 2](../plan/phase-2-core-cli.md): contracts, `ModelRouter`, the first real provider (`planner`), cost tracking.
- Local roles (`classifier`, `embeddings`, `memory`) arrive with the phases that use them
  ([Phase 7](../plan/README.md#phase-7--memory), [Phase 8](../plan/README.md#phase-8--events--notifications)).
