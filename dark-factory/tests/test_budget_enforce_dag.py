"""Tests for Phase 4 T3: enforce-budget DAG nodes + per-scenario config."""
import sys
from pathlib import Path

import pytest
import yaml

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CONFIG = _REPO_ROOT / ".claude/skills/refinement/config.yaml"
_WORKFLOW = _REPO_ROOT / ".archon/workflows/archon-dark-factory.yaml"
_LOAD_MEMORY = _REPO_ROOT / "dark-factory/scripts/load_memory_context.sh"
_CODE_REVIEW_CMD = _REPO_ROOT / ".archon/commands/dark-factory-code-review.md"
_CONFORMANCE_CMD = _REPO_ROOT / ".archon/commands/dark-factory-conformance.md"


def _config():
    return yaml.safe_load(_CONFIG.read_text())


def _tok_opt():
    return _config().get("token_optimization", {})


def _workflow_nodes():
    data = yaml.safe_load(_WORKFLOW.read_text())
    return {n["id"]: n for n in data.get("nodes", []) if isinstance(n, dict) and "id" in n}


# ── T3-C1: config default_budget_tokens raised to 30000 ──────────────────────

def test_config_default_budget_tokens_30000():
    assert _tok_opt().get("default_budget_tokens") == 30000, \
        "default_budget_tokens must be 30000 (raised from 24000)"


# ── T3-C2: config has budgets: map ───────────────────────────────────────────

def test_config_has_budgets_map():
    assert "budgets" in _tok_opt(), "token_optimization must have a 'budgets' key"


def test_config_budgets_has_all_scenarios():
    # Kept alongside test_config_budgets_t6_state as independent scenario-presence guard:
    # catches a missing key even if the exact-value dict comparison changes in the future.
    budgets = _tok_opt().get("budgets", {})
    for scenario in ("refine", "plan", "implement", "conformance", "code-review"):
        assert scenario in budgets, f"budgets map must include '{scenario}'"


def test_config_budgets_t6_state():
    budgets = _tok_opt().get("budgets", {})
    expected = {
        "refine": 30000,
        "plan": 30000,
        "implement": 30000,
        "conformance": 22000,
        "code-review": 22000,
    }
    assert budgets == expected, (
        f"budgets must match the T6 intended state {expected}, got {budgets}"
    )


# ── T3-C3: config has enforce: map ───────────────────────────────────────────

def test_config_has_enforce_map():
    assert "enforce" in _tok_opt(), "token_optimization must have an 'enforce' key"


def test_config_enforce_has_all_scenarios():
    # Kept alongside test_config_enforce_t6_state as independent scenario-presence guard:
    # catches a missing key even if the exact-value dict comparison changes in the future.
    enforce = _tok_opt().get("enforce", {})
    for scenario in ("refine", "plan", "implement", "conformance", "code-review"):
        assert scenario in enforce, f"enforce map must include '{scenario}'"


def test_config_enforce_t6_state():
    enforce = _tok_opt().get("enforce", {})
    expected = {
        "refine": True,
        "plan": True,
        "implement": False,
        "conformance": True,
        "code-review": True,
    }
    assert enforce == expected, (
        f"enforce must match the T3b intended state {expected}, got {enforce}"
    )


# ── T3-D1: enforce-budget nodes exist in workflow ────────────────────────────

@pytest.mark.parametrize("node_id", [
    "enforce-budget-refine",
    "enforce-budget-plan",
    "enforce-budget-implement",
    "enforce-budget-conformance",
    "enforce-budget-code-review",
])
def test_enforce_budget_node_exists(node_id):
    nodes = _workflow_nodes()
    assert node_id in nodes, f"Node '{node_id}' not found in workflow"


# ── T3-D2: enforce-budget nodes have correct depends_on ──────────────────────

@pytest.mark.parametrize("node_id,expected_dep", [
    ("enforce-budget-refine",      "budget-refine"),
    ("enforce-budget-plan",        "budget-plan"),
    ("enforce-budget-implement",   "budget-implement"),
    ("enforce-budget-conformance", "budget-conformance"),
    ("enforce-budget-code-review", "budget-code-review"),
])
def test_enforce_budget_node_depends_on_budget(node_id, expected_dep):
    nodes = _workflow_nodes()
    node = nodes.get(node_id, {})
    deps = node.get("depends_on", [])
    assert expected_dep in deps, \
        f"'{node_id}' must include '{expected_dep}' in depends_on, got {deps}"


