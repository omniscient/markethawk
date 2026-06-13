"""Tests for check_workflow_when.py — `when:` expression linter.

Guards against the class of invalid `when:` expression (parenthesised or mixed
&&/|| operators) that caused the #397 factory outage when PR #359 merged without
a CI gate.
"""

import sys
from pathlib import Path

import pytest
import yaml

_SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from check_workflow_when import check  # noqa: E402

_WORKFLOW_PATH = (
    Path(__file__).resolve().parents[2]
    / ".archon" / "workflows" / "archon-dark-factory.yaml"
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_workflow(nodes: list[dict]) -> str:
    return yaml.dump({"name": "test-workflow", "nodes": nodes})


def _write_tmp(tmp_path: Path, content: str) -> Path:
    p = tmp_path / "workflow.yaml"
    p.write_text(content, encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# Happy-path: live production file must pass
# ---------------------------------------------------------------------------

def test_current_workflow_passes():
    """The live archon-dark-factory.yaml must produce zero when: lint errors."""
    assert _WORKFLOW_PATH.exists(), f"Workflow file not found: {_WORKFLOW_PATH}"
    errors = check(_WORKFLOW_PATH)
    assert errors == [], "\n".join(errors)


# ---------------------------------------------------------------------------
# Allowed expressions
# ---------------------------------------------------------------------------

def test_simple_equality_allowed(tmp_path):
    """A simple equality expression is valid."""
    nodes = [{"id": "a", "when": "$node.output == 'value'"}]
    path = _write_tmp(tmp_path, _make_workflow(nodes))
    assert check(path) == []


def test_same_operator_chain_allowed(tmp_path):
    """Same-operator chaining (triple-OR) must be accepted — in active production use."""
    expr = "$parse-intent.output.intent == 'new' || $parse-intent.output.intent == 'continue' || $parse-intent.output.intent == 'resolve'"
    nodes = [{"id": "a", "when": expr}]
    path = _write_tmp(tmp_path, _make_workflow(nodes))
    assert check(path) == []


def test_triple_and_allowed(tmp_path):
    """Same-operator chaining with && (no || present) must be accepted."""
    expr = "$a.output == 'x' && $b.output == 'y' && $c.output == 'z'"
    nodes = [{"id": "a", "when": expr}]
    path = _write_tmp(tmp_path, _make_workflow(nodes))
    assert check(path) == []


# ---------------------------------------------------------------------------
# Rejected expressions
# ---------------------------------------------------------------------------

def test_parentheses_rejected(tmp_path):
    """An expression containing parentheses must be rejected."""
    nodes = [{"id": "a", "when": "($a.output == 'x') && $b.output == 'y'"}]
    path = _write_tmp(tmp_path, _make_workflow(nodes))
    errors = check(path)
    assert errors, "Expected an error for parenthesised expression"
    assert any("parenthes" in e.lower() or "(" in e for e in errors)


def test_mixed_operators_rejected(tmp_path):
    """An expression mixing && and || must be rejected."""
    nodes = [{"id": "a", "when": "$a.output == 'x' && $b.output == 'y' || $c.output == 'z'"}]
    path = _write_tmp(tmp_path, _make_workflow(nodes))
    errors = check(path)
    assert errors, "Expected an error for mixed-operator expression"
    assert any("mix" in e.lower() or "&&" in e or "||" in e for e in errors)


# ---------------------------------------------------------------------------
# Regression: exact PR #359 expression must be rejected
# ---------------------------------------------------------------------------

def test_regression_pr359_expression_rejected(tmp_path):
    """The exact parenthesised expression from PR #359 that broke the factory must be caught."""
    pr359_expr = "($parse-intent.output.intent == 'new') && $bench-mode-probe.output == 'live'"
    nodes = [{"id": "implement", "when": pr359_expr}]
    path = _write_tmp(tmp_path, _make_workflow(nodes))
    errors = check(path)
    assert errors, (
        f"PR #359 regression: expected lint to catch parenthesised expression but got no errors"
    )
