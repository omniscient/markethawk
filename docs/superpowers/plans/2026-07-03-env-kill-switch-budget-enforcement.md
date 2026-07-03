# Plan: Env Kill-Switch for Budget Enforcement (Issue #732)

**Goal:** Wire `TOKEN_OPTIMIZATION_ENFORCE_BUDGETS` as a live env kill-switch into all five `enforce-budget-*` DAG nodes so an operator can force all enforcement back to observe mode without a git commit. Kill-only semantics: `false`/`0`/`no` (case-insensitive) forces `_MODE=observe`; unset or any other value defers to config. Update the runbook with a new Tier 0 section and remove stale "no env override" statements.

**Architecture:** Inline bash-level addition to each of the five DAG nodes. Two lines appended after the existing `if [ "$_EB" = "true" ]...` mode-setting block: lowercase expansion via `${VAR,,}`, then a `case` block. No Python changes, no new Docker images, no config.yaml changes.

**Tech Stack:** Bash (in YAML bash blocks), Python (pytest), Markdown (runbook).

---

## File Structure

| File | Change | Scope |
|------|--------|-------|
| `.archon/workflows/archon-dark-factory.yaml` | 5 × 3-line append to `enforce-budget-*` bash blocks | Narrow — insert only, no restructuring |
| `dark-factory/tests/test_budget_enforce_dag.py` | Add `test_enforce_budget_node_env_kill_switch` (parametrized, 5 nodes) | Append to existing test file |
| `docs/agents/dark-factory-token-optimization.md` | Add Tier 0 section; remove/update 4 stale "no env override" statements | Targeted edits, no restructuring |

---

## Task 1: Write failing test for env kill-switch (TDD first)

**Files:** `dark-factory/tests/test_budget_enforce_dag.py`

### Steps

1. Append the new test block to the end of `dark-factory/tests/test_budget_enforce_dag.py`:

```python
# ── T4-D1: enforce-budget nodes read TOKEN_OPTIMIZATION_ENFORCE_BUDGETS ───────
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
        f"'{node_id}' must read TOKEN_OPTIMIZATION_ENFORCE_BUDGETS from env"
    assert ",," in bash, \
        f"'{node_id}' must lowercase the env var with bash ,, expansion (case-insensitive kill)"
```

2. Verify the test **fails** before implementation:

```bash
cd /workspace/markethawk
python -m pytest dark-factory/tests/test_budget_enforce_dag.py::test_enforce_budget_node_env_kill_switch -v
```

Expected output:
```
FAILED dark-factory/tests/test_budget_enforce_dag.py::test_enforce_budget_node_env_kill_switch[enforce-budget-refine] - AssertionError: 'enforce-budget-refine' must read TOKEN_OPTIMIZATION_ENFORCE_BUDGETS from env
...
5 failed
```

---

## Task 2: Implement env kill-switch in 5 DAG nodes

**Files:** `.archon/workflows/archon-dark-factory.yaml`

### Steps

For each of the five `enforce-budget-*` nodes, the kill-switch lines are inserted immediately after the existing `if [ "$_EB" = "true" ]...` mode-setting line, before the `python3 ...budget_enforce.py` call. The indentation inside the subshell uses 8 spaces (matching the surrounding block).

**1. `enforce-budget-refine` (line ~370):**

Before:
```
        if [ "$_EB" = "true" ] && [ "$_ES" = "true" ]; then _MODE="enforce"; else _MODE="observe"; fi
        python3 "${_CLONE}/dark-factory/scripts/budget_enforce.py" \
          --context-budget-json "$ARTIFACTS_DIR/context-budget.json" \
          --budget-tokens "${_BUD:-30000}" --mode "$_MODE" --config "$_CFG" \
          > "$ARTIFACTS_DIR/token-opt-caps.env"  # truncate (not append) — clears stale caps from prior enforce runs
      ) || true
    depends_on: [budget-refine]
    when: "$parse-intent.output.intent == 'refine'"
```

