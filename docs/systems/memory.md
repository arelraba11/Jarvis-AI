# Memory

## Purpose

Jarvis proposes what to remember, and only what I approve is saved. Long-term memory lives in local
Postgres with pgvector ([storage](infra.md#storage)).

## Responsibilities

- **Short-term memory:** the current session's history, summarized automatically when the
  conversation gets long. A session closes after an idle time set in config.
- **Proposals:** at the end of a session, a cheap model (`memory` role, [LLM](llm.md)) extracts
  facts and preferences and proposes them on the memory screen ([app](app.md)). A proposal that
  isn't approved affects nothing. Saving is an `action` ([permissions](permissions.md)).
- **Long-term memory:** every approved item is stored with `user_id`, a space (`personal`, `mail`,
  and later one space per module), source, date and embedding.
- **Retrieval:** before every answer, a semantic search in the active module's spaces and in the
  personal space.
- **Update and delete:** an updated fact is proposed as a replacement of the old one, not a
  duplicate. Deletion is full deletion.

**Not responsible for:** data that can be fetched again (emails, calendar events). Memory holds
facts about me, not a copy of the data.

## Contracts

| Contract | Kind | Definition | Phase |
|---|---|---|---|
| `Session` | class | Short-term history plus an idle timeout from config | 2 |
| `MemoryItem` | model | Tentative | 7 |
| `MemorySpace` | model | Tentative | 7 |
| `MemoryProposal` | model | Tentative | 7 |
| `MemoryStore` | Protocol | Tentative | 7 |
| `Embedder` | Protocol | Tentative (`embeddings` role) | 7 |
| `SessionSummarizer` | class | Tentative | 7 |

## Config keys

- Session idle timeout.
- Open question: key names are not specified yet.

## Decisions

- None yet.

## Open questions

- Postgres in Docker or from Homebrew: see [open decisions](../design.md#open-decisions).

## Introduced in phase

- [Phase 2](../plan/phase-2-core-cli.md): `Session` (history across turns, idle timeout).
- [Phase 7](../plan/README.md#phase-7--memory): everything else, including session summarization.
  It belongs with the other memory work, and Phase 2 sessions are short.
