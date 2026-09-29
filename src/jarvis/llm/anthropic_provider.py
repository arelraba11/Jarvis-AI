"""The Anthropic provider: maps `LLMRequest` / `LLMResponse` to the Messages API (ADR-0003).

The official SDK is used only as a typed client for `messages.create`, in the beta namespace for
the preserved-thinking controls: no tool runner and no agent helpers, because the loop is ours.

A concrete provider: only `jarvis.composition` imports this module (docs/systems/llm.md).
"""

from collections.abc import Callable
from typing import Final, cast, get_args

import anthropic
from anthropic.types.beta import (
    BetaContentBlockParam,
    BetaMessage,
    BetaMessageParam,
    BetaTextBlockParam,
    BetaToolParam,
    BetaToolUseBlockParam,
)
from pydantic import JsonValue, TypeAdapter, ValidationError

from jarvis.core.config import RoleModelConfig
from jarvis.core.secret_store import SecretStore
from jarvis.llm.contracts import (
    ContentBlock,
    LLMAuthError,
    LLMError,
    LLMRateLimitError,
    LLMRequest,
    LLMRequestError,
    LLMResponse,
    LLMResponseError,
    LLMUnavailableError,
    Message,
    OpaqueBlock,
    PrefixMismatchError,
    RawBlock,
    StopReason,
    TextBlock,
    ThinkingBlock,
    ToolCall,
    ToolResult,
    Usage,
)

SECRET_NAME: Final = "anthropic"  # Keychain: service "jarvis", account "anthropic"
# Explicit, so ANTHROPIC_BASE_URL in the environment can't send the key to another host.
BASE_URL: Final = "https://api.anthropic.com"
# Needed to set thinking.block_binding on every request (ADR-0003).
BETAS: Final = ["thinking-binding-controls-2026-08-01"]

# Explicit instead of the SDK's hidden defaults (the values match them). A non-streaming call
# sends nothing until the answer is complete, so the read timeout must cover the longest answer
# max_tokens allows. The SDK's own estimate is 3600 s per 128,000 output tokens, so 600 s covers
# up to 21,333 tokens; the factory rejects a larger max_tokens (streaming would be needed).
TIMEOUT_S: Final = 600.0
CONNECT_TIMEOUT_S: Final = 5.0
MAX_NONSTREAMING_TOKENS: Final = int(TIMEOUT_S * 128_000 / 3600)
# The SDK retries connection errors, 408, 409, 429 and 5xx with backoff; errors are mapped after.
MAX_RETRIES: Final = 2

_STOP_REASONS: Final = frozenset(get_args(StopReason))
# Anthropic's docs: the prefix-check 400 is identified only by its message text. A tampered
# signature has the same leading clause without this sentence, and is a different error.
_PREFIX_MISMATCH: Final = "bound to a different conversation"
_RAW_BLOCKS: Final = TypeAdapter(list[RawBlock])
_ARGUMENTS: Final = TypeAdapter(dict[str, JsonValue])


def anthropic_factory(
    secrets: SecretStore, *, http_client: anthropic.DefaultAsyncHttpxClient | None = None
) -> Callable[[RoleModelConfig], "AnthropicProvider"]:
    """The `anthropic` factory for `ModelRouter`. `http_client` lets tests fake the network."""

    def build(config: RoleModelConfig) -> AnthropicProvider:
        # Every Effort level is an Anthropic effort level; max_tokens is the one value this
        # (non-streaming) provider can't always honor.
        if config.max_tokens > MAX_NONSTREAMING_TOKENS:
            raise ValueError(
                f"max_tokens {config.max_tokens} is above {MAX_NONSTREAMING_TOKENS}, the most a "
                f"non-streaming call can finish within its {TIMEOUT_S:.0f} s timeout"
            )
        client = anthropic.AsyncAnthropic(
            api_key=secrets.get(SECRET_NAME),
            base_url=BASE_URL,
            timeout=anthropic.Timeout(TIMEOUT_S, connect=CONNECT_TIMEOUT_S),
            max_retries=MAX_RETRIES,
            http_client=http_client,
        )
        return AnthropicProvider(client, config)

    return build


