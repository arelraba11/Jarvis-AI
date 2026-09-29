"""API keys come from the macOS Keychain only (service "jarvis-spike"), never from files or env."""

import keyring

SERVICE = "jarvis-spike"


def get_key(name: str) -> str:
    key = keyring.get_password(SERVICE, name)
    if not key:
        raise SystemExit(
            f"No '{name}' key in the Keychain. Store it with:\n"
            f"  uv run keyring set {SERVICE} {name}"
        )
    return key