After (insert 3 lines after the `if` line):
```
        if [ "$_EB" = "true" ] && [ "$_ES" = "true" ]; then _MODE="enforce"; else _MODE="observe"; fi
        # Env kill-switch: false|0|no → force observe (kill-only; cannot force enforcement ON)
        _EKS="${TOKEN_OPTIMIZATION_ENFORCE_BUDGETS,,}"
        case "$_EKS" in false|0|no) _MODE="observe" ;; esac
        python3 "${_CLONE}/dark-factory/scripts/budget_enforce.py" \
          --context-budget-json "$ARTIFACTS_DIR/context-budget.json" \
          --budget-tokens "${_BUD:-30000}" --mode "$_MODE" --config "$_CFG" \
          > "$ARTIFACTS_DIR/token-opt-caps.env"  # truncate (not append) — clears stale caps from prior enforce runs
      ) || true
    depends_on: [budget-refine]
    when: "$parse-intent.output.intent == 'refine'"
```

**2. `enforce-budget-plan` (line ~415):**

Same pattern — insert 3 lines after the `if` line in the `enforce-budget-plan` bash block:
```
        if [ "$_EB" = "true" ] && [ "$_ES" = "true" ]; then _MODE="enforce"; else _MODE="observe"; fi
        # Env kill-switch: false|0|no → force observe (kill-only; cannot force enforcement ON)
        _EKS="${TOKEN_OPTIMIZATION_ENFORCE_BUDGETS,,}"
        case "$_EKS" in false|0|no) _MODE="observe" ;; esac
        python3 "${_CLONE}/dark-factory/scripts/budget_enforce.py" \
          --context-budget-json "$ARTIFACTS_DIR/context-budget.json" \
          --budget-tokens "${_BUD:-30000}" --mode "$_MODE" --config "$_CFG" \
          > "$ARTIFACTS_DIR/token-opt-caps.env"  # truncate (not append) — clears stale caps from prior enforce runs
      ) || true
    depends_on: [budget-plan]
    when: "$parse-intent.output.intent == 'plan'"
```

**3. `enforce-budget-implement` (line ~522):**

Same pattern — insert after the `if` line in the `enforce-budget-implement` bash block:
```
        if [ "$_EB" = "true" ] && [ "$_ES" = "true" ]; then _MODE="enforce"; else _MODE="observe"; fi
        # Env kill-switch: false|0|no → force observe (kill-only; cannot force enforcement ON)
        _EKS="${TOKEN_OPTIMIZATION_ENFORCE_BUDGETS,,}"
        case "$_EKS" in false|0|no) _MODE="observe" ;; esac
        python3 "${_CLONE}/dark-factory/scripts/budget_enforce.py" \
          --context-budget-json "$ARTIFACTS_DIR/context-budget.json" \
          --budget-tokens "${_BUD:-30000}" --mode "$_MODE" --config "$_CFG" \
          > "$ARTIFACTS_DIR/token-opt-caps.env"  # truncate (not append) — clears stale caps from prior enforce runs
      ) || true
    depends_on: [budget-implement]
    when: "$parse-intent.output.intent == 'new' || $parse-intent.output.intent == 'continue'"
```

**4. `enforce-budget-conformance` (line ~918):**

Same pattern — insert after the `if` line in the `enforce-budget-conformance` bash block:
```
        if [ "$_EB" = "true" ] && [ "$_ES" = "true" ]; then _MODE="enforce"; else _MODE="observe"; fi
        # Env kill-switch: false|0|no → force observe (kill-only; cannot force enforcement ON)
        _EKS="${TOKEN_OPTIMIZATION_ENFORCE_BUDGETS,,}"
        case "$_EKS" in false|0|no) _MODE="observe" ;; esac
        python3 "${_CLONE}/dark-factory/scripts/budget_enforce.py" \
          --context-budget-json "$ARTIFACTS_DIR/context-budget.json" \
          --budget-tokens "${_BUD:-30000}" --mode "$_MODE" --config "$_CFG" \
          > "$ARTIFACTS_DIR/token-opt-caps.env"  # truncate (not append) — clears stale caps from prior enforce runs
      ) || true
    depends_on: [budget-conformance]
    when: "$parse-intent.output.intent == 'new' || $parse-intent.output.intent == 'continue'"
```

**5. `enforce-budget-code-review` (line ~1124):**

