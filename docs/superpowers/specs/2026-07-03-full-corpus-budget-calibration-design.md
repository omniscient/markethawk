# Phase 4b T1: Full-Corpus Budget Calibration

**Status:** design
**Date:** 2026-07-03
**Issue:** #730
**Parent epic:** #713 (token optimization)
**Predecessor:** #719 (T5 smoke calibration — 2-issue run, set provisional 22k conformance/code-review budgets)

---

## Problem

Issue #719 set provisional `budgets.conformance = 22000` and `budgets.code-review = 22000` in `.claude/skills/refinement/config.yaml` based on a 2-issue smoke run. With both enforcement scenarios live (T6: `enforce.conformance = true`, `enforce.code-review = true`), those budgets need validation against the full bench corpus before the values can be treated as authoritative. If the full-corpus calibration recommends a different safe budget for either scenario, the config and its test guard must be updated atomically.

Additionally, the p90 uncapped `architecture_md` slice size per scenario is needed as the direct input for a follow-up cap-raise ticket (`architecture.max_tokens` is currently 3000 and may need to increase for the deferred scenarios).

## Goal

1. Run the calibration evaluator over the full bench corpus and commit the artifacts.
2. Confirm or adjust the provisional 22k budgets, updating config and test guard if needed.
3. Record per-scenario p90 uncapped architecture slice sizes in the PR description.
4. Leave `enforce` flags untouched (refine/plan/implement stay `false`).

## In Scope

- Running `token_opt_eval.py --calibrate` with no `--issues` filter (uses the full bench suite + supplemental issues the script auto-includes)
- Committing the generated `budget-calibration-scorecard-<date>.md` to `dark-factory/evals/reports/`
- Committing the raw `token-opt-eval-<date>.json` (containing `calibration_results`) to `dark-factory/evals/results/`
- Updating `budgets.conformance` and/or `budgets.code-review` in `.claude/skills/refinement/config.yaml` **only if** the safe-budget recommendation diverges from 22000
- Updating `test_config_budgets_t6_state` in `dark-factory/tests/test_budget_enforce_dag.py` to match any changed budget values
- Noting any budget change in the runbook table in `docs/agents/dark-factory-token-optimization.md`
- Reporting per-scenario p90 uncapped arch-slice sizes in the PR description

## Out of Scope

- Changing `enforce` flags (must stay at T6 state: `conformance: true`, `code-review: true`; refine/plan/implement: `false`)
- Updating refine/plan/implement budget values (those are 30000 and not under calibration)
- Modifying the calibration script itself (`token_opt_eval.py`)
- Any changes to DAG files or budget_enforce.py

---

## Approach

### Step 1: Run the calibration

Inside the factory container:

```bash
python3 dark-factory/evals/token_opt_eval.py --calibrate
```

The `--calibrate` flag runs the full token-optimization eval across all corpus issues, then sweeps candidate budgets (`[22000, 24000, 26000, 28000, 30000, 32000, 36000, 40000]` by default) for all 5 enforcement scenarios. It emits:

- `dark-factory/evals/results/token-opt-eval-<date>.json` — raw eval + `calibration_results` key
- `dark-factory/evals/reports/budget-calibration-scorecard-<date>.md` — human-readable scorecard with per-scenario p50/p90, over-budget rates, section-at-risk rates, and safe-budget recommendations

The `safe_budget_recommendation()` function returns the lowest budget where:
- `section_at_risk_rate == 0%` (no required arch sections trimmed)
- `over_budget_rate ≤ 10%`

### Step 2: Interpret the scorecard

Read the scorecard's "Safe Budget Recommendations" table. For each of conformance and code-review:

- **If recommendation == 22000**: no config change needed. Document confirmed.
- **If recommendation > 22000**: update the config and test guard as described in Step 3.
- **If no recommendation** (all budgets fail): post a comment on #730 flagging this unexpected state and add `needs-discussion`.

Each scenario is evaluated independently — conformance and code-review may get different safe-budget recommendations.

### Step 3: Update config and test guard (conditional)

If either budget changes from 22000:

**`.claude/skills/refinement/config.yaml`** — update `token_optimization.budgets`:
```yaml
budgets:
  conformance: <new_value>   # only if changed
  code-review: <new_value>   # only if changed
```

