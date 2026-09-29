"""AnthropicProvider: request and response mapping, errors and secrecy (Phase 2 task 5).

No network: the SDK talks to an httpx2 MockTransport that records each request and answers from a
script. The response fixtures in tests/fixtures/anthropic/ are hand-built from the shapes in
Anthropic's docs (Messages API, preserved thinking, stop reasons, errors), not recorded from the
live API. The live smoke tests (tests/test_anthropic_live.py) cover the real API.
"""

import asyncio
import json
import logging
import traceback
from pathlib import Path
from typing import Any

import httpx2
import pytest

from fakes.secrets import FakeSecretStore
from jarvis.core.config import RoleModelConfig
from jarvis.core.secret_store import SecretNotFoundError
from jarvis.llm.anthropic_provider import anthropic_factory
from jarvis.llm.contracts import (
    LLMAuthError,
    LLMError,
    LLMProvider,
    LLMRateLimitError,
    LLMRequest,
    LLMRequestError,
    LLMResponse,
    LLMResponseError,
    LLMUnavailableError,
    Message,
    OpaqueBlock,
    PrefixMismatchError,
    Role,
    TextBlock,
    ThinkingBlock,
    ToolCall,
    ToolDefinition,
    ToolResult,
    Usage,
)
from jarvis.llm.router import ModelRouter, ModelRouterError

FIXTURES = Path(__file__).parent / "fixtures" / "anthropic"
KEY = "sk-ant-api03-TEST-KEY-that-must-never-leak"
CONFIG = RoleModelConfig(provider="anthropic", model="claude-sonnet-5-5")
SYSTEM = "You are Jarvis."
TOOLS = (
    ToolDefinition(
        name="get_current_time",
        description="The current time in the user's timezone.",
        input_schema={"type": "object", "properties": {"timezone": {"type": "string"}}},
    ),
    ToolDefinition(
        name="resolve_date",
        description="Resolve a relative date.",
        input_schema={"type": "object", "properties": {"days": {"type": "integer"}}},
    ),
)


