"""Live smoke tests against the real Anthropic API (Phase 2 task 5).

Two opt-ins, so no other `-m` expression can run them by accident: the `live` marker (excluded
by default and in CI, `-m "not live"` in pyproject.toml) and JARVIS_LIVE=1. Run by hand on the Mac:

    JARVIS_LIVE=1 uv run pytest -m live -s

They read the API key from the real Keychain (service `jarvis`, account `anthropic`) and spend
a few cents. On the first read macOS asks for Keychain access: choose "Always Allow".

Every exchange is captured, so each test also confirms that the preserved-thinking controls took
effect: the request carried the beta header and `block_binding: error`, and the API answered with
`input_transformations: []`. Anthropic's docs: with the header, every response from a
thinking-capable model carries that array (empty when no block was dropped); without it the field
is absent, and `block_binding` without the header is a 400.
"""

import asyncio
import json
import os
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import anthropic
import httpx2
import keyring
import keyring.core
import pytest

from jarvis.core.config import load_settings
from jarvis.core.secret_store import KeyringSecretStore
from jarvis.llm.anthropic_provider import BETAS, anthropic_factory
from jarvis.llm.contracts import (
    LLMProvider,
    LLMRequest,
    LLMResponse,
    Message,
    PrefixMismatchError,
    Role,
    TextBlock,
    ThinkingBlock,
)

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        os.environ.get("JARVIS_LIVE") != "1",
        reason="live API test: set JARVIS_LIVE=1 (reads the real Keychain, costs money)",
    ),
]

# The planner's real system prompt: well above Sonnet 5.5's 512-token minimum cacheable prefix.
SYSTEM = (Path(__file__).parents[1] / "docs" / "behavior.md").read_text(encoding="utf-8")
# A question that makes the model reason, so the first turn produces a thinking block.
REASONING_QUESTION = "כמה זה 17 כפול 23? תסביר בקצרה איך חישבת."
THINKING_ATTEMPTS = 3


@pytest.fixture(autouse=True)
def keyring_backend() -> Iterator[None]:
    """Overrides conftest's in-memory keyring and restores the real macOS backend, on purpose.

    The one allowed exception to "tests never touch the real Keychain" (CLAUDE.md): these tests
    run only with `-m live` AND JARVIS_LIVE=1, never in CI. Every other test keeps the fake.
    """
    previous = keyring.get_keyring()
    keyring.set_keyring(keyring.core.load_keyring("keyring.backends.macOS.Keyring"))
    yield
    keyring.set_keyring(previous)


# Any: request and response bodies are JSON checked by key in assertions.
@dataclass
class Exchanges:
    """Every request the provider sent and every response body it got, in order."""

    sent: list[tuple[str, dict[str, Any]]] = field(default_factory=list)  # (beta header, body)
    received: list[dict[str, Any]] = field(default_factory=list)

    async def on_request(self, request: httpx2.Request) -> None:
        self.sent.append((request.headers.get("anthropic-beta", ""), json.loads(request.content)))

    async def on_response(self, response: httpx2.Response) -> None:
        await response.aread()
        self.received.append(response.json())

    def assert_binding_confirmed(self) -> None:
        """The last exchange used the preserved-thinking controls, and the API applied them."""
        beta, body = self.sent[-1]
        assert set(BETAS) <= set(beta.split(",")), f"beta header not sent: {beta!r}"
        assert body["thinking"] == {
            "type": "adaptive",
            "block_binding": {"prefix_mismatch_behavior": "error"},
        }
        response = self.received[-1]
        assert "input_transformations" in response, (
            "no input_transformations in the response: the API did not apply the beta"
        )
        # Empty: no block was dropped, so every replayed thinking block reached the model.
        assert response["input_transformations"] == [], response["input_transformations"]


@pytest.fixture
def exchanges() -> Exchanges:
    return Exchanges()


@pytest.fixture
def provider(exchanges: Exchanges) -> LLMProvider:
    config = load_settings().models[Role.PLANNER]
    assert config.provider == "anthropic", "the planner in config is not the Anthropic provider"
    client = anthropic.DefaultAsyncHttpxClient(
        event_hooks={"request": [exchanges.on_request], "response": [exchanges.on_response]}
    )
    return anthropic_factory(KeyringSecretStore(), http_client=client)(config)


def user(text: str) -> Message:
    return Message(role="user", content=(TextBlock(text=text),))


def complete(provider: LLMProvider, *messages: Message) -> LLMResponse:
    return asyncio.run(provider.complete(LLMRequest(system=SYSTEM, messages=messages)))


def first_turn_with_thinking(provider: LLMProvider) -> Message:
    """A first turn that produced a thinking block; fails loudly if the model never thinks."""
    for _ in range(THINKING_ATTEMPTS):
        response = complete(provider, user(REASONING_QUESTION))
        message = response.message
        assert message is not None, f"the first turn was refused: {response}"
        if any(isinstance(b, ThinkingBlock) for b in message.content):
            return message
    pytest.fail(
        f"no thinking block in {THINKING_ATTEMPTS} first turns: the replay check would prove "
        "nothing. Check the planner's effort in config (adaptive thinking may skip easy turns)."
    )


def test_a_repeated_hebrew_request_reads_the_cached_prefix(
    provider: LLMProvider, exchanges: Exchanges
) -> None:
    question = user("שלום, מי אתה? תענה במשפט אחד.")
    first = complete(provider, question)
    exchanges.assert_binding_confirmed()
    second = complete(provider, question)
    exchanges.assert_binding_confirmed()
    print(f"\nfirst:  {first.usage}\nsecond: {second.usage}")
    assert second.stop_reason == "end_turn"
    assert second.usage.cache_read_tokens > 0


def test_a_second_turn_replays_the_first_turn_verbatim(
    provider: LLMProvider, exchanges: Exchanges
) -> None:
    # With prefix_mismatch_behavior "error", a replayed turn that differs from what the API
    # returned is a 400 (PrefixMismatchError). An empty input_transformations on the second
    # response also shows the replayed thinking block was not dropped.
    first = first_turn_with_thinking(provider)
    second = complete(provider, user(REASONING_QUESTION), first, user("ועכשיו כפול 2?"))
    exchanges.assert_binding_confirmed()
    print(f"\nsecond turn: {second.stop_reason}, {second.usage}")
    assert second.stop_reason == "end_turn"


def test_an_edited_history_is_rejected_by_the_api(provider: LLMProvider) -> None:
    # The negative check: editing a message before a kept thinking block must fail, not be
    # silently dropped. This proves the API enforces "error" for this account.
    first = first_turn_with_thinking(provider)
    edited_question = user(REASONING_QUESTION + " (edited)")
    with pytest.raises(PrefixMismatchError, match="bound to a different conversation") as exc:
        complete(provider, edited_question, first, user("ועכשיו כפול 2?"))
    print(f"\nrejected as expected: {exc.value}")
