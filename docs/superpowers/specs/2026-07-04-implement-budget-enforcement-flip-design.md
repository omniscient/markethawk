# Phase 4b T5: Flip Budget Enforcement for Implement

**Status:** design
**Date:** 2026-07-04
**Issue:** #734
**Parent epic:** Phase 4 budget enforcement (#713 design: docs/superpowers/specs/2026-07-02-token-opt-phase4-enforcement-design.md)
**Depends on:** #730 (full-corpus calibration), #731 (arch-cap raise), #733 (refine/plan flip)

---

## Problem

Budget enforcement (Phase 4) is live for four of the five factory scenarios — conformance, code-review, refine, and plan. The `implement` scenario was deferred because T5 calibration (#713) found `section_at_risk_rate == 50%` at every tested budget (22k–40k). Root cause: `architecture.max_tokens: 3000` was below the real uncapped p90 arch slice size (~4,645 tokens), causing `derive_caps` to trim the architecture section on every issue regardless of total budget.

#731 raised the cap to 5,000 and re-ran the full-corpus calibration, proving `section_at_risk_rate == 0%` for refine/plan at 30,000 — the same corpus, the same arch slice sizes, and therefore the same result applies to implement. #733 flipped refine/plan. This ticket (#734) is the final flip, completing the Phase 4 rollout.

## Requirements

1. `enforce.implement` must be set to `true` in `.claude/skills/refinement/config.yaml`, with inline comment documenting T5 go-live provenance.
2. `budgets.implement` stays at 30,000 — confirmed by the #730/#731 calibration chain; no separate implement-specific number was warranted.
3. The exact-state test guard in `dark-factory/tests/test_budget_enforce_dag.py` (`test_config_enforce_t6_state`) must be updated to reflect `implement: True`.
4. The runbook `docs/agents/dark-factory-token-optimization.md` must be updated:
   - Status table row for implement: `enforced (T5)`.
   - "Path to Phase 4 — Current Status" preamble: "mostly live as of T3b" → "fully live as of T5 (#734)".
   - The `implement` bullet in the preamble list must reflect enforcement active.
   - The "Follow-up Path for deferred scenario (implement)" subsection must be **removed** — it describes completed work and is now stale.
5. Scope is config + tests + runbook **only** — no new scripts, no new DAG nodes, no schema changes.

## Architecture / Approach

**Approach: direct 4-file mechanical flip** (same shape as the refine/plan flip in #733)

Files changed:

| File | Change |
|------|--------|
| `.claude/skills/refinement/config.yaml` | `enforce.implement: false → true`; add T5 provenance comment |
| `dark-factory/tests/test_budget_enforce_dag.py` | `test_config_enforce_t6_state`: `"implement": False → True` |
| `docs/agents/dark-factory-token-optimization.md` | Status table + preamble update; remove Follow-up Path subsection |

The change is purely declarative — no new logic, no new DAG nodes (the `enforce-budget-implement` node already exists and already reads the `enforce.implement` config key). Setting the flag to `true` causes `budget_enforce.py` to export derived caps in enforce mode instead of observe mode, tightening the architecture/memory/comments context sections to fit the 30,000-token budget. The flip takes effect on the next factory run (config.yaml is clone-read).

**Config diff (`.claude/skills/refinement/config.yaml`):**
```yaml
  enforce:
    refine: true               # T3b: enforcement live — #733 via #731 scorecard: 0% section_at_risk
    plan: true                 # T3b: enforcement live — #733 via #731 scorecard: 0% section_at_risk
-   implement: false           # deferred; see Follow-up Path below
+   implement: true            # T5 (#734): enforcement live — #730/#731 calibration, arch-cap raise → 0% section_at_risk at 30000
    conformance: true          # T6 live
    code-review: true          # T6 live
```

**Test guard diff (`dark-factory/tests/test_budget_enforce_dag.py`):**
```python
def test_config_enforce_t6_state():
    enforce = _tok_opt().get("enforce", {})
    expected = {
        "refine": True,
        "plan": True,
-       "implement": False,
+       "implement": True,
        "conformance": True,
        "code-review": True,
    }
```

**Runbook diff (`docs/agents/dark-factory-token-optimization.md`):**

Status table row:
```
- | implement | false | 30 000 | observe-only |
+ | implement | **true** | **30 000** | **enforced (T5)** |
```

Current status preamble:
```
- Phase 4 (budget enforcement) is **mostly live** as of T3b (#733):
+ Phase 4 (budget enforcement) is **fully live** as of T5 (#734):
- - **Implement**: observe-only — deferred pending calibration.
+ - **Implement**: enforcement active since T5 (#734) — #730/#731 calibration confirmed 0% section_at_risk at 30,000.
```

Remove entire "Follow-up Path for deferred scenario (implement)" subsection.

## Alternatives Considered

**A — Minimal: config + test only, skip runbook update**
Rejected. The issue acceptance criteria explicitly require "Runbook status table + 'Path to Phase 4' update." Leaving the runbook with "mostly live" and a Follow-up Path describing completed work would mislead operators.

**B — Keep Follow-up Path with a "completed" note instead of removing it**
Rejected. Product owner confirmed Option A (remove). The runbook is an operational status document, not an audit log. Completed unlock steps become stale guidance; the git history and the inline `config.yaml` comment carry the durable breadcrumb.

**C — Raise the budget above 30,000 for implement**
Rejected. The calibration chain (#730 + #731) confirms 30,000 is valid for implement — same corpus, same arch slice sizes, same result as refine/plan. No higher budget is warranted.

## Assumptions

- The `ready-for-agent` label on #734 implies both gate conditions have been met: (1) observation window of ≥10 enforced runs without regressions, and (2) the calibrated budget derived from #730/#731. The spec takes these as given.
- `enforce-budget-implement` DAG node already exists (shipped in #723 T3) and already reads `enforce.implement` from config. No DAG changes needed.
- The test function is named `test_config_enforce_t6_state` ("t6" refers to an earlier snapshot label) — updating the expected dict value is the correct change; the function name is not changed, consistent with #733's refine/plan flip.

## Open Questions

None blocking. The gate conditions are confirmed by the `ready-for-agent` label.
