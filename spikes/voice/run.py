"""Hold one spoken session with a candidate and record everything.

    uv run python run.py gemini 1 --input macbook --output airpod    # Ctrl+C to end the session
    uv run python run.py gemini 8 --max-seconds 240

Writes runs/<time>_<candidate>_ex<N>/: audio.wav (mic, model) and events.jsonl.
Hebrew goes only to those files: the terminal shows ASCII status lines.
"""

import argparse
import asyncio
import contextlib
import importlib
import json
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from adapters.base import (
    MIC_RATE,
    Adapter,
    AudioOut,
    Interrupted,
    ProviderOther,
    ToolCall,
    ToolCallCancelled,
    TranscriptIn,
    TranscriptOut,
    TurnComplete,
    Usage,
)
from audio import SPEECH_THRESHOLD_DB, Mic, Speaker, device_name, find_device, write_wav
from keys import get_key
from stub import TOOL, StubOrchestrator

HERE = Path(__file__).parent


class EventLog:
    """JSONL, one event per line; t = seconds since the session started (monotonic clock)."""

    def __init__(self, path: Path, t0: float) -> None:
        self.file = path.open("w", encoding="utf-8")
        self.t0 = t0

    def write(self, kind: str, at: float | None = None, **fields: Any) -> None:
        t = (time.monotonic() if at is None else at) - self.t0
        line = {"t": round(t, 4), "kind": kind, **fields}
        self.file.write(json.dumps(line, ensure_ascii=False) + "\n")
        self.file.flush()


METER = sys.stdout.isatty()  # the meter redraws one line, so only on a real terminal
METER_FLOOR_DB, METER_WIDTH = -60.0, 40


def say(status: str) -> None:
    clear = "\r\033[K" if METER else ""  # wipe the meter line, print, let the meter redraw below
    print(f"{clear}[{time.strftime('%H:%M:%S')}] {status}", flush=True)


def meter_line(level_db: float) -> str:
    """e.g. `mic [#############|......      ] -35 dBFS`; `|` marks the speech threshold."""

    def column(db: float) -> int:
        fraction = (db - METER_FLOOR_DB) / -METER_FLOOR_DB
        return round(min(max(fraction, 0.0), 1.0) * METER_WIDTH)

    bar = ["#" if i < column(level_db) else " " for i in range(METER_WIDTH)]
    bar[min(column(SPEECH_THRESHOLD_DB), METER_WIDTH - 1)] = "|"
    return f"mic [{''.join(bar)}] {max(level_db, METER_FLOOR_DB):4.0f} dBFS"


