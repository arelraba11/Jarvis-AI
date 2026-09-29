"""SecretStore: API keys and OAuth tokens in the macOS Keychain (docs/systems/infra.md#secrets).

Keychain naming: service "jarvis", account = the secret's name (the provider name for an API key,
for example "anthropic"). A secret value never appears in a repr, a log line or an error message.
"""

from contextlib import suppress
from typing import Protocol

import keyring
from keyring.errors import PasswordDeleteError

SERVICE = "jarvis"


class SecretNotFoundError(Exception):
    """The secret is not stored. The message gives the command that adds it (behavior.md R3)."""

    def __init__(self, name: str, service: str = SERVICE) -> None:
        super().__init__(
            f"secret {name!r} not found in the Keychain. "
            f"Add it with: security add-generic-password -s {service} -a {name} -w"
        )
        self.name = name


class SecretStore(Protocol):
    def get(self, name: str) -> str: ...

    def set(self, name: str, value: str) -> None: ...

    def delete(self, name: str) -> None:
        """Remove the secret. Removing one that isn't stored is not an error."""
        ...


class KeyringSecretStore:
    """Holds no values itself: every call goes to keyring (the macOS Keychain on the Mac)."""

    def __init__(self, service: str = SERVICE) -> None:
        self._service = service

    def get(self, name: str) -> str:
        value = keyring.get_password(self._service, name)
        if value is None:
            raise SecretNotFoundError(name, self._service)
        return value

    def set(self, name: str, value: str) -> None:
        keyring.set_password(self._service, name, value)

    def delete(self, name: str) -> None:
        with suppress(PasswordDeleteError):  # already gone: the goal state
            keyring.delete_password(self._service, name)

    def __repr__(self) -> str:
        return f"KeyringSecretStore(service={self._service!r})"