Same pattern — insert after the `if` line in the `enforce-budget-code-review` bash block:
```
        if [ "$_EB" = "true" ] && [ "$_ES" = "true" ]; then _MODE="enforce"; else _MODE="observe"; fi
        # Env kill-switch: false|0|no → force observe (kill-only; cannot force enforcement ON)
        _EKS="${TOKEN_OPTIMIZATION_ENFORCE_BUDGETS,,}"
        case "$_EKS" in false|0|no) _MODE="observe" ;; esac
        python3 "${_CLONE}/dark-factory/scripts/budget_enforce.py" \
          --context-budget-json "$ARTIFACTS_DIR/context-budget.json" \
          --budget-tokens "${_BUD:-30000}" --mode "$_MODE" --config "$_CFG" \
          > "$ARTIFACTS_DIR/token-opt-caps.env"  # truncate (not append) — clears stale caps from prior enforce runs
      ) || true
    depends_on: [budget-code-review]
    when: "$parse-intent.output.intent == 'new' || $parse-intent.output.intent == 'continue'"
```

### Verify tests pass

```bash
cd /workspace/markethawk
python -m pytest dark-factory/tests/test_budget_enforce_dag.py::test_enforce_budget_node_env_kill_switch -v
```

Expected output:
```
PASSED dark-factory/tests/test_budget_enforce_dag.py::test_enforce_budget_node_env_kill_switch[enforce-budget-refine]
PASSED dark-factory/tests/test_budget_enforce_dag.py::test_enforce_budget_node_env_kill_switch[enforce-budget-plan]
PASSED dark-factory/tests/test_budget_enforce_dag.py::test_enforce_budget_node_env_kill_switch[enforce-budget-implement]
PASSED dark-factory/tests/test_budget_enforce_dag.py::test_enforce_budget_node_env_kill_switch[enforce-budget-conformance]
PASSED dark-factory/tests/test_budget_enforce_dag.py::test_enforce_budget_node_env_kill_switch[enforce-budget-code-review]
5 passed
```

### Verify DAG validator still passes

```bash
cd /workspace/markethawk
python -m pytest dark-factory/tests/test_budget_enforce_dag.py::test_dag_validator_passes -v
```

Expected: `PASSED`

### Commit

```bash
cd /workspace/markethawk
git add .archon/workflows/archon-dark-factory.yaml dark-factory/tests/test_budget_enforce_dag.py
git commit -m "feat(#732): env kill-switch for budget enforcement — 5 DAG nodes + test"
```

---

## Task 3: Update runbook with Tier 0 and remove stale "no env override" statements

**Files:** `docs/agents/dark-factory-token-optimization.md`

### Stale statements to remove/update

There are four locations in the runbook asserting that no env override exists for enforcement gates. Each must be updated:

**Location A — Configuration section (lines 64–67):**

Current text:
```
**No env override exists for `enforce_budgets` or per-scenario `enforce`
flags** — these are enforcement gates read exclusively from the cloned `config.yaml`.
The stale `TOKEN_OPTIMIZATION_ENFORCE_BUDGETS` env comment (from #673) was never wired
into the Phase 4 enforce nodes; ignore it.
```

Replace with:
```
`TOKEN_OPTIMIZATION_ENFORCE_BUDGETS` is the **Tier 0 kill-switch** — setting it to `false`, `0`, or `no` forces all enforcement nodes to observe mode without a git commit (see Tier 0 in the rollback section below). Kill-only semantics: the var cannot force enforcement ON. Per-scenario `enforce` flags are read from config only and have no env override.
```

**Location B — Budget enforcement rollback section heading (lines 93–98):**

Current:
```
### Budget enforcement rollback (Tier 1 and Tier 2)

Enforcement gates (`enforce_budgets`, per-scenario `enforce`) have **no env override** —
they are read exclusively from the cloned `config.yaml`. Both rollback tiers are git
commits to `config.yaml` on `main`; they take effect on the **next factory run**
(no scheduler restart, no image rebuild needed).
```

Replace with:
```
### Budget enforcement rollback (Tier 0, Tier 1, and Tier 2)

Three rollback tiers are available. Tier 0 is instant (no git commit); Tiers 1 and 2 are git commits that take effect on the next factory run.
```

