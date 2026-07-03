# Phase 4 T6: Runbook Update + Staged Enforcement Flip

**Status:** design  
**Date:** 2026-07-03  
**Issue:** #719  
**Epic:** #713 (Phase 4 budget enforcement)  
**Design:** `docs/superpowers/specs/2026-07-02-token-opt-phase4-enforcement-design.md`  
**Depends on:** T1 (#714), T2 (#715), T3 (#716 / PR #723), T4 (#717 / PR #725), T5 (#718 / PR #727)

---

## Overview

T6 is the go-live step for Phase 4 budget enforcement. T1–T5 shipped all the machinery (derivation script, optimizer cap-override reads, DAG wiring, telemetry, calibration eval) with `enforce_budgets: false` and all `enforce` per-scenario flags at `false` — everything has been in measure-only (observe) mode since T3. T6 turns enforcement ON for the scenarios that calibration data proves safe, updates the operator runbook with the enforcement lifecycle documentation, and records the deferred path for the remaining scenarios.

**Deviation from issue body scope:** The issue originally planned to flip refine/plan/code-review. T5 calibration (smoke run, 2 bench issues) shows 50% `section_at_risk` at all budgets for refine/plan/implement — budget-invariant because `architecture.max_tokens: 3000` is below real arch slice sizes (3–4k+). Conformance and code-review show 0% `section_at_risk` and are safe to enforce today. **T6 flips conformance + code-review only;** refine/plan are explicitly deferred pending a `architecture.max_tokens` recalibration.

---

## Requirements

### Config changes (`.claude/skills/refinement/config.yaml`)

1. Set `enforce_budgets: true` — flip the master gate ON.
2. Set per-scenario `budgets`:
   - `conformance: 22000` — T5 safe-budget recommendation (provisional, smoke run).
   - `code-review: 22000` — T5 safe-budget recommendation (provisional, smoke run).
   - `refine: 30000`, `plan: 30000`, `implement: 30000` — unchanged; observe-only at conservative headroom.
3. Set per-scenario `enforce`:
   - `conformance: true`, `code-review: true` — enforcement live.
   - `refine: false`, `plan: false`, `implement: false` — remain in observe mode.

### Runbook update (`docs/agents/dark-factory-token-optimization.md`)

4. Add a **Budget Enforcement** section documenting:
   - Which scenarios are currently enforced (conformance/code-review) and why.
   - The `over_budget`, `would_trim`, and `section_at_risk` telemetry signals and where to find them (`context-budget.json` in `$ARTIFACTS_DIR`).
5. Add an **Observe → Enforce Procedure** covering:
   - Prerequisite: run the full bench-corpus calibration (`token_opt_eval.py --calibrate`) and confirm `section_at_risk_rate == 0%` and `over_budget_rate ≤ 10%` at the target budget for the scenario.
   - How to set the `budgets.<scenario>` and `enforce.<scenario>` values in `config.yaml`.
   - Confirming the budget and enforce change lands by checking `context-budget.json` on the next enforced run.
6. Extend **Disable / Rollback Procedure** with a two-tier enforcement rollback — **both tiers via git** (enforcement gates are clone-read from `config.yaml`; no env override exists, no scheduler restart required):
   - **Tier 1 — master kill** (fastest): commit `enforce_budgets: false` to `config.yaml` on main, or `git revert` the T6 config commit. Takes effect on the next factory run.
   - **Tier 2 — targeted** (one scenario): commit `enforce.<scenario>: false` to `config.yaml` on main. Same immediacy as Tier 1.
   - Document explicitly: **no env override exists** for the enforcement gates. The `enforce-budget-*` DAG nodes read `enforce_budgets` and `enforce.<scenario>` exclusively from the cloned `config.yaml` via inline Python — `TOKEN_OPTIMIZATION_ENFORCE_BUDGETS` is a stale claim from issue #673 that Phase 4 never wired up. Remove that env-override comment from the runbook; an operator relying on `.archon/.env` for enforcement rollback would be stranded mid-incident.
   - Note that wiring `TOKEN_OPTIMIZATION_ENFORCE_BUDGETS` into the enforce-budget nodes is a candidate follow-up ticket (see Open Question 2).
   - Add a **Deploy Nuance** callout: `config.yaml`, workflow YAML, and command files are **clone-read** (fresh `git clone` on every factory run) — a commit to main takes effect on the next run with no image rebuild or scheduler restart. `entrypoint.sh` (including the T4 cost-report savings line) is **baked** into the Docker image and requires a rebuild + redeploy. An operator asking "why is the cost line missing" needs this distinction.
7. Add a **Follow-up Path** section for the deferred scenarios:
   - **refine/plan**: blocked on `section_at_risk`. Next step: run full-corpus calibration to determine p90 uncapped arch slice size; raise `architecture.max_tokens` above that p90 as a separate data-driven change; re-run calibration to confirm `section_at_risk_rate == 0%`; then flip `enforce.refine` and `enforce.plan`.
   - **implement**: operational follow-up per the original Phase 4 design, gated on continued observation of conformance/code-review enforcement in production.
8. Update the **Path to Phase 4** section (lines 126–141 of current runbook) to reflect that enforcement is now live for conformance/code-review and the remaining scenarios are gated on calibration data.
9. Add a note that the 22000 budget for conformance/code-review is **provisional from a 2-issue smoke run** and should be updated after the full-corpus calibration is run.

---

## Architecture / Approach

### Config edit

```yaml
# .claude/skills/refinement/config.yaml — token_optimization block
token_optimization:
  enabled: true
  enforce_budgets: true            # WAS: false — flip ON (master gate)
  default_budget_tokens: 30000
  budgets:
    refine: 30000                  # unchanged — observe-only
    plan: 30000                    # unchanged — observe-only
    implement: 30000               # unchanged — observe-only
    conformance: 22000             # WAS: 30000 — set to T5 safe-budget rec
    code-review: 22000             # WAS: 30000 — set to T5 safe-budget rec
  enforce:
    refine: false                  # unchanged — deferred (section_at_risk)
    plan: false                    # unchanged — deferred (section_at_risk)
    implement: false               # unchanged — operational follow-up
    conformance: true              # WAS: false — flip ON
    code-review: true              # WAS: false — flip ON
  # ... per-feature enabled/max_tokens blocks unchanged ...
```

### Runbook update

The existing `docs/agents/dark-factory-token-optimization.md` has five sections:
- Active Features
- Configuration
- Disable / Rollback Procedure
- Reading the Cost Report
- Per-Section Savings Data
- Path to Phase 4

T6 adds three new sections (Budget Enforcement, Observe → Enforce Procedure, Follow-up Path) and expands the existing Disable / Rollback and Path to Phase 4 sections. No sections are removed.

### What T6 does NOT include

- No changes to `architecture.max_tokens` — that requires full-corpus calibration first.
- No changes to refine/plan/implement enforcement — deferred.
- No new env override keys for per-scenario enforce/budgets — out of scope; a follow-up if needed.
- No code changes — config.yaml and runbook doc only.

---

## Alternatives Considered

### Option A: Flip refine/plan/code-review as originally scoped

The issue body listed this set as the go-live target. Rejected because the T5 calibration shows 50% `section_at_risk` for refine/plan at all budgets — enforcement would silently trim architecture context on half of all refine/plan issues. This contradicts the Phase 4 design's core goal ("Never drop safety-critical content").

### Option B: Flip conformance/code-review only (chosen)

Data-proven safe: both scenarios show 0% `section_at_risk` and 0% `over_budget` at the T5-recommended 22000 budget. Keeps the invariant that enforcement is only turned on where calibration gives a green light. Defers refine/plan explicitly with documented reasoning and a clear follow-up path.

### Option C: Raise `architecture.max_tokens` and flip all scenarios

Would eliminate the `section_at_risk` problem for refine/plan, but requires knowing the p90 uncapped arch slice size across the full bench corpus — data not yet available. Bundling an uncalibrated cap increase with the enforcement flip is higher risk than deferring. Treat as a separate follow-up change.

---

## Open Questions (non-blocking)

1. **Full-corpus calibration timing.** The 22000 budget for conformance/code-review is from a 2-issue smoke run. Running `token_opt_eval.py --calibrate` over the full bench corpus will produce more robust budget recommendations. Should this be filed as a follow-up ticket (T7?) to confirm or adjust the 22000 values post-go-live?

2. **Per-scenario env overrides.** Currently, per-scenario `enforce` and `budgets` have no env override — rollback of a single scenario requires a `config.yaml` edit + restart. If operators need hot per-scenario rollback without a file edit, env overrides for `TOKEN_OPTIMIZATION_ENFORCE_CONFORMANCE`, `TOKEN_OPTIMIZATION_ENFORCE_CODE_REVIEW`, etc. would be needed. Worth filing a follow-up ticket?

---

## Assumptions

- **[ASSUMED]** T1–T5 are merged and in the baked image. The `budget_enforce.py` derivation script, optimizer cap-override reads, DAG `enforce-budget-*` nodes, `over_budget` telemetry, and `--calibrate` eval extension are all live.
- **[ASSUMED]** The 22000 budget for conformance/code-review is a provisional starting point from the smoke run. The full bench-corpus calibration should be run post-go-live and the budgets updated if the data diverges significantly.
- **[ASSUMED]** `section_at_risk` being budget-invariant for refine/plan is confirmed by the T5 smoke run analysis. The root cause (arch cap 3000 < real slice 3–4k+) has been identified; `architecture.max_tokens` recalibration is the required unlock.
- **[ASSUMED]** `enforce_budgets: true` + per-scenario `enforce: false` for the non-flipped scenarios means those scenarios continue in pure measure-only mode — no enforcement side-effects for refine/plan/implement.
