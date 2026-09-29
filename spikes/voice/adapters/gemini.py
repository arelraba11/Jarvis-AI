"""Gemini 3.8 Live. VAD and function-calling behaviour are left at the SDK defaults.

No speech_config language code: per Google's Live docs, native-audio models pick the language
themselves and don't support setting one, so Hebrew is requested in the system prompt.
"""

import contextlib
import re
from collections.abc import AsyncIterator
from typing import Any

from google import genai
from google.genai import types

from adapters.base import (
    MIC_RATE,
    AudioOut,
    Event,
    Interrupted,
    ProviderOther,
    ToolCall,
    ToolCallCancelled,
    TranscriptIn,
    TranscriptOut,
    TurnComplete,
    Usage,
)

KEY_NAME = "gemini"

# What _translate maps to events; everything else in a message is logged as ProviderOther.
# model_turn is covered by AudioOut (its audio parts); other part kinds would be dropped here.
_MAPPED = {
    "server_content": {
        "model_turn",
        "interrupted",
        "input_transcription",
        "output_transcription",
        "turn_complete",
    },
    "tool_call": True,
    "tool_call_cancellation": True,
    "usage_metadata": True,
}


class Adapter:
    model = "gemini-3.8-live"
    output_rate = 24_000

    def __init__(self) -> None:
        self._stack = contextlib.AsyncExitStack()
        self._session: Any = None  # genai's AsyncSession; Any keeps the spike free of SDK internals

    async def connect(self, api_key: str, system_prompt: str, tool: dict[str, Any]) -> None:
        client = genai.Client(api_key=api_key)
        config = types.LiveConnectConfig(
            response_modalities=[types.Modality.AUDIO],
            system_instruction=system_prompt,
            tools=[types.Tool(function_declarations=[types.FunctionDeclaration(**tool)])],
            # The hint only shapes the input transcript, which is logged, never scored.
            input_audio_transcription=types.AudioTranscriptionConfig(language_codes=["he-IL"]),
            output_audio_transcription=types.AudioTranscriptionConfig(),
        )
        self._session = await self._stack.enter_async_context(
            client.aio.live.connect(model=self.model, config=config)
        )

    async def send_audio(self, pcm16: bytes) -> None:
        blob = types.Blob(data=pcm16, mime_type=f"audio/pcm;rate={MIC_RATE}")
        await self._session.send_realtime_input(audio=blob)

    async def send_tool_result(self, call: ToolCall, result: str) -> None:
        response = types.FunctionResponse(id=call.id, name=call.name, response={"result": result})
        await self._session.send_tool_response(function_responses=[response])

    async def events(self) -> AsyncIterator[Event]:
        # session.receive() stops after each model turn, so loop to keep the session going.
        while True:
            async for msg in self._session.receive():
                for event in self._translate(msg):
                    yield event

    def _translate(self, msg: types.LiveServerMessage) -> list[Event]:
        out: list[Event] = []
        content = msg.server_content
        if content:
            if content.interrupted:
                out.append(Interrupted())
            if content.input_transcription and content.input_transcription.text:
                out.append(TranscriptIn(content.input_transcription.text))
            if content.output_transcription and content.output_transcription.text:
                out.append(TranscriptOut(content.output_transcription.text))
            parts = content.model_turn.parts if content.model_turn else None
            for part in parts or []:
                blob = part.inline_data
                if blob and blob.data and (blob.mime_type or "").startswith("audio/"):
                    rate = re.search(r"rate=(\d+)", blob.mime_type or "")
                    hz = int(rate.group(1)) if rate else self.output_rate
                    out.append(AudioOut(blob.data, hz))
            if content.turn_complete:
                out.append(TurnComplete())
        if msg.tool_call:
            for fc in msg.tool_call.function_calls or []:
                out.append(ToolCall(id=fc.id or "", name=fc.name or "", args=dict(fc.args or {})))
        if msg.tool_call_cancellation:
            out.append(ToolCallCancelled(list(msg.tool_call_cancellation.ids or [])))
        if msg.usage_metadata:
            out.append(Usage(msg.usage_metadata.model_dump(mode="json", exclude_none=True)))
        rest = msg.model_dump(mode="json", exclude_none=True, exclude=_MAPPED)
        if rest.get("server_content") == {}:
            del rest["server_content"]
        if rest:
            out.append(ProviderOther(rest))
        return out

    async def close(self) -> None:
        await self._stack.aclose()
