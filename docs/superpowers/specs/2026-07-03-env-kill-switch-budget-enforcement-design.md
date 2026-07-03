# Phase 4b T4: Env Kill-Switch for Budget Enforcement

**Status:** design  
**Date:** 2026-07-03  
**Issue:** #732  
**Predecessor:** #728 (Phase 4 T6 — staged enforcement flip + runbook)  
**Epic:** Dark Factory token optimization Phase 4b  

---

## Problem

The five `enforce-budget-*` DAG nodes in `.archon/workflows/archon-dark-factory.yaml` read `enforce_budgets` and `enforce.<scenario>` exclusively from the cloned `config.yaml`. No live env override exists for these enforcement gates. A mid-incident operator who needs to force all nodes back to observe mode must commit to `main` and wait for the next factory run — a ~1–5 minute delay that is acceptable in a planned rollback but slow for a reactive incident response. The runbook currently documents this constraint and directs operators to git commits (Tier 1/2).

This ticket wires a Tier 0 kill-switch: an env var (`TOKEN_OPTIMIZATION_ENFORCE_BUDGETS`) that, when set to a kill value, immediately overrides the config and forces observe mode across all five nodes — without a git commit or image rebuild.

---

## Requirements

1. Each of the five `enforce-budget-<scenario>` nodes reads `TOKEN_OPTIMIZATION_ENFORCE_BUDGETS` from the environment after parsing the config.
2. **Kill-only semantics**: values `false`, `0`, `no` (case-insensitive) force `_MODE=observe` regardless of config. Any other value, including unset, defers to the existing config-driven logic. The env var **cannot** force enforcement ON.
3. The bash check uses `${TOKEN_OPTIMIZATION_ENFORCE_BUDGETS,,}` (bash 4 lowercase expansion) so operator typos of `FALSE`, `No`, etc. are handled correctly.
4. `dark-factory/tests/test_budget_enforce_dag.py` gains assertions that each node's bash block contains the env-var read and the lowercase expansion construct.
5. The runbook in `docs/agents/dark-factory-token-optimization.md` gains a **Tier 0 — env kill** section above the existing Tier 1/2 sections. It must:
   - Specify setting the var in `.archon/.env`
   - Use `docker compose --profile scheduler up -d --force-recreate backlog-scheduler` (not `restart`, which does not re-read `env_file`)
   - Note that the kill-switch takes effect on the **next factory run** — in-flight factory containers keep the env they were spawned with
6. All statements in the runbook asserting "no env override exists" for enforcement gates are removed or updated.
7. The workflow YAML must still parse and `check_workflow_dag.py` must pass with no new errors after the change.
8. No parentheses added to `when:` gates (Archon parser constraint documented in T6 runbook).

---

## Architecture

### Inline bash addition (per node)

Each of the five nodes currently ends with:

```bash
if [ "$_EB" = "true" ] && [ "$_ES" = "true" ]; then _MODE="enforce"; else _MODE="observe"; fi
```

The env kill-switch is appended immediately after:

```bash
# Env kill-switch: false|0|no → force observe (kill-only; cannot force enforcement ON)
_EKS="${TOKEN_OPTIMIZATION_ENFORCE_BUDGETS,,}"
case "$_EKS" in false|0|no) _MODE="observe" ;; esac
```

`${TOKEN_OPTIMIZATION_ENFORCE_BUDGETS,,}` lowercases the env value before the case match. When the var is unset, it expands to the empty string, which does not match any kill value, so the existing config-driven `_MODE` is preserved.

This is appended after the existing `if` block — the env kill always wins over config, but only in the kill direction.

### Affected files

| File | Change |
|------|--------|
| `.archon/workflows/archon-dark-factory.yaml` | 5× one-liner append to `enforce-budget-*` bash blocks |
| `dark-factory/tests/test_budget_enforce_dag.py` | New `test_enforce_budget_node_env_kill_switch` parametrized test |
| `docs/agents/dark-factory-token-optimization.md` | Tier 0 section added; stale "no env override" lines updated |

No image rebuild required — the nodes are clone-read. No changes to `budget_enforce.py`, `config.yaml`, or command files.

### Runbook Tier 0 (new section)

```
**Tier 0 — env kill (instant, no git commit):**
1. Edit `.archon/.env`:
   TOKEN_OPTIMIZATION_ENFORCE_BUDGETS=false
2. Force-recreate the scheduler so new factory containers inherit the var:
   docker compose --profile scheduler up -d --force-recreate backlog-scheduler
3. Takes effect on the **next factory run** — in-flight factory containers keep
   the environment they were spawned with and are not retroactively switched to observe.
4. To re-enable, remove or comment out the line and recreate again.
```

Note: `docker compose restart` does NOT re-read `env_file:` entries — the container must be recreated to pick up a newly-added env var. This is why `up -d --force-recreate` is specified here.

### Test addition

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

---

## Alternatives Considered

### A: Per-scenario env vars (`TOKEN_OPTIMIZATION_ENFORCE_REFINE=false`, etc.)

Adding five separate vars (one per scenario) would give finer-grained control but dramatically increases operator cognitive load during an incident. The kill-switch use case is "all enforcement off immediately" — a global flag matches that intent. Per-scenario granularity is already covered by Tier 2 (git commit to set one `enforce.<scenario>: false`). Rejected for scope and incident ergonomics.

### B: Inject env check into the existing Python one-liner

The Python one-liner already parses config in a single call. Adding `os.environ.get(...)` logic there would keep the env check co-located with config parsing, but would make the already-dense 1-line expression harder to read and test. The test suite already asserts on node bash content as strings; a bash-level `case` block is more readable and directly assertable. Rejected for maintainability.

### C: New `budget_enforce.py` flag (`--env-kill`)

Passing the env var as a CLI argument to `budget_enforce.py` would centralize the kill logic in Python, but the env var is specifically designed to be read from the DAG node environment — not piped through a script argument. The entire point is that the var propagates via container environment inheritance, not config. Rejected — wrong abstraction layer.

---

## Open Questions

None blocking.

---

## Assumptions

- The Archon DAG runner does not strip `TOKEN_OPTIMIZATION_ENFORCE_BUDGETS` from the environment before executing bash nodes (assumed: it inherits the scheduler process's environment).
- Bash 4+ is available in the factory container (assumed: existing nodes already use `${CLONE_DIR:-.}` which is standard bash; `,,` expansion requires bash 4, confirmed by existing `set -euo pipefail` use).
- The existing per-feature restart pattern in the runbook (`docker compose --profile scheduler restart`) may not reliably pick up `env_file` changes; this ticket fixes the pattern only for Tier 0 and does not backport a fix to existing runbook sections (out of scope).
