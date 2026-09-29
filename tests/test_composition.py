"""The composition root: the one place that knows concrete providers."""

import ast
import shutil
from pathlib import Path

from fakes.secrets import FakeSecretStore
from jarvis.composition import build_router, provider_factories
from jarvis.core.config import CONFIG_DIR, load_settings
from jarvis.llm.contracts import Role

SRC = Path(__file__).parents[1] / "src" / "jarvis"
COMPOSITION = SRC / "composition.py"


def test_the_repo_defaults_build_a_router_whose_planner_is_anthropic(tmp_path: Path) -> None:
    # The CI case: default.yaml only, no local.yaml.
    shutil.copy(CONFIG_DIR / "default.yaml", tmp_path / "default.yaml")
    router = build_router(load_settings(tmp_path), FakeSecretStore({"anthropic": "sk-test"}))
    assert repr(router.for_role(Role.PLANNER)) == "AnthropicProvider(model='claude-sonnet-5-5')"


def test_anthropic_is_a_registered_provider() -> None:
    assert set(provider_factories(FakeSecretStore())) == {"anthropic"}


def _imports(path: Path) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
            names.update(f"{node.module}.{alias.name}" for alias in node.names)
    return names


def test_only_the_composition_root_imports_concrete_providers() -> None:
    # A concrete provider is a jarvis.llm module named *_provider; core and the router know only
    # the LLMProvider interface (CLAUDE.md, docs/systems/llm.md).
    providers = {f"jarvis.llm.{p.stem}" for p in (SRC / "llm").glob("*_provider.py")}
    assert providers, "expected at least one concrete provider module"
    importers = {
        path.relative_to(SRC).as_posix() for path in SRC.rglob("*.py") if _imports(path) & providers
    }
    assert importers == {COMPOSITION.relative_to(SRC).as_posix()}


def test_only_a_provider_module_imports_its_sdk() -> None:
    importers = {
        path.relative_to(SRC).as_posix()
        for path in SRC.rglob("*.py")
        if any(name == "anthropic" or name.startswith("anthropic.") for name in _imports(path))
    }
    assert importers == {"llm/anthropic_provider.py"}
