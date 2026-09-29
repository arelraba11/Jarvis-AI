"""LLM contracts: what code sends to a provider and gets back (docs/systems/llm.md#contracts).

A leaf module: it imports nothing from jarvis. config imports Role from it and the router imports
config, so any jarvis import here creates a cycle.

Provider-neutral: each provider maps these to and from its own API. Code asks for a `Role`, never a
model; `ModelRouter` (task 3) resolves the role to an `LLMProvider`.
"""

from enum import StrEnum
from typing import Annotated, Literal, Protocol, Self

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator


class _Contract(BaseModel):
    # Same rules as config: no silent coercion, no unknown fields, read-only once built.
    # frozen matters here: history must not be edited in place (ADR-0003, append-only).
    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)


class Role(StrEnum):
    PLANNER = "planner"
    WRITER = "writer"
    CLASSIFIER = "classifier"
    EMBEDDINGS = "embeddings"
    MEMORY = "memory"


# A provider's own block, exactly as its API returned it. Provider-opaque: core never reads it;
# only the provider that produced it does, to send the block back unchanged (ADR-0003).
RawBlock = dict[str, JsonValue]


class TextBlock(_Contract):
    type: Literal["text"] = "text"
    text: str
    raw: RawBlock | None = None  # set on assistant text a provider returned


class ThinkingBlock(_Contract):
    """A thinking block exactly as the provider returned it, passed back unchanged.

    `raw` is opaque: only the provider that produced it reads it (ADR-0003).
    """

    type: Literal["thinking"] = "thinking"
    raw: RawBlock


class ToolCall(_Contract):
    type: Literal["tool_call"] = "tool_call"
    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    arguments: dict[str, JsonValue]
    raw: RawBlock | None = None  # set on a tool call a provider returned


class OpaqueBlock(_Contract):
    """An assistant block of a type we don't model, carried through in order and sent back
    unchanged by the provider that produced it. Core ignores it; it is never dropped."""

    type: Literal["opaque"] = "opaque"
    raw: RawBlock


class ToolResult(_Contract):
    type: Literal["tool_result"] = "tool_result"
    tool_call_id: str = Field(min_length=1)
    content: str
    is_error: bool = False


ContentBlock = Annotated[
    TextBlock | ThinkingBlock | ToolCall | ToolResult | OpaqueBlock, Field(discriminator="type")
]


# Only the model produces thinking and tool calls; only the user side returns tool results.
_ALLOWED_BLOCKS: dict[str, tuple[type[BaseModel], ...]] = {
    "user": (TextBlock, ToolResult),
    "assistant": (TextBlock, ThinkingBlock, ToolCall, OpaqueBlock),
}


