# Voice spike: Hebrew realtime vs pipeline

Phase 1, tasks 1–3 ([phase file](../../docs/plan/phase-1-voice-spike.md)). Throwaway code: exempt
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

## Running the harness

`spikes/voice/` is its own uv project (own `pyproject.toml` and `uv.lock`), so the spike's
dependencies never touch the main project.

**Setup** (once):

```bash
cd spikes/voice
uv sync
uv run keyring set jarvis-spike gemini       # prompts for the key; it goes to the macOS Keychain
uv run keyring set jarvis-spike openai
uv run keyring set jarvis-spike elevenlabs
```

Keys are read only from the Keychain (service `jarvis-spike`), never from files or env.

**Microphone permission:** grant it to your terminal app in System Settings → Privacy & Security →
Microphone. Without it, sounddevice records silence with no error: the run looks normal but the
mic channel is all zeros (seen in a real run). The level meter `run.py` draws
(`mic [####|   ] -35 dBFS`, `|` = the speech threshold) shows this before you speak: if the bar
stays empty while you talk, the mic isn't reaching the harness.

**Measurement setup, fixed for every candidate: MacBook mic in, headphones out.**

- **Headphones are required.** With speakers the model hears itself and interrupts itself
  (see [Findings](#findings)), and end of speech is detected from mic energy, which assumes the
  mic hears only me.
- **Never the AirPods mic.** Using it switches Bluetooth to the call profile, which degrades both
  the input and the output audio. AirPods are fine as output only.
- Pick the devices with `--input` / `--output` (any part of the device name, any case); an unknown
  or ambiguous name exits with the list of devices. Both are printed at start and logged in
  `session_start` (`input_device`, `output_device`), so every run records its setup.
- **Model settings are fixed for scored runs.** Thinking affects both latency and cost (thinking
  tokens are billed as output text), so it's stated per candidate and never changed between runs:
  - Gemini 3.8 Live: **SDK default** (`thinking_config` not set). Thinking is on under this default:
    every turn logged so far had 40–140 thinking tokens (16 turns, runs of 2026-09-29).

**Run one example** (one fresh session per example; example 8 is one continuous session too):

```bash
uv run python run.py gemini 1 --input macbook --output airpod   # speak, wait for the answer, Ctrl+C
uv run python analyze.py runs/<run dir> [more run dirs...]
```

Each run writes `runs/<time>_<candidate>_ex<N>/` (gitignored: it holds my voice):

- `audio.wav`: 2 channels at 16 kHz on one clock, ch0 = mic, ch1 = model output as heard.
- `events.jsonl`: every event with `t` in seconds since session start (monotonic clock).
  Provider messages are logged in full: what the adapter doesn't map to an event is kept raw as
  `provider_other`, and cancelled tool calls as `tool_call_cancelled`. The log contains tool
  calls with the request text, tool responses sent, usage, transcripts, interruptions, and when
  the model's audio was actually heard (`playback_start`, `tool_answer_heard`).
- After `analyze.py`: `turns.md` (per-turn latencies) and `requests.txt` (the request texts, for
  scoring comprehension). Hebrew goes only to these files, since the terminal reverses RTL.

**Files:** `adapters/base.py` is the adapter contract (connect → send mic audio → event stream:
`audio_out`, `tool_call`, `transcript_in/out`, `usage`, `interrupted` → close). Adding a candidate
means one new file `adapters/<name>.py`; `run.py` loads it by name. `stub.py` holds
`ask_orchestrator` and the canned answers, `system_prompt.txt` the one system prompt, and
`prices.yaml` the prices; all shared by every candidate.

### How latency and cost are measured

Everything is recorded during the run and computed afterwards by `analyze.py`.

- **End of speech:** the last mic frame (20 ms) above an energy threshold (default −40 dBFS)
  before the model responds. A pause the model doesn't answer isn't a turn end.
- **Secondary latency:** end of speech → first output audio heard after it.
- **Primary latency:** end of speech → first output audio heard among the audio that arrived
  after the tool response was sent. "First audio after the tool response" approximates "the answer
  that contains the result": a filler still streaming at that moment would count too.
- "Heard" = the moment the audio device plays the sample (callback time plus output latency),
  so queueing in the harness is included the same way for every candidate.
- **Cost:** usage tokens × `prices.yaml`, per modality; **cost per minute** divides by the
  session's wall-clock length, silence included. Gemini reports usage once per model turn (observed:
  response counts go up and down, so they are not a running total), and each turn's prompt count
  includes the session context so far; summing bills that context once per turn. Not yet checked
  against an actual invoice.
- **Gemini 3.8 Live:** VAD and function-calling behaviour are left at SDK defaults. Per Google's
  docs (see Notes above) that makes the tool `NON_BLOCKING`; not yet observed in a run. No speech
  language code is set: Google's Live docs say native-audio models choose the language themselves
  and don't support setting one, so Hebrew is requested by the shared system prompt instead.
  Input transcription gets the hint `language_codes=["he-IL"]`, which **affects the log only**:
  the transcript is a side channel, and comprehension is scored on the tool request.

## Findings

Observations from runs, including exploratory (unscored) ones.

- **No echo cancellation → built-in speakers cause self-interruption.** The harness does no AEC, so
  with the MacBook mic and speakers the model hears its own output, and its VAD treats it as the
  user barging in. Exploratory run `20260929-105614_gemini_ex1` (MacBook mic + speakers): 5
  `interrupted` events in about 30 s. Muting the mic during playback would stop this but would
  also break barge-in, which example 7 tests. Hence headphones in the fixed setup. AEC is out of
  scope for the spike; it's an open question for the product
  ([voice](../../docs/systems/voice.md#open-questions)).
- **Voice models send context-dependent and duplicate tool requests** (input for Phase 6).
  Exploratory run `20260929-105418_gemini_ex1`: Gemini passed "what else besides that?" to
  `ask_orchestrator` as is, which means nothing without the conversation the orchestrator doesn't
  hear, and sent that same request twice, 0.65 s apart, with nothing from me in between. So
  `ask_orchestrator` needs self-contained requests, and the orchestrator
  must tolerate duplicates: harmless for reads, but an action (send, move a meeting) must not
  run twice. For scoring, comprehension uses the first request of each turn; `analyze.py` marks
  the rest in `requests.txt` and counts duplicates in Notes.
- **Gemini bills the full context every turn, so its cost per minute grows with session length
  and turn count.** Google: "The API charges you per turn for all tokens present in the session
  context window… Past tokens are re-processed and accounted for in each new turn"
  ([Live API best practices](https://ai.google.dev/gemini-api/docs/live-api/best-practices)). In
  exploratory run `20260929-105418_gemini_ex1`, input (audio and text) was billed 4.7x what billing each
  token once would cost, and input made up 64% of the total (about 2x the per-minute estimate in
  Candidates, which assumed audio is billed once). **Compare candidates' cost on example 8 only**:
  short examples understate Gemini's cost, and GPT-Live-1 bills by session duration, a different
  model. Phase 6 input: close sessions after silence (already planned in
  [voice](../../docs/systems/voice.md)), and evaluate context window compression, which per Google
  evicts older tokens so later turns aren't billed for the whole history (not tested).

## Results

Filled in on day 3.

| Candidate | Comprehension (min / mean) | Accent (mean) | Passes gate | Primary p50 | Primary p95 | Secondary p50 | Secondary p95 | Cost/min (voice layer) | Pipeline LLM cost/min | Notes |
|---|---|---|---|---|---|---|---|---|---|---|
| GPT-Live-1 | | | | | | | | | n/a | |
| Gemini 3.8 Live | | | | | | | | | n/a | |
| Pipeline (ElevenLabs) | | | | | | | | | | |
| gpt-realtime-2.1 (optional) | | | | | | | | | n/a | |

**Decision:** _pending_ → ADR-0002.
