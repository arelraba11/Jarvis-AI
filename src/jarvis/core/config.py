"""Settings: config/default.yaml, with config/local.yaml deep-merged over it.

Every field has a safe default, so the app and tests work without local.yaml (as in CI).
Unknown keys and wrong types are rejected with an error that names the file and the key.
"""

from collections.abc import Mapping
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

# src/jarvis/core/config.py -> repo root. Valid for the editable install `uv sync` makes.
CONFIG_DIR = Path(__file__).resolve().parents[3] / "config"

Weekday = Literal["sunday", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday"]


class ConfigError(Exception):
    """The config could not be loaded. The message names the file and the offending keys."""


class _Section(BaseModel):
    # strict: a quoted "3" is not silently turned into a number.
    # extra="forbid": a misspelled key is an error instead of being ignored.
    # frozen: settings are read-only once loaded.
    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)


class UserSettings(_Section):
    id: str = "default"
    name: str | None = None
    timezone: str = "UTC"
    language: str = "he"
    week_start: Weekday = "sunday"
    default_account_id: str | None = None

    @field_validator("timezone")
    @classmethod
    def _known_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as e:
            raise ValueError(f"unknown timezone {value!r}") from e
        return value


class BudgetSettings(_Section):
    daily_cap_usd: float = Field(default=3.0, gt=0)


class Settings(_Section):
    user: UserSettings = Field(default_factory=UserSettings)
    budget: BudgetSettings = Field(default_factory=BudgetSettings)


def load_settings(config_dir: Path = CONFIG_DIR) -> Settings:
    default_path = config_dir / "default.yaml"
    local_path = config_dir / "local.yaml"
    if not default_path.is_file():
        raise ConfigError(f"{default_path}: file not found")

    # default.yaml is validated on its own first, so an error is blamed on the file that caused it.
    data = _read_yaml(default_path)
    settings = _validate(data, default_path)
    if local_path.is_file():
        data = deep_merge(data, _read_yaml(local_path))
        settings = _validate(data, local_path)
    return settings


def deep_merge(base: Mapping[str, object], override: Mapping[str, object]) -> dict[str, object]:
    """Return `base` with `override` merged in. Nested mappings merge key by key; any other value
    in `override` (scalar, list, null) replaces the one in `base`. Neither input is modified."""
    merged = dict(base)
    for key, value in override.items():
        current = merged.get(key)
        if isinstance(current, Mapping) and isinstance(value, Mapping):
            merged[key] = deep_merge(current, value)
        else:
            merged[key] = value
    return merged


def _read_yaml(path: Path) -> dict[str, object]:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        raise ConfigError(f"{path}: invalid YAML: {e}") from e
    if data is None:  # an empty file
        return {}
    if not isinstance(data, dict):
        raise ConfigError(f"{path}: top level must be a mapping, got {type(data).__name__}")
    return data


def _validate(data: Mapping[str, object], source: Path) -> Settings:
    try:
        return Settings.model_validate(data)
    except ValidationError as e:
        problems = "\n".join(
            f"  {'.'.join(str(part) for part in error['loc'])}: {error['msg']}"
            for error in e.errors()
        )
        raise ConfigError(f"Invalid config in {source}:\n{problems}") from e
