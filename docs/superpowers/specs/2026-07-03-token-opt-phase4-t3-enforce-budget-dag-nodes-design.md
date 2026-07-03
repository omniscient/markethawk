# Phase 4 T3: enforce-budget DAG Nodes + Per-Scenario Config

**Status:** design
**Date:** 2026-07-03
**Issue:** #716
**Epic:** #713 (Phase 4 budget enforcement)
**Epic spec:** `docs/superpowers/specs/2026-07-02-token-opt-phase4-enforcement-design.md`
**Depends on:** T1 (#721 — `budget_enforce.py`), T2 (#722 — optimizer cap-override reads)

---

## Overview

T1 shipped `budget_enforce.py` with derivation math and observe/enforce modes. T2 added env-override reads to all four optimizer scripts. T3 wires everything together: it inserts `enforce-budget-<phase>` DAG nodes that call `budget_enforce.py`, adds per-scenario `budgets:` and `enforce:` toggles to `config.yaml`, and updates the command files to source the generated `token-opt-caps.env` file so the optimizer env overrides actually propagate.

---

## Requirements

1. **Five `enforce-budget-<phase>` bash nodes** inserted immediately before each scenario command node in `.archon/workflows/archon-dark-factory.yaml`:
   - `enforce-budget-refine` → before `refine` command
   - `enforce-budget-plan` → before `plan` command
   - `enforce-budget-implement` → before `implement` command
   - `enforce-budget-conformance` → before `conformance` command
   - `enforce-budget-code-review` → before `code-review` command

2. **Each node mirrors the `budget-*` telemetry node pattern:**
   - `|| true` fail-open (never blocks the run)
   - `${CLONE_DIR:-.}` for clone path
   - `when:`-gated with the same condition as the corresponding command node
   - `depends_on: [budget-<phase>]` (runs after context-budget.json is written)
   - `timeout: 30000`

3. **Each node's logic:**
   - Reads `enforce_budgets` (global) and `enforce.<scenario>` (per-scenario toggle) from config
   - Reads per-scenario budget from `budgets.<scenario>` (falls back to `default_budget_tokens`)
   - Mode = `enforce` only when BOTH `enforce_budgets=true` AND `enforce.<scenario>=true` (otherwise `observe`)
   - Calls `budget_enforce.py` with `--mode observe|enforce`
   - Redirects stdout to `$ARTIFACTS_DIR/token-opt-caps.env`
   - In observe mode: stdout is empty → env file created but empty (sourcing is a no-op)
   - In enforce mode: stdout is `KEY=VALUE` lines → sourcing exports the optimizer overrides

4. **Command nodes update their `depends_on`:** replace `budget-<phase>` with `enforce-budget-<phase>` (the enforce node is the new pre-command gate; budget-* is still in the chain via enforce-budget's depends_on).

5. **`config.yaml` additions** under `token_optimization`:
   - Raise `default_budget_tokens` from `24000` to `30000` (CLAUDE.md alone is ~18k; 24k was too tight)
   - Add `budgets:` map with per-scenario values (all 30000 initially)
   - Add `enforce:` map with per-scenario toggles (all `false` initially — staged flip later in T6)

6. **`load_memory_context.sh`** sources `$ARTIFACTS_DIR/token-opt-caps.env` before calling `memory_retrieve.py`, so `TOKEN_OPTIMIZATION_MEMORY_MAX_TOKENS` propagates to the subprocess.

7. **`dark-factory-code-review.md` (Phase 2)** and **`dark-factory-conformance.md` (Phase 3 ranking block)** source `token-opt-caps.env` in the same bash block as the `diff_rank.py` call, so `TOKEN_OPTIMIZATION_DIFF_MAX_REVIEW_TOKENS` propagates. The source must be in the same subprocess as diff_rank.py since each Claude Code bash tool call is an independent process.

8. **`check_workflow_dag.py` validator passes** with no changes — the new nodes have a single same-gated upstream and need no `trigger_rule`, so the tripwire (trigger_rule count == REQUIRED_OR_JOIN_NODES size) is unaffected.

---

## Architecture

### DAG structure (post-T3)

```
budget-refine ──→ enforce-budget-refine ──→ refine (command)
budget-plan ────→ enforce-budget-plan ────→ plan (command)
budget-implement → enforce-budget-implement → implement (command)  [OR-join via digest-comments still on implement]
budget-conformance → enforce-budget-conformance → conformance (command)
budget-code-review → enforce-budget-code-review → code-review (command)
```

### enforce-budget node bash logic

Config reading uses **single-line Python `-c`** (YAML-safe, no multiline heredoc issues):

```bash
_CLONE="${CLONE_DIR:-.}"
_CFG="${_CLONE}/.claude/skills/refinement/config.yaml"
_EB=$(python3 -c "import yaml,sys; c=yaml.safe_load(open(sys.argv[1])); print('true' if c.get('token_optimization',{}).get('enforce_budgets') else 'false')" "$_CFG" 2>/dev/null||echo false)
_SE=$(python3 -c "import yaml,sys; c=yaml.safe_load(open(sys.argv[1])); print('true' if c.get('token_optimization',{}).get('enforce',{}).get('<scenario>') else 'false')" "$_CFG" 2>/dev/null||echo false)
_BUDGET=$(python3 -c "import yaml,sys; c=yaml.safe_load(open(sys.argv[1])); t=c.get('token_optimization',{}); print(int(t.get('budgets',{}).get('<scenario>',t.get('default_budget_tokens',30000))))" "$_CFG" 2>/dev/null||echo 30000)
_MODE=observe
[ "${_EB:-false}" = "true" ] && [ "${_SE:-false}" = "true" ] && _MODE=enforce
if [ ! -f "${ARTIFACTS_DIR}/context-budget.json" ]; then
  echo "enforce-budget-<scenario>: context-budget.json absent — skipped" >&2; exit 0
fi
python3 "${_CLONE}/dark-factory/scripts/budget_enforce.py" \
  --context-budget-json "${ARTIFACTS_DIR}/context-budget.json" \
  --budget-tokens "${_BUDGET:-30000}" \
  --mode "${_MODE}" \
  --config "${_CFG}" \
  > "${ARTIFACTS_DIR}/token-opt-caps.env" 2>/dev/null || true
echo "enforce-budget-<scenario>: mode=${_MODE} budget=${_BUDGET:-30000}" >&2
```

**Why single-line Python:** YAML literal block scalars (`bash: |`) require all content to be indented. Multiline Python code passed via `$(python3 -c "...")` would place Python top-level statements at column 0 (inside the unquoted heredoc), which the YAML parser misidentifies as new YAML keys. Single-line Python -c avoids this entirely.

### `enforce-budget-implement` trigger_rule

`enforce-budget-implement` depends on `[budget-implement]` — a **single upstream** — with no `trigger_rule`. The `none_failed_min_one_success` rule on `budget-implement` itself handles the `digest-comments` OR-join below it. Since `enforce-budget-implement` has exactly one upstream that shares the same `when:` gate (`new || continue`), the default `all_success` trigger rule is correct: if `budget-implement` runs, `enforce-budget-implement` runs; if it's skipped (wrong intent), the skip propagates correctly. The `implement` command node keeps its `trigger_rule: none_failed_min_one_success` because `digest-comments` is still a direct dependency.

### `token-opt-caps.env` sourcing pattern

The sourcing form used everywhere:
```bash
[ -f "${ARTIFACTS_DIR}/token-opt-caps.env" ] && . "${ARTIFACTS_DIR}/token-opt-caps.env" || true
```

This is:
- **Non-fatal** (matches the `|| true` pattern of the enforcement infrastructure)
- **No-op** when enforcement is off (file absent or empty)
- **Same-subprocess** for diff_rank.py calls (sourced in the same bash block)
- **Inherited by child processes** in `load_memory_context.sh` (sourced before the `memory_retrieve.py` call; env vars are inherited by subprocesses)

### config.yaml additions

```yaml
token_optimization:
  enforce_budgets: false      # global master switch (existing)
  default_budget_tokens: 30000  # raised from 24000 (CLAUDE.md ~18k; 24k was too tight)
  budgets:                    # per-scenario overrides of default_budget_tokens
    refine: 30000
    plan: 30000
    implement: 30000
    conformance: 30000
    code-review: 30000
  enforce:                    # per-scenario enforcement toggle (all false = staged flip in T6)
    refine: false
    plan: false
    implement: false
    conformance: false
    code-review: false
  # ... existing per-feature enabled/max_tokens blocks unchanged ...
```

---

## Alternatives Considered

### A: Python heredoc in YAML bash block (rejected)

Multi-line Python code can be passed via `$(python3 -c "...\n...")` inside a YAML literal block scalar. This fails because Python top-level statements at column 0 are treated by the YAML parser as new mapping keys, breaking YAML parsing. Discovered during implementation prototyping.

### B: `yq` for config reading

`yq` is available in the factory container (used in `entrypoint.sh`). It would produce cleaner config reads. Rejected in favor of Python because: (a) `yq`'s null handling differs between versions (mikefarah v4 returns "null" for missing keys, not empty string, requiring extra guard logic), and (b) Python is already used in the `budget-*` telemetry nodes — consistency matters.

### C: Script file for config reading

Extract the Python config reading into a `budget_enforce_mode.py` helper. Unnecessary complexity for what is a 3-variable lookup. Inline single-line Python is simpler and keeps the enforce-budget node self-contained.

---

## Files to Change

| File | Change |
|------|--------|
| `.archon/workflows/archon-dark-factory.yaml` | Insert 5 `enforce-budget-*` nodes; update 5 command node `depends_on` |
| `.claude/skills/refinement/config.yaml` | Raise `default_budget_tokens` to 30000; add `budgets:` and `enforce:` maps |
| `dark-factory/scripts/load_memory_context.sh` | Source `token-opt-caps.env` before `memory_retrieve.py` |
| `.archon/commands/dark-factory-code-review.md` | Source `token-opt-caps.env` at top of Phase 2 diff block |
| `.archon/commands/dark-factory-conformance.md` | Source `token-opt-caps.env` at top of Phase 3 diff_rank block |
| `dark-factory/scripts/check_workflow_dag.py` | No changes needed (no new OR-join nodes) |

---

## Open Questions

- **None blocking.** All key decisions (trigger_rule, sourcing placement, YAML-safe Python, scenario key for `code-review`) are resolved above.

---

## Assumptions

- `budget_enforce.py` (`--mode observe`) outputs nothing to stdout — confirmed by reviewing T1 implementation: observe mode only writes to stderr. This means observe-mode runs create an empty `token-opt-caps.env` which is a safe no-op when sourced.
- The `code-review` scenario key in Python dict lookups uses the hyphenated form `'code-review'` to match the YAML config key. This must be consistent across the enforce-budget node and the `budgets:` / `enforce:` config maps.
- `context-budget.json` is always written by the preceding `budget-<phase>` node before `enforce-budget-<phase>` runs, since `budget-<phase>` is in `depends_on`. However, `budget-*` nodes use `|| true` so the JSON may be absent on script failure — the absent-file guard handles this.
- T6 (runbook + staged flip) will flip individual `enforce.<scenario>` toggles to `true` after T4/T5 calibration data confirms safe budget values. The T3 design intentionally ships all toggles `false`.