# ── T3-D3: enforce-budget nodes have no trigger_rule ─────────────────────────

@pytest.mark.parametrize("node_id", [
    "enforce-budget-refine",
    "enforce-budget-plan",
    "enforce-budget-implement",
    "enforce-budget-conformance",
    "enforce-budget-code-review",
])
def test_enforce_budget_node_no_trigger_rule(node_id):
    nodes = _workflow_nodes()
    node = nodes.get(node_id, {})
    assert "trigger_rule" not in node, \
        f"'{node_id}' must NOT have a trigger_rule (single-upstream node)"


# ── T3-D4: enforce-budget nodes have || true (non-fatal) ─────────────────────

@pytest.mark.parametrize("node_id", [
    "enforce-budget-refine",
    "enforce-budget-plan",
    "enforce-budget-implement",
    "enforce-budget-conformance",
    "enforce-budget-code-review",
])
def test_enforce_budget_node_nonfatal(node_id):
    nodes = _workflow_nodes()
    bash = nodes.get(node_id, {}).get("bash", "")
    assert "|| true" in bash, \
        f"'{node_id}' bash block must contain '|| true' (non-fatal)"


# ── T3-D5: enforce-budget nodes have CLONE_DIR fallback ──────────────────────

@pytest.mark.parametrize("node_id", [
    "enforce-budget-refine",
    "enforce-budget-plan",
    "enforce-budget-implement",
    "enforce-budget-conformance",
    "enforce-budget-code-review",
])
def test_enforce_budget_node_clone_dir_fallback(node_id):
    nodes = _workflow_nodes()
    bash = nodes.get(node_id, {}).get("bash", "")
    assert "${CLONE_DIR:-.}" in bash or "CLONE_DIR" in bash, \
        f"'{node_id}' must use ${{CLONE_DIR:-.}} fallback"


# ── T3-D6: enforce-budget nodes have timeout: 30000 ─────────────────────────

@pytest.mark.parametrize("node_id", [
    "enforce-budget-refine",
    "enforce-budget-plan",
    "enforce-budget-implement",
    "enforce-budget-conformance",
    "enforce-budget-code-review",
])
def test_enforce_budget_node_timeout(node_id):
    nodes = _workflow_nodes()
    node = nodes.get(node_id, {})
    assert node.get("timeout") == 30000, \
        f"'{node_id}' must have timeout: 30000"


# ── T3-D7: enforce-budget nodes have correct when: gates ─────────────────────

def test_enforce_budget_refine_when():
    nodes = _workflow_nodes()
    when = nodes.get("enforce-budget-refine", {}).get("when", "")
    assert "refine" in when, \
        "enforce-budget-refine must be gated on refine intent"


def test_enforce_budget_plan_when():
    nodes = _workflow_nodes()
    when = nodes.get("enforce-budget-plan", {}).get("when", "")
    assert "plan" in when, \
        "enforce-budget-plan must be gated on plan intent"


def test_enforce_budget_implement_when():
    nodes = _workflow_nodes()
    when = nodes.get("enforce-budget-implement", {}).get("when", "")
    assert "new" in when and "continue" in when, \
        "enforce-budget-implement must be gated on new|continue intent"


def test_enforce_budget_conformance_when():
    nodes = _workflow_nodes()
    when = nodes.get("enforce-budget-conformance", {}).get("when", "")
    assert "new" in when and "continue" in when, \
        "enforce-budget-conformance must be gated on new|continue intent"


def test_enforce_budget_code_review_when():
    nodes = _workflow_nodes()
    when = nodes.get("enforce-budget-code-review", {}).get("when", "")
    assert "new" in when and "continue" in when, \
        "enforce-budget-code-review must be gated on new|continue intent"


# ── T3-D8: command nodes updated to depend on enforce-budget-* ───────────────

