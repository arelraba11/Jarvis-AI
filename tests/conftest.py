from collections.abc import Iterator

import keyring
import pytest

from fakes.keyring_backend import InMemoryKeyring


@pytest.fixture(autouse=True)
def keyring_backend() -> Iterator[InMemoryKeyring]:
    """Every test gets a fresh in-memory keyring: no test can reach the real Keychain."""
    previous = keyring.get_keyring()
    backend = InMemoryKeyring()
    keyring.set_keyring(backend)
    yield backend
    keyring.set_keyring(previous)
