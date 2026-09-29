# Jarvis v2 — Design overview

Sep 28, 2026 · @Arel Raba

This is the entry point to the design. Each system has its own file (see [Doc map](#doc-map)).

## Goals and principles

Jarvis is a personal AI assistant in the style of the movie: I talk to it by voice or chat, it knows
my tools and my life, and it proposes actions that I approve. It runs on the Mac first, and later
will be available from the phone too.

- **Sees everything, acts only with approval:** free reading of everything connected. Every change
  in the world, including drafts and saving to memory, happens only after my approval.
- **A long-term system:** a fixed core and pluggable modules. Every new connector, capability, model
  or device comes in as a module or as config, without changing the core.
- **One brain, many mouths:** the Mac app, voice and the phone are clients of the same service, with
  the same memory and the same permissions.
- **Learning:** the agent loop, tools and memory are written from scratch, to understand every layer.

## Decisions

| Topic | Decision | Design impact |
| --- | --- | --- |
| Where it runs | On the Mac now, 24/7 later | A background service on the Mac. When the Mac is off, Jarvis is unavailable |
| Mac interface | A wrapped web app (Tauri) | A TypeScript UI that will later also serve as a PWA on the phone |
| Phone | Later, no channel preference | The brain exposes one API, and the phone is another client |
| Voice | Live conversation | A realtime voice model that delegates to the brain |
| Voice activation | Keyboard shortcut | No constant listening to the microphone |
| Language | Hebrew | Hebrew voice quality is tested before everything else |
| Permissions | Free reading, every action approved | One approval queue for all actions |
| Memory | It proposes and I approve | Saving to memory is an action that needs approval |
| Initiative | Notifications about what matters | macOS notifications from the app |
| Models | A mix of local and API | Local for classification and embeddings, API for planning, writing and voice |
| Mac memory | 24GB | Small local models only |
| Budget | Set after measurement | Cost tracking from day one and a temporary daily cap |
| Google accounts | One now, more in the future | An `accounts` table; every tool takes an `account_id` |
| Connectors | Google, Apple and files, messages, browser, and more | Every connector is a separate module |
| MVP | Email and calendar | The other connectors in later phases |
| Dev language | Python for the service, TypeScript for the UI | My own agent loop, no framework |

## MVP scope

The MVP is email and calendar, in chat and voice, with approval for every action. It tests every core
layer end to end: client, voice, orchestrator, tools, approvals, memory and events.

| Capability | Example | Result |
| --- | --- | --- |
| Inbox summary | "מה חשוב במייל היום?" | A summary of what needs a reply or an action |
| Mail search | "מה סיכמנו עם בעל הדירה על החוזה?" | An answer with a link to the original email |
| Reply draft | "תענה לו שאני מאשר ליום ראשון" | An approval card with the draft, sent after approval |
| Agenda | "מה יש לי מחר?" | A list of meetings and free slots |
| Meeting management | "תזיז את הפגישה עם דני לחמישי" | An approval card, and the calendar changes after approval |
| Notifications | An important email arrived, a meeting is coming up | A macOS notification with context |
| Memory | "אני לא קובע פגישות לפני 10" | A memory proposal; after approval it affects future proposals |

**Out of the MVP:** Apple apps, files, messages, browser, Drive, phone, a morning briefing, and any
specific domain (job search, real estate, home).

## Doc map

| Topic | File |
|---|---|
| Components, flows, processes, extension points, iron rules, repo layout | [architecture.md](architecture.md) |
| Agent loop, time and date tools | [systems/orchestrator.md](systems/orchestrator.md) |
| Read/action levels, approval queue, external content | [systems/permissions.md](systems/permissions.md) |
| Roles, providers, cost tracking | [systems/llm.md](systems/llm.md) |
| Live voice | [systems/voice.md](systems/voice.md) |
| Short- and long-term memory | [systems/memory.md](systems/memory.md) |
| Event bus, importance, notifications | [systems/events.md](systems/events.md) |
| Module system, tool registry, accounts, connectors | [systems/modules.md](systems/modules.md) |
| Mac app, phone | [systems/app.md](systems/app.md) |
| Config, secrets, storage, observability, CI | [systems/infra.md](systems/infra.md) |
| Eval format, runner, grader | [systems/evals.md](systems/evals.md) |
| Gmail and Calendar | [modules/google.md](modules/google.md) |
| Architecture decision records | [adr/](adr/) |

## Roadmap

The roadmap, phase order and each phase's tasks are in [plan/README.md](plan/README.md). It is the
only roadmap, and it is updated there.

## Open decisions

The single list of open design decisions. Each closes with an ADR.

| Decision | Options | Details | Closes |
|---|---|---|---|
| Voice approach | Realtime model, or a transcription → LLM → speech pipeline | [voice](systems/voice.md) | Phase 1 (ADR-0002) |
| Monthly budget | — | [LLM](systems/llm.md) | After two weeks of measurement |
| Models per role | Local or API, by the Hebrew eval set | [LLM](systems/llm.md) | — (`planner` for now: ADR-0003) |
| Langfuse | Cloud (simple, but email content leaves the Mac) or self-hosted on the Mac (private, but one more service to maintain) | [infra](systems/infra.md#observability) | Before Phase 3 (ADR-0006) |
| Postgres | Docker or Homebrew | [infra](systems/infra.md#storage) | — |
| When and how 24/7 | A cloud VM or an always-on computer (e.g. a Mac mini) | [infra](systems/infra.md#ci-and-updates) | Opened when the phone is connected |
| Phone channel | PWA, Siri shortcut or bot | [app](systems/app.md) | — |
| What counts as an important email | The first rules (senders and keywords) | [events](systems/events.md) | Before the events phase (Phase 8) |