async def run(
    candidate: str,
    example: int,
    max_seconds: float | None,
    input_name: str | None,
    output_name: str | None,
) -> Path:
    module = importlib.import_module(f"adapters.{candidate}")
    adapter: Adapter = module.Adapter()
    api_key = get_key(module.KEY_NAME)
    system_prompt = (HERE / "system_prompt.txt").read_text(encoding="utf-8")
    stub = StubOrchestrator(example)

    run_dir = HERE / "runs" / f"{datetime.now():%Y%m%d-%H%M%S}_{candidate}_ex{example}"
    run_dir.mkdir(parents=True)
    t0 = time.monotonic()
    log = EventLog(run_dir / "events.jsonl", t0)
    loop = asyncio.get_running_loop()
    mic_queue: asyncio.Queue[bytes] = asyncio.Queue()

    def on_mic(pcm: bytes, captured: float) -> None:
        loop.call_soon_threadsafe(mic_queue.put_nowait, pcm)

    def on_playback_start(play_time: float) -> None:
        loop.call_soon_threadsafe(lambda: log.write("playback_start", at=play_time))

    def on_tool_answer_heard(play_time: float) -> None:
        loop.call_soon_threadsafe(lambda: log.write("tool_answer_heard", at=play_time))

    mic = Mic(on_mic, find_device(input_name, "input"))
    speaker = Speaker(
        adapter.output_rate,
        on_playback_start,
        on_tool_answer_heard,
        find_device(output_name, "output"),
    )
    log.write(
        "session_start",
        candidate=candidate,
        example=example,
        model=adapter.model,
        mic_rate=MIC_RATE,
        output_rate=adapter.output_rate,
        input_device=device_name(mic.stream),
        output_device=device_name(speaker.stream),
    )

    async def pump_mic() -> None:
        while True:
            await adapter.send_audio(await mic_queue.get())

    async def handle_events() -> None:
        warned_rate = False
        async for event in adapter.events():
            match event:
                case AudioOut(pcm, rate):
                    speaker.play(pcm)
                    log.write("audio_out", bytes=len(pcm), rate=rate)
                    if rate != speaker.rate and not warned_rate:
                        warned_rate = True
                        say(f"WARNING: model audio is {rate} Hz, speaker is {speaker.rate} Hz")
                case Interrupted():
                    dropped = speaker.clear()  # first, so playback stops at once
                    log.write("interrupted", dropped_bytes=dropped)
                    say("interrupted: playback cleared")
                case ToolCall(call_id, name, args):
                    request = str(args.get("request", ""))
                    log.write("tool_call", id=call_id, name=name, request=request, args=args)
                    say("tool_call")
                    result = stub.ask(request)
                    await adapter.send_tool_result(event, result)
                    speaker.mark_next()  # times the first audio that arrives after this
                    log.write("tool_response_sent", id=call_id, result=result)
                case TranscriptIn(text):
                    log.write("transcript_in", text=text)
                case TranscriptOut(text):
                    log.write("transcript_out", text=text)
                case Usage(raw):
                    log.write("usage", usage=raw)
                case TurnComplete():
                    log.write("turn_complete")
                    say("turn complete")
                case ToolCallCancelled(ids):
                    log.write("tool_call_cancelled", ids=ids)
                    say("tool_call_cancelled")
                case ProviderOther(raw):
                    log.write("provider_other", message=raw)

    async def show_meter() -> None:
        while True:
            await asyncio.sleep(0.2)
            sys.stdout.write("\r" + meter_line(mic.take_level()) + "\033[K")
            sys.stdout.flush()

    async def stop_after() -> None:
        # Parenthesized: `await a if c else b` would await only a, leaving b never awaited.
        await (asyncio.sleep(max_seconds) if max_seconds else asyncio.Event().wait())

    await adapter.connect(api_key, system_prompt, TOOL)
    log.write("connected")
    # The session ends when any task finishes, so every task here must run until stopped.
    jobs = [pump_mic(), handle_events(), stop_after()] + ([show_meter()] if METER else [])
    tasks = [asyncio.create_task(job) for job in jobs]
    try:
        with mic.stream, speaker.stream:
            say(f"input: {device_name(mic.stream)} | output: {device_name(speaker.stream)}")
            say(f"connected to {adapter.model}. Speak example {example} now; Ctrl+C to stop.")
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                if task.exception():
                    log.write("error", error=repr(task.exception()))
                    say(f"session ended with an error: {task.exception()!r}")
    finally:
        for task in tasks:
            task.cancel()
        log.write(
            "session_end",
            mic_start_t=None if mic.start_time is None else round(mic.start_time - t0, 4),
            tool_calls=stub.calls,
        )
        write_wav(run_dir / "audio.wav", mic, speaker)
        with contextlib.suppress(Exception):
            await asyncio.shield(adapter.close())
        log.file.close()
        say(f"saved {run_dir.relative_to(HERE)}")
    return run_dir


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("candidate", help="adapter module name in adapters/, e.g. gemini")
    parser.add_argument("example", type=int, choices=range(1, 9), help="conversation script #")
    parser.add_argument("--max-seconds", type=float, help="end the session after N seconds")
    parser.add_argument("--input", help="mic: part of the device name (default: system input)")
    parser.add_argument("--output", help="speaker: part of the name (default: system output)")
    args = parser.parse_args()
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(run(args.candidate, args.example, args.max_seconds, args.input, args.output))


if __name__ == "__main__":
    main()
