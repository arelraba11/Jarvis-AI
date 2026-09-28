# Evals

## Purpose

Each phase's acceptance examples become evals in `evals/`, so behavior is checked the same way every
time, including against real models.

## Responsibilities

- **Case format:** a request, deterministic checks and a judge rubric.
  - **Deterministic checks:** which tools were called or not called, with which arguments, and
    facts the answer must contain.
  - **Judge rubric:** 1–3 short items an LLM judge checks in the answer text.
- **Pass rule:** a case passes only if every deterministic check passes and the judge passes every
  rubric item.
- **Runner:** executes each case through the [orchestrator](orchestrator.md) against the real
  `planner`, and reports to Langfuse.
- **Source of truth:** the cases live in `evals/` in git. Langfuse receives run results only.
- **Grader:** applies the deterministic checks to `RunResult` (tool calls and their arguments, facts
  in the answer). Then an LLM judge scores the answer text against the rubric, returning pass/fail
  and a one-line reason per item.
- **Judge reliability:** an LLM judge can be inconsistent. Keep rubric items short and binary, and
  re-run a failing case before trusting the result.
- **When evals run:** only when prompts or the model layer change, so they don't burn budget.
- **Tests:** the judge is faked in tests; the runner works end to end against `FakeProvider`.

Per-role model-choice eval sets are described in [LLM](llm.md).

**Not responsible for:** unit tests, which never call a real LLM (see `CLAUDE.md`).

## Contracts

| Contract | Kind | Definition |
|---|---|---|
| `EvalCase` | model | Request, deterministic checks, judge rubric |
| `EvalResult` | model | The outcome of one case |
| `Grader` | class | Deterministic checks, then the LLM judge |

## Config keys

- The judge model. Proposal: an eval-only setting in the eval config, kept out of `Role`.
- Open question: key names are not specified yet.

## Decisions

- ADR-0007 — Evals: case format, deterministic checks, the LLM judge and its model (planned, Phase 2).

## Open questions

- Which model is the judge (see the proposal above).
- The CI trigger for evals: a path filter or manual. Decided once the runner exists.

## Introduced in phase

- [Phase 2](../plan/phase-2-core-cli.md): the runner, the grader and the first set, run manually.
- [Phase 3](../plan/phase-3-gmail-read.md): mail cases against a fixture mailbox.
