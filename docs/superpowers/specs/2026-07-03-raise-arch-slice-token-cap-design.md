# Phase 4b T2: Raise Arch-Slice Token Cap + Recalibrate

**Status:** design
**Date:** 2026-07-03
**Issue:** #731
**Predecessor:** #730 (full-corpus budget calibration — provides the p90 data)
**Builds on:** budget_enforce.py (T1 #714), token_opt_eval.py calibration (T5 #719), T6 enforcement flip (#728)

---

## Problem

`derive_caps` in `budget_enforce.py` distributes per-scenario budget across optimizable sections by clamping each proportional allocation to `[floor, config_default]`. The current `architecture.max_tokens: 3000` is below the real uncapped arch-slice size for the majority of issues in the corpus. As a result, `derive_caps` always clamps the architecture slot to 3,000 regardless of the scenario budget — making the cap, not the budget, the binding constraint.

Consequence: `token_opt_eval.py --calibrate` (T5 run) showed `section_at_risk_rate: 50%` for refine/plan/implement at **every** budget from 22k to 40k. The entire rate is attributable to this cap mis-calibration, not to actual budget insufficiency. Raising the cap above the p90 uncapped slice size eliminates the structural root cause.

## p90 Data (from #730)

From the full-corpus calibration run (22 issues, PR #736):

| Scenario | Sliced issues | p90 uncapped arch-slice (tokens) |
|---|---|---|
| refine | 5 | **4,645** |
| plan | 5 | **4,644** |
| implement | 5 | **4,645** |
| conformance | no sliced samples | — |
| code-review | no sliced samples | — |

The current cap of 3,000 is 35% below p90. Any issue with an arch slice above 3,000 triggers `section_at_risk`.

## Requirements

1. Raise `architecture.max_tokens` above the p90 (4,645 tokens) in `config.yaml`.
2. Update `architecture.min_tokens` to preserve the 50%-of-max floor convention (T1 #714).
3. Update `_HARDCODED` in `budget_enforce.py` to stay in lockstep with config.yaml (it is the fallback for missing/partially-specified config, not a dead branch).
4. Update test assertions in `test_budget_enforce.py` that pin the old cap value as exact expected values.
5. Re-run `token_opt_eval.py --calibrate` (full corpus, no `--issues` filter); commit the scorecard.
6. Scorecard must show `section_at_risk_rate == 0%` and `over_budget_rate <= 10%` for refine/plan at their 30,000-token budgets.
7. `enforce` flags must NOT be touched (the enforcement flip is a separate follow-on ticket).

## Architecture / Approach

### New cap values

```
architecture.max_tokens: 5000   # raised from 3000; ~7.6% above p90=4645
architecture.min_tokens: 2500   # 50% of max, raised from 1500
```

**Justification for 5,000:** The p90 is 4,645. A cap at 4,700/4,800 leaves 1–3.5% headroom — fragile against any future corpus addition that shifts p90 up. 5,000 is a round, self-documenting number that eliminates fragility while adding only 2,000 tokens to the reserved-sum versus the old cap (within a 28,000-token allowance on a 30k budget, this is safe for `over_budget_rate`).

### Files changed

**`config.yaml`** (`token_optimization.architecture`):
- `max_tokens: 3000` → `5000`
- `min_tokens: 1500` → `2500`

**`dark-factory/scripts/budget_enforce.py`** (`_HARDCODED` dict, lines 28–35):
- `"architecture": {"max_tokens": 3000, "min_tokens": 1500}` → `{"max_tokens": 5000, "min_tokens": 2500}`

**`dark-factory/tests/test_budget_enforce.py`** — update all assertions that pin the old cap as an expected exact value:
- `DEFAULT_CONFIG` (lines 18–19): `max_tokens: 3000` → `5000`, `min_tokens: 1500` → `2500`
- Test 12 (proportional distribution — normal): comment sum-of-defaults `12500` → `14500`; `== 3000` assertion → `== 5000`
- Test 13 (floor clamp — tiny allowance): comment sum-of-floors `6250` → `7250` (2500+750+1000+3000); `== 1500` arch assertion → `== 2500`
- Test 14 (default clamp — large allowance): comment sum-of-defaults `12500` → `14500`; `== 3000` arch assertion → `== 5000`
- Test 24 (missing config uses hardcoded defaults): `== 3000` → `== 5000`, `== 1500` → `== 2500`

**Do NOT change:**
- Line 282: `"architecture": {"max_tokens": 3000, "min_tokens": 100}` — custom test config with intentional floor=100, not DEFAULT_CONFIG.
- Line 388: `"architecture_md": {"tokens": 3000, ...}` — a section *size* (the arch slice token count in that test fixture), not a cap value.
- `make_sections(arch_tokens=3000)` default — represents typical arch slice size in test helpers, not the cap.

### Calibration step

After the config and code changes, inside the factory container:

```bash
python3 dark-factory/evals/token_opt_eval.py --calibrate
```

Commit the generated scorecard to `dark-factory/evals/reports/` and raw JSON to `dark-factory/evals/results/`.

The scorecard must show for refine and plan (at their 30,000-token budgets):
- `section_at_risk_rate == 0%`
- `over_budget_rate <= 10%`

If `section_at_risk_rate` is non-zero after the cap raise, investigate whether any new corpus issue has an arch slice above 5,000 before accepting the result.

## Alternatives Considered

**Option A — cap at 4,700 (minimal headroom ~1.2% above p90)**
Rejected: p90 will shift as corpus grows; a 1.2% buffer re-introduces the fragility the ticket exists to eliminate. The cost of being wrong is another 50% `section_at_risk` rate until the next cap-raise cycle.

**Option B — cap at 4,800 (~3.4% headroom)**
Rejected for the same reason; slightly better but still too close to the current p90 for a config value that will not be re-calibrated until the next tokenopt cycle.

**Option C — cap at 5,000 (selected, ~7.6% headroom)**
Sufficient headroom for the foreseeable corpus while remaining well within the scenario budget. Budget impact: arch slot grows from 3k to 5k → +2k to reserved-sum against 28k allowance. `over_budget_rate` impact is negligible.

## Assumptions

- The p90=4,645 from #730's 22-issue corpus is stable enough to base the cap on. If the corpus substantially changes before the next calibration cycle, the cap may need re-evaluation (but will not silently reintroduce `section_at_risk` unless a slice exceeds 5,000 tokens).
- The factory container has `ANTHROPIC_API_KEY` and full corpus access to run `--calibrate`.
- conformance/code-review scenarios are not affected (no sliced samples in the corpus → no `section_at_risk` from this change).

## Open Questions

- None blocking. The T6 enforcement flip for refine/plan (setting `enforce.refine: true` and `enforce.plan: true`) is a separate follow-on ticket and is explicitly out of scope here.
