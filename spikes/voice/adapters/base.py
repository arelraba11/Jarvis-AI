"""The adapter contract: every candidate turns its provider's protocol into these events.

Adding a candidate = one new file adapters/<name>.py that defines a class named `Adapter`
implementing the protocol below. run.py loads it by name; nothing else changes.
"""

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any, Protocol

MIC_RATE = 16_000  # every candidate gets 16 kHz mono PCM16 from the mic


@dataclass
class AudioOut:
    pcm: bytes  # PCM16 mono
    rate: int  # Hz; the runner warns if it differs from the adapter's output_rate


@dataclass
class ToolCall:
    id: str
    name: str
    args: dict[str, Any]


@dataclass
class TranscriptIn:
    text: str


@dataclass
class TranscriptOut:
    text: str


@dataclass
class Usage:
    raw: dict[str, Any]  # the provider's usage payload, logged verbatim; analyze.py prices it


@dataclass
class Interrupted:
    """The user barged in: stop playback and drop everything queued."""


@dataclass
class TurnComplete:
    """The model finished its turn. Logged only."""


@dataclass
class ToolCallCancelled:
    """The provider withdrew tool calls it had made (e.g. the user barged in). Logged only."""

    ids: list[str]


@dataclass
class ProviderOther:
    """Any part of a provider message no other event covers, logged raw so nothing is lost."""

    raw: dict[str, Any]


Event = (
    AudioOut
    | ToolCall
    | TranscriptIn
    | TranscriptOut
    | Usage
    | Interrupted
    | TurnComplete
    | ToolCallCancelled
    | ProviderOther
)


class Adapter(Protocol):
    model: str
    output_rate: int  # Hz the speaker is opened at, before the first AudioOut arrives

    async def connect(self, api_key: str, system_prompt: str, tool: dict[str, Any]) -> None: ...

    async def send_audio(self, pcm16: bytes) -> None:
        """Mic audio: PCM16 mono at MIC_RATE."""

    async def send_tool_result(self, call: ToolCall, result: str) -> None: ...

    def events(self) -> AsyncIterator[Event]: ...

    async def close(self) -> None: ...
