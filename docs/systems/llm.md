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
| `Message`, `ToolCall`, `ToolResult` | models | Conversation content sent to and from a provider. A `Message` holds content blocks: `TextBlock`, `ThinkingBlock` (the provider's block, carried opaquely and sent back unchanged), `ToolCall`, `ToolResult`, `OpaqueBlock` (an assistant block type we don't model, kept in order and sent back unchanged; never dropped). Assistant `TextBlock` and `ToolCall` also carry the provider's `raw` block, so a whole assistant turn goes back exactly as the API returned it ([preserved thinking](#provider-anthropic)). `raw` is provider-opaque: core never reads it, only the provider that produced it |
| `ToolDefinition` | model | A tool as offered to the model: name, description, JSON schema. No permission level: core enforces that, not the model |
| `LLMRequest`, `LLMResponse` | models | One provider call, including tool calls. `LLMResponse.message` is `None` exactly when `stop_reason` is `refusal`: a refusal can come before any output, and partial output before one is discarded |
| `Usage` | model | Token usage of one call |
| `LLMProvider` | Protocol | One implementation per provider: `async complete(LLMRequest) -> LLMResponse` |
| `LLMError` | exception | Base of every provider error; the loop catches it without knowing the provider. Subclasses: `PrefixMismatchError`, `LLMAuthError` (401/403), `LLMRateLimitError` (429 after retries), `LLMUnavailableError` (timeout, network, 5xx/529 after retries), `LLMRequestError` (other 4xx), `LLMResponseError` (a stop reason we don't handle, or a response that breaks the contracts). Messages name the provider and never contain a secret |
| `Effort` | type | Provider-neutral effort level: `low`, `medium`, `high`, `xhigh`, `max` |
| `PrefixMismatchError` | exception | A provider rejected a request because history before a kept thinking block changed, or a thinking block was removed from the middle (removing from the start, from the end, or all of them is allowed; [ADR-0003](../adr/0003-llm-layer.md)); `FakeProvider` raises it too |
| `ModelRouter` | class | Role → provider, from `RoleModelConfig`, through a registry of provider name → `ProviderFactory` (`RoleModelConfig` → `LLMProvider`) |
| `UsageRecord` | model | Cost, role, module, run id, `user_id`; computed from `Usage` and per-model prices |
| `CostLedger` | Protocol | Where `UsageRecord`s are written |
| `DailyBudgetGuard` | class | Refuses a new run once the daily cap is reached |

`LLMRequest` rejects a history that no provider would accept, so a loop bug (from
[Phase 2](../plan/phase-2-core-cli.md) task 8 on) fails in unit tests, not as a 400 from the API:

- The first message is from the user. So is the last: the loop never sends a request that ends on
  an assistant turn (our rule, not an API one).
- Every `ToolCall` has its `ToolResult` in the very next message, and every `ToolResult` answers a
  `ToolCall` in the message right before it. Anthropic and OpenAI both require this, so it is
  provider-neutral.

`jarvis/llm/contracts.py` is a leaf module: it imports nothing from `jarvis`. Config imports
`Role` from it and `ModelRouter` imports config, so any `jarvis` import in `contracts.py` creates a
cycle.

## Config keys

- `models` (in config): a role → `RoleModelConfig` mapping, with `provider` and `model` (both
  non-empty), and two optional provider-neutral fields:
  - `max_tokens` (default 16000, > 0): the output ceiling, thinking included. 16000 is the
    value Anthropic's own non-streaming adaptive-thinking examples use; it leaves room for
    thinking plus a reply and stays well inside what a non-streaming call can finish.
  - `effort` (default `medium`): Anthropic's effort guide for Sonnet 5.5 says to start with
    `medium` for multistep tool use and `medium` or `low` for chat, which is the planner's mix.
    The API default (`high`) is not relied on: effort is always sent. The planner eval set
    re-tunes it.

  Each provider maps these to its own API and rejects a value it can't honor when the router is
  built. No provider-specific keys go in the shared config. An unknown role name is a config
  error. Code has no default: core names no provider or
  model, so the `planner` entry comes from `default.yaml`:

  ```yaml
  models:
    planner: {provider: anthropic, model: claude-sonnet-5-5}
  ```

  `local.yaml` can change one key of a role (only `model`, say) or add a role.
- `ModelRouter` gets a registry of provider name → factory(`RoleModelConfig`) → `LLMProvider`, and
  builds each role's provider once, when it is built. Config can't know which providers exist, so
  a provider name with no registered factory fails when the router is built, not on the first
  call; so do a missing API key and a value the provider can't honor.
- **Composition root:** `jarvis/composition.py` registers the factories (`provider_factories`)
  and builds the router (`build_router`). It is the only module that imports concrete providers
  (`jarvis/llm/*_provider.py`); a test enforces it. Core and the router know only `LLMProvider`.
- `BudgetSettings` (`budget` in config): `daily_cap_usd`, the temporary daily cap (default 3.0, finite and > 0).
- `prices` (in config): model name → `ModelPrices`, USD per million tokens: `input_per_mtok`,
  `output_per_mtok`, `cache_write_per_mtok`, `cache_read_per_mtok` (each finite and ≥ 0).
  `default.yaml` holds the prices from the provider's pricing page with the date checked. Cost
  math from them is task 11.

## Provider: Anthropic

`jarvis/llm/anthropic_provider.py`, registered as `anthropic`. The official `anthropic` SDK is
used only as a typed client for `messages.create` (beta namespace): no tool runner, no agent
helpers.

- **Key:** `SecretStore.get("anthropic")` when the router is built. The client gets it
  explicitly, so no environment credential is read, and `base_url` is explicit, so
  `ANTHROPIC_BASE_URL` can't send the key elsewhere. The key never appears in a repr, log or
  error; API error text is redacted as well, and errors are raised without a reference to the
  SDK's exception (whose request holds the key header).
- **Request:** adaptive thinking with `block_binding.prefix_mismatch_behavior: "error"` and the
  `thinking-binding-controls-2026-08-01` beta ([ADR-0003](../adr/0003-llm-layer.md));
  `output_config.effort`; `tool_choice: auto` when there are tools.
- **Prompt caching:** one `cache_control` breakpoint on the system block, which caches tools and
  system together (the cache prefix is tools, then system). With no system prompt, the last tool
  carries it. Sonnet 5.5's minimum cacheable prefix is 512 tokens.
- **Preserved thinking:** each assistant turn is sent back exactly as the API returned it: every
  block, in order, with every field. Anthropic's docs: "A serializer that drops unknown block
  types, drops empty fields, or reorders blocks edits the prefix." `redacted_thinking` maps to
  `ThinkingBlock` (it is signed and bound like thinking); any other unmodeled type maps to
  `OpaqueBlock`. The 400 for a prefix mismatch is recognized by its message ("bound to a
  different conversation": the docs name no structured field) and raises `PrefixMismatchError`.
- **Stop reasons:** `end_turn`, `tool_use`, `max_tokens`, `refusal` map; anything else, including
  documented ones our requests never ask for (`stop_sequence`, `pause_turn`, `compaction`,
  `model_context_window_exceeded`), is an `LLMResponseError` that names it.
- **Timeout and retries:** set explicitly: 600 s (connect 5 s) and 2 retries, the SDK's values.
  A non-streaming call sends nothing until it is done, so the timeout must cover the longest
  answer; by the SDK's estimate (3600 s per 128,000 tokens) that is 21,333 tokens, and the
  factory rejects a larger `max_tokens`.
- **Tests:** mapping tests against hand-built fixtures (`tests/fixtures/anthropic/`, shapes from
  the docs) through a mock HTTP transport; live smoke tests behind the `live` marker
  (`uv run pytest -m live`), never in CI.

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