class Message(_Contract):
    role: Literal["user", "assistant"]
    content: tuple[ContentBlock, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _blocks_match_role(self) -> Self:
        for block in self.content:
            if not isinstance(block, _ALLOWED_BLOCKS[self.role]):
                raise ValueError(f"a {self.role} message cannot carry a {block.type} block")
            # Checks only that raw is set, never what it holds (raw is provider-opaque). On a user
            # turn it could carry content the history checks never see.
            if self.role == "user" and isinstance(block, TextBlock) and block.raw is not None:
                raise ValueError("only assistant blocks carry a raw block")
        return self


class ToolDefinition(_Contract):
    """What a provider needs to offer a tool to the model. The permission level is not here: it is
    enforced by core, never by the model (docs/systems/permissions.md)."""

    name: str = Field(min_length=1)
    description: str
    input_schema: dict[str, JsonValue]


class LLMRequest(_Contract):
    system: str
    messages: tuple[Message, ...] = Field(min_length=1)
    tools: tuple[ToolDefinition, ...] = ()

    @model_validator(mode="after")
    def _valid_history(self) -> Self:
        # Checked here so a loop bug fails in unit tests, not as a 400 from the API (llm.md).
        if self.messages[0].role != "user":
            raise ValueError("the first message must be from the user")
        # Our rule, not the APIs': the loop never sends a request that ends on an assistant turn.
        if self.messages[-1].role != "user":
            raise ValueError("the last message must be from the user")
        # Anthropic and OpenAI both require every tool call to be answered in the very next
        # message, and every tool result to answer a call from the message right before it.
        for i, message in enumerate(self.messages):
            previous = self.messages[i - 1].content if i > 0 else ()
            calls = {b.id for b in previous if isinstance(b, ToolCall)}
            for block in message.content:
                if isinstance(block, ToolResult) and block.tool_call_id not in calls:
                    raise ValueError(
                        f"messages[{i}]: tool result {block.tool_call_id!r} matches no tool call "
                        "in the previous message"
                    )
            # Anthropic requires tool results first in the content array, any text after them.
            kinds = [isinstance(b, ToolResult) for b in message.content]
            if kinds != sorted(kinds, reverse=True):
                raise ValueError(f"messages[{i}]: tool results must come before any other block")
            answered = {b.tool_call_id for b in message.content if isinstance(b, ToolResult)}
            if unanswered := sorted(calls - answered):
                raise ValueError(
                    f"messages[{i - 1}]: tool call {unanswered[0]!r} has no result in the next "
                    "message"
                )
        return self


class Usage(_Contract):
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    cache_read_tokens: int = Field(default=0, ge=0)
    cache_write_tokens: int = Field(default=0, ge=0)


StopReason = Literal["end_turn", "tool_use", "max_tokens", "refusal"]


# Provider-neutral effort levels. Each provider maps them to its own API, and its factory rejects
# a level it can't honor when the router is built.
Effort = Literal["low", "medium", "high", "xhigh", "max"]


class LLMResponse(_Contract):
    # None exactly on a refusal: a refusal can come before any output, and partial output before
    # a refusal is discarded, so nothing of it can enter the history.
    message: Message | None
    stop_reason: StopReason
    usage: Usage
    model: str  # the model that answered; per-model prices turn `usage` into cost

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        if self.message is None:
            if self.stop_reason != "refusal":
                raise ValueError(f"stop_reason {self.stop_reason} needs a message")
            return self
        if self.stop_reason == "refusal":
            raise ValueError("a refusal carries no message")
        if self.message.role != "assistant":
            raise ValueError("the response message must be from the assistant")
        if self.stop_reason == "tool_use" and not any(
            isinstance(block, ToolCall) for block in self.message.content
        ):
            raise ValueError("stop_reason is tool_use but the message has no tool call")
        return self


class LLMError(Exception):
    """A provider call failed. The loop catches this without knowing which provider raised it.
    Messages name the provider and never contain a secret."""


class PrefixMismatchError(LLMError):
    """The history before a kept thinking block changed, or a thinking block was removed from the
    middle of the history (ADR-0003). The real provider raises it on the API's 400; `FakeProvider`
    raises it too, so a history bug fails in unit tests."""


class LLMAuthError(LLMError):
    """The provider rejected the credentials (invalid, revoked, or not allowed)."""


class LLMRateLimitError(LLMError):
    """Rate limited, still after the client's own retries."""


class LLMUnavailableError(LLMError):
    """Timeout, network failure, overload or server error, still after the client's retries."""


class LLMRequestError(LLMError):
    """The provider rejected the request itself (a bug on our side, or a limit); retrying the same
    request fails the same way."""


class LLMResponseError(LLMError):
    """The provider answered with something we can't map: a stop reason we don't handle, or a
    response that breaks our contracts. Never guessed at. `usage` is set when the call's token
    usage is known, so a failed but billed call can still be costed."""

    def __init__(self, message: str, usage: Usage | None = None) -> None:
        super().__init__(message)
        self.usage = usage


class LLMProvider(Protocol):
    async def complete(self, request: LLMRequest) -> LLMResponse: ...
