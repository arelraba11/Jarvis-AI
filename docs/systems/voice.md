# Voice

## Purpose

Voice is a live conversation in Hebrew, in which the voice model is the "mouth and ears" and the
orchestrator is the brain. It is the riskiest component technically, so it is tested before
everything else ([Phase 1](../plan/phase-1-voice-spike.md)).

## Responsibilities

- **Structure:** a realtime speech-to-speech model runs the conversation and has one tool: hand the
  request to the [orchestrator](orchestrator.md). So tools, memory and permissions are identical in
  chat and voice.
- **Alternative:** a pipeline of transcription, LLM and speech, all streaming. Cheaper and more
  controllable, but with noticeable latency. The voice provider interface lets config switch between the two.
- **Not an LLM role:** voice goes only through `VoiceProvider`, never through the `ModelRouter` ([LLM](llm.md)).
- **Approvals in voice:** Jarvis says what it proposes, and the card appears on screen. Approval is
  by click, so a wrong transcription can't run an action ([permissions](permissions.md)).
- **Activation:** a keyboard shortcut opens a conversation. It closes by shortcut or after a long
  silence, so empty minutes aren't paid for. There is no always-on microphone.
- **Transcript:** the same conversation appears as a transcript in the chat ([app](app.md)).

**Not responsible for:** tools, memory or decisions; every request needing data or an action goes
to the orchestrator.

## Contracts

All tentative until Phase 6 is detailed.

| Contract | Kind | Definition |
|---|---|---|
| `VoiceProvider` | Protocol | One implementation per approach (realtime or pipeline), chosen in config |
| `VoiceSession` | class | Tentative |
| `ask_orchestrator` | tool | The voice model's only tool |
| `TranscriptEntry` | model | Tentative |

## Config keys

- The voice provider, chosen in config.
- Open question: key names and the silence timeout are not specified yet.

## Decisions

- ADR-0002 — Voice approach: realtime vs pipeline, with the results table (planned, Phase 1).

## Open questions

- Voice approach: see [open decisions](../design.md#open-decisions); closed by Phase 1.
- Where the voice session runs: see [architecture](../architecture.md#open-questions).

## Introduced in phase

- [Phase 1](../plan/phase-1-voice-spike.md): the spike chooses the approach; its code is thrown away.
- [Phase 6](../plan/README.md#phase-6--live-voice): live voice.