@pytest.mark.parametrize("cmd_node,enforce_dep,budget_dep", [
    ("refine",      "enforce-budget-refine",      "budget-refine"),
    ("plan",        "enforce-budget-plan",         "budget-plan"),
    ("implement",   "enforce-budget-implement",    "budget-implement"),
    ("conformance", "enforce-budget-conformance",  "budget-conformance"),
    ("code-review", "enforce-budget-code-review",  "budget-code-review"),
])
def test_command_node_depends_on_enforce_not_budget(cmd_node, enforce_dep, budget_dep):
    nodes = _workflow_nodes()
    node = nodes.get(cmd_node, {})
    deps = node.get("depends_on", [])
    assert enforce_dep in deps, \
        f"'{cmd_node}' must depend on '{enforce_dep}', got {deps}"
    assert budget_dep not in deps, \
        f"'{cmd_node}' must NOT directly depend on '{budget_dep}' (mediated via {enforce_dep})"


# ── T3-D9: implement node retains its trigger_rule ───────────────────────────

def test_implement_retains_trigger_rule():
    nodes = _workflow_nodes()
    node = nodes.get("implement", {})
    assert node.get("trigger_rule") == "none_failed_min_one_success", \
        "implement must retain trigger_rule: none_failed_min_one_success"


# ── T3-D10: DAG validator passes (tripwire count unchanged) ──────────────────

def test_dag_validator_passes():
    sys.path.insert(0, str(_REPO_ROOT / "dark-factory/scripts"))
    from check_workflow_dag import check
    errors = check(_WORKFLOW)
    assert errors == [], "\n".join(errors)


# ── T3-S1: load_memory_context.sh sources token-opt-caps.env ─────────────────

def test_load_memory_context_sources_caps():
    content = _LOAD_MEMORY.read_text()
    assert "token-opt-caps.env" in content, \
        "load_memory_context.sh must source token-opt-caps.env"
    assert "[ -f" in content or "test -f" in content, \
        "load_memory_context.sh must guard with absent-file check"


# ── T3-S2: code-review command sources token-opt-caps.env ────────────────────

def test_code_review_cmd_sources_caps():
    content = _CODE_REVIEW_CMD.read_text()
    assert "token-opt-caps.env" in content, \
        "dark-factory-code-review.md must source token-opt-caps.env"


def test_code_review_cmd_sources_after_rank_in():
    content = _CODE_REVIEW_CMD.read_text()
    rank_pos = content.find("RANK_IN=$(mktemp")
    caps_pos = content.find("token-opt-caps.env")
    assert rank_pos != -1, "code-review must have RANK_IN=$(mktemp ...) block"
    assert caps_pos != -1, "code-review must source token-opt-caps.env"
    assert caps_pos > rank_pos, \
        "token-opt-caps.env must be sourced after RANK_IN=$(mktemp ...)"


# ── T3-S3: conformance command sources token-opt-caps.env ────────────────────

def test_conformance_cmd_sources_caps():
    content = _CONFORMANCE_CMD.read_text()
    assert "token-opt-caps.env" in content, \
        "dark-factory-conformance.md must source token-opt-caps.env"


def test_conformance_cmd_sources_near_diff_rank():
    content = _CONFORMANCE_CMD.read_text()
    # Find the ranking block RANK_IN (not the pre-triage RANK_IN)
    # The ranking block calls diff_rank.py with TRIAGED_DIFF
    rank_pos = content.rfind("RANK_IN=$(mktemp")  # last occurrence = ranking block
    caps_pos = content.rfind("token-opt-caps.env")  # last occurrence
    assert rank_pos != -1, "conformance must have RANK_IN=$(mktemp ...) in ranking block"
    assert caps_pos != -1, "conformance must source token-opt-caps.env"
    assert caps_pos > rank_pos, \
        "token-opt-caps.env must be sourced after RANK_IN=$(mktemp ...) in ranking block"


# ── T4-E1: enforce-budget nodes read env kill-switch ─────────────────────────

@pytest.mark.parametrize("node_id", [
    "enforce-budget-refine",
    "enforce-budget-plan",
    "enforce-budget-implement",
    "enforce-budget-conformance",
    "enforce-budget-code-review",
])
def test_enforce_budget_node_env_kill_switch(node_id):
    nodes = _workflow_nodes()
    bash = nodes.get(node_id, {}).get("bash", "")
    assert "TOKEN_OPTIMIZATION_ENFORCE_BUDGETS" in bash, \
        f"'{node_id}' bash must read TOKEN_OPTIMIZATION_ENFORCE_BUDGETS from env"
    assert ",,}" in bash, \
        f"'{node_id}' bash must use bash 4 lowercase expansion (,,) for the env var"
