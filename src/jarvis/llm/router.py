"""ModelRouter: role -> provider, from the `models` section of config (ADR-0003).

The router never imports or names a provider. Whoever builds it (jarvis.composition) passes a
registry of provider name -> factory; the factory takes the role's `RoleModelConfig` (model,
max_tokens, effort) and returns an `LLMProvider`.
"""

from collections.abc import Callable, Mapping

from jarvis.core.config import RoleModelConfig
from jarvis.llm.contracts import LLMProvider, Role

ProviderFactory = Callable[[RoleModelConfig], LLMProvider]


class ModelRouterError(Exception):
    """A role has no model configured, or config names a provider with no registered factory."""


class ModelRouter:
    def __init__(
        self, models: Mapping[Role, RoleModelConfig], factories: Mapping[str, ProviderFactory]
    ) -> None:
        # Every name is checked before any provider is built, so a typo fails at startup
        # with nothing half-built.
        for role, config in models.items():
            if config.provider not in factories:
                registered = ", ".join(sorted(factories)) or "none"
                raise ModelRouterError(
                    f"models.{role}: unknown provider {config.provider!r} "
                    f"(registered: {registered})"
                )
        # Built once here and reused for every call.
        self._providers: dict[Role, LLMProvider] = {}
        for role, config in models.items():
            try:
                self._providers[role] = factories[config.provider](config)
            # Any failure (a missing API key, a value the provider can't honor) is reported with
            # the role and provider it belongs to; the original error stays attached as the cause.
            except Exception as e:
                raise ModelRouterError(
                    f"models.{role}: provider {config.provider!r} failed to start: {e}"
                ) from e

    def for_role(self, role: Role) -> LLMProvider:
        try:
            return self._providers[role]
        except KeyError:
            raise ModelRouterError(
                f"no model configured for role {role.value!r} (add models.{role} to config)"
            ) from None
