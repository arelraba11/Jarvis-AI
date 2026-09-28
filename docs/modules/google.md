# Google module (Gmail + Calendar)

`modules/google` is the MVP connector. It follows the general [module system](../systems/modules.md):
loaded through `module.yaml`, every tool takes an `account_id`, `read` tools are free and `action`
tools need [approval](../systems/permissions.md).

## Gmail

| Read | Action (approved) | How it connects |
|---|---|---|
| Search, read, classify incoming emails | Draft, send, label, archive | Gmail API, OAuth, watch with Pub/Sub in pull mode |

Read tools, all at `read` level:

- `search_emails(account_id, query)`
- `read_email(account_id, message_id)`
- `read_thread(account_id, thread_id)`
- `inbox_digest(account_id, date)`: lists the day's emails; the `writer` role summarizes what needs
  a reply or an action.

Rules:

- Messages map to `EmailMessage` with a link to the original; search answers include that link.
- Long bodies are truncated to a budget.
- Every email body reaches the model wrapped as [`ExternalContent`](../systems/permissions.md#contracts).
- Watch renewal and missed-event sync: [events](../systems/events.md).

## Calendar

| Read | Action (approved) | How it connects |
|---|---|---|
| Events, availability | Create, move, cancel | Calendar API |

Calendar tools use the user's `timezone` ([config](../systems/infra.md#config)).

## OAuth

- `jarvis accounts add google`: a desktop OAuth flow for one account, stored as an `accounts` record.
- Tokens are saved through `SecretStore` (Keychain only) and refreshed on expiry.
- An OAuth app in Testing mode gets refresh tokens that expire after 7 days, so the app moves to
  Production mode for personal use. The requirements need checking against current Google documentation.
- If a call fails on auth, Jarvis says the account needs reconnecting (`jarvis accounts add google`).

## Contracts

| Contract | Kind | Definition | Phase |
|---|---|---|---|
| `GoogleCredentials` | class | Loads and refreshes tokens through `SecretStore` | 3 |
| `EmailMessage` | model | One email, with a link to the original | 3 |
| `EmailSummary` | model | Tentative fields | 3 |
| `EmailQuery` | model | Tentative fields | 3 |
| `GmailClient` | Protocol | Search, fetch message, fetch thread; `FakeGmailClient` for tests | 3 |
| `CalendarEvent` | model | Tentative | 4 |
| `FreeSlot` | model | Tentative | 4 |
| `CalendarClient` | Protocol | Tentative | 4 |

## Decisions

- ADR-0009 — Google OAuth: flow, token storage in the Keychain, Production mode (planned, Phase 3).
- ADR-0011 — Google API client choice (planned, Phase 3).

## Open questions

- **Client library:** the official client or plain HTTP. It is a new dependency, so ask before adding it.
- **Production mode requirements** for personal use; if Testing mode is needed, tokens expire after 7 days.
- **Long threads and HTML emails** can exceed token budgets; truncation may lose the part that matters.

## Introduced in phase

- [Phase 3](../plan/phase-3-gmail-read.md): OAuth, Gmail read tools.
- [Phase 4](../plan/README.md#phase-4--approvals--actions): Gmail actions, Calendar read and actions.
- [Phase 8](../plan/README.md#phase-8--events--notifications): Gmail watch.