def fixture(name: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    return data


def ok(body: dict[str, Any]) -> httpx2.Response:
    return httpx2.Response(200, json=body)


def api_error(status: int, error_type: str, message: str) -> httpx2.Response:
    body = {"type": "error", "error": {"type": error_type, "message": message}, "request_id": "r1"}
    # retry-after-ms keeps the SDK's retries (of 429 and 5xx) fast in tests.
    return httpx2.Response(status, json=body, headers={"retry-after-ms": "1"})


class FakeApi:
    """Stands in for api.anthropic.com: records each request and answers from a script."""

    def __init__(self, *replies: httpx2.Response | Exception) -> None:
        self._replies = list(replies)
        self.requests: list[httpx2.Request] = []

    def handle(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        reply = self._replies.pop(0) if len(self._replies) > 1 else self._replies[0]
        if isinstance(reply, Exception):
            raise reply
        return reply

    def body(self, index: int = -1) -> dict[str, Any]:
        data: dict[str, Any] = json.loads(self.requests[index].content)
        return data


def build(
    api: FakeApi, config: RoleModelConfig = CONFIG, secrets: FakeSecretStore | None = None
) -> LLMProvider:
    factory = anthropic_factory(
        secrets or FakeSecretStore({"anthropic": KEY}),
        http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(api.handle)),
    )
    return factory(config)


def user(*blocks: TextBlock | ToolResult | str) -> Message:
    content = tuple(TextBlock(text=b) if isinstance(b, str) else b for b in blocks)
    return Message(role="user", content=content)


def request(
    *messages: Message, system: str = SYSTEM, tools: tuple[ToolDefinition, ...] = TOOLS
) -> LLMRequest:
    return LLMRequest(system=system, messages=messages, tools=tools)


def complete(provider: LLMProvider, req: LLMRequest) -> LLMResponse:
    return asyncio.run(provider.complete(req))


def said(response: LLMResponse) -> Message:
    assert response.message is not None
    return response.message


EPHEMERAL = {"type": "ephemeral"}


# --- Request mapping ------------------------------------------------------------------------


def test_sends_the_model_limits_and_thinking_settings_on_the_beta_endpoint() -> None:
    api = FakeApi(ok(fixture("thinking_text.json")))
    config = RoleModelConfig(
        provider="anthropic", model="claude-sonnet-5-5", max_tokens=4096, effort="low"
    )
    complete(build(api, config), request(user("שלום")))

    sent = api.requests[0]
    assert (sent.url.host, sent.url.path) == ("api.anthropic.com", "/v1/messages")
    assert sent.headers["anthropic-beta"] == "thinking-binding-controls-2026-08-01"
    body = api.body()
    assert body["model"] == "claude-sonnet-5-5"
    assert body["max_tokens"] == 4096
    assert body["output_config"] == {"effort": "low"}
    # Set explicitly, never "drop_block": an edited history must fail, not be hidden (ADR-0003).
    assert body["thinking"] == {
        "type": "adaptive",
        "block_binding": {"prefix_mismatch_behavior": "error"},
    }
    assert "stream" not in body or body["stream"] is False


def test_system_and_tools_form_the_cached_prefix() -> None:
    # The cache prefix is tools, then system; a breakpoint on the system block caches both.
    api = FakeApi(ok(fixture("thinking_text.json")))
    complete(build(api), request(user("q")))
    body = api.body()
    assert body["system"] == [{"type": "text", "text": SYSTEM, "cache_control": EPHEMERAL}]
    assert body["tools"] == [
        {"name": t.name, "description": t.description, "input_schema": t.input_schema}
        for t in TOOLS
    ]
    # Forced tool use (any / tool) is a 400 on this model (ADR-0003).
    assert body["tool_choice"] == {"type": "auto"}


def test_without_a_system_prompt_the_last_tool_carries_the_cache_breakpoint() -> None:
    # The API rejects an empty text block, so an empty system prompt is left out.
    api = FakeApi(ok(fixture("thinking_text.json")))
    complete(build(api), request(user("q"), system=""))
    body = api.body()
    assert "system" not in body
    assert "cache_control" not in body["tools"][0]
    assert body["tools"][1]["cache_control"] == EPHEMERAL


def test_a_request_without_tools_sends_no_tools_and_no_tool_choice() -> None:
    api = FakeApi(ok(fixture("thinking_text.json")))
    complete(build(api), request(user("q"), tools=()))
    body = api.body()
    assert "tools" not in body
    assert "tool_choice" not in body
    assert body["system"][0]["cache_control"] == EPHEMERAL


def test_maps_user_text_tool_calls_and_tool_results() -> None:
    api = FakeApi(ok(fixture("thinking_text.json")))
    messages = (
        user("מה השעה?"),
        Message(
            role="assistant",
            content=(
                TextBlock(text="בודק"),
                ToolCall(id="c1", name="get_current_time", arguments={"timezone": "UTC"}),
                ToolCall(id="c2", name="resolve_date", arguments={"days": 2}),
            ),
        ),
        user(
            ToolResult(tool_call_id="c1", content="10:42"),
            ToolResult(tool_call_id="c2", content="bad input", is_error=True),
            "ועוד משהו",
        ),
    )
    complete(build(api), request(*messages))
    assert api.body()["messages"] == [
        {"role": "user", "content": [{"type": "text", "text": "מה השעה?"}]},
        {
            "role": "assistant",
            "content": [
                {"type": "text", "text": "בודק"},
                {
                    "type": "tool_use",
                    "id": "c1",
                    "name": "get_current_time",
                    "input": {"timezone": "UTC"},
                },
                {"type": "tool_use", "id": "c2", "name": "resolve_date", "input": {"days": 2}},
            ],
        },
        {
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": "c1", "content": "10:42", "is_error": False},
                {
                    "type": "tool_result",
                    "tool_use_id": "c2",
                    "content": "bad input",
                    "is_error": True,
                },
                {"type": "text", "text": "ועוד משהו"},
            ],
        },
    ]


