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


def _imports_of(source: str, package: str) -> set[str]:
    """Absolute names `source` imports; relative imports start from `package`."""
    parts = package.split(".")
    names: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = parts[: len(parts) - node.level + 1] if node.level else []
            prefix = ".".join([*base, *([node.module] if node.module else [])])
            names.add(prefix)
            names.update(f"{prefix}.{alias.name}" for alias in node.names)
    return names


def _imports(path: Path) -> set[str]:
    # A module's package is its directory; an __init__.py is its own package's code.
    package = ".".join(["jarvis", *path.relative_to(SRC).parent.parts])
    return _imports_of(path.read_text(encoding="utf-8"), package)


def test_relative_imports_are_resolved() -> None:
    # Otherwise `from .anthropic_provider import ...` would slip past the checks below.
    source = "from .anthropic_provider import f\nfrom . import anthropic_provider\n"
    names = _imports_of(source, "jarvis.llm")
    assert "jarvis.llm.anthropic_provider" in names
    assert "jarvis.llm.anthropic_provider.f" in names


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
