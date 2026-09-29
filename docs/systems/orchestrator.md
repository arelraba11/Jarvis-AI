# Orchestrator

## Purpose

The orchestrator is Jarvis's single brain: it understands a request, chooses tools and produces the
answer. Chat and voice both go through it, so tools, memory and permissions are the same in every
client ([request flows](../architecture.md#request-flows)).

## Responsibilities

- Run the agent loop: system prompt + history + request → model (`planner` role) → tool calls →
  results → model, until an answer or a limit.
- Load memory before answering ([memory](memory.md)).
- Read freely; every action it proposes goes into the approval queue ([permissions](permissions.md)).
- Enforce loop limits: a max number of iterations and a cost cap for every run.
- Pass a tool's error back to the model instead of failing the run.
- Inject the account into tool calls ([account resolution](modules.md#accounts)).
- Report live status of what it's doing (e.g. "קורא מיילים…") to the client.
- Report every step to the `Tracer` ([infra](infra.md#observability)).
- Provide the deterministic time and date tools (below), so the model never does date arithmetic itself.

**System prompt:** `docs/behavior.md`, Jarvis's behavior spec, is loaded as the `planner` system
prompt. It is written in [Phase 2](../plan/phase-2-core-cli.md), task 0.

**Not responsible for:**

- Knowing clients, modules or providers by name. Tools come from the
  [tool registry](modules.md#tool-registry), models from the [model router](llm.md).
- Deciding which tool levels need approval. The loop calls the permission gate; the gate belongs
  to [permissions](permissions.md).

### Time and date tools

- `get_current_time()` returns the current date and time in the user's `timezone`
  ([config](infra.md#config)).
- `resolve_date(...)` turns a structured relative date into an exact date in the user's timezone.
  - Inputs: offset in days or weeks, target weekday, or a period boundary such as end of month.
  - Outputs: the exact date and the days until it.
  - How inputs combine. Weeks start on `UserSettings.week_start` (default `sunday`,
    [config](infra.md#config)); "today" is the current date in the user's timezone.
    - `weeks=N` + `weekday=W`: day W in the week that starts N weeks after the start of the
      current week.
    - `days=N`: today + N days.
    - `weekday=W` alone: the next W after today; today is excluded, so "Thursday" asked on a
      Thursday means a week later.
  - Example (today = Friday 2026-10-02, weeks start on Sunday): `weeks=2, weekday=thursday` →
    2026-10-15 (the week starting Sunday 2026-10-11). The other reading, "+14 days, then the next
    Thursday", would give 2026-10-22; `resolve_date` uses the week-based reading.

## Contracts

| Contract | Kind | Definition |
|---|---|---|
| `AgentRun` | model | The input to one run |
| `RunResult` | model | Answer, tool calls made, usage, stop reason |
| `Orchestrator` | class | Runs the loop above |
| `AgentLimits` | settings | Max iterations and per-run cost cap |

## Config keys

- `AgentLimits` (part of `Settings`, see [infra](infra.md#config)): max iterations and the per-run cost cap.
- Open question: exact key names and default values are not specified yet.

## Decisions

- ADR-0004 — Where tool permissions are enforced: the loop calls the permission gate; the gate belongs to [permissions](permissions.md) (planned, Phase 2).

## Open questions

- Config key names above.
- `resolve_date`: the result of `weeks=N` without a weekday, and of `days` combined with other
  inputs, is not defined yet.

## Introduced in phase

- [Phase 2](../plan/phase-2-core-cli.md): minimal loop, tool calling, limits, time and date tools.
- [Phase 6](../plan/README.md#phase-6--live-voice): voice hands requests to it through `ask_orchestrator` ([voice](voice.md)).
