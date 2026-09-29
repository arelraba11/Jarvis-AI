import shutil
from pathlib import Path

import pytest
from pydantic import ValidationError

from jarvis.core.config import (
    CONFIG_DIR,
    ConfigError,
    ModelPrices,
    RoleModelConfig,
    Settings,
    deep_merge,
    load_settings,
)
from jarvis.llm.contracts import Role

# The price fields after input_per_mtok, for YAML test cases that vary input_per_mtok.
PRICE_REST = "output_per_mtok: 1, cache_write_per_mtok: 1, cache_read_per_mtok: 1}\n"


def write(config_dir: Path, name: str, text: str) -> None:
    (config_dir / name).write_text(text, encoding="utf-8")


@pytest.fixture
def repo_defaults(tmp_path: Path) -> Path:
    """A config dir holding the repo's real default.yaml and no local.yaml (the CI case)."""
    shutil.copy(CONFIG_DIR / "default.yaml", tmp_path / "default.yaml")
    return tmp_path


def test_settings_have_safe_defaults_without_any_file() -> None:
    settings = Settings()
    assert settings.user.timezone == "UTC"
    assert settings.user.week_start == "sunday"
    assert settings.user.default_account_id is None
    assert settings.budget.daily_cap_usd > 0
    # Code names no provider or model (ADR-0003): the planner entry comes from default.yaml.
    assert settings.models == {}


def test_repo_default_yaml_loads_without_local_yaml(repo_defaults: Path) -> None:
    settings = load_settings(repo_defaults)
    assert settings.budget.daily_cap_usd == 3.0
    assert settings.user == Settings().user
    assert settings.models == {
        Role.PLANNER: RoleModelConfig(provider="anthropic", model="claude-sonnet-5-5")
    }


def test_role_model_config_has_provider_neutral_defaults() -> None:
    # Each provider maps these to its own API; see docs/systems/llm.md for why these values.
    config = RoleModelConfig(provider="p", model="m")
    assert config.max_tokens == 16_000
    assert config.effort == "medium"


def test_repo_default_yaml_has_the_planner_model_price(repo_defaults: Path) -> None:
    # USD per million tokens, from Anthropic's pricing page (checked 2026-09-29).
    assert load_settings(repo_defaults).prices["claude-sonnet-5-5"] == ModelPrices(
        input_per_mtok=2.0,
        output_per_mtok=10.0,
        cache_write_per_mtok=2.5,
        cache_read_per_mtok=0.2,
    )


def test_local_yaml_can_change_one_key_of_a_role_and_add_a_role(repo_defaults: Path) -> None:
    write(
        repo_defaults,
        "local.yaml",
        "models:\n  planner: {model: claude-opus-5-5}\n  writer: {provider: other, model: m}\n",
    )
    assert load_settings(repo_defaults).models == {
        Role.PLANNER: RoleModelConfig(provider="anthropic", model="claude-opus-5-5"),
        Role.WRITER: RoleModelConfig(provider="other", model="m"),
    }


def test_local_yaml_overrides_one_field_and_keeps_the_rest(repo_defaults: Path) -> None:
    write(repo_defaults, "local.yaml", "user:\n  timezone: Asia/Jerusalem\n")
    settings = load_settings(repo_defaults)
    assert settings.user.timezone == "Asia/Jerusalem"
    # Siblings in the same section keep their defaults, and other sections keep default.yaml's.
    assert settings.user.week_start == "sunday"
    assert settings.budget.daily_cap_usd == 3.0


def test_local_yaml_overrides_a_value_set_in_default_yaml(repo_defaults: Path) -> None:
    write(repo_defaults, "local.yaml", "budget:\n  daily_cap_usd: 1.5\n")
    assert load_settings(repo_defaults).budget.daily_cap_usd == 1.5


def test_empty_local_yaml_is_allowed(repo_defaults: Path) -> None:
    write(repo_defaults, "local.yaml", "")
    assert load_settings(repo_defaults).budget.daily_cap_usd == 3.0


def test_an_int_is_accepted_for_a_float_field(repo_defaults: Path) -> None:
    write(repo_defaults, "local.yaml", "budget:\n  daily_cap_usd: 2\n")
    assert load_settings(repo_defaults).budget.daily_cap_usd == 2.0


