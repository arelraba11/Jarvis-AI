from collections.abc import Mapping

from jarvis.core.secret_store import SecretNotFoundError


class FakeSecretStore:
    """An in-memory SecretStore. Not a dataclass: its repr would print the values."""

    def __init__(self, secrets: Mapping[str, str] | None = None) -> None:
        self._secrets = dict(secrets or {})

    def get(self, name: str) -> str:
        try:
            return self._secrets[name]
        except KeyError:
            raise SecretNotFoundError(name) from None

    def set(self, name: str, value: str) -> None:
        self._secrets[name] = value

    def delete(self, name: str) -> None:
        self._secrets.pop(name, None)

    def __repr__(self) -> str:
        return f"FakeSecretStore(names={sorted(self._secrets)})"