class AnthropicProvider:
    def __init__(self, client: anthropic.AsyncAnthropic, config: RoleModelConfig) -> None:
        self._client = client
        self._config = config

    def __repr__(self) -> str:
        # Never the client: it holds the API key.
        return f"AnthropicProvider(model={self._config.model!r})"

    async def complete(self, request: LLMRequest) -> LLMResponse:
        try:
            raw = await self._client.beta.messages.with_raw_response.create(
                model=self._config.model,
                max_tokens=self._config.max_tokens,
                output_config={"effort": self._config.effort},
                thinking={
                    "type": "adaptive",
                    # Never "drop_block": it would hide the bug that edited the history.
                    "block_binding": {"prefix_mismatch_behavior": "error"},
                },
                betas=BETAS,
                system=_system(request),
                tools=_tools(request),
                # Forced tool use (any / tool) is a 400 on Sonnet 5.5 (ADR-0003).
                tool_choice={"type": "auto"} if request.tools else anthropic.omit,
                messages=[_message(m) for m in request.messages],
            )
        except anthropic.APIError as e:
            error: LLMError = self._error(e)
        else:
            try:
                message: object = await raw.parse()
                body: object = raw.http_response.json()
            except ValueError:  # includes JSONDecodeError
                error = LLMResponseError("anthropic: the response body is not a JSON message")
            else:
                return self._response(message, body)
        # Raised outside the except block, so it holds no reference to the SDK's exception,
        # whose request carries the API key header.
        raise error

    def _response(self, message: object, body: object) -> LLMResponse:
        # The SDK does not validate a response, so a malformed one is checked here: every failure
        # must reach the loop as an LLMError.
        if not isinstance(message, BetaMessage) or not isinstance(body, dict):
            raise LLMResponseError("anthropic: the response body is not a JSON message")
        where = f"(model {message.model}, request {message.id})"
        try:
            usage = Usage(
                input_tokens=message.usage.input_tokens,
                output_tokens=message.usage.output_tokens,
                cache_read_tokens=message.usage.cache_read_input_tokens or 0,
                cache_write_tokens=message.usage.cache_creation_input_tokens or 0,
            )
        except (AttributeError, ValidationError) as e:  # no usage object, or bad counts
            raise LLMResponseError(f"anthropic: response without valid usage {where}") from e
        stop = message.stop_reason
        if stop not in _STOP_REASONS:
            # The call was billed: keep its usage for the cost log.
            raise LLMResponseError(f"anthropic: unsupported stop_reason {stop!r} {where}", usage)
        # The blocks exactly as the API sent them, to be sent back unchanged (preserved thinking).
        try:
            raw_blocks = _RAW_BLOCKS.validate_python(body.get("content"))
        except ValidationError as e:
            raise LLMResponseError(
                f"anthropic: response content is not a list of blocks {where}"
            ) from e
        try:
            blocks = [_block(raw) for raw in raw_blocks]
            # A refusal's partial output is discarded (Anthropic's docs); nothing enters history.
            content = (
                None
                if stop == "refusal" or not blocks
                else Message(role="assistant", content=tuple(blocks))
            )
            return LLMResponse(
                message=content,
                stop_reason=cast(StopReason, stop),
                usage=usage,
                model=message.model,
            )
        except ValidationError as e:
            problems = "; ".join(err["msg"] for err in e.errors())
            raise LLMResponseError(f"anthropic: invalid response {where}: {problems}") from e

    def _error(self, e: anthropic.APIError) -> LLMError:
        kind: type[LLMError]
        if isinstance(e, anthropic.APIStatusError):
            error_type, detail, request_id = _error_details(e)
            status = e.status_code
            if status == 400 and _PREFIX_MISMATCH in detail:
                kind = PrefixMismatchError
            elif status in (401, 403):
                kind = LLMAuthError
            elif status == 429:
                kind = LLMRateLimitError
            elif status == 408 or status >= 500:  # 529 is "overloaded"
                kind = LLMUnavailableError
            else:
                kind = LLMRequestError
            text = f"anthropic {status} {error_type}: {detail} (request {request_id})"
        elif isinstance(e, anthropic.APIConnectionError):  # includes APITimeoutError
            kind = LLMUnavailableError
            text = f"anthropic: {e.message} (after {MAX_RETRIES} retries)"
        else:  # the response did not match the SDK's schema
            kind = LLMResponseError
            text = f"anthropic: {e.message}"
        return kind(self._redact(text))

    def _redact(self, text: str) -> str:
        # Defense in depth: no API error should echo the key, but one that did would not leak.
        key = self._client.api_key
        return text.replace(key, "[redacted]") if key else text


