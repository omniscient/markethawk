# Plan: Phase 4b T3 — Flip Budget Enforcement for Refine + Plan

**Date:** 2026-07-03
**Issue:** #733
**Spec:** docs/superpowers/specs/2026-07-03-flip-budget-enforcement-refine-plan-design.md
**Depends on:** #731 (PR #739) — must be merged before this PR

---

## Goal

Flip `token_optimization.enforce.refine` and `token_optimization.enforce.plan` from `false` to `true` in `.claude/skills/refinement/config.yaml`, update the exact-state test guard in `dark-factory/tests/test_budget_enforce_dag.py`, and update the operator runbook to reflect the new enforcement state. No code changes are required — the `enforce-budget-refine` and `enforce-budget-plan` DAG nodes were already wired in Phase 4 T3/T6; flipping the config flag is sufficient.

## Architecture

The enforce flags in `config.yaml` are the sole gating mechanism. With `enforce: false`, the pre-phase `enforce-budget-<scenario>` DAG nodes run `budget_enforce.py` but do not export derived caps — observe-only mode. With `enforce: true`, the node writes `$ARTIFACTS_DIR/token-opt-caps.env` which the command phase sources to tighten architecture, memory, comments, and diff caps to fit within the 30,000-token budget. Config is clone-read (every factory run clones the repo fresh), so a commit to `main` takes effect on the next run with no scheduler restart or image rebuild.

Gate evidence: PR #739 (#731) proved `section_at_risk_rate == 0%` and `over_budget_rate == 0%` at 30,000 tokens for both scenarios after raising `architecture.max_tokens` to 5,000.

## Tech Stack

- **Config:** `.claude/skills/refinement/config.yaml` (YAML)
- **Tests:** `dark-factory/tests/test_budget_enforce_dag.py` (pytest + pyyaml, no Docker required)
- **Docs:** `docs/agents/dark-factory-token-optimization.md` (Markdown)

---

## File Structure

| File | Change |
|------|--------|
| `dark-factory/tests/test_budget_enforce_dag.py` | Update `test_config_enforce_t6_state` expected map: `refine: True`, `plan: True` |
| `.claude/skills/refinement/config.yaml` | Flip `enforce.refine: false → true`, `enforce.plan: false → true` |
| `docs/agents/dark-factory-token-optimization.md` | Update Budget Enforcement section header + table; update "Path to Phase 4" section |

---

## Tasks

### Task 1: Update test guard to new intended enforcement state

**Files:** `dark-factory/tests/test_budget_enforce_dag.py`

This is the TDD gate: write the new expected enforce map before touching the config. The test will be red until Task 2 flips the flag — confirming that the config change, and only the config change, is what makes it pass.

#### Steps

1. **Edit `test_config_enforce_t6_state`** — change `"refine": False` and `"plan": False` to `True` (lines 78–89):

```python
# dark-factory/tests/test_budget_enforce_dag.py
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
        f"enforce must match the T6 intended state {expected}, got {enforce}"
    )
```

2. **Verify the test is red** (config still has `false`):

```bash
cd /workspace/markethawk
python -m pytest dark-factory/tests/test_budget_enforce_dag.py::test_config_enforce_t6_state -v
# Expected output:
# FAILED dark-factory/tests/test_budget_enforce_dag.py::test_config_enforce_t6_state
# AssertionError: enforce must match the T6 intended state
# {'refine': True, 'plan': True, ...}, got {'refine': False, 'plan': False, ...}
```

3. **Commit:**

```bash
git add dark-factory/tests/test_budget_enforce_dag.py
git commit -m "test(#733): update t6 enforce guard — refine + plan expected True"
```

---

### Task 2: Flip enforcement flags in config.yaml

**Files:** `.claude/skills/refinement/config.yaml`

Set `enforce.refine: true` and `enforce.plan: true`. `enforce.implement` stays `false` — out of scope per the issue body and acceptance criteria.

#### Steps

1. **Edit the `enforce:` block** in `.claude/skills/refinement/config.yaml` (lines 115–120). Replace:

```yaml
  enforce:
    refine: false
    plan: false
    implement: false
    conformance: true          # T6: enforcement live — 0% section_at_risk in T5 calibration
    code-review: true          # T6: enforcement live — 0% section_at_risk in T5 calibration
```

With:

```yaml
  enforce:
    refine: true               # T3b: enforcement live — 0% section_at_risk, 0% over_budget (#731)
    plan: true                 # T3b: enforcement live — 0% section_at_risk, 0% over_budget (#731)
    implement: false
    conformance: true          # T6: enforcement live — 0% section_at_risk in T5 calibration
    code-review: true          # T6: enforcement live — 0% section_at_risk in T5 calibration
```

2. **Verify the guard test is now green:**

```bash
cd /workspace/markethawk
python -m pytest dark-factory/tests/test_budget_enforce_dag.py::test_config_enforce_t6_state -v
# Expected: PASSED
```

3. **Verify `test_config_budgets_t6_state` is unchanged (budgets did not move):**

```bash
python -m pytest dark-factory/tests/test_budget_enforce_dag.py::test_config_budgets_t6_state -v
# Expected: PASSED
```

4. **Run the full enforce DAG test suite:**

```bash
python -m pytest dark-factory/tests/test_budget_enforce_dag.py -v
# Expected: all tests PASSED (no regressions)
```

5. **Commit:**

```bash
git add .claude/skills/refinement/config.yaml
git commit -m "config(#733): flip enforce.refine + enforce.plan to true

Gate evidence: #731 (PR #739) full-corpus scorecard — 0% section_at_risk,
0% over_budget at 30k tokens for both scenarios after architecture.max_tokens
raised to 5000. enforce.implement stays false (out of scope)."
```

