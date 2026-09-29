import pytest
from pydantic import JsonValue, ValidationError

from jarvis.llm.contracts import (
    LLMRequest,
    LLMResponse,
    Message,
    TextBlock,
    ThinkingBlock,
    ToolCall,
    ToolResult,
    Usage,
)

TOOL_CALL = ToolCall(id="call_1", name="get_current_time", arguments={})
TOOL_RESULT = ToolResult(tool_call_id="call_1", content="10:42")
THINKING = ThinkingBlock(raw={"type": "thinking", "thinking": "...", "signature": "sig"})


def user(text: str) -> Message:
    return Message(role="user", content=(TextBlock(text=text),))


def assistant(text: str) -> Message:
    return Message(role="assistant", content=(TextBlock(text=text),))


@pytest.mark.parametrize(
    ("role", "block"),
    [
        # Only the model produces thinking and tool calls; only the user side returns tool results.
        ("user", THINKING),
        ("user", TOOL_CALL),
        ("assistant", TOOL_RESULT),
    ],
)
def test_message_rejects_a_block_its_role_cannot_carry(
    role: str, block: ThinkingBlock | ToolCall | ToolResult
) -> None:
    with pytest.raises(ValidationError, match="cannot carry"):
        Message.model_validate({"role": role, "content": (block,)})


def test_message_rejects_empty_content() -> None:
    with pytest.raises(ValidationError, match="at least 1 item"):
        Message(role="user", content=())


def test_thinking_block_round_trips_through_json_unchanged() -> None:
    # The provider's block must come back byte-for-byte, including fields we don't model.
    raw: dict[str, JsonValue] = {
        "type": "thinking",
        "thinking": "המשתמש שואל על השעה",
        "signature": "EqQBCkYIBxgCKkA...",
        "binding": {"previous": None, "version": 2},
    }
    message = Message(
        role="assistant", content=(ThinkingBlock(raw=raw), TOOL_CALL, TextBlock(text="רגע"))
    )
    restored = Message.model_validate_json(message.model_dump_json())
    assert restored == message
    block = restored.content[0]
    assert isinstance(block, ThinkingBlock)
    assert block.raw == raw


def test_request_rejects_empty_messages() -> None:
    with pytest.raises(ValidationError, match="at least 1 item"):
        LLMRequest(system="s", messages=())


def test_request_must_start_with_a_user_message() -> None:
    with pytest.raises(ValidationError, match="first message must be from the user"):
        LLMRequest(system="s", messages=(assistant("hi"), user("hi")))


def call(call_id: str) -> ToolCall:
    return ToolCall(id=call_id, name="get_current_time", arguments={})


def result(call_id: str) -> ToolResult:
    return ToolResult(tool_call_id=call_id, content="10:42")


def turn(role: str, *blocks: TextBlock | ToolCall | ToolResult) -> Message:
    return Message.model_validate({"role": role, "content": blocks})


def test_request_accepts_tool_calls_answered_in_the_next_message() -> None:
    # Results may come in any order, and text may follow them.
    messages = (
        user("what time is it here and in London?"),
        turn("assistant", TextBlock(text="checking"), call("a"), call("b")),
        turn("user", result("b"), result("a"), TextBlock(text="and?")),
    )
    assert LLMRequest(system="s", messages=messages).messages == messages


@pytest.mark.parametrize(
    ("messages", "expected"),
    [
        pytest.param(
            (user("q"), turn("assistant", call("a")), user("q2")),
            r"messages\[1\]: tool call 'a' has no result in the next message",
            id="call-unanswered",
        ),
        pytest.param(
            (user("q"), turn("assistant", call("a"), call("b")), turn("user", result("a"))),
            r"messages\[1\]: tool call 'b' has no result in the next message",
            id="call-partly-answered",
        ),
        pytest.param(
            (user("q"), assistant("hi"), turn("user", result("x"))),
            r"messages\[2\]: tool result 'x' matches no tool call in the previous message",
            id="result-orphan",
        ),
        pytest.param(
            (turn("user", result("x")),),
            r"messages\[0\]: tool result 'x' matches no tool call in the previous message",
            id="result-in-first-message",
        ),
        pytest.param(
            (
                user("q"),
                turn("assistant", call("a")),
                turn("user", result("a")),
                assistant("10:42"),
                turn("user", result("a")),
            ),
            r"messages\[4\]: tool result 'a' matches no tool call in the previous message",
            id="result-for-an-older-call",
        ),
        pytest.param(
            (user("q"), assistant("hi")),
            "the last message must be from the user",
            id="ends-on-assistant",
        ),
    ],
)
def test_request_rejects_an_invalid_history(messages: tuple[Message, ...], expected: str) -> None:
    with pytest.raises(ValidationError, match=expected):
        LLMRequest(system="s", messages=messages)


def test_response_message_must_be_from_the_assistant() -> None:
    with pytest.raises(ValidationError, match="must be from the assistant"):
        LLMResponse(message=user("hi"), stop_reason="end_turn", usage=Usage(), model="m")


def test_tool_use_stop_reason_requires_a_tool_call() -> None:
    with pytest.raises(ValidationError, match="no tool call"):
        LLMResponse(message=assistant("hi"), stop_reason="tool_use", usage=Usage(), model="m")


def test_tool_use_response_with_a_tool_call_is_valid() -> None:
    message = Message(role="assistant", content=(THINKING, TOOL_CALL))
    response = LLMResponse(message=message, stop_reason="tool_use", usage=Usage(), model="m")
    assert response.message.content[1] == TOOL_CALL


@pytest.mark.parametrize(
    "field", ["input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens"]
)
def test_usage_rejects_negative_token_counts(field: str) -> None:
    with pytest.raises(ValidationError, match="greater than or equal to 0"):
        Usage.model_validate({field: -1})