**`dark-factory/tests/test_budget_enforce_dag.py`** — update `test_config_budgets_t6_state`:
```python
expected = {
    "refine": 30000,
    "plan": 30000,
    "implement": 30000,
    "conformance": <new_value>,   # only if changed
    "code-review": <new_value>,   # only if changed
}
```

**`docs/agents/dark-factory-token-optimization.md`** — note the change in the runbook's budget table (the row(s) for conformance/code-review showing "provisional 22k → full-corpus N").

### Step 4: Compute and report p90 uncapped arch-slice sizes

For each of the 5 enforcement scenarios, compute the p90 of `sections.architecture_md.tokens` from the raw eval JSON, restricted to:
- Issues where slicing occurred (`fallback == false` or `sliced == true` in the per-issue data)
- Using the script's existing `_percentile(vals, 90)` helper (linear interpolation) for consistency with the scorecard

Report 5 numbers — one p90 per scenario (refine, plan, implement, conformance, code-review) — in the PR description. If a scenario has no sliced issues in the corpus, report "no sliced samples" rather than computing over fallback sizes.

These numbers feed the follow-up ticket that decides whether to raise `architecture.max_tokens` (currently 3000) for the deferred scenarios.

### Step 5: Commit

```bash
git add dark-factory/evals/reports/ dark-factory/evals/results/
# If budgets changed:
git add .claude/skills/refinement/config.yaml dark-factory/tests/test_budget_enforce_dag.py docs/agents/dark-factory-token-optimization.md
git commit -m "feat(#730): full-corpus budget calibration — confirm/adjust 22k budgets"
```

---

## Alternatives Considered

### Alt A: Only calibrate conformance/code-review scenarios (`--scenarios conformance,code-review`)

**Pro:** Faster run; narrowly scoped to the two live-enforcement scenarios.  
**Con:** Loses p90 arch-slice data for refine/plan/implement needed by the cap-raise ticket. The full-corpus run is needed anyway to report p90 per scenario, so there's no cost saving.

**Verdict:** Rejected. Run all 5 scenarios with no filter.

### Alt B: Adjust budgets in a separate PR from the calibration artifacts

**Pro:** Cleaner commit history.  
**Con:** The test guard is an atomic constraint — `test_config_budgets_t6_state` checks exact values, so config and test must change in the same commit. Splitting into two PRs creates a window where CI would fail. Issue #730 also explicitly says to do both in the same pass.

**Verdict:** Rejected. Config, test guard, and runbook note go in the same commit as the artifacts if a change is needed.

---

## Acceptance Criteria

- [ ] `budget-calibration-scorecard-<date>.md` committed to `dark-factory/evals/reports/`
- [ ] `token-opt-eval-<date>.json` with `calibration_results` key committed to `dark-factory/evals/results/`
- [ ] `budgets.conformance` and `budgets.code-review` in `config.yaml` either confirmed (unchanged) or adjusted to the full-corpus safe-budget recommendation
- [ ] `test_config_budgets_t6_state` matches config exactly
- [ ] If budgets changed: runbook table updated
- [ ] PR description includes per-scenario p90 uncapped arch-slice sizes (5 values, sliced-issues-only, flagging "no sliced samples" where applicable)
- [ ] `enforce` flags NOT changed from T6 state

---

## Assumptions

- **[ASSUMED]** The factory container has `gh` CLI access and the necessary `ANTHROPIC_API_KEY` to run `token_opt_eval.py --calibrate`. If the calibration pass requires real API calls to estimate token counts, the run must happen inside the factory container, not locally.
- **[ASSUMED]** The "full bench corpus" is defined by `token_opt_eval.py`'s default issue list — bench suite 10 issues + supplementals (`SUPPLEMENTAL_SCOPE_SPILLOVER` + `SUPPLEMENTAL_FACTORY_REGRESSION`, currently 18 issues total). No `--issues` filter needed.
- **[ASSUMED]** If the safe-budget recommendation for a scenario is `None` (no candidate budget passes the criteria), the implementer posts a comment on #730 and adds `needs-discussion` rather than guessing a value.

---

## Open Questions (non-blocking)

- **Follow-up cap-raise ticket**: The p90 arch-slice data from this run will inform whether `architecture.max_tokens` should be raised from 3000. That ticket is explicitly NOT part of #730.
- **Phase 4b T2+**: Subsequent Phase 4b tasks (plan/implement budget calibration, flipping enforce flags for deferred scenarios) depend on this run's output.
