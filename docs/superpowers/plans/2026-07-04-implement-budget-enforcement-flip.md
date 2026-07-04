# Phase 4b T5: Flip Budget Enforcement for Implement — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete the Phase 4 budget enforcement rollout by flipping `enforce.implement: false → true` in `config.yaml`, updating the exact-state test guard, and bringing the runbook to reflect full Phase 4 live status (all 5 scenarios enforced).

**Architecture:** Purely declarative — no new logic, no new DAG nodes. The `enforce-budget-implement` node already exists (shipped in #723 T3) and already reads `enforce.implement` from config. Setting the flag to `true` causes `budget_enforce.py` to export derived caps in enforce mode on the next factory run (config.yaml is clone-read). The change takes effect immediately without a container rebuild.

**Tech Stack:** YAML config edit + pytest guard update + Markdown runbook update. All changes are clone-read at runtime — no Docker rebuild required.

**Spec:** `docs/superpowers/specs/2026-07-04-implement-budget-enforcement-flip-design.md`

**Key constraint:** Scope is config + tests + runbook **only**. Do not create new scripts, new DAG nodes, or schema changes.

---

## File Structure

| File | Change |
|---|---|
| `.claude/skills/refinement/config.yaml` | **MODIFY** `enforce.implement: false → true` with T5 provenance comment |
| `dark-factory/tests/test_budget_enforce_dag.py` | **MODIFY** `test_config_enforce_t6_state`: `"implement": False → True` |
| `docs/agents/dark-factory-token-optimization.md` | **MODIFY** Status table + preamble + Overview config block; remove Follow-up Path subsection |

---

## Tasks

### Task 1: Update test guard to expect `implement: True`

**Files:** `dark-factory/tests/test_budget_enforce_dag.py`

This is the TDD step — update the exact-state guard to reflect the intended post-flip state, then verify the test fails (because config still says `false`). The test failing confirms the guard is a real gate, not a no-op.

- [ ] Edit `dark-factory/tests/test_budget_enforce_dag.py` at the `test_config_enforce_t6_state` function (lines 78–89):

  Change:
  ```python
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
  ```

  To:
  ```python
  def test_config_enforce_t6_state():
      enforce = _tok_opt().get("enforce", {})
      expected = {
          "refine": True,
          "plan": True,
          "implement": True,
          "conformance": True,
          "code-review": True,
      }
      assert enforce == expected, (
          f"enforce must match the T5 intended state {expected}, got {enforce}"
      )
  ```

- [ ] Verify the test now **fails** (config still says `false`):
  ```bash
  python3 -m pytest dark-factory/tests/test_budget_enforce_dag.py::test_config_enforce_t6_state -v
  ```
  Expected output:
  ```
  FAILED dark-factory/tests/test_budget_enforce_dag.py::test_config_enforce_t6_state
  AssertionError: enforce must match the T5 intended state {'refine': True, 'plan': True, 'implement': True, ...}
  ```

> Do NOT commit yet — the test must remain broken until Task 2 supplies the config fix.

---

### Task 2: Flip `enforce.implement` in config.yaml

**Files:** `.claude/skills/refinement/config.yaml`

Flip the flag to `true` and add the T5 provenance comment (matching the style used for refine/plan in #733).

- [ ] Edit `.claude/skills/refinement/config.yaml` at line 118 (under `token_optimization.enforce`):

  Change:
  ```yaml
      implement: false
  ```

  To:
  ```yaml
      implement: true            # T5 (#734): enforcement live — #730/#731 calibration, arch-cap raise → 0% section_at_risk at 30000
  ```

- [ ] Verify the test now **passes**:
  ```bash
  python3 -m pytest dark-factory/tests/test_budget_enforce_dag.py::test_config_enforce_t6_state -v
  ```
  Expected output:
  ```
  PASSED dark-factory/tests/test_budget_enforce_dag.py::test_config_enforce_t6_state
  1 passed in 0.06s
  ```

- [ ] Run the full budget-enforce DAG test file to confirm no regressions:
  ```bash
  python3 -m pytest dark-factory/tests/test_budget_enforce_dag.py -v 2>&1 | tail -20
  ```
  Expected: all tests pass.

- [ ] Commit tasks 1 and 2 together:
  ```bash
  git add dark-factory/tests/test_budget_enforce_dag.py .claude/skills/refinement/config.yaml
  git commit -m "feat(#734): flip enforce.implement true — Phase 4b T5 final flip

  Sets enforce.implement: true in config.yaml with T5 provenance comment.
  Updates test_config_enforce_t6_state to reflect T5 intended state.
  No DAG changes — enforce-budget-implement node already exists (#723).

  Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
  ```

---

### Task 3: Update runbook to reflect Phase 4 fully live

**Files:** `docs/agents/dark-factory-token-optimization.md`

Four distinct edits to the runbook: (a) Overview config code block, (b) status table row, (c) preamble + bullet, (d) remove Follow-up Path subsection.

#### 3a — Overview "Configuration" code block (lines 38, 44)

- [ ] Update the illustrative config snippet in the "Configuration" section to reflect enforce: true and remove the stale "observe-only" and "deferred" comments.

  Change (line 38):
  ```yaml
      implement: 30000       # observe-only — enforce: false
  ```
  To:
  ```yaml
      implement: 30000       # enforced — T5 go-live (#734)
  ```

  Change (line 44):
  ```yaml
      implement: false       # deferred; see Follow-up Path below
  ```
  To:
  ```yaml
      implement: true        # T5 (#734): enforcement live — #730/#731 calibration, arch-cap raise → 0% section_at_risk at 30000
  ```

#### 3b — Status table row (line 202)

- [ ] Update the enforce status table row for implement:

  Change:
  ```
  | implement | false | 30 000 | observe-only |
  ```
  To:
  ```
  | implement | **true** | **30 000** | **enforced (T5)** |
  ```

- [ ] Update the "As of T3b" sentence above the table (line 196) to reflect all 5 scenarios are now active:

  Change:
  ```
  As of T3b (#733), budget enforcement is **active** for `conformance`, `code-review`, `refine`, and `plan`.
  ```
  To:
  ```
  As of T5 (#734), budget enforcement is **active** for all 5 scenarios.
  ```

#### 3c — "Path to Phase 4 — Current Status" preamble (lines 271–274)

- [ ] Update the section preamble:

  Change:
  ```
  Phase 4 (budget enforcement) is **mostly live** as of T3b (#733):
  - **Conformance and code-review**: enforcement active since T6 (#719).
  - **Refine and plan**: enforcement active since T3b (#733) — #731 scorecard gated go-live.
  - **Implement**: observe-only — deferred pending calibration.
  ```
  To:
  ```
  Phase 4 (budget enforcement) is **fully live** as of T5 (#734):
  - **Conformance and code-review**: enforcement active since T6 (#719).
  - **Refine and plan**: enforcement active since T3b (#733) — #731 scorecard gated go-live.
  - **Implement**: enforcement active since T5 (#734) — #730/#731 calibration confirmed 0% section_at_risk at 30,000.
  ```

#### 3d — Remove "Follow-up Path for deferred scenario (implement)" subsection (lines 276–311)

- [ ] Delete the entire `### Follow-up Path for deferred scenario (implement)` subsection and its contents (from `### Follow-up Path...` through the last `4. **Flip** implement...` paragraph, stopping before the `---` separator). The section to remove:

  ```
  ### Follow-up Path for deferred scenario (implement)

  **Why deferred:** T5 calibration showed `section_at_risk_rate == 50%` at ALL tested
  budgets (22k–40k) for implement. Root cause: `architecture.max_tokens: 3000`
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

  4. **Flip** implement using the Observe → Enforce Procedure above.
  ```

  After deletion, the blank line before `---` at line 312 should remain so the separator is still present before `## Troubleshooting`.

- [ ] Verify the runbook no longer mentions "observe-only", "deferred", or "Follow-up Path":
  ```bash
  grep -n "observe-only\|deferred\|Follow-up Path" docs/agents/dark-factory-token-optimization.md
  ```
  Expected: no output.

- [ ] Verify "fully live" and "enforced (T5)" appear:
  ```bash
  grep -n "fully live\|enforced (T5)" docs/agents/dark-factory-token-optimization.md
  ```
  Expected:
  ```
  <line>: Phase 4 (budget enforcement) is **fully live** as of T5 (#734):
  <line>: | implement | **true** | **30 000** | **enforced (T5)** |
  ```

- [ ] Commit the runbook:
  ```bash
  git add docs/agents/dark-factory-token-optimization.md
  git commit -m "docs(#734): update runbook — Phase 4 fully live as of T5

  Marks implement as enforced (T5) in status table, updates preamble
  to 'fully live as of T5 (#734)', and removes the now-completed
  Follow-up Path subsection. Config code block updated to match.

  Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
  ```
