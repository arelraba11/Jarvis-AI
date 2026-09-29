"""The composition root: where the app is assembled from config (docs/systems/llm.md).

The only module allowed to import concrete providers. Core, the router and the loop know only the
`LLMProvider` interface; adding a provider means registering its factory here.
"""

from jarvis.core.config import Settings
from jarvis.core.secret_store import SecretStore
from jarvis.llm.anthropic_provider import anthropic_factory
from jarvis.llm.router import ModelRouter, ProviderFactory


def provider_factories(secrets: SecretStore) -> dict[str, ProviderFactory]:
    """Provider name (as written in config `models`) -> factory."""
    return {"anthropic": anthropic_factory(secrets)}


def build_router(settings: Settings, secrets: SecretStore) -> ModelRouter:
    return ModelRouter(settings.models, provider_factories(secrets))