def _system(request: LLMRequest) -> list[BetaTextBlockParam] | anthropic.Omit:
    # The API rejects an empty text block. The cache prefix is tools, then system, so this one
    # breakpoint caches both (docs: prompt caching).
    if not request.system:
        return anthropic.omit
    return [{"type": "text", "text": request.system, "cache_control": {"type": "ephemeral"}}]


def _tools(request: LLMRequest) -> list[BetaToolParam] | anthropic.Omit:
    if not request.tools:
        return anthropic.omit
    # cast: the SDK types input_schema as a TypedDict; ours is the same JSON schema as a dict.
    tools = [
        cast(
            BetaToolParam,
            {"name": t.name, "description": t.description, "input_schema": t.input_schema},
        )
        for t in request.tools
    ]
    if not request.system:  # no system block to carry the breakpoint: the last tool does
        tools[-1]["cache_control"] = {"type": "ephemeral"}
    return tools


def _message(message: Message) -> BetaMessageParam:
    return {"role": message.role, "content": [_block_param(b) for b in message.content]}


def _block_param(block: ContentBlock) -> BetaContentBlockParam:
    match block:
        case ThinkingBlock(raw=raw) | OpaqueBlock(raw=raw):
            # cast: the API's own block, sent back exactly as it returned it.
            return cast(BetaContentBlockParam, raw)
        case TextBlock(text=text, raw=raw):
            text_block: BetaTextBlockParam = {"type": "text", "text": text}
            return _raw_if_unchanged(raw, text_block)
        case ToolCall(id=call_id, name=name, arguments=arguments, raw=raw):
            tool_use: BetaToolUseBlockParam = {
                "type": "tool_use",
                "id": call_id,
                "name": name,
                "input": dict(arguments),  # a copy typed as the SDK's dict[str, object]
            }
            return _raw_if_unchanged(raw, tool_use)
        case ToolResult(tool_call_id=call_id, content=content, is_error=is_error):
            return {
                "type": "tool_result",
                "tool_use_id": call_id,
                "content": content,
                "is_error": is_error,
            }
    raise AssertionError(f"unhandled content block {type(block).__name__}")  # pragma: no cover


def _raw_if_unchanged(
    raw: RawBlock | None, block: BetaTextBlockParam | BetaToolUseBlockParam
) -> BetaContentBlockParam:
    """The raw block while it still agrees with the validated fields, else the fields.

    What LLMRequest validated is what gets sent: a block edited after the API returned it goes out
    as edited, so the API (like FakeProvider) sees the edit, never a stale raw block.
    """
    if raw is not None and all(raw.get(k) == v for k, v in block.items()):
        # cast: the API's own block, with fields we don't model, sent back as it returned it.
        return cast(BetaContentBlockParam, raw)
    return block


def _block(raw: RawBlock) -> ContentBlock:
    # Dispatch on the API's own type field: the SDK parses an unknown block type as a text block.
    match raw.get("type"):
        # redacted_thinking is signed and prefix-bound like thinking (preserved thinking docs).
        case "thinking" | "redacted_thinking":
            return ThinkingBlock(raw=raw)
        case "text":
            text = raw.get("text")
            if not isinstance(text, str):
                raise LLMResponseError(f"anthropic: text block without text: {raw!r}")
            return TextBlock(text=text, raw=raw)
        case "tool_use":
            call_id, name = raw.get("id"), raw.get("name")
            if not isinstance(call_id, str) or not isinstance(name, str):
                raise LLMResponseError(f"anthropic: tool_use block without id or name: {raw!r}")
            return ToolCall(
                id=call_id,
                name=name,
                arguments=_ARGUMENTS.validate_python(raw.get("input")),
                raw=raw,
            )
        case _:
            return OpaqueBlock(raw=raw)


def _error_details(e: anthropic.APIStatusError) -> tuple[str, str, str | None]:
    """(error type, message, request id) from the API's error body, falling back to the SDK's."""
    body = e.body if isinstance(e.body, dict) else {}
    error = body.get("error")
    error = error if isinstance(error, dict) else {}

    def text(mapping: dict[object, object], key: str) -> str | None:
        value = mapping.get(key)
        return value if isinstance(value, str) else None

    return (
        text(error, "type") or "error",
        text(error, "message") or e.message,
        e.request_id or text(body, "request_id"),
    )
