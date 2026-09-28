# Modules, tools and accounts

## Purpose

Every connector is a separate module, with free `read` tools and `action` tools that go through
approval. Core discovers modules and tools without knowing their names.

## Responsibilities

### Module system

- A module is a folder with a `module.yaml` that declares its tools, prompts, triggers and memory space.
- Core discovers modules through `module.yaml` only; nothing in core imports `jarvis.modules.*`.
- Mac-dependent modules (Apple, messages, files) run in `mac-agent` ([processes](../architecture.md#processes)).

### Tool registry

- A tool is a function with a decorator in the tool registry, or an external MCP server.
- `ToolSpec` is built from a typed function signature; the JSON schema comes from Pydantic.
- Every tool must declare a permission level ([permissions](permissions.md)). A tool without a level
  is rejected, and so is a duplicate name.

### Accounts

- Accounts live in an `accounts` table (file-based until Postgres, [storage](infra.md#storage)).
- Every external tool takes an `account_id`. Adding a Google account means another OAuth and one
  more `accounts` row: data only.

### Connectors

The MVP starts with Google; the rest arrive after the MVP, one module per phase.

| Connector | Read | Action (approved) | How it connects | Phase |
|---|---|---|---|---|
| Gmail, Google Calendar | See [Google](../modules/google.md) | | | MVP |
| Apple apps | Notes, Reminders, Contacts | Create a note or a reminder | EventKit and AppleScript | After MVP |
| Files on the Mac | Search and read, summarize documents | Move, rename | Spotlight (`mdfind`) and direct reads | After MVP |
| Messages | iMessage and SMS: what's new, who is waiting for a reply | Send | The local Messages database, and AppleScript to send | After MVP |
| Browser | History, open tabs, page content | Actions on websites | Reading the local history, and Playwright for actions | After MVP |
| Google Drive, Docs, Sheets | Search and read | Create and edit | Drive, Docs and Sheets APIs | After MVP |

**WhatsApp:** there is no official API for a personal account, and the unofficial libraries put the
number at risk. It stays out of the plan until there is an official solution or a business number.

**Not responsible for:** enforcing permission levels ([permissions](permissions.md)); running the
loop ([orchestrator](orchestrator.md)).

## Contracts

| Contract | Kind | Definition | Phase |
|---|---|---|---|
| `ToolSpec` | model | Name, description, JSON schema, `PermissionLevel` | 2 |
| `Tool` | Protocol | A callable tool with its `ToolSpec` | 2 |
| `ToolRegistry` | class | Holds all tools; rejects missing levels and duplicate names | 2 |
| `@tool` | decorator | Registers a typed function as a tool | 2 |
| `ModuleManifest` | model | The `module.yaml` schema: tools, prompts, triggers, memory space | 3 |
| `ModuleLoader` | class | Parses and validates `module.yaml`, registers the module's tools | 3 |
| `Account` | model | `user_id`, `account_id`, provider, email | 3 |
| `AccountStore` | Protocol | Add, list and get accounts; an unknown `account_id` fails | 3 |

## Config keys

- Open question: how modules are enabled or configured is not specified yet.

## Decisions

- ADR-0008 — Module format: the `module.yaml` schema and how core loads modules (planned, Phase 3).

## Open questions

- None beyond the config question above.

## Introduced in phase

- [Phase 2](../plan/phase-2-core-cli.md): tool registry.
- [Phase 3](../plan/phase-3-gmail-read.md): module system, accounts, the Google module.
- After the MVP: the other connectors ([plan](../plan/README.md#after-the-mvp)).
