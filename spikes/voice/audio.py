"""Mic in, speaker out, and the 2-channel recording, all stamped on one clock: time.monotonic().

sounddevice runs the callbacks on PortAudio's thread, so they only copy data and hand it over;
nothing here blocks.
"""

import threading
import time
import wave
from collections.abc import Callable
from pathlib import Path

import numpy as np
import sounddevice as sd
from adapters.base import MIC_RATE

BLOCK_MS = 20
# A 20 ms mic frame louder than this counts as speech: analyze.py's end-of-speech threshold,
# also marked on run.py's level meter so I can see whether my voice clears it.
SPEECH_THRESHOLD_DB = -40.0


def dbfs(samples: np.ndarray) -> float:
    """RMS level of int16 samples, in dB relative to full scale (0 = loudest possible)."""
    rms = np.sqrt(np.mean((samples.astype(np.float64) / 32768) ** 2))
    return float(20 * np.log10(rms + 1e-10))


def find_device(name_part: str | None, kind: str) -> int | None:
    """The one device whose name contains name_part (any case), or None for the system default.

    kind is "input" or "output". Exits with the list of devices if zero or several match.
    """
    if name_part is None:
        return None
    channels = f"max_{kind}_channels"
    devices = [(i, d["name"]) for i, d in enumerate(sd.query_devices()) if d[channels] > 0]
    matches = [(i, n) for i, n in devices if name_part.lower() in n.lower()]
    if len(matches) != 1:
        found = "no" if not matches else "several"
        names = "\n".join(f"  {n}" for _, n in devices)
        raise SystemExit(f"{found} {kind} devices match '{name_part}'. {kind.title()}s:\n{names}")
    return matches[0][0]


def device_name(stream: sd.InputStream | sd.OutputStream) -> str:
    """The name of the device a stream is open on, e.g. "MacBook Pro Microphone"."""
    return str(sd.query_devices(stream.device)["name"])


def _device_delay(reported: float, fallback: float) -> float:
    """PortAudio's per-buffer timing, or the stream's nominal latency when it reports nothing."""
    return reported if 0 < reported < 1 else fallback


class Mic:
    """16 kHz mono PCM16. Calls on_chunk(pcm, capture_time) from the audio thread."""

    def __init__(self, on_chunk: Callable[[bytes, float], None], device: int | None = None) -> None:
        self.on_chunk = on_chunk
        self.chunks: list[bytes] = []
        self.start_time: float | None = None  # monotonic capture time of the first sample
        self._peak_db = -100.0  # loudest block since the last take_level(), for the meter
        self.stream = sd.InputStream(
            device=device,
            samplerate=MIC_RATE,
            channels=1,
            dtype="int16",
            blocksize=MIC_RATE * BLOCK_MS // 1000,
            callback=self._callback,
        )

    def _callback(self, indata, frames, t, status) -> None:
        captured = time.monotonic() - _device_delay(
            t.currentTime - t.inputBufferAdcTime, self.stream.latency
        )
        if self.start_time is None:
            self.start_time = captured
        pcm = indata.tobytes()
        self.chunks.append(pcm)
        self._peak_db = max(self._peak_db, dbfs(indata))
        self.on_chunk(pcm, captured)

    def take_level(self) -> float:
        """Loudest block level (dBFS) since the previous call."""
        level, self._peak_db = self._peak_db, -100.0
        return level


class Speaker:
    """Plays PCM16 mono as it arrives. clear() drops everything queued, for barge-in.

    Reports when sound reaches the ear, which is what latency is measured to:
    - on_start(play_time) whenever sound starts after silence;
    - on_mark(play_time) when the first audio queued after mark_next() is heard. The runner marks
      right after sending a tool response, so an answer that follows a filler without a pause
      is still timed.
    """

    def __init__(
        self,
        rate: int,
        on_start: Callable[[float], None],
        on_mark: Callable[[float], None],
        device: int | None = None,
    ) -> None:
        self.rate = rate
        self.on_start = on_start
        self.on_mark = on_mark
        self.played: list[tuple[float, np.ndarray]] = []  # (play time, samples) for the recording
        self._buffer = bytearray()
        self._lock = threading.Lock()
        self._idle = True
        # Byte positions in the stream of audio: queued so far, played so far, and the mark.
        self._queued = 0
        self._consumed = 0
        self._mark_pending = False
        self._mark_at: int | None = None
        self.stream = sd.OutputStream(
            device=device, samplerate=rate, channels=1, dtype="int16", callback=self._callback
        )

    def play(self, pcm: bytes) -> None:
        with self._lock:
            if self._mark_pending:
                self._mark_pending, self._mark_at = False, self._queued
            self._buffer += pcm
            self._queued += len(pcm)

    def mark_next(self) -> None:
        with self._lock:
            self._mark_pending, self._mark_at = True, None

    def clear(self) -> int:
        """Drop queued audio at once; returns how many bytes were dropped."""
        with self._lock:
            dropped = len(self._buffer)
            self._buffer.clear()
            self._queued -= dropped
            if self._mark_at is not None and self._mark_at >= self._queued:
                self._mark_at = None  # the marked audio was dropped, never heard
            return dropped

    def _callback(self, outdata, frames, t, status) -> None:
        with self._lock:
            chunk = bytes(self._buffer[: frames * 2])
            del self._buffer[: frames * 2]
            start = self._consumed
            self._consumed += len(chunk)
            mark = self._mark_at
            if mark is not None and mark < self._consumed:
                self._mark_at = None
        samples = np.frombuffer(chunk, dtype=np.int16)
        outdata[:] = 0
        outdata[: len(samples), 0] = samples
        if len(samples):
            play_time = time.monotonic() + _device_delay(
                t.outputBufferDacTime - t.currentTime, self.stream.latency
            )
            self.played.append((play_time, samples))
            if self._idle:
                self.on_start(play_time)
            if mark is not None and mark < self._consumed:
                self.on_mark(play_time + (mark - start) / 2 / self.rate)
        self._idle = len(samples) < frames


def write_wav(path: Path, mic: Mic, speaker: Speaker) -> None:
    """ch0 = mic, ch1 = model output as heard, both at 16 kHz on the mic's sample clock.

    The output channel is resampled linearly: it is for listening back and eyeballing
    alignment, not for measurement (analyze.py takes play times from the event log).
    """
    mic_samples = np.frombuffer(b"".join(mic.chunks), dtype=np.int16)
    if mic.start_time is None:
        return
    out = np.zeros_like(mic_samples)
    for play_time, samples in speaker.played:
        start = round((play_time - mic.start_time) * MIC_RATE)
        n = round(len(samples) * MIC_RATE / speaker.rate)
        resampled = np.interp(
            np.linspace(0, len(samples) - 1, n), np.arange(len(samples)), samples
        ).astype(np.int16)
        lo, hi = max(start, 0), min(start + n, len(out))
        if lo < hi:
            out[lo:hi] = resampled[lo - start : hi - start]
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(MIC_RATE)
        w.writeframes(np.column_stack([mic_samples, out]).tobytes())
