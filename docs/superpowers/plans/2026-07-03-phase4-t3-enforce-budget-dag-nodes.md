# Plan: Phase 4 T3 — enforce-budget DAG Nodes + Per-Scenario Config

**Date:** 2026-07-03
**Issue:** #716
**Epic:** #713 (Phase 4 budget enforcement)
**Spec:** `docs/superpowers/specs/2026-07-03-token-opt-phase4-t3-enforce-budget-dag-nodes-design.md`
**Depends on:** T1 (#721 — `budget_enforce.py` merged), T2 (#722 — optimizer cap-override reads merged)

---

## Goal

Wire Phase 4 budget enforcement into the Archon DAG and factory config. Insert five `enforce-budget-<phase>` bash nodes (one per scenario) that call `budget_enforce.py`, add per-scenario `budgets:` and `enforce:` maps to `config.yaml`, and update `load_memory_context.sh` and the two command files that call `diff_rank.py` to source the generated `token-opt-caps.env` so optimizer env overrides actually propagate to subprocesses.

---

## Architecture

```
budget-refine ──→ enforce-budget-refine ──→ refine (command)
budget-plan ────→ enforce-budget-plan ────→ plan (command)
budget-implement → enforce-budget-implement → implement (command)   [OR-join via digest-comments still on implement]
budget-conformance → enforce-budget-conformance → conformance (command)
budget-code-review → enforce-budget-code-review → code-review (command)
```

Each `enforce-budget-<phase>` node: reads `enforce_budgets` + `enforce.<scenario>` + `budgets.<scenario>` from config via single-line Python `-c` (YAML-safe), calls `budget_enforce.py` in observe or enforce mode, redirects stdout to `$ARTIFACTS_DIR/token-opt-caps.env`. The `|| true` fail-open pattern ensures a bad node never kills the run. The enforce-budget-implement node has a single upstream (`budget-implement`) and no `trigger_rule` — the `implement` command node's existing `none_failed_min_one_success` handles the `digest-comments` OR-join.

---

## Tech Stack

- `.archon/workflows/archon-dark-factory.yaml` — Archon DAG (5 new bash nodes, 5 depends_on updates)
- `.claude/skills/refinement/config.yaml` — factory config (raise `default_budget_tokens`, add `budgets:` + `enforce:` maps)
- `dark-factory/scripts/load_memory_context.sh` — source `token-opt-caps.env` before `memory_retrieve.py`
- `.archon/commands/dark-factory-code-review.md` — source `token-opt-caps.env` in Phase 2 diff block
- `.archon/commands/dark-factory-conformance.md` — source `token-opt-caps.env` in Phase 3 ranking block
- `dark-factory/scripts/check_workflow_dag.py` — no changes (no new OR-join nodes; tripwire count unchanged)

---

## File Structure

| File | Change |
|------|--------|
| `.archon/workflows/archon-dark-factory.yaml` | Insert 5 `enforce-budget-*` nodes; update 5 command `depends_on` |
| `.claude/skills/refinement/config.yaml` | Raise `default_budget_tokens` 24000→30000; add `budgets:` + `enforce:` maps |
| `dark-factory/scripts/load_memory_context.sh` | Source `token-opt-caps.env` before `memory_retrieve.py` |
| `.archon/commands/dark-factory-code-review.md` | Source `token-opt-caps.env` at top of Phase 2 diff block |
| `.archon/commands/dark-factory-conformance.md` | Source `token-opt-caps.env` at top of Phase 3 ranking block |
| `dark-factory/tests/test_phase4_t3_config.py` | New: config structure assertions |
| `dark-factory/tests/test_phase4_t3_dag_nodes.py` | New: DAG node + depends_on assertions |
| `dark-factory/tests/test_phase4_t3_sourcing.py` | New: command-file sourcing order assertions |

---

## Task 1: Raise default_budget_tokens and add per-scenario maps in config.yaml

**Goal:** Update `.claude/skills/refinement/config.yaml` under `token_optimization`: raise `default_budget_tokens` from 24000 to 30000, add `budgets:` map (all 30000), add `enforce:` map (all false).

**Files:**
- `.claude/skills/refinement/config.yaml`
- `dark-factory/tests/test_phase4_t3_config.py` (new)

### TDD Steps

**1.1 — Write failing test** — create `dark-factory/tests/test_phase4_t3_config.py`:

```python
"""Tests for Phase 4 T3 config.yaml changes — per-scenario budgets and enforce maps."""
import sys
from pathlib import Path

import yaml

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CONFIG_PATH = _REPO_ROOT / ".claude/skills/refinement/config.yaml"

SCENARIOS = ("refine", "plan", "implement", "conformance", "code-review")


def _load():
    return yaml.safe_load(_CONFIG_PATH.read_text())


def test_default_budget_tokens_raised_to_30000():
    cfg = _load()
    val = cfg["token_optimization"]["default_budget_tokens"]
    assert val == 30000, f"Expected 30000 but got {val}"


def test_budgets_map_present_with_all_scenarios():
    cfg = _load()
    budgets = cfg["token_optimization"].get("budgets", {})
    for s in SCENARIOS:
        assert s in budgets, f"Missing budgets.{s}"
        assert budgets[s] == 30000, f"Expected budgets.{s}=30000, got {budgets[s]}"


def test_enforce_map_present_all_false():
    cfg = _load()
    enforce = cfg["token_optimization"].get("enforce", {})
    for s in SCENARIOS:
        assert s in enforce, f"Missing enforce.{s}"
        assert enforce[s] is False, f"Expected enforce.{s}=false, got {enforce[s]}"
```

**1.2 — Verify test fails:**
```bash
cd /workspace/markethawk && python -m pytest dark-factory/tests/test_phase4_t3_config.py -x -v 2>&1 | tail -20
```
Expected output: `FAILED test_phase4_t3_config.py::test_default_budget_tokens_raised_to_30000 — AssertionError: Expected 30000 but got 24000`

**1.3 — Implement: edit `.claude/skills/refinement/config.yaml`**

Change line:
```yaml
  default_budget_tokens: 24000  # per-scenario budget when no override is set; env: TOKEN_OPTIMIZATION_DEFAULT_BUDGET_TOKENS overrides
```
to:
```yaml
  default_budget_tokens: 30000  # per-scenario budget when no override is set; env: TOKEN_OPTIMIZATION_DEFAULT_BUDGET_TOKENS overrides
```

After the `enforce_budgets:` line (and before `issue_context:`), insert:
```yaml
  budgets:                      # per-scenario budget override (all 30000 initially; T6 calibrates)
    refine: 30000
    plan: 30000
    implement: 30000
    conformance: 30000
    code-review: 30000
  enforce:                      # per-scenario enforcement toggle (all false — T6 flips after T4/T5 calibration)
    refine: false
    plan: false
    implement: false
    conformance: false
    code-review: false
```

**1.4 — Verify test passes:**
```bash
cd /workspace/markethawk && python -m pytest dark-factory/tests/test_phase4_t3_config.py -v 2>&1 | tail -20
```
Expected: `3 passed`

**1.5 — Commit:**
```bash
git add .claude/skills/refinement/config.yaml dark-factory/tests/test_phase4_t3_config.py
git commit -m "feat(token-opt): raise default_budget_tokens to 30000; add per-scenario budgets + enforce maps (#716)"
```

---

## Task 2: Insert enforce-budget-refine and enforce-budget-plan nodes

**Goal:** Add `enforce-budget-refine` (before `refine` command) and `enforce-budget-plan` (before `plan` command) bash nodes. Update `refine` and `plan` command `depends_on` to point to the new enforce nodes.

**Files:**
- `.archon/workflows/archon-dark-factory.yaml`
- `dark-factory/tests/test_phase4_t3_dag_nodes.py` (new)

### TDD Steps

**2.1 — Write failing test** — create `dark-factory/tests/test_phase4_t3_dag_nodes.py`:

```python
"""Tests for Phase 4 T3 DAG node insertions in archon-dark-factory.yaml."""
import sys
from pathlib import Path

import yaml

_REPO_ROOT = Path(__file__).resolve().parents[2]
_WORKFLOW_PATH = _REPO_ROOT / ".archon/workflows/archon-dark-factory.yaml"

# Add scripts dir for check_workflow_dag import
_SCRIPTS = _REPO_ROOT / "dark-factory/scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from check_workflow_dag import check  # noqa: E402


def _nodes():
    data = yaml.safe_load(_WORKFLOW_PATH.read_text())
    return {n["id"]: n for n in data["nodes"] if isinstance(n, dict) and "id" in n}


# ── enforce-budget-refine ────────────────────────────────────────────────────

def test_enforce_budget_refine_exists():
    assert "enforce-budget-refine" in _nodes(), "Missing enforce-budget-refine"


def test_enforce_budget_refine_depends_on_budget_refine():
    n = _nodes()["enforce-budget-refine"]
    assert n.get("depends_on") == ["budget-refine"]


def test_enforce_budget_refine_when_gate():
    n = _nodes()["enforce-budget-refine"]
    assert n.get("when") == "$parse-intent.output.intent == 'refine'"


def test_enforce_budget_refine_timeout():
    n = _nodes()["enforce-budget-refine"]
    assert n.get("timeout") == 30000


def test_enforce_budget_refine_fail_open():
    n = _nodes()["enforce-budget-refine"]
    assert "|| true" in n.get("bash", ""), "enforce-budget-refine must be fail-open (|| true)"


def test_enforce_budget_refine_no_trigger_rule():
    n = _nodes()["enforce-budget-refine"]
    assert "trigger_rule" not in n, "enforce-budget-refine must not have a trigger_rule"


# ── enforce-budget-plan ──────────────────────────────────────────────────────

def test_enforce_budget_plan_exists():
    assert "enforce-budget-plan" in _nodes(), "Missing enforce-budget-plan"


def test_enforce_budget_plan_depends_on_budget_plan():
    n = _nodes()["enforce-budget-plan"]
    assert n.get("depends_on") == ["budget-plan"]


def test_enforce_budget_plan_when_gate():
    n = _nodes()["enforce-budget-plan"]
    assert n.get("when") == "$parse-intent.output.intent == 'plan'"


def test_enforce_budget_plan_no_trigger_rule():
    n = _nodes()["enforce-budget-plan"]
    assert "trigger_rule" not in n, "enforce-budget-plan must not have a trigger_rule"


# ── refine command node update ───────────────────────────────────────────────

def test_refine_command_depends_on_enforce_not_budget():
    n = _nodes()["refine"]
    deps = n.get("depends_on", [])
    assert "enforce-budget-refine" in deps, "refine must depend on enforce-budget-refine"
    assert "budget-refine" not in deps, "refine must not depend directly on budget-refine"


# ── plan command node update ─────────────────────────────────────────────────

def test_plan_command_depends_on_enforce_not_budget():
    n = _nodes()["plan"]
    deps = n.get("depends_on", [])
    assert "enforce-budget-plan" in deps, "plan must depend on enforce-budget-plan"
    assert "budget-plan" not in deps, "plan must not depend directly on budget-plan"


# ── DAG validator (run after each task, included here as the definitive gate) ─

def test_dag_validator_passes():
    errors = check(_WORKFLOW_PATH)
    assert errors == [], "check_workflow_dag errors:\n" + "\n".join(errors)
```

**2.2 — Verify test fails:**
```bash
cd /workspace/markethawk && python -m pytest dark-factory/tests/test_phase4_t3_dag_nodes.py -x -v -k "refine or plan" 2>&1 | tail -20
```
Expected: `FAILED — AssertionError: Missing enforce-budget-refine`

**2.3 — Implement: insert enforce-budget-refine node**

In `.archon/workflows/archon-dark-factory.yaml`, immediately before the `# Layer 2a: Refine` comment (after the closing lines of the `budget-refine` node), insert:

```yaml
  # Budget enforcement — runs after budget-refine writes context-budget.json
  - id: enforce-budget-refine
    bash: |
      _CLONE="${CLONE_DIR:-.}"
      _CFG="${_CLONE}/.claude/skills/refinement/config.yaml"
      _EB=$(python3 -c "import yaml,sys; c=yaml.safe_load(open(sys.argv[1])); print('true' if c.get('token_optimization',{}).get('enforce_budgets') else 'false')" "$_CFG" 2>/dev/null||echo false)
      _SE=$(python3 -c "import yaml,sys; c=yaml.safe_load(open(sys.argv[1])); print('true' if c.get('token_optimization',{}).get('enforce',{}).get('refine') else 'false')" "$_CFG" 2>/dev/null||echo false)
      _BUDGET=$(python3 -c "import yaml,sys; c=yaml.safe_load(open(sys.argv[1])); t=c.get('token_optimization',{}); print(int(t.get('budgets',{}).get('refine',t.get('default_budget_tokens',30000))))" "$_CFG" 2>/dev/null||echo 30000)
      _MODE=observe
      [ "${_EB:-false}" = "true" ] && [ "${_SE:-false}" = "true" ] && _MODE=enforce
      if [ ! -f "${ARTIFACTS_DIR}/context-budget.json" ]; then
        echo "enforce-budget-refine: context-budget.json absent — skipped" >&2; exit 0
      fi
      python3 "${_CLONE}/dark-factory/scripts/budget_enforce.py" \
        --context-budget-json "${ARTIFACTS_DIR}/context-budget.json" \
        --budget-tokens "${_BUDGET:-30000}" \
        --mode "${_MODE}" \
        --config "${_CFG}" \
        > "${ARTIFACTS_DIR}/token-opt-caps.env" 2>/dev/null || true
      echo "enforce-budget-refine: mode=${_MODE} budget=${_BUDGET:-30000}" >&2
    depends_on: [budget-refine]
    when: "$parse-intent.output.intent == 'refine'"
    timeout: 30000
```

Update the existing `refine` command node's `depends_on`:
```yaml
  - id: refine
    command: dark-factory-refine
    depends_on: [enforce-budget-refine, setup-refine-branch, fetch-issue]
```

**2.4 — Implement: insert enforce-budget-plan node**

Immediately before `# Layer 2b: Plan` (after the closing lines of `budget-plan`), insert:

```yaml
  # Budget enforcement — runs after budget-plan writes context-budget.json
  - id: enforce-budget-plan
    bash: |
      _CLONE="${CLONE_DIR:-.}"
      _CFG="${_CLONE}/.claude/skills/refinement/config.yaml"
      _EB=$(python3 -c "import yaml,sys; c=yaml.safe_load(open(sys.argv[1])); print('true' if c.get('token_optimization',{}).get('enforce_budgets') else 'false')" "$_CFG" 2>/dev/null||echo false)
      _SE=$(python3 -c "import yaml,sys; c=yaml.safe_load(open(sys.argv[1])); print('true' if c.get('token_optimization',{}).get('enforce',{}).get('plan') else 'false')" "$_CFG" 2>/dev/null||echo false)
      _BUDGET=$(python3 -c "import yaml,sys; c=yaml.safe_load(open(sys.argv[1])); t=c.get('token_optimization',{}); print(int(t.get('budgets',{}).get('plan',t.get('default_budget_tokens',30000))))" "$_CFG" 2>/dev/null||echo 30000)
      _MODE=observe
      [ "${_EB:-false}" = "true" ] && [ "${_SE:-false}" = "true" ] && _MODE=enforce
      if [ ! -f "${ARTIFACTS_DIR}/context-budget.json" ]; then
        echo "enforce-budget-plan: context-budget.json absent — skipped" >&2; exit 0
      fi
      python3 "${_CLONE}/dark-factory/scripts/budget_enforce.py" \
        --context-budget-json "${ARTIFACTS_DIR}/context-budget.json" \
        --budget-tokens "${_BUDGET:-30000}" \
        --mode "${_MODE}" \
        --config "${_CFG}" \
        > "${ARTIFACTS_DIR}/token-opt-caps.env" 2>/dev/null || true
      echo "enforce-budget-plan: mode=${_MODE} budget=${_BUDGET:-30000}" >&2
    depends_on: [budget-plan]
    when: "$parse-intent.output.intent == 'plan'"
    timeout: 30000
```

Update the `plan` command node:
```yaml
  - id: plan
    command: dark-factory-plan
    depends_on: [enforce-budget-plan, setup-refine-branch, fetch-issue]
```

**2.5 — Verify tests pass + DAG validates:**
```bash
cd /workspace/markethawk && python -m pytest dark-factory/tests/test_phase4_t3_dag_nodes.py -v -k "refine or plan or dag" 2>&1 | tail -25
```
Expected: all matching tests pass, `test_dag_validator_passes` green.

**2.6 — Commit:**
```bash
git add .archon/workflows/archon-dark-factory.yaml dark-factory/tests/test_phase4_t3_dag_nodes.py
git commit -m "feat(token-opt): add enforce-budget-refine and enforce-budget-plan DAG nodes (#716)"
```

---

## Task 3: Insert enforce-budget-implement node

**Goal:** Add `enforce-budget-implement` node between `budget-implement` and the `implement` command node. Single upstream (`budget-implement`), no `trigger_rule` — the `implement` command node's existing `none_failed_min_one_success` already handles the `digest-comments` OR-join.

**Files:**
- `.archon/workflows/archon-dark-factory.yaml`
- `dark-factory/tests/test_phase4_t3_dag_nodes.py` (extend)

### TDD Steps

**3.1 — Extend test file:** add to `dark-factory/tests/test_phase4_t3_dag_nodes.py`:

```python
# ── enforce-budget-implement ─────────────────────────────────────────────────

def test_enforce_budget_implement_exists():
    assert "enforce-budget-implement" in _nodes(), "Missing enforce-budget-implement"


def test_enforce_budget_implement_single_upstream():
    n = _nodes()["enforce-budget-implement"]
    assert n.get("depends_on") == ["budget-implement"], (
        f"enforce-budget-implement must depend only on [budget-implement], "
        f"got {n.get('depends_on')}"
    )


def test_enforce_budget_implement_when_gate():
    n = _nodes()["enforce-budget-implement"]
    assert n.get("when") == (
        "$parse-intent.output.intent == 'new' || "
        "$parse-intent.output.intent == 'continue'"
    )


def test_enforce_budget_implement_no_trigger_rule():
    n = _nodes()["enforce-budget-implement"]
    assert "trigger_rule" not in n, (
        "enforce-budget-implement must not have trigger_rule — "
        "implement's none_failed_min_one_success handles the OR-join"
    )


def test_implement_command_depends_on_enforce_not_budget():
    n = _nodes()["implement"]
    deps = n.get("depends_on", [])
    assert "enforce-budget-implement" in deps, "implement must depend on enforce-budget-implement"
    assert "budget-implement" not in deps, "implement must not depend directly on budget-implement"
    # OR-join deps must remain
    assert "update-codeindex" in deps
    assert "fetch-issue" in deps
    assert "digest-comments" in deps


def test_implement_command_keeps_or_join_trigger_rule():
    n = _nodes()["implement"]
    assert n.get("trigger_rule") == "none_failed_min_one_success", (
        "implement must retain none_failed_min_one_success for digest-comments OR-join"
    )
```

**3.2 — Verify new tests fail:**
```bash
cd /workspace/markethawk && python -m pytest dark-factory/tests/test_phase4_t3_dag_nodes.py -x -v -k "implement" 2>&1 | tail -20
```
Expected: `FAILED — AssertionError: Missing enforce-budget-implement`

**3.3 — Implement: insert enforce-budget-implement node**

In `.archon/workflows/archon-dark-factory.yaml`, immediately before the comment `# Layer 2: Implement the feature` (after the `budget-implement` node's closing lines), insert the following node in full. Note the scenario key `'implement'` in all three Python -c calls and the `new || continue` when-gate (matching `budget-implement` and `implement`):

```yaml
  # Budget enforcement — single upstream (budget-implement), no trigger_rule.
  # The implement command node's none_failed_min_one_success handles the digest-comments OR-join.
  - id: enforce-budget-implement
    bash: |
      _CLONE="${CLONE_DIR:-.}"
      _CFG="${_CLONE}/.claude/skills/refinement/config.yaml"
      _EB=$(python3 -c "import yaml,sys; c=yaml.safe_load(open(sys.argv[1])); print('true' if c.get('token_optimization',{}).get('enforce_budgets') else 'false')" "$_CFG" 2>/dev/null||echo false)
      _SE=$(python3 -c "import yaml,sys; c=yaml.safe_load(open(sys.argv[1])); print('true' if c.get('token_optimization',{}).get('enforce',{}).get('implement') else 'false')" "$_CFG" 2>/dev/null||echo false)
      _BUDGET=$(python3 -c "import yaml,sys; c=yaml.safe_load(open(sys.argv[1])); t=c.get('token_optimization',{}); print(int(t.get('budgets',{}).get('implement',t.get('default_budget_tokens',30000))))" "$_CFG" 2>/dev/null||echo 30000)
      _MODE=observe
      [ "${_EB:-false}" = "true" ] && [ "${_SE:-false}" = "true" ] && _MODE=enforce
      if [ ! -f "${ARTIFACTS_DIR}/context-budget.json" ]; then
        echo "enforce-budget-implement: context-budget.json absent — skipped" >&2; exit 0
      fi
      python3 "${_CLONE}/dark-factory/scripts/budget_enforce.py" \
        --context-budget-json "${ARTIFACTS_DIR}/context-budget.json" \
        --budget-tokens "${_BUDGET:-30000}" \
        --mode "${_MODE}" \
        --config "${_CFG}" \
        > "${ARTIFACTS_DIR}/token-opt-caps.env" 2>/dev/null || true
      echo "enforce-budget-implement: mode=${_MODE} budget=${_BUDGET:-30000}" >&2
    depends_on: [budget-implement]
    when: "$parse-intent.output.intent == 'new' || $parse-intent.output.intent == 'continue'"
    timeout: 30000
```

Update the `implement` command node `depends_on` (keep `trigger_rule` and `idle_timeout` unchanged):
```yaml
  - id: implement
    command: dark-factory-implement
    depends_on: [enforce-budget-implement, update-codeindex, fetch-issue, digest-comments]
    trigger_rule: none_failed_min_one_success
    when: "$parse-intent.output.intent == 'new' || $parse-intent.output.intent == 'continue'"
    idle_timeout: 600000
```

**3.4 — Verify tests pass + DAG validates:**
```bash
cd /workspace/markethawk && python -m pytest dark-factory/tests/test_phase4_t3_dag_nodes.py -v -k "implement or dag" 2>&1 | tail -25
```
Expected: all implement tests and `test_dag_validator_passes` green.

**3.5 — Commit:**
```bash
git add .archon/workflows/archon-dark-factory.yaml dark-factory/tests/test_phase4_t3_dag_nodes.py
git commit -m "feat(token-opt): add enforce-budget-implement DAG node (#716)"
```

---

## Task 4: Insert enforce-budget-conformance and enforce-budget-code-review nodes

**Goal:** Add the final two enforce-budget nodes and update `conformance` and `code-review` command node `depends_on`.

**Files:**
- `.archon/workflows/archon-dark-factory.yaml`
- `dark-factory/tests/test_phase4_t3_dag_nodes.py` (extend)

### TDD Steps

**4.1 — Extend test file:** add to `dark-factory/tests/test_phase4_t3_dag_nodes.py`:

```python
# ── enforce-budget-conformance ───────────────────────────────────────────────

def test_enforce_budget_conformance_exists():
    assert "enforce-budget-conformance" in _nodes(), "Missing enforce-budget-conformance"


def test_enforce_budget_conformance_depends_on_budget_conformance():
    n = _nodes()["enforce-budget-conformance"]
    assert n.get("depends_on") == ["budget-conformance"]


def test_enforce_budget_conformance_when_gate():
    n = _nodes()["enforce-budget-conformance"]
    assert n.get("when") == (
        "$parse-intent.output.intent == 'new' || "
        "$parse-intent.output.intent == 'continue'"
    )


def test_enforce_budget_conformance_no_trigger_rule():
    n = _nodes()["enforce-budget-conformance"]
    assert "trigger_rule" not in n


def test_conformance_command_depends_on_enforce_not_budget():
    n = _nodes()["conformance"]
    deps = n.get("depends_on", [])
    assert "enforce-budget-conformance" in deps
    assert "budget-conformance" not in deps
    assert "validate" in deps


# ── enforce-budget-code-review ───────────────────────────────────────────────

def test_enforce_budget_code_review_exists():
    assert "enforce-budget-code-review" in _nodes(), "Missing enforce-budget-code-review"


def test_enforce_budget_code_review_depends_on_budget_code_review():
    n = _nodes()["enforce-budget-code-review"]
    assert n.get("depends_on") == ["budget-code-review"]


def test_enforce_budget_code_review_when_gate():
    n = _nodes()["enforce-budget-code-review"]
    assert n.get("when") == (
        "$parse-intent.output.intent == 'new' || "
        "$parse-intent.output.intent == 'continue'"
    )


def test_enforce_budget_code_review_no_trigger_rule():
    n = _nodes()["enforce-budget-code-review"]
    assert "trigger_rule" not in n


def test_code_review_command_depends_on_enforce_not_budget():
    n = _nodes()["code-review"]
    deps = n.get("depends_on", [])
    assert "enforce-budget-code-review" in deps
    assert "budget-code-review" not in deps
    assert "push-and-pr" in deps
```

**4.2 — Verify new tests fail:**
```bash
cd /workspace/markethawk && python -m pytest dark-factory/tests/test_phase4_t3_dag_nodes.py -x -v -k "conformance or code_review" 2>&1 | tail -20
```
Expected: `FAILED — AssertionError: Missing enforce-budget-conformance`

**4.3 — Implement: insert enforce-budget-conformance node**

Immediately before `# Layer 3.5: Verify implementation conforms to spec` (after `budget-conformance` node), insert the following node in full. Note the scenario key `'conformance'` in all three Python -c calls:

```yaml
  # Budget enforcement — runs after budget-conformance writes context-budget.json
  - id: enforce-budget-conformance
    bash: |
      _CLONE="${CLONE_DIR:-.}"
      _CFG="${_CLONE}/.claude/skills/refinement/config.yaml"
      _EB=$(python3 -c "import yaml,sys; c=yaml.safe_load(open(sys.argv[1])); print('true' if c.get('token_optimization',{}).get('enforce_budgets') else 'false')" "$_CFG" 2>/dev/null||echo false)
      _SE=$(python3 -c "import yaml,sys; c=yaml.safe_load(open(sys.argv[1])); print('true' if c.get('token_optimization',{}).get('enforce',{}).get('conformance') else 'false')" "$_CFG" 2>/dev/null||echo false)
      _BUDGET=$(python3 -c "import yaml,sys; c=yaml.safe_load(open(sys.argv[1])); t=c.get('token_optimization',{}); print(int(t.get('budgets',{}).get('conformance',t.get('default_budget_tokens',30000))))" "$_CFG" 2>/dev/null||echo 30000)
      _MODE=observe
      [ "${_EB:-false}" = "true" ] && [ "${_SE:-false}" = "true" ] && _MODE=enforce
      if [ ! -f "${ARTIFACTS_DIR}/context-budget.json" ]; then
        echo "enforce-budget-conformance: context-budget.json absent — skipped" >&2; exit 0
      fi
      python3 "${_CLONE}/dark-factory/scripts/budget_enforce.py" \
        --context-budget-json "${ARTIFACTS_DIR}/context-budget.json" \
        --budget-tokens "${_BUDGET:-30000}" \
        --mode "${_MODE}" \
        --config "${_CFG}" \
        > "${ARTIFACTS_DIR}/token-opt-caps.env" 2>/dev/null || true
      echo "enforce-budget-conformance: mode=${_MODE} budget=${_BUDGET:-30000}" >&2
    depends_on: [budget-conformance]
    when: "$parse-intent.output.intent == 'new' || $parse-intent.output.intent == 'continue'"
    timeout: 30000
```

Update `conformance` command node:
```yaml
  - id: conformance
    command: dark-factory-conformance
    depends_on: [enforce-budget-conformance, validate]
    when: "$parse-intent.output.intent == 'new' || $parse-intent.output.intent == 'continue'"
    idle_timeout: 600000
```

**4.4 — Implement: insert enforce-budget-code-review node**

Immediately before `# Layer 4.5: AI code review` (after `budget-code-review` node), insert the following node in full. Note the scenario key `'code-review'` (hyphenated — matches the YAML config key) in all three Python -c calls:

```yaml
  # Budget enforcement — runs after budget-code-review writes context-budget.json
  - id: enforce-budget-code-review
    bash: |
      _CLONE="${CLONE_DIR:-.}"
      _CFG="${_CLONE}/.claude/skills/refinement/config.yaml"
      _EB=$(python3 -c "import yaml,sys; c=yaml.safe_load(open(sys.argv[1])); print('true' if c.get('token_optimization',{}).get('enforce_budgets') else 'false')" "$_CFG" 2>/dev/null||echo false)
      _SE=$(python3 -c "import yaml,sys; c=yaml.safe_load(open(sys.argv[1])); print('true' if c.get('token_optimization',{}).get('enforce',{}).get('code-review') else 'false')" "$_CFG" 2>/dev/null||echo false)
      _BUDGET=$(python3 -c "import yaml,sys; c=yaml.safe_load(open(sys.argv[1])); t=c.get('token_optimization',{}); print(int(t.get('budgets',{}).get('code-review',t.get('default_budget_tokens',30000))))" "$_CFG" 2>/dev/null||echo 30000)
      _MODE=observe
      [ "${_EB:-false}" = "true" ] && [ "${_SE:-false}" = "true" ] && _MODE=enforce
      if [ ! -f "${ARTIFACTS_DIR}/context-budget.json" ]; then
        echo "enforce-budget-code-review: context-budget.json absent — skipped" >&2; exit 0
      fi
      python3 "${_CLONE}/dark-factory/scripts/budget_enforce.py" \
        --context-budget-json "${ARTIFACTS_DIR}/context-budget.json" \
        --budget-tokens "${_BUDGET:-30000}" \
        --mode "${_MODE}" \
        --config "${_CFG}" \
        > "${ARTIFACTS_DIR}/token-opt-caps.env" 2>/dev/null || true
      echo "enforce-budget-code-review: mode=${_MODE} budget=${_BUDGET:-30000}" >&2
    depends_on: [budget-code-review]
    when: "$parse-intent.output.intent == 'new' || $parse-intent.output.intent == 'continue'"
    timeout: 30000
```

Update `code-review` command node:
```yaml
  - id: code-review
    command: dark-factory-code-review
    depends_on: [enforce-budget-code-review, push-and-pr]
    when: "$parse-intent.output.intent == 'new' || $parse-intent.output.intent == 'continue'"
    idle_timeout: 600000
```

**4.5 — Verify all DAG tests pass:**
```bash
cd /workspace/markethawk && python -m pytest dark-factory/tests/test_phase4_t3_dag_nodes.py -v 2>&1 | tail -35
```
Expected: all 26 tests pass.

**4.6 — Run existing OR-join regression suite:**
```bash
cd /workspace/markethawk && python -m pytest dark-factory/tests/test_workflow_or_join.py -v 2>&1 | tail -20
```
Expected: all existing OR-join tests pass, including `test_current_workflow_passes`.

**4.7 — Commit:**
```bash
git add .archon/workflows/archon-dark-factory.yaml dark-factory/tests/test_phase4_t3_dag_nodes.py
git commit -m "feat(token-opt): add enforce-budget-conformance and enforce-budget-code-review DAG nodes (#716)"
```

---

## Task 5: Update load_memory_context.sh to source token-opt-caps.env

**Goal:** Source `$ARTIFACTS_DIR/token-opt-caps.env` before invoking `memory_retrieve.py` so `TOKEN_OPTIMIZATION_MEMORY_MAX_TOKENS` propagates to the subprocess.

**Files:**
- `dark-factory/scripts/load_memory_context.sh`
- `dark-factory/tests/test_phase4_t3_sourcing.py` (new)

### TDD Steps

**5.1 — Write failing test** — create `dark-factory/tests/test_phase4_t3_sourcing.py`:

```python
"""Tests for Phase 4 T3 token-opt-caps.env sourcing in scripts and command files."""
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]

LOAD_MEMORY_PATH = _REPO_ROOT / "dark-factory/scripts/load_memory_context.sh"
CODE_REVIEW_PATH = _REPO_ROOT / ".archon/commands/dark-factory-code-review.md"
CONFORMANCE_PATH = _REPO_ROOT / ".archon/commands/dark-factory-conformance.md"

CAPS_PATTERN = "token-opt-caps.env"


def test_load_memory_sources_caps_before_memory_retrieve():
    content = LOAD_MEMORY_PATH.read_text()
    assert CAPS_PATTERN in content, (
        f"load_memory_context.sh must source {CAPS_PATTERN}"
    )
    caps_pos = content.index(CAPS_PATTERN)
    retrieve_pos = content.index("memory_retrieve.py")
    assert caps_pos < retrieve_pos, (
        f"{CAPS_PATTERN} must appear before memory_retrieve.py "
        f"(positions: caps={caps_pos}, retrieve={retrieve_pos})"
    )
```

**5.2 — Verify test fails:**
```bash
cd /workspace/markethawk && python -m pytest dark-factory/tests/test_phase4_t3_sourcing.py::test_load_memory_sources_caps_before_memory_retrieve -x -v 2>&1 | tail -20
```
Expected: `FAILED — AssertionError: load_memory_context.sh must source token-opt-caps.env`

**5.3 — Implement: edit `dark-factory/scripts/load_memory_context.sh`**

After the `mkdir -p "$ARTIFACTS_DIR"` line and before `MEMORY_CONTEXT=$(python3 ...)`, add:

```bash
# Source caps env so TOKEN_OPTIMIZATION_MEMORY_MAX_TOKENS propagates to memory_retrieve.py subprocess.
# Non-fatal: absent or empty file is a no-op.
[ -f "${ARTIFACTS_DIR}/token-opt-caps.env" ] && . "${ARTIFACTS_DIR}/token-opt-caps.env" || true
```

The relevant section of `load_memory_context.sh` becomes:
```bash
mkdir -p "$ARTIFACTS_DIR"

# Source caps env so TOKEN_OPTIMIZATION_MEMORY_MAX_TOKENS propagates to memory_retrieve.py subprocess.
# Non-fatal: absent or empty file is a no-op.
[ -f "${ARTIFACTS_DIR}/token-opt-caps.env" ] && . "${ARTIFACTS_DIR}/token-opt-caps.env" || true

MEMORY_CONTEXT=$(python3 "${REPO_ROOT}/dark-factory/scripts/memory_retrieve.py" \
  --phase "$PHASE" \
  ...
```

**5.4 — Verify test passes:**
```bash
cd /workspace/markethawk && python -m pytest dark-factory/tests/test_phase4_t3_sourcing.py::test_load_memory_sources_caps_before_memory_retrieve -x -v 2>&1 | tail -20
```
Expected: `PASSED`

**5.5 — Commit:**
```bash
git add dark-factory/scripts/load_memory_context.sh dark-factory/tests/test_phase4_t3_sourcing.py
git commit -m "feat(token-opt): load_memory_context.sh sources token-opt-caps.env before memory_retrieve.py (#716)"
```

---

## Task 6: Update dark-factory-code-review.md Phase 2 diff block

**Goal:** Source `token-opt-caps.env` at the top of the Phase 2 diff bash block in `.archon/commands/dark-factory-code-review.md` (same subprocess as `diff_rank.py`) so `TOKEN_OPTIMIZATION_DIFF_MAX_REVIEW_TOKENS` propagates.

**Files:**
- `.archon/commands/dark-factory-code-review.md`
- `dark-factory/tests/test_phase4_t3_sourcing.py` (extend)

### TDD Steps

**6.1 — Extend test file:** add to `dark-factory/tests/test_phase4_t3_sourcing.py`:

```python
def test_code_review_sources_caps_before_diff_rank():
    content = CODE_REVIEW_PATH.read_text()
    assert CAPS_PATTERN in content, (
        f"dark-factory-code-review.md must source {CAPS_PATTERN}"
    )
    caps_pos = content.index(CAPS_PATTERN)
    rank_pos = content.index("diff_rank.py")
    assert caps_pos < rank_pos, (
        f"{CAPS_PATTERN} must appear before diff_rank.py "
        f"(positions: caps={caps_pos}, rank={rank_pos})"
    )
```

**6.2 — Verify test fails:**
```bash
cd /workspace/markethawk && python -m pytest dark-factory/tests/test_phase4_t3_sourcing.py::test_code_review_sources_caps_before_diff_rank -x -v 2>&1 | tail -20
```
Expected: `FAILED — AssertionError: dark-factory-code-review.md must source token-opt-caps.env`

**6.3 — Implement: edit `.archon/commands/dark-factory-code-review.md`**

In Phase 2 (DIFF), locate the bash block that begins with:
```bash
RANK_IN=$(mktemp /tmp/rank_in_XXXXXX.txt)
git diff main...HEAD \
```

Add the sourcing line immediately after `RANK_IN=$(mktemp ...)`:
```bash
RANK_IN=$(mktemp /tmp/rank_in_XXXXXX.txt)
[ -f "${ARTIFACTS_DIR}/token-opt-caps.env" ] && . "${ARTIFACTS_DIR}/token-opt-caps.env" || true
git diff main...HEAD \
  -- ':!*.lock' ':!*.md' \
  ':!.archon/memory/**' \
  ':!codeindex.json' ':!symbolindex.json' \
  ':!docs/codeindex-hotspots.md' ':!docs/database-schema.md' \
  2>/dev/null > "$RANK_IN"
python3 dark-factory/scripts/diff_rank.py \
  --diff "$RANK_IN" \
  --artifacts-dir "$ARTIFACTS_DIR" \
  --config ".claude/skills/refinement/config.yaml" \
  --hotspots "docs/codeindex-hotspots.md" \
  2>/tmp/diff_rank_err.txt > "$ARTIFACTS_DIR/review_diff.txt" \
  || {
    echo "diff_rank: ranking failed ($(cat /tmp/diff_rank_err.txt)) — using raw diff"
    cp "$RANK_IN" "$ARTIFACTS_DIR/review_diff.txt"
  }
rm -f "$RANK_IN"
```

**6.4 — Verify test passes:**
```bash
cd /workspace/markethawk && python -m pytest dark-factory/tests/test_phase4_t3_sourcing.py -v -k "load_memory or code_review" 2>&1 | tail -20
```
Expected: `2 passed`

**6.5 — Commit:**
```bash
git add .archon/commands/dark-factory-code-review.md dark-factory/tests/test_phase4_t3_sourcing.py
git commit -m "feat(token-opt): code-review command sources token-opt-caps.env in Phase 2 diff block (#716)"
```

---

## Task 7: Update dark-factory-conformance.md Phase 3 ranking block

**Goal:** Source `token-opt-caps.env` at the top of the Phase 3 ranking block in `.archon/commands/dark-factory-conformance.md` (same subprocess as `diff_rank.py`) so `TOKEN_OPTIMIZATION_DIFF_MAX_REVIEW_TOKENS` propagates. Run the full test suite to close.

**Files:**
- `.archon/commands/dark-factory-conformance.md`
- `dark-factory/tests/test_phase4_t3_sourcing.py` (extend)

### TDD Steps

**7.1 — Extend test file:** add to `dark-factory/tests/test_phase4_t3_sourcing.py`:

```python
def test_conformance_sources_caps_before_diff_rank():
    content = CONFORMANCE_PATH.read_text()
    assert CAPS_PATTERN in content, (
        f"dark-factory-conformance.md must source {CAPS_PATTERN}"
    )
    caps_pos = content.index(CAPS_PATTERN)
    rank_pos = content.index("diff_rank.py")
    assert caps_pos < rank_pos, (
        f"{CAPS_PATTERN} must appear before diff_rank.py "
        f"(positions: caps={caps_pos}, rank={rank_pos})"
    )
```

**7.2 — Verify test fails:**
```bash
cd /workspace/markethawk && python -m pytest dark-factory/tests/test_phase4_t3_sourcing.py::test_conformance_sources_caps_before_diff_rank -x -v 2>&1 | tail -20
```
Expected: `FAILED — AssertionError: dark-factory-conformance.md must source token-opt-caps.env`

**7.3 — Implement: edit `.archon/commands/dark-factory-conformance.md`**

In Phase 3 (pre-triage and conformance review), locate the diff_rank.py ranking block:
```bash
# Rank and chunk the fmt-filtered diff (fail-open)
RANK_IN=$(mktemp /tmp/rank_in_XXXXXX.txt)
printf '%s' "$TRIAGED_DIFF" > "$RANK_IN"
RANKED=$(python3 dark-factory/scripts/diff_rank.py \
```

Add the sourcing line immediately after `RANK_IN=$(mktemp ...)`:
```bash
# Rank and chunk the fmt-filtered diff (fail-open)
RANK_IN=$(mktemp /tmp/rank_in_XXXXXX.txt)
[ -f "${ARTIFACTS_DIR}/token-opt-caps.env" ] && . "${ARTIFACTS_DIR}/token-opt-caps.env" || true
printf '%s' "$TRIAGED_DIFF" > "$RANK_IN"
RANKED=$(python3 dark-factory/scripts/diff_rank.py \
  --diff "$RANK_IN" \
  --artifacts-dir "$ARTIFACTS_DIR" \
  --config ".claude/skills/refinement/config.yaml" \
  ${SPEC_FILE:+--spec-file "$SPEC_FILE"} \
  --hotspots "docs/codeindex-hotspots.md" \
  2>/tmp/diff_rank_err.txt) \
  && TRIAGED_DIFF="$RANKED" \
  || echo "diff_rank: ranking failed ($(cat /tmp/diff_rank_err.txt)) — using fmt-filtered diff"
rm -f "$RANK_IN"
```

**7.4 — Verify all sourcing tests pass:**
```bash
cd /workspace/markethawk && python -m pytest dark-factory/tests/test_phase4_t3_sourcing.py -v 2>&1 | tail -20
```
Expected: `3 passed`

**7.5 — Run full Phase 4 T3 test suite:**
```bash
cd /workspace/markethawk && python -m pytest dark-factory/tests/test_phase4_t3_config.py dark-factory/tests/test_phase4_t3_dag_nodes.py dark-factory/tests/test_phase4_t3_sourcing.py -v 2>&1 | tail -40
```
Expected: all tests pass (3 + ~26 + 3 = ~32 tests).

**7.6 — Run DAG validator and OR-join regression suite one final time:**
```bash
cd /workspace/markethawk && python dark-factory/scripts/check_workflow_dag.py .archon/workflows/archon-dark-factory.yaml && python -m pytest dark-factory/tests/test_workflow_or_join.py -v 2>&1 | tail -20
```
Expected: DAG validator exits 0, all OR-join tests pass.

**7.7 — Commit:**
```bash
git add .archon/commands/dark-factory-conformance.md dark-factory/tests/test_phase4_t3_sourcing.py
git commit -m "feat(token-opt): conformance command sources token-opt-caps.env in Phase 3 ranking block (#716)"
```