@pytest.mark.parametrize(
    ("local_yaml", "expected_key", "expected_msg"),
    [
        ("user:\n  timezon: UTC\n", "user.timezon", "Extra inputs are not permitted"),
        ("colour: blue\n", "colour", "Extra inputs are not permitted"),
        ("budget:\n  daily_cap_usd: three\n", "budget.daily_cap_usd", "valid number"),
        # Strict: a quoted number is a string, not silently coerced.
        ('budget:\n  daily_cap_usd: "3"\n', "budget.daily_cap_usd", "valid number"),
        ("budget:\n  daily_cap_usd: 0\n", "budget.daily_cap_usd", "greater than 0"),
        ("user:\n  timezone: Mars/Olympus\n", "user.timezone", "unknown timezone"),
        ("user:\n  week_start: sun\n", "user.week_start", "'sunday'"),
        ("user: [a, b]\n", "user", "valid dictionary"),
        # inf/nan would silently disable the daily budget guard.
        ("budget:\n  daily_cap_usd: .inf\n", "budget.daily_cap_usd", "finite number"),
        ("budget:\n  daily_cap_usd: .nan\n", "budget.daily_cap_usd", "finite number"),
        # user.id keys every store, so it can't be empty.
        ('user:\n  id: ""\n', "user.id", "at least 1 character"),
        ('user:\n  default_account_id: ""\n', "user.default_account_id", "at least 1 character"),
        ("models:\n  plannr: {provider: p, model: m}\n", "models.plannr.[key]", "'planner'"),
        ('models:\n  writer: {provider: "", model: m}\n', "models.writer.provider", "at least 1"),
        ('models:\n  writer: {provider: p, model: ""}\n', "models.writer.model", "at least 1"),
        ("models:\n  writer: {provider: p}\n", "models.writer.model", "Field required"),
        (
            "models:\n  writer: {provider: p, model: m, temperature: 0.5}\n",
            "models.writer.temperature",
            "Extra inputs are not permitted",
        ),
        (
            "models:\n  writer: {provider: p, model: m, max_tokens: 0}\n",
            "models.writer.max_tokens",
            "greater than 0",
        ),
        (
            'models:\n  writer: {provider: p, model: m, max_tokens: "16000"}\n',
            "models.writer.max_tokens",
            "valid integer",
        ),
        (
            "models:\n  writer: {provider: p, model: m, max_tokens: 1.5}\n",
            "models.writer.max_tokens",
            "valid integer",
        ),
        (
            "models:\n  writer: {provider: p, model: m, max_tokens: true}\n",
            "models.writer.max_tokens",
            "valid integer",
        ),
        (
            "models:\n  writer: {provider: p, model: m, effort: extreme}\n",
            "models.writer.effort",
            "'medium'",
        ),
        (
            "prices:\n  m: {input_per_mtok: -1, " + PRICE_REST,
            "prices.m.input_per_mtok",
            "greater than or equal to 0",
        ),
        (
            "prices:\n  m: {input_per_mtok: .inf, " + PRICE_REST,
            "prices.m.input_per_mtok",
            "finite number",
        ),
        ("prices:\n  m: {input_per_mtok: 1}\n", "prices.m.output_per_mtok", "Field required"),
        (
            'prices:\n  "": {input_per_mtok: 1, ' + PRICE_REST,
            "prices..[key]",
            "at least 1 character",
        ),
    ],
)
def test_invalid_local_yaml_fails_naming_file_and_key(
    repo_defaults: Path, local_yaml: str, expected_key: str, expected_msg: str
) -> None:
    write(repo_defaults, "local.yaml", local_yaml)
    with pytest.raises(ConfigError) as exc:
        load_settings(repo_defaults)
    message = str(exc.value)
    assert str(repo_defaults / "local.yaml") in message
    assert f"{expected_key}: " in message
    assert expected_msg in message


def test_invalid_default_yaml_is_blamed_on_default_yaml(tmp_path: Path) -> None:
    write(tmp_path, "default.yaml", "budget:\n  daily_cap: 3\n")
    write(tmp_path, "local.yaml", "user:\n  name: Arel\n")
    with pytest.raises(ConfigError) as exc:
        load_settings(tmp_path)
    message = str(exc.value)
    assert str(tmp_path / "default.yaml") in message
    assert str(tmp_path / "local.yaml") not in message
    assert "budget.daily_cap: " in message


def test_missing_default_yaml_fails_clearly(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match=r"default\.yaml: file not found"):
        load_settings(tmp_path)


def test_yaml_syntax_error_names_the_file(repo_defaults: Path) -> None:
    write(repo_defaults, "local.yaml", "user: [unclosed\n")
    with pytest.raises(ConfigError, match=r"local\.yaml: invalid YAML"):
        load_settings(repo_defaults)


def test_top_level_must_be_a_mapping(repo_defaults: Path) -> None:
    write(repo_defaults, "local.yaml", "- a\n- b\n")
    with pytest.raises(ConfigError, match="top level must be a mapping"):
        load_settings(repo_defaults)


def test_settings_are_read_only() -> None:
    settings = Settings()
    with pytest.raises(ValidationError):
        settings.user.timezone = "Asia/Jerusalem"  # type: ignore[misc]  # the point: it's frozen


def test_deep_merge_merges_mappings_and_replaces_everything_else() -> None:
    base: dict[str, object] = {"a": {"x": 1, "y": [1, 2]}, "b": 1, "c": {"z": 1}}
    override: dict[str, object] = {"a": {"y": [3]}, "b": {"new": 2}, "c": None}
    assert deep_merge(base, override) == {"a": {"x": 1, "y": [3]}, "b": {"new": 2}, "c": None}


def test_deep_merge_does_not_modify_its_inputs() -> None:
    base: dict[str, object] = {"a": {"x": 1}}
    override: dict[str, object] = {"a": {"y": 2}}
    deep_merge(base, override)
    assert base == {"a": {"x": 1}}
    assert override == {"a": {"y": 2}}