**Location C — Insert new Tier 0 section immediately after the updated heading, before Tier 1:**

Insert this block:
```markdown
**Tier 0 — env kill (instant, no git commit):**
1. Edit `.archon/.env`:
   ```
   TOKEN_OPTIMIZATION_ENFORCE_BUDGETS=false
   ```
2. Force-recreate the scheduler so new factory containers inherit the var:
   ```bash
   docker compose --profile scheduler up -d --force-recreate backlog-scheduler
   ```
   > **Note:** `docker compose restart` does NOT re-read `env_file:` entries — the
   > container must be recreated (`up -d --force-recreate`) to pick up a newly-added var.
3. Takes effect on the **next factory run** — in-flight factory containers keep the
   environment they were spawned with and are not retroactively switched to observe.
4. To re-enable enforcement, remove or comment out the line, then force-recreate again:
   ```bash
   docker compose --profile scheduler up -d --force-recreate backlog-scheduler
   ```

**Kill-only semantics:** `false`, `0`, and `no` (case-insensitive) force observe mode.
Unset or any other value defers to the config-driven `enforce_budgets`/`enforce.<scenario>` logic.
The var cannot force enforcement ON.
```

**Location D — Remove the "Note" block at the end of the rollback section (lines 122–126):**

Current:
```
> **Note:** To wire a hot-changeable env override for enforcement gates in a future ticket,
> the `enforce-budget-*` DAG nodes must be updated to read
> `TOKEN_OPTIMIZATION_ENFORCE_BUDGETS` (and per-scenario equivalents) from the environment
> alongside the config file. This is a candidate follow-up (see Open Question 2 in
> the Phase 4 design doc).
```

Remove this block entirely — it is now obsolete.

### Verify all stale statements removed

```bash
grep -n "no env override" /workspace/markethawk/docs/agents/dark-factory-token-optimization.md
```

Expected: no output (all stale references removed).

```bash
grep -n "TOKEN_OPTIMIZATION_ENFORCE_BUDGETS" /workspace/markethawk/docs/agents/dark-factory-token-optimization.md
```

Expected: at least 2 matches — one in the config section and one in the Tier 0 block.

```bash
grep -n "Tier 0" /workspace/markethawk/docs/agents/dark-factory-token-optimization.md
```

Expected: at least 2 matches — the heading and at least one body reference.

### Commit

```bash
cd /workspace/markethawk
git add docs/agents/dark-factory-token-optimization.md
git commit -m "docs(#732): add Tier 0 env kill runbook; remove stale no-env-override statements"
```

---

## Task 4: Full test suite verification

**Files:** none (verification only)

### Steps

Run the full `test_budget_enforce_dag.py` suite to confirm no regressions:

```bash
cd /workspace/markethawk
python -m pytest dark-factory/tests/test_budget_enforce_dag.py -v
```

Expected output: all tests pass (existing T3 tests + new T4 test). The DAG validator (`test_dag_validator_passes`) must be green — the 3-line insertion does not add any OR-join node and does not touch `when:` gates or `trigger_rule`.

Also verify the YAML still parses cleanly:

```bash
python3 -c "import yaml; yaml.safe_load(open('/workspace/markethawk/.archon/workflows/archon-dark-factory.yaml'))" && echo "YAML OK"
```

Expected: `YAML OK`

---

## Acceptance Checklist

- [ ] `TOKEN_OPTIMIZATION_ENFORCE_BUDGETS` read in all 5 `enforce-budget-*` nodes
- [ ] `${TOKEN_OPTIMIZATION_ENFORCE_BUDGETS,,}` (bash `,,` expansion) present in all 5 nodes
- [ ] Kill-only: `false|0|no` → `_MODE=observe`; unset → defers to config (cannot force ON)
- [ ] `test_enforce_budget_node_env_kill_switch` passes for all 5 parametrize values
- [ ] `test_dag_validator_passes` still green; `when:` gates untouched (no parentheses)
- [ ] Runbook has Tier 0 section with `up -d --force-recreate` and in-flight caveat
- [ ] All "no env override" stale statements removed from the runbook
- [ ] No changes to `budget_enforce.py`, `config.yaml`, or command files
