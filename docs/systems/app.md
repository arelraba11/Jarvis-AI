# App and clients

## Purpose

The first interface is a Mac app opened by a keyboard shortcut, with chat and a voice conversation in
the same window. Every client (the Mac app, voice, later the phone) talks to the same API, with the
same memory and permissions.

## Responsibilities

**Mac app (Tauri):**

- **Chat:** history, live status of what the agent is doing ("קורא מיילים…"), and answers with links.
- **Voice:** a button or keyboard shortcut opens a live conversation ([voice](voice.md)). The same
  conversation also appears as a transcript in the chat.
- **Approval queue:** every proposed action appears as a card showing exactly what will be done,
  with approve, edit and reject buttons ([permissions](permissions.md)).
- **Notifications:** macOS notifications about what matters. Clicking one opens the context in the
  app ([events](events.md)).
- **Memory:** a screen showing memory proposals waiting for approval, and everything saved, with the
  option to delete ([memory](memory.md)).
- **UI:** TypeScript, running inside Tauri, opened by a global shortcut. The same code later becomes
  the phone PWA.

**Phone, later:** the same UI as a PWA, connecting to the service on the Mac through Tailscale, a
private network with no exposure to the internet. The final phone channel (PWA, Siri shortcut or bot)
is chosen when we get there; each is just another client of the same API.

**Not responsible for:** any logic. The app is a client of `jarvis-core`
([processes](../architecture.md#processes)).

## Contracts

All tentative until Phase 5 is detailed.

| Contract | Kind | Definition |
|---|---|---|
| `ChatRequest` | model | Tentative |
| `RunEvent` | model | The stream of live status |
| `ApprovalCardDTO` | model | Tentative |
| API-backed `Approver` | class | Implements [`Approver`](permissions.md#contracts) over the API |

## Config keys

- Open question: none are specified yet (e.g. the global shortcut).

## Decisions

- None yet.

## Open questions

- Phone channel: see [open decisions](../design.md#open-decisions).
- The API's shape (transport, endpoints): not specified yet.

## Introduced in phase

- [Phase 5](../plan/README.md#phase-5--api--tauri-app): API and Tauri app with chat and approval cards.
- [Phase 6](../plan/README.md#phase-6--live-voice): voice and transcript.
- [Phase 7](../plan/README.md#phase-7--memory): memory screen.
- [Phase 8](../plan/README.md#phase-8--events--notifications): notifications.
