"""FakeProvider: an `LLMProvider` that returns scripted responses and enforces the API's
preserved-thinking prefix check (ADR-0003), so a history bug fails in unit tests, not against the
real API.

The rule it enforces, for every thinking block in a request:
- The system prompt, the tools and everything before the block (earlier messages, and earlier
  blocks of its own message) must be unchanged since the block was produced. Thinking blocks are
  not part of that prefix, so removing one does not change it.
- Thinking blocks may be removed from the start, from the end, or all of them. A gap in the middle
  fails: each block records the thinking blocks kept before it when it was produced, and the ones
  before it now must be that run or its tail. So does putting back a removed block: the blocks
  produced while it was gone never recorded it.
- Every other block (text, tool calls, results, `OpaqueBlock`) is part of the prefix.
"""

import json
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from jarvis.llm.contracts import (
    ContentBlock,
    LLMRequest,
    LLMResponse,
    Message,
    PrefixMismatchError,
    ThinkingBlock,
    ToolDefinition,
)

# Plain JSON data: comparable with ==, and a copy, so a later in-place edit of a message shows up.
_Snapshot = list[object]


@dataclass(frozen=True)
class _Produced:
    system: str
    tools: _Snapshot
    prefix: _Snapshot
    before: tuple[str, ...]  # the keys of the thinking blocks kept before it, in order


class FakeProvider:
    def __init__(self, responses: Iterable[LLMResponse]) -> None:
        self._script = list(responses)
        self._produced: dict[str, _Produced] = {}
        keys = [_key(b) for r in self._script if r.message for b in _thinking(r.message.content)]
        if len(keys) != len(set(keys)):
            raise AssertionError("scripted thinking blocks must be unique: give each its own text")

    async def complete(self, request: LLMRequest) -> LLMResponse:
        self._check_prefix(request)
        if not self._script:
            raise AssertionError("FakeProvider: no scripted responses left")
        response = self._script.pop(0)
        if response.message is not None:  # a refusal produces nothing to check later
            self._record(request, response.message)
        return response

    def _check_prefix(self, request: LLMRequest) -> None:
        kept: tuple[str, ...] = ()
        for m, message in enumerate(request.messages):
            for b, block in enumerate(message.content):
                if not isinstance(block, ThinkingBlock):
                    continue
                key = _key(block)
                produced = self._produced.get(key)
                if produced is None:
                    raise ValueError(
                        f"messages[{m}].content[{b}]: thinking block not produced by this "
                        "FakeProvider, or edited since"
                    )
                where = f"thinking block at messages[{m}].content[{b}]"
                # Removing blocks from the start leaves a tail of the recorded run.
                if kept != produced.before[len(produced.before) - len(kept) :]:
                    if set(kept) - set(produced.before):
                        raise PrefixMismatchError(
                            f"{where}: a thinking block removed before it was produced was put back"
                        )
                    raise PrefixMismatchError(f"{where}: the thinking block before it was removed")
                if request.system != produced.system:
                    raise PrefixMismatchError(f"{where}: the system prompt changed")
                if _tools(request.tools) != produced.tools:
                    raise PrefixMismatchError(f"{where}: the tools changed")
                if _prefix(request.messages[:m], message.content[:b]) != produced.prefix:
                    raise PrefixMismatchError(f"{where}: the history before it changed")
                kept += (key,)

    def _record(self, request: LLMRequest, reply: Message) -> None:
        before = tuple(_key(b) for m in request.messages for b in _thinking(m.content))
        tools = _tools(request.tools)
        for b, block in enumerate(reply.content):
            if isinstance(block, ThinkingBlock):
                self._produced[_key(block)] = _Produced(
                    system=request.system,
                    tools=tools,
                    prefix=_prefix(request.messages, reply.content[:b]),
                    before=before,
                )
                before += (_key(block),)


def _key(block: ThinkingBlock) -> str:
    return json.dumps(block.raw, sort_keys=True)


def _thinking(blocks: Sequence[ContentBlock]) -> list[ThinkingBlock]:
    return [b for b in blocks if isinstance(b, ThinkingBlock)]


def _tools(tools: Sequence[ToolDefinition]) -> _Snapshot:
    return [t.model_dump(mode="json") for t in tools]


def _prefix(messages: Sequence[Message], partial: Sequence[ContentBlock]) -> _Snapshot:
    """The history before a thinking block: whole earlier messages, then the blocks before it in
    its own (assistant) message. Thinking blocks are left out: they are not part of the prefix."""
    turns = [(m.role, m.content) for m in messages] + [("assistant", tuple(partial))]
    return [
        {
            "role": role,
            "content": [
                b.model_dump(mode="json") for b in blocks if not isinstance(b, ThinkingBlock)
            ],
        }
        for role, blocks in turns
    ]
