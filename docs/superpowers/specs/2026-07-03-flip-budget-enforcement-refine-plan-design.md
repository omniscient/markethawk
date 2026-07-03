# Phase 4b T3: Flip Budget Enforcement for Refine + Plan

**Status:** design
**Date:** 2026-07-03
**Issue:** #733
**Depends on:** #731 (arch-slice cap raise + full-corpus recalibration — PR #739)
**Predecessor spec:** `docs/superpowers/specs/2026-07-02-token-opt-phase4-enforcement-design.md`

---

## Problem

Budget enforcement for `refine` and `plan` was blocked during Phase 4 T6 because
`architecture.max_tokens: 3000` was below real arch-slice sizes (~4,600 tokens p90),
causing `section_at_risk_rate == 50%` at every tested budget. #731 fixed the root cause
by raising the cap to 5,000 and proving via full-corpus recalibration that
`section_at_risk_rate == 0%` and `over_budget_rate == 0%` for both scenarios at 30,000 tokens.

This ticket is the mechanical go-live: flip `enforce.refine` and `enforce.plan` from
`false` to `true` in `config.yaml`, update the exact-state test guard, and update the
operator runbook to reflect the new enforcement state.

## Requirements

1. **`config.yaml`** — set `token_optimization.enforce.refine: true` and
   `token_optimization.enforce.plan: true`. Budgets for both remain 30,000 (validated
   by #731's scorecard).

2. **`enforce.implement` stays `false`** — out of scope; this ticket is narrowly scoped
   to refine + plan only.

3. **Test guard** — update `test_config_enforce_t6_state` in
   `dark-factory/tests/test_budget_enforce_dag.py` to the new intended map:
   `refine: True, plan: True`. The `test_config_budgets_t6_state` guard is unchanged
   (budgets map does not change). Test names stay as-is (`_t6_state`).

4. **Runbook** — update `docs/agents/dark-factory-token-optimization.md`:
   - Budget Enforcement status table: mark refine and plan as **enforced**.
   - "Path to Phase 4 — Current Status" section: update prose and the deferred-scenarios
     section to remove refine/plan from the "Follow-up Path" (they are now live) and
     leave only `implement` as deferred.

5. **Scope boundary** — only the three files above are touched:
   - `.claude/skills/refinement/config.yaml`
   - `dark-factory/tests/test_budget_enforce_dag.py`
   - `docs/agents/dark-factory-token-optimization.md`

## Architecture / Approach

### Chosen approach: direct in-place config flip

Set `enforce.refine: true` and `enforce.plan: true` directly in `config.yaml`. No code
changes needed — the enforcement machinery (`budget_enforce.py`, DAG nodes, optimizer
overrides) was already wired in Phase 4 T3/T6. The per-scenario `enforce` flags are the
sole gating mechanism; flipping them is sufficient for enforcement to activate on the next
factory run.

Since `config.yaml` is **clone-read** (every factory run clones the repo fresh), a commit
to `main` takes effect immediately on the next run — no scheduler restart, no image
rebuild.

### How enforcement activates for refine/plan

The `enforce-budget-refine` and `enforce-budget-plan` DAG nodes already exist (wired in
Phase 4 T3). Each runs `budget_enforce.py` pre-phase; with the enforce flag now `true`,
the script exports derived caps to `$ARTIFACTS_DIR/token-opt-caps.env`, which the command
phase sources — tightening context sections (architecture slice, memory, comments) to fit
within the 30,000-token budget. The node is `|| true` (fail-open), so any enforcement
failure falls back to config defaults.

### Test guard update rationale

`test_config_enforce_t6_state` is an exact-state guard: it asserts the full enforce map
matches the intended deployment state. Updating the expected `refine` and `plan` values
to `True` makes the test act as a regression tripwire — it will fail immediately if a
config edit accidentally reverts the enforcement flip. The test name (`_t6_state`) is kept
in place per the codebase convention: these guards track the config's intended state, not
which ticket last touched them.

## Alternatives Considered

### Option A: Flip only `enforce.refine` first, then `enforce.plan` in a follow-up

Safer blast radius — if refine enforcement regresses, plan is unaffected. Rejected:
the scorecard proves both scenarios clear the gate at the same budget (30k, same arch-cap
fix), and the issue explicitly scopes both together. Splitting adds churn with no
calibration benefit.

### Option B: Also flip `enforce.implement` in this ticket

Would complete the refine/plan/implement trio simultaneously. Rejected: the issue body
explicitly excludes `implement` and marks `enforce.implement` must stay `false`. The
acceptance criteria enforces this scope boundary; implement should be a separate ticket
after its own calibration evidence.

### Option C: Rename the test guard to `_t3_state`

Would reflect that Phase 4b T3 (this ticket) advanced the state. Rejected: the
`_t6_state` naming tracks the inception snapshot, not the last modifier. Renaming on
every flip creates indefinite churn; the product owner confirmed keeping names in place.

## Open Questions (non-blocking)

- The runbook's "Follow-up Path" section will still reference `implement` as deferred.
  When #732 (or a future implement-enforcement ticket) lands, that section should be
  removed entirely. No action needed here.

## Assumptions

- **#731 / PR #739 is merged to `main` before this PR merges.** The scorecard evidence
  that justifies the flip lives in that PR. If #731 is reverted, this ticket should be
  reverted via the Tier 2 rollback (see runbook).
- **The 30,000-token budget for refine/plan is stable.** It is derived from the
  full-corpus calibration across 22 issues in #731. Corpus growth may shift p90 arch
  sizes over time; re-run calibration if `over_budget` events spike.
- **Rollback is a Tier 2 git commit** (`enforce.refine: false`, `enforce.plan: false`
  in `config.yaml`) following the runbook procedure — no scheduler restart or image
  rebuild needed.
