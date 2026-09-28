# Permissions and approvals

## Purpose

Jarvis reads freely, and anything that changes the world goes through one approval queue. Nothing
happens automatically, including drafts and memory writes.

## Responsibilities

Every tool declares its level. The permission layer in core enforces it, not the tool.

| Level | Examples | Behavior |
|---|---|---|
| Read | Read emails, calendar, files, messages and browser history | Free |
| Action | Create a draft, send an email, schedule or cancel a meeting, save to memory, delete | A card in the approval queue; runs only after approval |

- **Approval card:** what will be done, on what (email, meeting, file), and the full content. It can
  be edited before approval.
- **CLI approval:** until the app exists, the same card is shown in the terminal and answered with
  y / e / n (approve, edit, reject). The `Approver` interface keeps the app's cards
  ([app](app.md)) a drop-in replacement.
- **Enforcement in core:** the permission layer blocks every `action` tool that has no approval.
  The model cannot get around it.
- **Prompt injection:** emails, messages and web pages are marked as external data. An instruction
  that comes from inside them is never executed. The system prompt and `docs/behavior.md` say so.
- **macOS permissions:** Full Disk Access (Messages), Automation (Apple apps), microphone and
  notifications. Each is granted only when the module that needs it arrives.
- **Audit:** every approval is logged with what was approved and when.

Voice approvals happen by click on screen, never by voice ([voice](voice.md)).

**Not responsible for:** storing secrets ([infra](infra.md#secrets)); rendering the cards ([app](app.md)).

## Contracts

| Contract | Kind | Definition | Phase |
|---|---|---|---|
| `PermissionLevel` | enum | `READ` / `ACTION`; declared on every `ToolSpec` ([modules](modules.md#tool-registry)) | 2 |
| `ExternalContent` | model | Wraps external text with its source, so the prompt marks it as data | 3 |
| `ActionProposal` | model | Tentative | 4 |
| `ApprovalDecision` | model | Tentative | 4 |
| `ApprovalQueue` | class | Tentative: the one queue for all actions | 4 |
| `PermissionGate` | class | Tentative: runs an `action` tool only after it is approved | 4 |
| `AuditEntry` | model | Tentative: one record per approval | 4 |
| `Approver` | Protocol | Tentative: CLI implementation in Phase 4, API-backed in Phase 5 | 4 |

## Config keys

- Open question: none are specified yet.

## Decisions

- ADR-0004 — Where tool permissions are enforced (planned, Phase 2).
- ADR-0010 — Handling external content, the prompt-injection defense (planned, Phase 3).

## Open questions

- Fields of the Phase 4 contracts: detailed when Phase 4 is planned.

## Introduced in phase

- [Phase 2](../plan/phase-2-core-cli.md): `PermissionLevel`; core blocks every `action` tool until approvals exist.
- [Phase 3](../plan/phase-3-gmail-read.md): `ExternalContent` for email bodies.
- [Phase 4](../plan/README.md#phase-4--approvals--actions): the approval queue, `PermissionGate`, CLI approver, audit log.
- [Phase 5](../plan/README.md#phase-5--api--tauri-app): approval cards in the app.
