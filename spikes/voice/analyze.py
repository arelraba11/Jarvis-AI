"""Latency and cost per run, computed afterwards from audio.wav and events.jsonl.

    uv run python analyze.py runs/<run dir> [more run dirs...]

Prints one markdown row per run, in the shape of the README's results table (comprehension,
accent and the gate are scored by hand). Per run it also writes turns.md (per-turn latencies) and
requests.txt (the Hebrew request texts, for scoring comprehension) into the run dir.
"""

import argparse
import json
import math
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import yaml
from audio import SPEECH_THRESHOLD_DB

HERE = Path(__file__).parent
FRAME_S = 0.02
MERGE_GAP_S = 0.2  # voiced frames closer than this belong to one speech segment
MIN_SEGMENT_S = 0.1  # shorter segments are clicks or breaths, not speech

HEADER = (
    "| Run | Example | Candidate | Comprehension (min / mean) | Accent (mean) | Passes gate "
    "| Primary p50 | Primary p95 | Secondary p50 | Secondary p95 | Cost/min (voice layer) "
    "| Pipeline LLM cost/min | Notes |"
)


@dataclass
class Turn:
    end_of_speech: float
    secondary: float | None
    primary: float | None
    requests: list[dict[str, Any]]  # this turn's tool_call events; the first one is scored

    def duplicates(self) -> int:
        """Calls repeating a request already made in this turn (seen: Gemini re-asking)."""
        texts = [call["request"] for call in self.requests]
        return len(texts) - len(set(texts))


def load_events(run_dir: Path) -> list[dict[str, Any]]:
    lines = (run_dir / "events.jsonl").read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line]


def speech_segments(
    run_dir: Path, mic_start_t: float, threshold_db: float
) -> list[tuple[float, float]]:
    """(start, end) of each stretch of my speech, in session seconds, from the mic channel."""
    with wave.open(str(run_dir / "audio.wav")) as w:
        rate = w.getframerate()
        mic = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)[0::2]
    n = int(rate * FRAME_S)
    frames = mic[: len(mic) // n * n].reshape(-1, n).astype(np.float64) / 32768
    db = 20 * np.log10(np.sqrt((frames**2).mean(axis=1)) + 1e-10)
    segments: list[list[float]] = []
    for i in np.flatnonzero(db > threshold_db):
        start, end = mic_start_t + i * FRAME_S, mic_start_t + (i + 1) * FRAME_S
        if segments and start - segments[-1][1] < MERGE_GAP_S:
            segments[-1][1] = end
        else:
            segments.append([start, end])
    return [(s, e) for s, e in segments if e - s >= MIN_SEGMENT_S]


def find_turns(events: list[dict[str, Any]], segments: list[tuple[float, float]]) -> list[Turn]:
    """A turn = a speech segment the model answered before I spoke again.

    End of speech is the last voiced mic frame before the model responds. A pause with no
    response in it isn't a turn end, so it simply folds into the next segment's turn.
    """
    times = {
        kind: [e["t"] for e in events if e["kind"] == kind]
        for kind in ("playback_start", "tool_response_sent", "tool_answer_heard")
    }

    def first(kind: str, after: float, before: float) -> float | None:
        return next((t for t in times[kind] if after < t < before), None)

    turns = []
    for i, (_, end) in enumerate(segments):
        next_start = segments[i + 1][0] if i + 1 < len(segments) else math.inf
        heard = first("playback_start", end, next_start)
        if heard is None:
            continue
        tool_sent = first("tool_response_sent", end, next_start)
        answer = first("tool_answer_heard", tool_sent, next_start) if tool_sent else None
        calls = [e for e in events if e["kind"] == "tool_call" and end < e["t"] < next_start]
        turns.append(Turn(end, heard - end, answer - end if answer else None, calls))
    return turns


def percentile(values: list[float], p: float) -> float | None:
    """Nearest rank: with few turns, p95 is simply the worst one."""
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(math.ceil(p / 100 * len(ordered)) - 1, 0)]