@pytest.mark.parametrize("name", ["thinking_text.json", "redacted_and_unmodeled_blocks.json"])
def test_an_assistant_turn_goes_back_exactly_as_the_api_returned_it(name: str) -> None:
    # Preserved thinking: every block, in order, with every field (even null ones) and the same
    # key order; a serializer that drops or reorders anything edits the prefix.
    returned = fixture(name)["content"]
    api = FakeApi(ok(fixture(name)), ok(fixture("thinking_text.json")))
    provider = build(api)
    first = said(complete(provider, request(user("q"))))
    complete(provider, request(user("q"), first, user("next")))
    sent = api.body(1)["messages"][1]
    assert sent["role"] == "assistant"
    assert json.dumps(sent["content"], ensure_ascii=False) == json.dumps(
        returned, ensure_ascii=False
    )


def test_a_tool_use_turn_goes_back_exactly_as_the_api_returned_it() -> None:
    # A null field we don't model: rebuilding the block from ToolCall's fields would drop it.
    body = fixture("tool_use.json")
    body["content"][2]["future_field"] = None
    returned = body["content"]
    api = FakeApi(ok(body), ok(fixture("thinking_text.json")))
    provider = build(api)
    first = said(complete(provider, request(user("מה השעה?"))))
    answer = user(ToolResult(tool_call_id="toolu_01A09q90qw90lq917835lq9", content="10:42"))
    complete(provider, request(user("מה השעה?"), first, answer))
    sent = api.body(1)["messages"][1]["content"]
    assert json.dumps(sent, ensure_ascii=False) == json.dumps(returned, ensure_ascii=False)


# --- Response mapping -----------------------------------------------------------------------


def test_maps_thinking_text_usage_and_model() -> None:
    body = fixture("thinking_text.json")
    response = complete(build(FakeApi(ok(body))), request(user("שלום")))
    assert response == LLMResponse(
        message=Message(
            role="assistant",
            content=(
                ThinkingBlock(raw=body["content"][0]),
                TextBlock(text="שלום! אני ג'רוויס.", raw=body["content"][1]),
            ),
        ),
        stop_reason="end_turn",
        usage=Usage(
            input_tokens=21, output_tokens=57, cache_read_tokens=1843, cache_write_tokens=0
        ),
        model="claude-sonnet-5-5",
    )


def test_maps_a_tool_call() -> None:
    body = fixture("tool_use.json")
    response = complete(build(FakeApi(ok(body))), request(user("מה השעה?")))
    assert response.stop_reason == "tool_use"
    assert said(response).content[2] == ToolCall(
        id="toolu_01A09q90qw90lq917835lq9",
        name="get_current_time",
        arguments={"timezone": "Asia/Jerusalem"},
        raw=body["content"][2],
    )
    assert response.usage == Usage(
        input_tokens=1864, output_tokens=88, cache_read_tokens=0, cache_write_tokens=1843
    )


def test_redacted_thinking_is_thinking_and_an_unmodeled_block_is_kept_in_order() -> None:
    # redacted_thinking is signed like thinking and bound the same way (preserved thinking), so
    # history trimming and FakeProvider must treat it as a thinking block.
    body = fixture("redacted_and_unmodeled_blocks.json")
    response = complete(build(FakeApi(ok(body))), request(user("q")))
    assert said(response).content == (
        ThinkingBlock(raw=body["content"][0]),
        ThinkingBlock(raw=body["content"][1]),
        OpaqueBlock(raw=body["content"][2]),
        TextBlock(text="סיימתי.", raw=body["content"][3]),
    )


def test_missing_cache_counts_are_zero() -> None:
    body = fixture("redacted_and_unmodeled_blocks.json")
    response = complete(build(FakeApi(ok(body))), request(user("q")))
    assert response.usage == Usage(input_tokens=30, output_tokens=12)


def test_a_refusal_maps_to_refusal_with_no_message() -> None:
    response = complete(build(FakeApi(ok(fixture("refusal.json")))), request(user("q")))
    assert response == LLMResponse(
        message=None,
        stop_reason="refusal",
        usage=Usage(input_tokens=25, output_tokens=0),
        model="claude-sonnet-5-5",
    )


def test_a_refusal_after_partial_output_drops_the_partial_output() -> None:
    # Anthropic's docs: discard partial output on a mid-stream refusal.
    body = fixture("refusal.json") | {"content": [{"type": "text", "text": "Sure, first"}]}
    response = complete(build(FakeApi(ok(body))), request(user("q")))
    assert (response.stop_reason, response.message) == ("refusal", None)


