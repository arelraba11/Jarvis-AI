# ADR-0003 — LLM layer: roles, `ModelRouter`, and the first `planner` provider

- **Status:** Accepted
- **Date:** 2026-09-29
- **Phase:** [Phase 2](../plan/phase-2-core-cli.md) (code: tasks 2–5)
- **System:** [LLM](../systems/llm.md)

## Context

Phase 2 needs one real model behind the `planner` role so `jarvis chat` works. The per-role eval
set that will choose models for good does not exist yet, so this is a choice for now, made so that
changing it later is a config edit, not a code change.

## Decision

1. **Roles.** Code asks for a `Role` (`planner`, `writer`, `classifier`, `embeddings`, `memory`),
   never a model. `ModelRouter` resolves a role to an `LLMProvider` from `RoleModelConfig` in config.
   Core never names a provider or a model.
2. **First `planner` provider:** Anthropic (Messages API), model **`claude-sonnet-5-5`**
   (Claude Sonnet 5.5).
3. **Client library:** the official `anthropic` SDK is a new dependency, so it needs approval
   before task 5 adds it. If approved, it is used only as a typed client for `messages.create`: no
   tool runner and no agent helpers, because the agent loop is ours
   ([orchestrator](../systems/orchestrator.md)).

## Why

- **Strong tier at the lowest output price.** $2 / $10 per million input / output tokens
  (Anthropic models overview, 2026-09-29).
- **Reproducible evals.** Anthropic's docs: "Every Claude model ID is a pinned snapshot, including
  the dateless IDs used from the 4.6 generation on." So `claude-sonnet-5-5` does not silently change
  under the eval set.
- **Prompt caching fits the shape of the requests.** Every `planner` call starts with the same
  system prompt (`docs/behavior.md`) and tool list, which is the prefix caching reuses.
  The minimum cacheable prefix is model-dependent; task 5 confirms caching actually happens by
  checking `cache_read_input_tokens` on repeated calls.

## Alternatives considered

- **Claude Sonnet 5 (`claude-sonnet-5`).** The first pick. Same price and tokenizer, but Anthropic
  lists it as a legacy model since Sonnet 5.5 was released, so it was replaced before any code
  used it.
- **Gemini 3.8 Flash.** The cheapest, but its introductory price doubles on 2027-01-01.
- **GPT-6 Sol.** The same list price, so no cost advantage.

The two non-Anthropic prices are from the comparison made on 2026-09-29 and are not re-checked in
this ADR.

## Consequences

- **Cost.** The tokenizer introduced with Claude Opus 4.7 (used by Sonnet 5 and 5.5) produces about
  30% more tokens than Sonnet 4.6 for the same text (Anthropic's migration guide). Hebrew may be
  affected more (UNVERIFIED: not measured). So budgets come from measured `Usage`, not from list
  prices.
- **Prices live in config**, taken from Anthropic's pricing page when task 5 is done, not from this
  ADR ([LLM config keys](../systems/llm.md#config-keys)).
- **Constraints of Sonnet 5.5's API** that the provider and the loop must respect (Anthropic's
  Sonnet 5.5 migration guide):
  - Forced tool choice (`tool_choice` `any` or `tool`) returns a 400. The loop uses `auto`.
  - `thinking: {type: "disabled"}` returns a 400.
  - **History is append-only within a conversation.** The API checks that `system`, `tools` and
    every earlier message are unchanged since a thinking block was produced. It is enforced by
    default for accounts created on or after 2026-08-31 (a 400 on violation). So the system prompt
    holds no per-request values (no timestamps: time comes from `get_current_time`), the tool list
    is fixed for a session, and assistant turns, including `thinking` blocks, are passed back
    unchanged. `Message` (task 2) must be able to carry those blocks opaquely.
  - **Thinking blocks may be removed from the start, from the end, or all of them.** Earlier
    thinking blocks are not part of the checked prefix, so removing one does not change it. Only a
    gap in the middle fails: each block records the one before it, so removing a block between two
    kept ones invalidates every later block. Editing or deleting any earlier message that precedes
    a kept thinking block fails too. History trimming ([Phase 2](../plan/phase-2-core-cli.md)
    task 13) relies on this. (Corrected in task 2: this bullet first said "from the front only",
    which is stricter than the API.)
  - **The check's behavior is set explicitly, not left to the account's age.** Every request sets
    `thinking.block_binding.prefix_mismatch_behavior: "error"`, which needs the
    `thinking-binding-controls-2026-08-01` beta header and adaptive thinking. Never `"drop_block"`:
    it drops the mismatched block and every thinking block after it and lets the request succeed,
    which hides the bug that edited the history.
  - Text between tool calls can come back as `thinking` blocks rather than `text`; a client that
    renders only `text` goes quiet between tool calls.
  - A response can stop with `stop_reason: "refusal"`; the provider checks `stop_reason` before
    reading content.
- **Judge independence.** The eval judge comes from a different vendor than the planner
  ([evals](../systems/evals.md#config-keys), ADR-0007).

## Revisit

- When the `planner` eval set runs ([LLM](../systems/llm.md), model choice).
- When Anthropic announces a retirement date for `claude-sonnet-5-5` (currently not sooner than
  2027-09-28).
