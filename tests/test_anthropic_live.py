"""Live smoke tests against the real Anthropic API (Phase 2 task 5).

Two opt-ins, so no other `-m` expression can run them by accident: the `live` marker (excluded
by default and in CI, `-m "not live"` in pyproject.toml) and JARVIS_LIVE=1. Run by hand on the Mac:

    JARVIS_LIVE=1 uv run pytest -m live -s

They read the API key from the real Keychain (service `jarvis`, account `anthropic`) and spend
a few cents. On the first read macOS asks for Keychain access: choose "Always Allow".
"""

import asyncio
import os
from collections.abc import Iterator
from pathlib import Path

import pytest

from jarvis.core.config import load_settings
from jarvis.core.secret_store import KeyringSecretStore
from jarvis.llm.anthropic_provider import anthropic_factory
from jarvis.llm.contracts import (
    LLMProvider,
    LLMRequest,
    LLMResponse,
    Message,
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


@pytest.fixture(autouse=True)
def keyring_backend() -> Iterator[None]:
    """Overrides conftest's in-memory keyring: these tests need the real Keychain key."""
    yield


@pytest.fixture
def provider() -> LLMProvider:
    config = load_settings().models[Role.PLANNER]
    assert config.provider == "anthropic", "the planner in config is not the Anthropic provider"
    return anthropic_factory(KeyringSecretStore())(config)


def user(text: str) -> Message:
    return Message(role="user", content=(TextBlock(text=text),))


def complete(provider: LLMProvider, *messages: Message) -> LLMResponse:
    return asyncio.run(provider.complete(LLMRequest(system=SYSTEM, messages=messages)))


def test_a_repeated_hebrew_request_reads_the_cached_prefix(provider: LLMProvider) -> None:
    question = user("שלום, מי אתה? תענה במשפט אחד.")
    first = complete(provider, question)
    second = complete(provider, question)
    print(f"\nfirst:  {first.usage}\nsecond: {second.usage}")
    assert second.stop_reason == "end_turn"
    assert second.usage.cache_read_tokens > 0


def test_a_second_turn_replays_the_first_turn_verbatim(provider: LLMProvider) -> None:
    # With prefix_mismatch_behavior "error", a replayed turn that differs from what the API
    # returned is a 400 (PrefixMismatchError); passing proves the round trip is exact.
    first = complete(provider, user("כמה זה 17 כפול 23? תסביר בקצרה."))
    assert first.message is not None
    if not any(isinstance(b, ThinkingBlock) for b in first.message.content):
        pytest.skip("the model did not think on the first turn, so there is nothing to replay")
    second = complete(
        provider, user("כמה זה 17 כפול 23? תסביר בקצרה."), first.message, user("ועכשיו כפול 2?")
    )
    print(f"\nsecond turn: {second.stop_reason}, {second.usage}")
    assert second.stop_reason == "end_turn"
