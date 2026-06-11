"""Regression tests for OR-join trigger_rule validation in archon-dark-factory.yaml.

These tests guard against a class of silent workflow breakage (issue #224):
commit ce9e4a3 introduced OR-join nodes with the default all_success trigger_rule,
causing validate/conformance/code-review/push-and-pr/report to be permanently skipped.
"""

import sys
import textwrap
from io import StringIO
from pathlib import Path

import pytest
import yaml

# Add dark-factory/scripts to path so we can import the module directly.
_SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from check_workflow_dag import (  # noqa: E402
    EXPECTED_TRIGGER_RULE_COUNT,
    REQUIRED_OR_JOIN_NODES,
    SKIP_TOLERANT_RULES,
    check,
)

_WORKFLOW_PATH = (
    Path(__file__).resolve().parents[2]
    / ".archon" / "workflows" / "archon-dark-factory.yaml"
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_workflow(nodes: list[dict]) -> str:
    """Return minimal workflow YAML containing *nodes*."""
    return yaml.dump({"name": "test-workflow", "nodes": nodes})


def _write_tmp(tmp_path: Path, content: str) -> Path:
    p = tmp_path / "workflow.yaml"
    p.write_text(content, encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# Happy-path: current workflow must pass
# ---------------------------------------------------------------------------

def test_current_workflow_passes():
    """The live archon-dark-factory.yaml must have zero OR-join errors."""
    assert _WORKFLOW_PATH.exists(), f"Workflow file not found: {_WORKFLOW_PATH}"
    errors = check(_WORKFLOW_PATH)
    assert errors == [], "\n".join(errors)


# ---------------------------------------------------------------------------
# Regression: pre-fix validate node (ce9e4a3 state) must be caught
# ---------------------------------------------------------------------------

def test_regression_pre_fix_validate_missing_trigger_rule(tmp_path):
    """A validate node with depends_on=[preview-up, preview-up-resolve] but NO
    trigger_rule reproduces the ce9e4a3 regression and must be rejected."""
    nodes = [
        # All other required OR-join nodes present and correct
        {"id": "de-conflict",       "trigger_rule": "none_failed_min_one_success", "depends_on": ["regen-codeindex", "setup-branch-resolve"]},
        {"id": "status-in-review",  "trigger_rule": "none_failed_min_one_success", "depends_on": ["push-and-pr", "push-resolve", "code-review"]},
        {"id": "report",            "trigger_rule": "none_failed_min_one_success", "depends_on": ["status-in-review", "code-review"]},
        # validate: pre-fix state — no trigger_rule
        {"id": "validate", "depends_on": ["preview-up", "preview-up-resolve"]},
    ]
    path = _write_tmp(tmp_path, _make_workflow(nodes))
    errors = check(path)
    assert any("validate" in e for e in errors), (
        f"Expected an error about 'validate' but got: {errors}"
    )


def test_regression_all_success_trigger_rule(tmp_path):
    """Explicitly setting trigger_rule: all_success on an OR-join node must be caught."""
    nodes = [
        {"id": "de-conflict",       "trigger_rule": "none_failed_min_one_success"},
        {"id": "status-in-review",  "trigger_rule": "none_failed_min_one_success"},
        {"id": "report",            "trigger_rule": "none_failed_min_one_success"},
        # validate: wrong trigger_rule
        {"id": "validate", "trigger_rule": "all_success", "depends_on": ["preview-up", "preview-up-resolve"]},
    ]
    path = _write_tmp(tmp_path, _make_workflow(nodes))
    errors = check(path)
    assert any("validate" in e for e in errors), (
        f"Expected an error about 'validate' but got: {errors}"
    )


# ---------------------------------------------------------------------------
# Count tripwire
# ---------------------------------------------------------------------------

def test_tripwire_fires_when_count_increases(tmp_path):
    """Adding a fifth trigger_rule node without updating the guard triggers the tripwire."""
    nodes = [
        {"id": "validate",          "trigger_rule": "none_failed_min_one_success"},
        {"id": "de-conflict",       "trigger_rule": "none_failed_min_one_success"},
        {"id": "status-in-review",  "trigger_rule": "none_failed_min_one_success"},
        {"id": "report",            "trigger_rule": "none_failed_min_one_success"},
        # surprise new OR-join node without updating the guard
        {"id": "new-or-join",       "trigger_rule": "none_failed_min_one_success"},
    ]
    path = _write_tmp(tmp_path, _make_workflow(nodes))
    errors = check(path)
    assert any("trigger_rule" in e and "5" in e for e in errors), (
        f"Expected a count-tripwire error but got: {errors}"
    )


def test_tripwire_fires_when_count_decreases(tmp_path):
    """Removing a trigger_rule node without updating the guard also triggers the tripwire."""
    nodes = [
        {"id": "validate",          "trigger_rule": "none_failed_min_one_success"},
        {"id": "de-conflict",       "trigger_rule": "none_failed_min_one_success"},
        {"id": "status-in-review",  "trigger_rule": "none_failed_min_one_success"},
        # report removed — count drops to 3
    ]
    path = _write_tmp(tmp_path, _make_workflow(nodes))
    errors = check(path)
    # Should flag missing 'report' node AND count mismatch
    assert errors, f"Expected errors but got none"
    assert any("report" in e for e in errors), (
        f"Expected an error about 'report' but got: {errors}"
    )


# ---------------------------------------------------------------------------
# one_success is also accepted
# ---------------------------------------------------------------------------

def test_one_success_is_accepted(tmp_path):
    """one_success is a valid skip-tolerant trigger_rule and must not produce errors."""
    nodes = [
        {"id": "validate",          "trigger_rule": "one_success"},
        {"id": "de-conflict",       "trigger_rule": "one_success"},
        {"id": "status-in-review",  "trigger_rule": "one_success"},
        {"id": "report",            "trigger_rule": "one_success"},
    ]
    path = _write_tmp(tmp_path, _make_workflow(nodes))
    errors = check(path)
    assert errors == [], "\n".join(errors)