---

### Task 3: Update operator runbook

**Files:** `docs/agents/dark-factory-token-optimization.md`

Two explicit scope targets from the spec: (a) Budget Enforcement status table, and (b) "Path to Phase 4 — Current Status" section. The Budget Enforcement section header at line 184 is also updated since it is the sentence that introduces the table.

#### Steps

1. **Update the Budget Enforcement section header** (line 184). Replace:

```
As of T6 (#719), budget enforcement is **active** for `conformance` and `code-review`.
```

With:

```
As of T3b (#733), budget enforcement is **active** for `conformance`, `code-review`, `refine`, and `plan`. `implement` remains in observe-only mode.
```

2. **Update the Budget Enforcement status table** (lines 186–192). Replace:

```markdown
| Scenario | Enforce | Budget | Status |
|----------|---------|--------|--------|
| refine | false | 30 000 | observe-only |
| plan | false | 30 000 | observe-only |
| implement | false | 30 000 | observe-only |
| conformance | **true** | **22 000** | **enforced (T6)** |
| code-review | **true** | **22 000** | **enforced (T6)** |
```

With:

```markdown
| Scenario | Enforce | Budget | Status |
|----------|---------|--------|--------|
| refine | **true** | **30 000** | **enforced (T3b)** |
| plan | **true** | **30 000** | **enforced (T3b)** |
| implement | false | 30 000 | observe-only |
| conformance | **true** | **22 000** | **enforced (T6)** |
| code-review | **true** | **22 000** | **enforced (T6)** |
```

3. **Update the "Path to Phase 4 — Current Status" section** (lines 256–297). Replace the entire section body (from the opening paragraph through step 4 and the trailing `---`):

Replace:

```markdown
## Path to Phase 4 — Current Status

Phase 4 (budget enforcement) is **partially live** as of T6 (#719):
- **Conformance and code-review**: enforcement active (see Budget Enforcement section).
- **Refine, plan, implement**: observe-only — deferred pending calibration.

### Follow-up Path for deferred scenarios (refine / plan / implement)

**Why deferred:** T5 calibration showed `section_at_risk_rate == 50%` at ALL tested
budgets (22k–40k) for refine/plan/implement. Root cause: `architecture.max_tokens: 3000`
is below real arch slice sizes (3–4k+ tokens), so enforcement trims architecture context
on every issue regardless of budget size. Flipping enforce would silently drop required
ARCHITECTURE.md sections — violating the "Never drop safety-critical content" goal.

**Required unlock steps:**

1. **Measure real arch slice sizes** — collect `sections.architecture_md.tokens` from
   per-run `context-budget.json` artifacts across ≥ 10 full-corpus bench issues:
   ```bash
   # Example: extract p90 slice size from recent artifacts
   python3 -c "
   import json, glob, statistics
   sizes = []
   for f in glob.glob('$ARTIFACTS_DIR/**/context-budget.json', recursive=True):
       d = json.load(open(f))
       s = d.get('sections', {}).get('architecture_md', {}).get('tokens')
       if s: sizes.append(s)
   sizes.sort()
   p90 = sizes[int(len(sizes) * 0.9)] if sizes else 'no data'
   print(f'p90 arch slice: {p90} tokens ({len(sizes)} samples)')
   "
   ```

2. **Raise `architecture.max_tokens`** above the p90 arch slice size (currently 3000;
   likely needs to be 4000–5000). This is a separate config-only change requiring a
   re-calibration pass to confirm `section_at_risk_rate` drops to 0%.

3. **Re-run calibration** with the new `architecture.max_tokens` and a candidate budget.
   Gates: `over_budget_rate ≤ 10%` + `section_at_risk_rate == 0%`.

4. **Flip** refine, plan, implement using the Observe → Enforce Procedure above.
```

With:

```markdown
## Path to Phase 4 — Current Status

Phase 4 (budget enforcement) is **live for all scenarios except `implement`**:
- **Conformance and code-review**: enforcement active since T6 (#719).
- **Refine and plan**: enforcement active since T3b (#733) — gate evidence in #731 (PR #739):
  `section_at_risk_rate == 0%` and `over_budget_rate == 0%` at 30,000 tokens after
  `architecture.max_tokens` was raised to 5,000.
- **Implement**: observe-only — deferred to a follow-up ticket.

### Follow-up Path for deferred scenarios (implement)

**Why deferred:** `implement` was explicitly excluded from this ticket per the issue scope
boundary. It requires its own calibration pass.

**Required unlock steps:**

1. Run calibration for `implement`:
   ```bash
   python3 dark-factory/evals/token_opt_eval.py --calibrate \
     --budget 30000 --scenario implement
   ```
2. Gates: `over_budget_rate ≤ 10%` + `section_at_risk_rate == 0%` across ≥ 10 issues.
3. Flip `enforce.implement: true` in `config.yaml` and update this runbook.
```

4. **Verify no test regressions:**

```bash
cd /workspace/markethawk
python -m pytest dark-factory/tests/test_budget_enforce_dag.py -v
# Expected: all tests PASSED
```

5. **Commit:**

```bash
git add docs/agents/dark-factory-token-optimization.md
git commit -m "docs(#733): update runbook — refine + plan enforcement now live (T3b)"
```

---

## Rollback

Per the runbook Tier 2 procedure: set `enforce.refine: false` and `enforce.plan: false` in `config.yaml` and commit. No scheduler restart or image rebuild required — takes effect on the next factory run (clone-read).
