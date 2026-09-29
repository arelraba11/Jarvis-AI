import logging
from collections.abc import Callable

import keyring
import pytest

from fakes.keyring_backend import InMemoryKeyring
from fakes.secrets import FakeSecretStore
from jarvis.core.secret_store import KeyringSecretStore, SecretNotFoundError, SecretStore

VALUE = "sk-ant-TOP-SECRET-0123456789"


@pytest.fixture(params=["keyring", "fake"])
def store(request: pytest.FixtureRequest) -> SecretStore:
    """The same behavior is required of the keyring implementation and the fake."""
    if request.param == "keyring":
        return KeyringSecretStore()
    return FakeSecretStore()


def test_a_secret_round_trips(store: SecretStore) -> None:
    store.set("anthropic", VALUE)
    assert store.get("anthropic") == VALUE


def test_set_replaces_the_value(store: SecretStore) -> None:
    store.set("anthropic", "old")
    store.set("anthropic", VALUE)
    assert store.get("anthropic") == VALUE


def test_a_missing_secret_fails_with_the_command_that_adds_it(store: SecretStore) -> None:
    # behavior.md R3: the user gets the exact step, not just "not found". -U updates an item that
    # exists but wasn't readable (Deny on the access prompt); without it, `security` fails.
    with pytest.raises(SecretNotFoundError) as exc:
        store.get("anthropic")
    assert "security add-generic-password -U -s jarvis -a anthropic -w" in str(exc.value)


def test_delete_removes_the_secret(store: SecretStore) -> None:
    store.set("anthropic", VALUE)
    store.delete("anthropic")
    with pytest.raises(SecretNotFoundError):
        store.get("anthropic")


def test_deleting_a_missing_secret_is_not_an_error(store: SecretStore) -> None:
    # Removing an account whose token is already gone reaches the goal state anyway (Phase 3).
    store.delete("anthropic")
    with pytest.raises(SecretNotFoundError):
        store.get("anthropic")


@pytest.mark.parametrize(
    "call",
    [
        pytest.param(lambda s: s.get(""), id="get"),
        pytest.param(lambda s: s.set("", VALUE), id="set"),
        pytest.param(lambda s: s.delete(""), id="delete"),
    ],
)
def test_an_empty_name_is_rejected(
    store: SecretStore, call: Callable[[SecretStore], object]
) -> None:
    with pytest.raises(ValueError, match="secret name must not be empty"):
        call(store)


def test_an_empty_value_is_rejected(store: SecretStore) -> None:
    # An empty API key would pass as valid here and only fail later, as a 401 from the provider.
    with pytest.raises(ValueError, match="secret value must not be empty"):
        store.set("anthropic", "")
    with pytest.raises(SecretNotFoundError):
        store.get("anthropic")


def test_values_never_appear_in_repr_str_errors_or_logs(
    store: SecretStore, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    store.set("anthropic", VALUE)
    store.get("anthropic")
    with pytest.raises(SecretNotFoundError) as exc:
        store.get("openai")
    for text in (repr(store), str(store), str(exc.value), repr(exc.value), caplog.text):
        assert VALUE not in text


def test_keyring_names_items_service_jarvis_account_name(keyring_backend: InMemoryKeyring) -> None:
    # The Anthropic key was created with `security add-generic-password -s jarvis -a anthropic -w`.
    keyring_backend.items[("jarvis", "anthropic")] = VALUE
    store = KeyringSecretStore()
    assert store.get("anthropic") == VALUE
    store.set("google-oauth", "token")
    assert keyring_backend.items[("jarvis", "google-oauth")] == "token"


def test_keyring_service_is_injectable(keyring_backend: InMemoryKeyring) -> None:
    store = KeyringSecretStore(service="jarvis-test")
    store.set("anthropic", VALUE)
    assert keyring_backend.items == {("jarvis-test", "anthropic"): VALUE}
    store.delete("anthropic")
    # The fix step names the service the store actually reads from.
    with pytest.raises(SecretNotFoundError, match="-U -s jarvis-test -a anthropic -w"):
        store.get("anthropic")


def test_fake_can_start_with_secrets() -> None:
    assert FakeSecretStore({"anthropic": VALUE}).get("anthropic") == VALUE


def test_every_non_live_test_gets_the_in_memory_keyring() -> None:
    # conftest's autouse fixture; only the live tests restore the real backend (CLAUDE.md).
    assert isinstance(keyring.get_keyring(), InMemoryKeyring)
