import pytest

from fakes.llm import FakeProvider
from jarvis.core.config import RoleModelConfig
from jarvis.llm.contracts import LLMProvider, Role
from jarvis.llm.router import ModelRouter, ModelRouterError


class RecordingFactory:
    """A provider factory that builds a new FakeProvider on each call and remembers each one."""

    def __init__(self) -> None:
        self.configs: list[RoleModelConfig] = []
        self.built: list[tuple[str, FakeProvider]] = []

    def __call__(self, config: RoleModelConfig) -> LLMProvider:
        provider = FakeProvider([])
        self.configs.append(config)
        self.built.append((config.model, provider))
        return provider


def test_a_configured_role_resolves_to_its_provider_built_for_its_model() -> None:
    factory = RecordingFactory()
    router = ModelRouter(
        {Role.PLANNER: RoleModelConfig(provider="fake", model="fake-large")}, {"fake": factory}
    )
    assert [model for model, _ in factory.built] == ["fake-large"]
    assert router.for_role(Role.PLANNER) is factory.built[0][1]


def test_the_factory_gets_the_whole_role_config() -> None:
    # max_tokens and effort reach the provider through its factory, not through the router.
    factory = RecordingFactory()
    config = RoleModelConfig(provider="fake", model="fake-large", max_tokens=2048, effort="low")
    ModelRouter({Role.PLANNER: config}, {"fake": factory})
    assert factory.configs == [config]


def test_each_role_gets_the_provider_and_model_it_is_configured_with() -> None:
    fake, other = RecordingFactory(), RecordingFactory()
    router = ModelRouter(
        {
            Role.PLANNER: RoleModelConfig(provider="fake", model="fake-large"),
            Role.WRITER: RoleModelConfig(provider="other", model="other-small"),
        },
        {"fake": fake, "other": other},
    )
    assert [model for model, _ in fake.built] == ["fake-large"]
    assert [model for model, _ in other.built] == ["other-small"]
    assert router.for_role(Role.PLANNER) is fake.built[0][1]
    assert router.for_role(Role.WRITER) is other.built[0][1]


def test_providers_are_built_once_and_reused() -> None:
    factory = RecordingFactory()
    router = ModelRouter(
        {Role.PLANNER: RoleModelConfig(provider="fake", model="fake-large")}, {"fake": factory}
    )
    first, second = router.for_role(Role.PLANNER), router.for_role(Role.PLANNER)
    assert first is second
    assert len(factory.built) == 1


def test_a_role_with_no_config_entry_fails_naming_the_role() -> None:
    router = ModelRouter(
        {Role.PLANNER: RoleModelConfig(provider="fake", model="fake-large")},
        {"fake": RecordingFactory()},
    )
    with pytest.raises(ModelRouterError, match=r"no model configured for role 'writer'"):
        router.for_role(Role.WRITER)


def test_building_fails_on_a_provider_with_no_registered_factory() -> None:
    # Config can't know which providers exist, so the router checks when it is built.
    factory = RecordingFactory()
    with pytest.raises(
        ModelRouterError,
        match=r"models\.writer: unknown provider 'antropic' \(registered: fake\)",
    ):
        ModelRouter(
            {
                Role.PLANNER: RoleModelConfig(provider="fake", model="fake-large"),
                Role.WRITER: RoleModelConfig(provider="antropic", model="m"),
            },
            {"fake": factory},
        )
    # Every name is checked before any provider is built.
    assert factory.built == []


def test_a_factory_failure_names_the_role_and_provider() -> None:
    # In task 5 a missing Keychain key fails here, at startup; the message must say where.
    missing_key = LookupError("no API key in the Keychain")

    def failing(config: RoleModelConfig) -> LLMProvider:
        raise missing_key

    with pytest.raises(
        ModelRouterError,
        match=r"^models\.planner: provider 'broken' failed to start: no API key in the Keychain$",
    ) as exc:
        ModelRouter(
            {Role.PLANNER: RoleModelConfig(provider="broken", model="m")}, {"broken": failing}
        )
    assert exc.value.__cause__ is missing_key