def cost(events: list[dict[str, Any]], prices: dict[str, Any]) -> float:
    """Tokens x price, per modality. Each usage message is priced on its own and summed.

    Gemini sends one usage message per model turn, not a running total: response tokens go up
    and down (104436: 82, 50, 101, 45; 105418: 63, 28, 183, 210, 130, 28, 28). Each turn's prompt
    holds the whole session context so far (105418 prompt audio: 248 -> 1067 tokens), and Google
    bills exactly that: "The API charges you per turn for all tokens present in the session
    context window" (https://ai.google.dev/gemini-api/docs/live-api/best-practices, 2026-09-29).
    So summing per-turn usage is the documented billing. Not checked against an actual invoice.

    Thinking tokens are billed as output text. Some tokens are in a total but not in its
    per-modality breakdown (seen: the 28 output tokens of a tool call; a prompt remainder growing
    from 55 tokens); their modality isn't reported, so they are priced as text.
    """
    total = 0.0
    for e in events:
        if e["kind"] != "usage":
            continue
        usage = e["usage"]
        for direction, total_key, details_key in (
            ("input_per_1m", "prompt_token_count", "prompt_tokens_details"),
            ("output_per_1m", "response_token_count", "response_tokens_details"),
        ):
            details = usage.get(details_key, [])
            for item in details:
                modality = item.get("modality", "TEXT").lower()
                total += item.get("token_count", 0) * prices[direction][modality] / 1e6
            unbroken = usage.get(total_key, 0) - sum(i.get("token_count", 0) for i in details)
            total += max(unbroken, 0) * prices[direction]["text"] / 1e6
        total += usage.get("thoughts_token_count", 0) * prices["output_per_1m"]["text"] / 1e6
    return total


def fmt(seconds: float | None) -> str:
    return "—" if seconds is None else f"{seconds * 1000:.0f} ms"


def analyze(run_dir: Path, threshold_db: float, all_prices: dict[str, Any]) -> str:
    events = load_events(run_dir)
    start = next(e for e in events if e["kind"] == "session_start")
    end = next((e for e in events if e["kind"] == "session_end"), events[-1])
    mic_start_t = end.get("mic_start_t") or 0.0
    duration_min = (end["t"] - next(e["t"] for e in events if e["kind"] == "connected")) / 60

    turns = find_turns(events, speech_segments(run_dir, mic_start_t, threshold_db))
    primary = [t.primary for t in turns if t.primary is not None]
    secondary = [t.secondary for t in turns if t.secondary is not None]
    run_cost = cost(events, all_prices[start["candidate"]])
    interruptions = sum(e["kind"] == "interrupted" for e in events)
    tool_calls = [e for e in events if e["kind"] == "tool_call"]

    (run_dir / "turns.md").write_text(
        "| Turn | End of speech (s) | Secondary | Primary |\n|---|---|---|---|\n"
        + "".join(
            f"| {i} | {t.end_of_speech:.2f} | {fmt(t.secondary)} | {fmt(t.primary)} |\n"
            for i, t in enumerate(turns, 1)
        ),
        encoding="utf-8",
    )
    # Comprehension is scored on the first request of each turn; later ones are marked.
    in_turns = {
        id(call): (n, call is turn.requests[0])
        for n, turn in enumerate(turns, 1)
        for call in turn.requests
    }
    lines = []
    for call in tool_calls:
        n, first = in_turns.get(id(call), (None, False))
        label = "no turn" if n is None else f"turn {n} " + ("SCORED" if first else "extra")
        lines.append(f"{call['t']:.2f}s\t{label}\t{call['request']}\n")
    (run_dir / "requests.txt").write_text("".join(lines), encoding="utf-8")
    duplicates = sum(turn.duplicates() for turn in turns)

    notes = (
        f"{len(turns)} turns, {len(tool_calls)} tool calls ({duplicates} duplicate), "
        f"{interruptions} interrupted, "
        f"{duration_min:.1f} min, ${run_cost:.4f} total"
    )
    cost_per_min = f"${run_cost / duration_min:.4f}" if duration_min > 0 else "—"
    cells = [
        run_dir.name,
        str(start["example"]),
        start["model"],
        "",
        "",
        "",
        fmt(percentile(primary, 50)),
        fmt(percentile(primary, 95)),
        fmt(percentile(secondary, 50)),
        fmt(percentile(secondary, 95)),
        cost_per_min,
        "n/a",
        notes,
    ]
    return "| " + " | ".join(cells) + " |"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("runs", nargs="+", type=Path)
    parser.add_argument(
        "--threshold",
        type=float,
        default=SPEECH_THRESHOLD_DB,
        help="mic energy in dBFS above which a 20 ms frame counts as speech",
    )
    args = parser.parse_args()
    prices = yaml.safe_load((HERE / "prices.yaml").read_text(encoding="utf-8"))
    print(HEADER)
    print("|" + "---|" * HEADER.count(" | ") + "---|")
    for run_dir in args.runs:
        print(analyze(run_dir, args.threshold, prices))


if __name__ == "__main__":
    main()
