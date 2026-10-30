"""app.decisions must stay importable without brokers, order code, or app-layer packages.

Two checks (spec §2): an AST walk over every source file, and a fresh-interpreter import —
the in-process ``sys.modules`` is useless here because tests/conftest.py imports app.main.
"""

import ast
import json
import pathlib
import subprocess
import sys

import pytest

BACKEND_DIR = pathlib.Path(__file__).resolve().parents[2]
PACKAGE_DIR = BACKEND_DIR / "app" / "decisions"
PACKAGE = "app.decisions"
FORBIDDEN_PREFIXES = (
    "ib_insync",
    "app.schemas",
    "app.providers",
    "app.services",
    "app.models",
    "app.routers",
    "app.tasks",
)


def _is_forbidden(module: str) -> bool:
    return any(module == p or module.startswith(p + ".") for p in FORBIDDEN_PREFIXES)


def _resolve_relative(module: str | None, level: int, current: str) -> str:
    parts = current.split(".")
    base = parts[: len(parts) - level]
    return ".".join(base + ([module] if module else []))


def _imported_modules(source: str, current: str) -> set[str]:
    """Every dotted module name a source file can bind via import statements or calls."""
    found: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            module = (
                _resolve_relative(node.module, node.level, current)
                if node.level
                else node.module or ""
            )
            found.add(module)
            found.update(f"{module}.{alias.name}" for alias in node.names)
        elif (
            isinstance(node, ast.Call)
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
            and (
                (isinstance(node.func, ast.Name) and node.func.id == "__import__")
                or (
                    isinstance(node.func, ast.Attribute)
                    and node.func.attr == "import_module"
                )
            )
        ):
            found.add(node.args[0].value)
    return found


def _package_sources() -> list[pathlib.Path]:
    files = sorted(PACKAGE_DIR.rglob("*.py"))
    assert files, f"no sources found under {PACKAGE_DIR}"
    return files


@pytest.mark.parametrize(
    "source",
    [
        "import ib_insync",
        "from ib_insync import IB",
        "from app.schemas.quality_gate import QualityGateVerdict",
        "import app.services.trading_service",
        "from app import models",
        "from .. import providers",
        "import importlib\nimportlib.import_module('app.tasks.trading')",
        "__import__('app.routers.scanner')",
    ],
)
def test_checker_detects_forbidden_imports(source):
    found = _imported_modules(source, current=f"{PACKAGE}.schema")
    assert any(_is_forbidden(m) for m in found), found


def test_checker_allows_stdlib_pydantic_and_own_package():
    source = (
        "import hashlib\nfrom pydantic import BaseModel\n"
        "from app.decisions.schema import FrozenContract\nfrom .request import DecisionRequest"
    )
    found = _imported_modules(source, current=f"{PACKAGE}.policy")
    assert not any(_is_forbidden(m) for m in found), found


def test_no_forbidden_import_prefixes():
    violations = []
    for path in _package_sources():
        rel = path.relative_to(BACKEND_DIR).with_suffix("")
        current = ".".join(rel.parts)
        for module in _imported_modules(path.read_text(), current):
            if _is_forbidden(module):
                violations.append(f"{path.name}: {module}")
    assert not violations, f"app.decisions imports forbidden modules: {violations}"


def test_fresh_import_leaves_no_forbidden_modules():
    code = (
        "import json, sys; import app.decisions; print(json.dumps(sorted(sys.modules)))"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code],
        cwd=BACKEND_DIR,
        capture_output=True,
        text=True,
        timeout=60,
        check=True,
    )
    loaded = json.loads(proc.stdout.strip().splitlines()[-1])
    assert "app.decisions" in loaded
    leaked = [m for m in loaded if _is_forbidden(m) or "auto_trade" in m]
    assert not leaked, f"importing app.decisions loaded {leaked}"


def test_package_reexports_resolve():
    import app.decisions

    missing = [n for n in app.decisions.__all__ if not hasattr(app.decisions, n)]
    assert not missing, missing
    assert {
        "DecisionSchema",
        "DecisionRequest",
        "DecisionResult",
        "DecisionProvider",
        "decide",
    } <= set(app.decisions.__all__)
