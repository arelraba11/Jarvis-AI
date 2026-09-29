"""FakeProvider's preserved-thinking prefix check (ADR-0003).

Every test starts from the same history, made of three model calls that each produced one thinking
block (T0, T1, T2):

    0 user       "what time is it?"
    1 assistant  T0, tool call get_current_time
    2 user       tool result
    3 assistant  T1, "10:42"
    4 user       "thanks"
    5 assistant  T2, "you're welcome"

and then sends one more request built from it.
"""

import asyncio

import pytest

from fakes.llm import FakeProvider
from jarvis.llm.contracts import (
    LLMProvider,
    LLMRequest,
    LLMResponse,
    Message,
    OpaqueBlock,
    PrefixMismatchError,
    StopReason,
    TextBlock,
    ThinkingBlock,
    ToolCall,
    ToolDefinition,
    ToolResult,
    Usage,
)

SYSTEM = "You are Jarvis."
TOOLS = (
    ToolDefinition(
        name="get_current_time",
        description="The current time in the user's timezone.",
        input_schema={"type": "object", "properties": {"timezone": {"type": "string"}}},
    ),
)
Messages = tuple[Message, ...]
THINKING_AT = {"T0": 1, "T1": 3, "T2": 5}  # the message index of each thinking block


def user(text: str) -> Message:
    return Message(role="user", content=(TextBlock(text=text),))


def reply(*blocks: TextBlock | ToolCall, thinking: str) -> LLMResponse:
    stop: StopReason = "tool_use" if any(isinstance(b, ToolCall) for b in blocks) else "end_turn"
    return LLMResponse(
        message=Message(
            role="assistant",
            content=(ThinkingBlock(raw={"type": "thinking", "thinking": thinking}), *blocks),
        ),
        stop_reason=stop,
        usage=Usage(input_tokens=10, output_tokens=5),
        model="fake-model",
    )


FINAL = reply(TextBlock(text="final"), thinking="t3")


def complete(provider: LLMProvider, messages: Messages, **overrides: object) -> LLMResponse:
    request = LLMRequest.model_validate(
        {"system": SYSTEM, "tools": TOOLS, "messages": messages} | overrides
    )
    return asyncio.run(provider.complete(request))


def said(provider: LLMProvider, messages: Messages) -> Message:
    """The assistant message of the next response (none of the scripted ones is a refusal)."""
    message = complete(provider, messages).message
    assert message is not None
    return message


@pytest.fixture
def provider() -> FakeProvider:
    return FakeProvider(
        [
            reply(
                ToolCall(id="c1", name="get_current_time", arguments={"timezone": "UTC"}),
                thinking="t0",
            ),
            reply(TextBlock(text="10:42"), thinking="t1"),
            reply(TextBlock(text="you're welcome"), thinking="t2"),
            FINAL,
        ]
    )


@pytest.fixture
def history(provider: FakeProvider) -> Messages:
    messages: Messages = (user("what time is it?"),)
    messages += (said(provider, messages),)
    messages += (Message(role="user", content=(ToolResult(tool_call_id="c1", content="10:42"),)),)
    messages += (said(provider, messages),)
    messages += (user("thanks"),)
    messages += (said(provider, messages),)
    return messages


def next_turn(messages: Messages) -> Messages:
    return (*messages, user("and the date?"))


def replace(messages: Messages, index: int, message: Message) -> Messages:
    return (*messages[:index], message, *messages[index + 1 :])


def drop_thinking(messages: Messages, *names: str) -> Messages:
    for name in names:
        index = THINKING_AT[name]
        kept = tuple(b for b in messages[index].content if not isinstance(b, ThinkingBlock))
        messages = replace(messages, index, messages[index].model_copy(update={"content": kept}))
    return messages


def test_the_fake_satisfies_the_provider_protocol(provider: FakeProvider) -> None:
    # The annotation is the check: mypy fails here if FakeProvider stops matching LLMProvider.
    typed: LLMProvider = provider
    assert said(typed, (user("hi"),)).content[1] == ToolCall(
        id="c1", name="get_current_time", arguments={"timezone": "UTC"}
    )


def test_returns_the_scripted_responses_in_order(history: Messages) -> None:
    texts = [b.text for m in history for b in m.content if isinstance(b, TextBlock)]
    assert texts == ["what time is it?", "10:42", "thanks", "you're welcome"]


def test_fails_clearly_when_the_script_runs_out(provider: FakeProvider, history: Messages) -> None:
    complete(provider, next_turn(history))
    with pytest.raises(AssertionError, match="no scripted responses left"):
        complete(provider, next_turn(history))


def test_accepts_an_append_only_history(provider: FakeProvider, history: Messages) -> None:
    assert complete(provider, next_turn(history)) == FINAL


@pytest.mark.parametrize(
    "change",
    [
        pytest.param({"system": SYSTEM + " Today is Monday."}, id="system"),
        pytest.param({"tools": ()}, id="tools"),
    ],
)
def test_rejects_a_changed_system_prompt_or_tool_list(
    provider: FakeProvider, history: Messages, change: dict[str, object]
) -> None:
    with pytest.raises(PrefixMismatchError):
        complete(provider, next_turn(history), **change)


def test_rejects_an_edited_earlier_message(provider: FakeProvider, history: Messages) -> None:
    with pytest.raises(PrefixMismatchError):
        complete(provider, next_turn(replace(history, 0, user("what's the time?"))))