def test_an_unknown_stop_reason_is_an_error_that_names_it() -> None:
    api = FakeApi(ok(fixture("unknown_stop_reason.json")))
    with pytest.raises(LLMResponseError, match=r"unsupported stop_reason 'budget_exhausted'"):
        complete(build(api), request(user("q")))


@pytest.mark.parametrize(
    "stop_reason", ["stop_sequence", "pause_turn", "compaction", "model_context_window_exceeded"]
)
def test_a_documented_stop_reason_jarvis_does_not_handle_is_an_error(stop_reason: str) -> None:
    # Our requests never ask for these (no stop sequences, server tools or compaction), and the
    # provider does not guess what one means.
    body = fixture("unknown_stop_reason.json") | {"stop_reason": stop_reason}
    with pytest.raises(LLMResponseError, match=f"unsupported stop_reason '{stop_reason}'"):
        complete(build(FakeApi(ok(body))), request(user("q")))


def test_an_empty_answer_that_is_not_a_refusal_is_an_error() -> None:
    body = fixture("thinking_text.json") | {"content": []}
    with pytest.raises(LLMResponseError, match="stop_reason end_turn needs a message"):
        complete(build(FakeApi(ok(body))), request(user("q")))


def test_a_tool_use_stop_without_a_tool_call_is_an_error() -> None:
    body = fixture("thinking_text.json") | {"stop_reason": "tool_use"}
    with pytest.raises(LLMResponseError, match="no tool call"):
        complete(build(FakeApi(ok(body))), request(user("q")))


# --- Errors ---------------------------------------------------------------------------------


def test_the_prefix_mismatch_400_raises_prefix_mismatch_error() -> None:
    api = FakeApi(httpx2.Response(400, json=fixture("prefix_mismatch_400.json")))
    with pytest.raises(PrefixMismatchError, match="bound to a different conversation") as exc:
        complete(build(api), request(user("q")))
    assert "req_011CPrefixMismatch" in str(exc.value)
    assert len(api.requests) == 1  # a 400 is not retried: the same body fails the same way


def test_a_tampered_signature_400_is_a_request_error_not_a_prefix_mismatch() -> None:
    # Anthropic's docs: an undecryptable signature has the same leading clause but no "bound to a
    # different conversation" sentence, and drop_block does not apply to it.
    message = "messages.1.content.0: Invalid `signature` in `thinking` block."
    api = FakeApi(api_error(400, "invalid_request_error", message))
    with pytest.raises(LLMRequestError, match="Invalid `signature`") as exc:
        complete(build(api), request(user("q")))
    assert not isinstance(exc.value, PrefixMismatchError)


@pytest.mark.parametrize(
    ("status", "error_type", "expected", "attempts"),
    [
        (401, "authentication_error", LLMAuthError, 1),
        (403, "permission_error", LLMAuthError, 1),
        (404, "not_found_error", LLMRequestError, 1),
        (413, "request_too_large", LLMRequestError, 1),
        # Retryable: the SDK retries max_retries (2) times, then we map the last failure.
        (429, "rate_limit_error", LLMRateLimitError, 3),
        (500, "api_error", LLMUnavailableError, 3),
        (529, "overloaded_error", LLMUnavailableError, 3),
    ],
)
def test_api_errors_map_to_our_types_after_the_sdk_retries(
    status: int, error_type: str, expected: type[LLMError], attempts: int
) -> None:
    api = FakeApi(api_error(status, error_type, "something failed"))
    with pytest.raises(
        expected, match=rf"anthropic {status} {error_type}: something failed"
    ) as exc:
        complete(build(api), request(user("q")))
    assert type(exc.value) is expected
    assert "request r1" in str(exc.value)
    assert len(api.requests) == attempts


@pytest.mark.parametrize(
    "failure",
    [httpx2.ConnectError("refused"), httpx2.ReadTimeout("slow")],
    ids=["connect", "timeout"],
)
def test_a_network_failure_is_unavailable_after_the_sdk_retries(failure: Exception) -> None:
    api = FakeApi(failure)
    with pytest.raises(LLMUnavailableError, match="anthropic"):
        complete(build(api), request(user("q")))
    assert len(api.requests) == 3


