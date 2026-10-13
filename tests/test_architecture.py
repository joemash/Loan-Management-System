"""Hexagonal boundary: the application layer must not depend on frameworks, adapters or infrastructure."""

import ast
from pathlib import Path

import pytest

APPLICATION = Path(__file__).resolve().parents[1] / "src" / "application"

FORBIDDEN = (
    "sqlalchemy",
    "fastapi",
    "starlette",
    "confluent_kafka",
    "prometheus_client",
    "apscheduler",
    "jwt",
    "pydantic",
    "pydantic_settings",
    "src.adapters",
    "src.infrastructure",
)


def _imports(path: Path) -> set[str]:
    modules: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(), filename=str(path))):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            modules.add(node.module)
    return modules


def _matches(module: str, prefix: str) -> bool:
    return module == prefix or module.startswith(prefix + ".")


MODULES = sorted(APPLICATION.rglob("*.py"))


def test_application_layer_is_scanned():
    assert len(MODULES) > 10


@pytest.mark.parametrize("path", MODULES, ids=lambda p: str(p.relative_to(APPLICATION)))
def test_application_module_has_no_outward_dependencies(path: Path):
    imports = _imports(path)
    violations = sorted(m for m in imports for prefix in FORBIDDEN if _matches(m, prefix))
    in_usecases = (APPLICATION / "usecases") in path.parents
    if not in_usecases:
        # Only use cases may use injector's @inject decorator
        violations += sorted(m for m in imports if _matches(m, "injector"))
    assert not violations, f"{path.relative_to(APPLICATION)} imports {violations}"
