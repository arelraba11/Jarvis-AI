# Voice spike: Hebrew realtime vs pipeline

Phase 1, tasks 1–2 ([phase file](../../docs/plan/phase-1-voice-spike.md)). Throwaway code: exempt
from tests and mypy; ruff still applies. The outcome is ADR-0002.

## Candidates

Prices are published rates as of Sep 2026. Per-minute figures are estimates until they are measured.

| # | Candidate | Model(s) | Why it's a candidate | Published price |
|---|---|---|---|---|
| 1 | GPT-Live-1 (OpenAI) | `gpt-live-1` | Full-duplex; client delegation lets the backend be our own orchestrator, which matches `ask_orchestrator` ([voice](../../docs/systems/voice.md)) | $0.05/min of session time, billed per second (silence included); the backend is billed separately |
| 2 | Gemini 3.8 Live (Google) | `gemini-3.8-live` | Hebrew (`he`) is officially supported | ~$3/1M audio input tokens, ~$12/1M audio output tokens (~$0.005/min in, ~$0.018/min out) |
| 3 | Pipeline (ElevenLabs) | Scribe v2 Realtime (STT) → a fast LLM → Eleven v3 Conversational (TTS) | The fallback: cheaper and more controllable, at the cost of latency | STT $0.39/h (~150 ms); TTS $0.05/1K chars (~280 ms); plus the LLM |
| 4 | *Optional* | `gpt-realtime-2.1` | Only if time remains on day 2 | — |

Notes:

- **GPT-Live-1:** Hebrew is **not** listed in OpenAI's docs, so the spike decides. It needs a paid
  API tier (the Free tier is not supported).
- **Gemini 3.8 Live:** function calling is async (`NON_BLOCKING`) by default. Audio-only sessions
  are limited to 15 min unless extended with session management.
- **Pipeline TTS:** Flash v2.5 and Turbo v2.5 do **not** support Hebrew; only v3 and v3
  Conversational do.
- **Pipeline STT fallback:** if Scribe's Hebrew is weak, use `ivrit-ai/whisper-large-v3-turbo`,
  run locally. It is not truly streaming.

## Harness contract

The same for every candidate, so they are compared on equal terms.

- **One stub tool:** `ask_orchestrator(request: str)`. It logs the request text and immediately
  returns a canned answer for the current example (e.g. a fixed agenda for tomorrow).
- **One system prompt:** "you're Jarvis's voice; delegate every request that needs data or an action".
- **Pipeline:** its LLM gets the same tool and prompt: STT transcript → LLM with `ask_orchestrator`
  → TTS. This mirrors the real design, where the voice layer hands the request to the orchestrator
  ([voice](../../docs/systems/voice.md)).
- **Comprehension is scored on the logged request text** passed to the tool, against the
  "understood" criteria below. Not on what the model says aloud.

## Scoring sheet

| Measure | How | Granularity |
|---|---|---|
| Comprehension | 1–5: the request text logged by `ask_orchestrator`, against the "understood" criteria | Per example, per candidate |
| Accent | 1–5, how natural the spoken Hebrew sounds | Per example, per candidate |
| Latency, primary | End of my speech → first audio of the answer that contains the stub's result; p50 and p95. **Decides the winner** | Per candidate, over all turns |
| Latency, secondary | End of my speech → first audio byte of any kind (fillers included); p50 and p95. Logged only; decides nothing | Per candidate, over all turns |
| Cost per minute | The voice layer only, from logged usage, including silence (example 8) | Per candidate |
| Pipeline LLM cost per minute | Logged in its own column and not added to the pipeline's cost, since GPT-Live-1's backend isn't counted either | Pipeline only |

## "Clear winner" (defined before any run)

1. **Gate:** comprehension ≥ 4 on all 8 examples.
2. Among candidates that pass the gate, the **lowest primary p50 latency** wins.
3. Cost (voice layer only) is a **tie-breaker only**.
4. If no candidate passes the gate, or the end of day 3 arrives first: the **pipeline** (the
   fallback in the phase file).

## Conversation script

Fixed wording, spoken the same way to every candidate. "Understood" means the request text
logged by `ask_orchestrator` captures every listed fact.

| # | Say (exact) | Understood = | Tests |
|---|---|---|---|
| 1 | "מה יש לי מחר?" | Intent: agenda; day: tomorrow | Baseline |
| 2 | "תזיז את הפגישה עם דני לחמישי בשלוש וחצי" | Intent: move a meeting; person: Dani; day: Thursday; time: 15:30 | Names, days, times |
| 3 | "תענה לו שאני מאשר ליום ראשון" | Intent: reply to an email; content: I approve; day: Sunday | Reply intent |
| 4 | "מה סיכמנו עם בעל הדירה על החוזה?" | Intent: search mail; person: the landlord; topic: the contract | Mail search |
| 5 | "יש לי משהו ב־Zoom אחרי הצהריים?" | Intent: agenda; "Zoom" recognized; time: this afternoon | Hebrew mixed with English |
| 6 | "תקבע לי פגישה ב־14 באוקטובר ב־9:15" | Intent: schedule a meeting; date: October 14; time: 09:15 | Dates and numbers |
| 7 | Start "מה יש לי מחר?", then interrupt mid-answer with "רגע, בעצם מה יש לי ביום חמישי?" | Stops speaking; the new request (agenda, Thursday) reaches the tool, not the old one | Interruption |
| 8 | Examples 1, 5 and 6 in order, with ~30 s of silence before each, to reach ≥ 3 min | Each part understood as above | Cost per minute with silence |

## Results

Filled in on day 3.

| Candidate | Comprehension (min / mean) | Accent (mean) | Passes gate | Primary p50 | Primary p95 | Secondary p50 | Secondary p95 | Cost/min (voice layer) | Pipeline LLM cost/min | Notes |
|---|---|---|---|---|---|---|---|---|---|---|
| GPT-Live-1 | | | | | | | | | n/a | |
| Gemini 3.8 Live | | | | | | | | | n/a | |
| Pipeline (ElevenLabs) | | | | | | | | | | |
| gpt-realtime-2.1 (optional) | | | | | | | | | n/a | |

**Decision:** _pending_ → ADR-0002.