def test_the_timeout_is_set_explicitly() -> None:
    api = FakeApi(ok(fixture("thinking_text.json")))
    complete(build(api), request(user("q")))
    assert api.requests[0].extensions["timeout"] == {
        "connect": 5.0,
        "read": 600.0,
        "write": 600.0,
        "pool": 600.0,
    }


# --- Secrecy --------------------------------------------------------------------------------


def test_the_provider_repr_names_the_model_and_never_the_key() -> None:
    provider = build(FakeApi(ok(fixture("thinking_text.json"))))
    assert repr(provider) == "AnthropicProvider(model='claude-sonnet-5-5')"


def test_the_key_is_sent_only_as_x_api_key_even_if_the_environment_has_other_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Secrets never come from the environment; the Keychain key is the only credential.
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-from-env")
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "token-from-env")
    api = FakeApi(ok(fixture("thinking_text.json")))
    complete(build(api), request(user("q")))
    headers = api.requests[0].headers
    assert headers["x-api-key"] == KEY
    assert "authorization" not in headers


def test_requests_go_to_the_anthropic_api_even_if_the_environment_points_elsewhere(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # ANTHROPIC_BASE_URL would otherwise send the key to another host.
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://attacker.example")
    api = FakeApi(ok(fixture("thinking_text.json")))
    complete(build(api), request(user("q")))
    assert api.requests[0].url.host == "api.anthropic.com"


def test_a_failing_calls_error_never_contains_the_key() -> None:
    # Even when the API's message echoes the key, our error, its repr and its traceback don't,
    # and it holds no reference to the SDK's exception (whose request carries the key header).
    api = FakeApi(api_error(401, "authentication_error", f"invalid x-api-key: {KEY}"))
    with pytest.raises(LLMAuthError) as exc:
        complete(build(api), request(user("q")))
    error = exc.value
    text = "".join(traceback.format_exception(error))
    assert KEY not in str(error)
    assert KEY not in repr(error)
    assert KEY not in text
    assert "invalid x-api-key: [redacted]" in str(error)
    assert error.__cause__ is None
    assert error.__context__ is None


def test_the_key_never_reaches_the_logs(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    api = FakeApi(
        ok(fixture("thinking_text.json")), api_error(401, "authentication_error", "invalid key")
    )
    provider = build(api)
    complete(provider, request(user("q")))
    with pytest.raises(LLMAuthError):
        complete(provider, request(user("q")))
    assert caplog.records, "expected the SDK's debug logs, so this test checks something"
    assert KEY not in caplog.text


# --- Building the provider ------------------------------------------------------------------


def test_a_missing_key_fails_when_the_router_is_built() -> None:
    factory = anthropic_factory(FakeSecretStore())
    with pytest.raises(
        ModelRouterError,
        match=r"^models\.planner: provider 'anthropic' failed to start: "
        r"secret 'anthropic' not found",
    ) as exc:
        ModelRouter({Role.PLANNER: CONFIG}, {"anthropic": factory})
    assert isinstance(exc.value.__cause__, SecretNotFoundError)


def test_max_tokens_a_non_streaming_call_can_finish_is_accepted() -> None:
    config = RoleModelConfig(provider="anthropic", model="claude-sonnet-5-5", max_tokens=21_333)
    api = FakeApi(ok(fixture("thinking_text.json")))
    complete(build(api, config), request(user("q")))
    assert api.body()["max_tokens"] == 21_333


def test_max_tokens_beyond_what_a_non_streaming_call_can_finish_fails_at_router_build() -> None:
    # A non-streaming call must finish within the 600 s timeout; the SDK's estimate is
    # 3600 s per 128,000 output tokens, so 21,333 is the most it can honor.
    config = RoleModelConfig(provider="anthropic", model="claude-sonnet-5-5", max_tokens=21_334)
    factory = anthropic_factory(FakeSecretStore({"anthropic": KEY}))
    with pytest.raises(
        ModelRouterError,
        match=r"models\.planner: provider 'anthropic' failed to start: max_tokens 21334 is above "
        r"21333",
    ):
        ModelRouter({Role.PLANNER: config}, {"anthropic": factory})
