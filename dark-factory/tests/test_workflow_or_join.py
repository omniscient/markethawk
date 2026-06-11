"""Regression tests for OR-join trigger_rule validation in archon-dark-factory.yaml.

These tests guard against a class of silent workflow breakage (issue #224):
commit ce9e4a3 introduced OR-join nodes with the default all_success trigger_rule,
causing validate/conformance/code-review/push-and-pr/report to be permanently skipped.
"""

import sys
from pathlib import Path

import pytest
import yaml

# Add dark-factory/scripts to path so we can import the module directly.
_SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from check_workflow_dag import check  # noqa: E402

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


# Four OR-join nodes with correct rules — used as a baseline in several fixtures.
_KNOWN_OR_JOINS = [
    {"id": "validate",         "trigger_rule": "none_failed_min_one_success", "depends_on": ["a", "b"]},
    {"id": "de-conflict",      "trigger_rule": "none_failed_min_one_success", "depends_on": ["c", "d"]},
    {"id": "status-in-review", "trigger_rule": "none_failed_min_one_success", "depends_on": ["e", "f"]},
    {"id": "report",           "trigger_rule": "none_failed_min_one_success", "depends_on": ["g", "h"]},
]


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
# Allowlist: missing known OR-join node is caught
# ---------------------------------------------------------------------------

def test_allowlist_catches_missing_or_join_node(tmp_path):
    """Removing a known OR-join node from the workflow is flagged by the allowlist check."""
    nodes = [
        {"id": "validate",          "trigger_rule": "none_failed_min_one_success"},
        {"id": "de-conflict",       "trigger_rule": "none_failed_min_one_success"},
        {"id": "status-in-review",  "trigger_rule": "none_failed_min_one_success"},
        # report removed
    ]
    path = _write_tmp(tmp_path, _make_workflow(nodes))
    errors = check(path)
    assert errors, "Expected errors but got none"
    assert any("report" in e for e in errors), (
        f"Expected an error about missing 'report' but got: {errors}"
    )


# ---------------------------------------------------------------------------
# Structural check: catches new OR-join nodes outside the allowlist
# ---------------------------------------------------------------------------

def test_structural_check_catches_new_or_join_without_rule(tmp_path):
    """A new node whose every upstream has a 'when:' condition but itself lacks a
    skip-tolerant trigger_rule is detected by the structural check.

    This is the precise blind spot of the old count-tripwire approach: a node added
    with NO trigger_rule has no rule to count and is not in the allowlist, so the old
    check would silently pass it.
    """
    nodes = _KNOWN_OR_JOINS + [
        # Two conditional upstreams
        {"id": "branch-a", "when": "$intent == 'new'"},
        {"id": "branch-b", "when": "$intent == 'resolve'"},
        # New OR-join: all upstreams are conditional, but no trigger_rule
        {"id": "new-join", "depends_on": ["branch-a", "branch-b"]},
    ]
    path = _write_tmp(tmp_path, _make_workflow(nodes))
    errors = check(path)
    assert any("new-join" in e for e in errors), (
        f"Expected a structural-check error about 'new-join' but got: {errors}"
    )


def test_structural_check_passes_for_correct_new_or_join(tmp_path):
    """A new node with all conditional upstreams and a skip-tolerant trigger_rule
    is accepted without errors."""
    nodes = _KNOWN_OR_JOINS + [
        {"id": "branch-a", "when": "$intent == 'new'"},
        {"id": "branch-b", "when": "$intent == 'resolve'"},
        # Correct: skip-tolerant rule present
        {"id": "new-join", "depends_on": ["branch-a", "branch-b"],
         "trigger_rule": "none_failed_min_one_success"},
    ]
    path = _write_tmp(tmp_path, _make_workflow(nodes))
    errors = check(path)
    assert errors == [], "\n".join(errors)


def test_structural_check_ignores_and_join_with_unconditional_upstream(tmp_path):
    """A node with an unconditional upstream (no 'when:') is not flagged even without
    a trigger_rule, because it's an AND-join (all upstreams run together)."""
    nodes = _KNOWN_OR_JOINS + [
        {"id": "cond-node",  "when": "$intent == 'new'"},
        {"id": "always-run"},  # no 'when:' — unconditional
        # AND-join: structural check should not fire
        {"id": "and-join", "depends_on": ["cond-node", "always-run"]},
    ]
    path = _write_tmp(tmp_path, _make_workflow(nodes))
    errors = check(path)
    assert errors == [], "\n".join(errors)


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
