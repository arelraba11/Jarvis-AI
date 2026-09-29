# Jarvis — Implementation plan

This is the project's only roadmap: it goes from the current repo to the end of the MVP. What each
system *is* lives in [`../systems/`](../systems/); this folder says *when* and in what order.
Goals and open decisions: [design](../design.md).

## Overview

| # | Phase | Goal | Detail | Status |
|---|---|---|---|---|
| 0 | Dev environment | Tooling, CI and a repo skeleton everything else builds on | — | ✅ done |
| 1 | Hebrew voice spike | Choose realtime speech-to-speech or a transcription→LLM→speech pipeline, within 3 days | [full](phase-1-voice-spike.md) | ⏭️ next |
| 2 | Core skeleton (CLI) | Chat with Jarvis in Hebrew in the terminal through my own agent loop, with role-based models, cost tracking and tracing | [full](phase-2-core-cli.md) | 🚧 in progress |
| 3 | Gmail read | Ask questions about my real inbox from the CLI | [full](phase-3-gmail-read.md) | — |
| 4 | Approvals + actions | Send email and manage meetings from the CLI, each action run only after I approve it | [stub](#phase-4--approvals--actions) | — |
| 5 | API + Tauri app | The same brain behind an API, with chat and approval cards in a Mac app | [stub](#phase-5--api--tauri-app) | — |
| 6 | Live voice | A live Hebrew conversation that hands requests to the orchestrator | [stub](#phase-6--live-voice) | — |
| 7 | Memory | Jarvis proposes facts, I approve them, and they change later answers | [stub](#phase-7--memory) | — |
| 8 | Events + notifications | An important email triggers a macOS notification within a minute | [stub](#phase-8--events--notifications) | — |

Rolling wave: phases 1–3 are planned in full. Phases 4–8 have only a goal, scope and done criteria
below, and get their own file with full detail when the phase before them is under way.

## Phase order

- **Voice spike → core in CLI → Gmail read → approvals + actions → API + app → voice → memory → events.**
  *Why:* each slice becomes usable daily with less work, and the app is built only once the core and
  approvals it shows actually work.
- **Google is split in two** (Phase 3 read, Phase 4 actions + Calendar).
  *Why:* reading is safe and useful on its own. It proves OAuth, the module system and the
  external-content handling before anything can change the world.
- **A CLI approver comes before the app's cards**, so approvals can be built and used in Phase 4.

## Working rules

- **Vertical slices:** every phase ends with something I use day to day.
- **Contracts first:** each phase defines its Pydantic models and Protocols before implementing
  them. Phase files list contracts by name; their definitions live in the system docs.
- **Small commits:** one task can be several commits; every commit leaves `main` green.
- **Tests with every change, mypy strict:** see the working rules in [`CLAUDE.md`](../../CLAUDE.md).
  Unit tests use fakes: no network, no Keychain, no real LLM in CI.
- **CI green before moving on**, to the next task and to the next phase.
- **Acceptance examples become evals** in `evals/`, with deterministic checks and a judge rubric
  ([evals](../systems/evals.md)).
- **One ADR per real decision** in [`docs/adr/`](../adr/), written in the phase that makes the decision.

---

## Phase 4 — Approvals + actions

**Goal:** send email and manage meetings from the CLI, with each action run only after I approve it.

**Scope:**
- One approval queue, `PermissionGate` and an audit log ([permissions](../systems/permissions.md)).
- The CLI approver: approve / edit / reject with y / e / n ([permissions](../systems/permissions.md)).
- Gmail actions and Google Calendar read and actions ([Google](../modules/google.md)).

**Tentative contracts:** `ActionProposal`, `ApprovalDecision`, `ApprovalQueue`, `PermissionGate`,
`AuditEntry`, `Approver` ([permissions](../systems/permissions.md#contracts)); `CalendarEvent`,
`FreeSlot`, `CalendarClient` ([Google](../modules/google.md#contracts)).

**Done criteria:**
- I can schedule a meeting and send an email, only after approval.
- The MVP rows "reply draft", "agenda" and "meeting management" ([design](../design.md#mvp-scope)) work from the CLI.
- No `action` tool can run without an approval record.

## Phase 5 — API + Tauri app

**Goal:** the same brain behind one API, used from a Mac app with chat and approval cards.

**Scope:**
- `jarvis-core` exposes an API and runs under `launchd`, starting at login ([processes](../architecture.md#processes)).
- The Tauri app: chat with history, live status and answers with links; approval cards ([app](../systems/app.md)).
- The update script ([infra](../systems/infra.md#ci-and-updates)).

**Tentative contracts:** `ChatRequest`, `RunEvent`, `ApprovalCardDTO`, API-backed `Approver`
([app](../systems/app.md#contracts)).

**Done criteria:**
- Everything from Phases 2–4 works from the app.
- Actions are approved on cards in the app.
- The core survives a restart and a logout/login.

## Phase 6 — Live voice

**Goal:** a live Hebrew conversation, using the approach chosen in Phase 1, that hands every request
needing data or an action to the orchestrator.

**Scope:** the voice provider from config, the `ask_orchestrator` tool, shortcut activation and
silence timeout, the transcript in the chat, approvals by click only ([voice](../systems/voice.md)).

**Tentative contracts:** `VoiceProvider`, `VoiceSession`, `ask_orchestrator`, `TranscriptEntry`
([voice](../systems/voice.md#contracts)).

**Done criteria:** I can move a meeting by voice and approve it on screen.

## Phase 7 — Memory

**Goal:** Jarvis proposes facts to remember, and only the facts I approve are saved and used.

**Scope:**
- Postgres with pgvector and the daily encrypted backup; the file-based stores move to Postgres,
  mechanically per ADR-0005 ([storage](../systems/infra.md#storage)).
- Session summarization, proposals, the memory screen, retrieval, update and delete ([memory](../systems/memory.md)).

**Tentative contracts:** `MemoryItem`, `MemorySpace`, `MemoryProposal`, `MemoryStore`, `Embedder`,
`SessionSummarizer` ([memory](../systems/memory.md#contracts)).

**Done criteria:** a fact I approved changes a proposal in a different conversation (the MVP row
"memory", [design](../design.md#mvp-scope)).

## Phase 8 — Events + notifications

**Goal:** the things that matter reach me as macOS notifications, without me asking.

**Scope:** Gmail watch and its daily renewal, sync after wake, idempotency, local classification
plus notification rules, macOS notifications for important emails and upcoming meetings
([events](../systems/events.md), [Google](../modules/google.md#gmail)).

**Tentative contracts:** `Event`, `EventBus`, `NotificationRule`, `ImportanceClassifier`,
`Notifier`, `Scheduler`, `CronJob`, `SyncCursor` ([events](../systems/events.md#contracts)).

**Done criteria:**
- An important email triggers a notification within a minute.
- The MVP row "notifications" works, including an upcoming meeting.

## After the MVP

One module per phase: Apple apps and files, messages, browser, Drive
([connectors](../systems/modules.md#connectors)), phone via Tailscale ([app](../systems/app.md)),
the move to 24/7, and domains such as job search. These get planned when the MVP is done.