def test_rejects_a_deleted_earlier_message(provider: FakeProvider, history: Messages) -> None:
    without_thanks = (*history[:4], *history[5:])
    with pytest.raises(PrefixMismatchError):
        complete(provider, next_turn(without_thanks))


def test_rejects_an_earlier_tool_call_edited_in_place(
    provider: FakeProvider, history: Messages
) -> None:
    # The models are frozen, but a dict inside one is not: the fake must keep its own copy.
    tool_call = history[1].content[1]
    assert isinstance(tool_call, ToolCall)
    tool_call.arguments["timezone"] = "Asia/Jerusalem"
    with pytest.raises(PrefixMismatchError):
        complete(provider, next_turn(history))


@pytest.mark.parametrize(
    "removed",
    [
        pytest.param(("T0",), id="leading-one"),
        pytest.param(("T0", "T1"), id="leading-run"),
        pytest.param(("T2",), id="trailing-one"),
        pytest.param(("T1", "T2"), id="trailing-run"),
        pytest.param(("T0", "T1", "T2"), id="all"),
    ],
)
def test_accepts_thinking_blocks_removed_from_the_start_or_the_end(
    provider: FakeProvider, history: Messages, removed: tuple[str, ...]
) -> None:
    assert complete(provider, next_turn(drop_thinking(history, *removed))) == FINAL


def test_rejects_a_thinking_block_removed_from_the_middle(
    provider: FakeProvider, history: Messages
) -> None:
    with pytest.raises(PrefixMismatchError):
        complete(provider, next_turn(drop_thinking(history, "T1")))


def test_with_every_thinking_block_removed_the_system_prompt_may_change(
    provider: FakeProvider, history: Messages
) -> None:
    # No thinking block is left to bind the prefix, so the API has nothing to check.
    messages = next_turn(drop_thinking(history, "T0", "T1", "T2"))
    assert complete(provider, messages, system="A different system prompt") == FINAL


def test_a_message_after_the_last_kept_thinking_block_may_change(
    provider: FakeProvider, history: Messages
) -> None:
    # "thanks" (index 4) precedes only T2; once T2 is removed, nothing binds it.
    messages = next_turn(replace(drop_thinking(history, "T2"), 4, user("thank you!")))
    assert complete(provider, messages) == FINAL


def test_rejects_a_thinking_block_it_did_not_produce(
    provider: FakeProvider, history: Messages
) -> None:
    forged = ThinkingBlock(raw={"type": "thinking", "thinking": "t1", "signature": "forged"})
    index = THINKING_AT["T1"]
    tampered = replace(
        history,
        index,
        history[index].model_copy(update={"content": (forged, *history[index].content[1:])}),
    )
    with pytest.raises(ValueError, match="not produced by this FakeProvider"):
        complete(provider, next_turn(tampered))


def test_scripted_thinking_blocks_must_be_unique() -> None:
    # The fake recognizes the blocks it produced by their content, so two equal ones are ambiguous.
    same = reply(TextBlock(text="hi"), thinking="same")
    with pytest.raises(AssertionError, match="unique"):
        FakeProvider([same, same])


def test_an_opaque_block_is_part_of_the_prefix_like_any_non_thinking_block() -> None:
    # A block type we don't model is carried through; editing it later is an edit of the history
    # before every later thinking block, as the real API sees it.
    opaque = OpaqueBlock(raw={"type": "compaction", "content": "summary v1"})
    provider = FakeProvider(
        [
            LLMResponse(
                message=Message(
                    role="assistant",
                    content=(
                        ThinkingBlock(raw={"type": "thinking", "thinking": "t0"}),
                        opaque,
                        TextBlock(text="a"),
                    ),
                ),
                stop_reason="end_turn",
                usage=Usage(),
                model="fake-model",
            ),
            reply(TextBlock(text="b"), thinking="t1"),
            FINAL,
        ]
    )
    messages: Messages = (user("q"),)
    messages += (said(provider, messages),)
    assert messages[1].content[1] == opaque
    messages += (user("more"),)
    messages += (said(provider, messages),)

    edited_block = OpaqueBlock(raw={"type": "compaction", "content": "summary v2"})
    edited = messages[1].model_copy(
        update={"content": (messages[1].content[0], edited_block, messages[1].content[2])}
    )
    with pytest.raises(PrefixMismatchError, match=r"messages\[3\].*history before it changed"):
        complete(provider, next_turn(replace(messages, 1, edited)))
    assert complete(provider, next_turn(messages)) == FINAL


def test_a_scripted_refusal_is_returned_without_a_message() -> None:
    refusal = LLMResponse(message=None, stop_reason="refusal", usage=Usage(), model="fake-model")
    provider = FakeProvider([refusal])
    assert complete(provider, (user("q"),)) == refusal


def test_rejects_a_removed_thinking_block_that_is_put_back(provider: FakeProvider) -> None:
    # Anthropic: "Once you remove a block, leave it out. Putting it back invalidates the thinking
    # blocks produced while it was gone."
    messages: Messages = (user("what time is it?"),)
    messages += (said(provider, messages),)  # T0
    messages += (Message(role="user", content=(ToolResult(tool_call_id="c1", content="10:42"),)),)
    messages += (said(provider, messages),)  # T1
    messages += (user("thanks"),)
    without_t0 = drop_thinking(messages, "T0")
    messages += (said(provider, without_t0),)  # T2, produced while T0 was gone
    with pytest.raises(PrefixMismatchError, match=r"messages\[5\].*put back"):
        complete(provider, next_turn(messages))
    assert complete(provider, next_turn(drop_thinking(messages, "T0"))) == FINAL
