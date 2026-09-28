# Phase 1 — Hebrew voice spike

**Goal:** choose between a realtime speech-to-speech model and a transcription→LLM→speech pipeline
([voice](../systems/voice.md)), based on real Hebrew conversations, latency and cost per minute.

**Timebox: 3 days.** If there's no clear winner by the end of day 3, choose the pipeline and move on.
The pipeline is the fallback because the voice design already describes it as cheaper and more
controllable. Its cost is the extra latency.

This is a throwaway spike, not product code. It is exempt from the tests and mypy rules;
its outputs are the results table and the ADR.

## Deliverables
- A minimal script that holds a spoken Hebrew conversation with each candidate (mic in, speaker out).
- A results table: candidate × comprehension / accent / latency / cost per minute.
- An ADR recording the chosen approach, which closes the open decision "voice approach"
  ([open decisions](../design.md#open-decisions)).

## Contracts introduced
None, because the code is thrown away. The spike informs the
[`VoiceProvider`](../systems/voice.md#contracts) contract in Phase 6.

## Tasks
1. **Candidates and scoring sheet** (day 1).
   - Candidates: 2–3 realtime models and one pipeline combination (transcription + LLM + speech).
   - Scores: 1–5 for comprehension and for accent.
   - Measurements: latency is the time from the end of my speech to the first audio byte; cost per
     minute is calculated from logged usage.
   - Define "clear winner" *before* any runs, so the results can't bias the definition.
   - Output: `spikes/voice/README.md`.
2. **Conversation script** (day 1). The fixed set of conversations (the acceptance examples below),
   used for every candidate so the comparison is fair.
3. **Harness + first realtime candidate** (day 1). Mic → model → speaker, logging latency and
   token/audio usage per turn. API keys are read from the Keychain, never from files.
   Check: one full conversation runs and is logged.
4. **Remaining realtime candidates** (day 2). Same harness, one adapter per candidate.
5. **Pipeline candidate** (day 2). Streaming transcription → LLM → streaming speech, through the same harness.
6. **Run and score** (day 3). Run the conversation script on every candidate, fill in the table
   and calculate cost per minute.
7. **ADR** (day 3). Write the decision with the table attached, or record that the timebox ran out
   and the fallback applied.

## Acceptance examples
Spoken, not typed. Each is scored on every candidate using the sheet from task 1.
1. "מה יש לי מחר?"
2. "תזיז את הפגישה עם דני לחמישי בשלוש וחצי" (names, days, times)
3. "תענה לו שאני מאשר ליום ראשון"
4. "מה סיכמנו עם בעל הדירה על החוזה?"
5. "יש לי משהו ב־Zoom אחרי הצהריים?" (Hebrew mixed with English words)
6. "תקבע לי פגישה ב־14 באוקטובר ב־9:15" (dates and numbers)
7. Interrupting Jarvis in the middle of an answer and changing the request
8. A 3-minute conversation with pauses, to measure cost per minute including silence

## Done criteria
- An approach is chosen: realtime model or pipeline, either on the results or by the timebox fallback.
- The results table covers comprehension, accent, latency and cost per minute for every candidate
  that was tested.
- An ADR exists, and the open decision in [design](../design.md#open-decisions) is updated.
- No more than 3 working days were spent.

## Risks and open questions
- **Hebrew quality** may be weak for every realtime model. Then the pipeline wins, and the
  latency cost needs a number.
- **Which candidates:** the specific models aren't chosen yet. They get picked in task 1,
  against current prices.
- **Where the spike lives** (open question): `spikes/voice/`, excluded from mypy and CI, or
  outside the repo? Recommendation: `spikes/` in the repo, so the ADR can link to the code behind
  the numbers ([repo layout](../architecture.md#repo-layout)).

## ADRs to write
- ADR-0001 — Src layout (backfill of the Phase 0 decision: packages live under `src/jarvis/`).
- ADR-0002 — Voice approach: realtime vs pipeline, with the results table.
