# Phase 4 T5 — Extend #672 Eval for Enforcement Calibration/Safety

**Status:** design  
**Date:** 2026-07-03  
**Issue:** #718  
**Epic:** #713 (Phase 4 budget enforcement)  
**Parent design:** `docs/superpowers/specs/2026-07-02-token-opt-phase4-enforcement-design.md`  
**Depends on:** T1 (`budget_enforce.py` + `derive_caps()`), T4 (`over_budget` telemetry fields in context-budget.json)  
**Feeds:** T6 (runbook + staged flip — T5 scorecard is the calibration data T6 uses to set per-scenario budgets and flip `enforce: true`)

---

## Problem

T1–T4 ship the budget enforcement machinery (derivation, optimizer cap-overrides, DAG wiring, telemetry). Before T6 can safely flip `enforce: true` per scenario, we need a calibration data set that answers:

1. **How often would enforcement fire `over_budget`** at a given budget, per scenario?
2. **Would enforcement ever drop a component-required ARCHITECTURE.md section** (the primary safety invariant)?
3. **What is the safe-floor budget** per scenario — the lowest budget where section-safety holds and `over_budget` rate is acceptable?

The existing #672 eval (`dark-factory/evals/token_opt_eval.py`) covers slice safety (baseline vs. optimized, section-presence). T5 extends it to simulate what `budget_enforce.derive_caps()` would *do at runtime* for each historical bench issue × scenario × candidate budget, without re-running the full context assembly.

---

## Requirements

From the issue scope and Q&A:

1. **Enforcement simulation**: for each issue × scenario × candidate budget, call `budget_enforce.derive_caps()` on the existing optimized-pack manifest data (from `context_pack.assemble_pack()` output — the same JSON already produced by the eval's existing pass). No re-assembly needed.

2. **Budget sweep**: default candidate set `[22000, 24000, 26000, 28000, 30000, 32000, 36000, 40000]`; always include `config.yaml`'s `default_budget_tokens` value even if not in the list. Overridable via `--budgets 24000,30000,...` CLI arg (mirroring the existing `--issues` comma-parse pattern).

3. **Scenario coverage**: expand to all 5 enforcement scenarios — `refine, plan, implement, conformance, code-review`. Rename the module-level constant from `TIER1_SCENARIOS` to `ENFORCEMENT_SCENARIOS`. Add `--scenarios` CLI override (comma-separated, default = all 5).

4. **Section-floor safety assertion**: when `arch_fallback=False` (architecture was sliced, not full-doc) and `derived_caps["architecture_md"] < opt_tokens["architecture_md"]`, flag `section_at_risk=True` for that issue × scenario × budget row. Reuse `_check_section_presence()` verdict: if the existing optimized-pack already shows `section_check` "missing" for any required section, propagate that as `section_at_risk=True` regardless of the budget (the risk pre-exists enforcement).

5. **Budget-calibration scorecard**: emit `dark-factory/evals/reports/budget-calibration-scorecard-<date>.md` (separate from the existing `token-opt-scorecard-*.md`). Per-scenario columns:
   - `p50_opt_tokens`, `p90_opt_tokens` — distribution of optimized-pack token counts across all issues × scenarios
   - `over_budget_rate_at_<N>` — fraction of issue × scenario rows where `over_budget=True` at each candidate budget  
   - `section_at_risk_rate_at_<N>` — fraction where `section_at_risk=True`
   - `p90_with_headroom` — `p90_opt_tokens * 1.1` (advisory column, not a gate)
   - `safe_budget_recommendation` — lowest swept candidate where `section_at_risk_rate == 0` AND `over_budget_rate ≤ 10%`; or `"none — widen --budgets"` if no candidate qualifies

6. **Raw results JSON**: append a `calibration_results` key to the existing `token-opt-eval-<date>.json` output (or write a separate `budget-calibration-<date>.json`). Each entry: `{issue, scenario, budget, over_budget, would_trim, derived_caps, section_at_risk, reserved_tokens, allowance}`.

7. **CLI mode flag**: add `--calibrate` flag. When set, run the enforcement simulation pass after the standard eval pass and emit the calibration scorecard. Without `--calibrate`, the existing eval behavior is unchanged.

8. **Fail-open**: if `budget_enforce` is unavailable (import error) or `derive_caps()` raises, log the error and mark the row `status: "calibration_error"` — do not abort the overall eval run.

---

## Architecture

### Integration point

The calibration simulation runs *after* `eval_issue_scenario()` completes for each issue × scenario. It consumes the existing `opt_manifest` dict (already in memory) — specifically:
- `opt_manifest["sections"]` → the `sections` dict passed to `derive_caps()`
- `opt_manifest["sections"]["architecture_md"]["fallback"]` → `arch_fallback`
- `opt_manifest["sections"]["architecture_md"]["tokens"]` → `opt_arch_tokens` (for `section_at_risk` check)

No re-assembly, no network calls. The simulation is pure-Python calling `derive_caps()` in a loop.

### New module structure

All changes are confined to `dark-factory/evals/token_opt_eval.py`:

```
# New top-level constant
ENFORCEMENT_SCENARIOS = ["refine", "plan", "implement", "conformance", "code-review"]
# (TIER1_SCENARIOS kept as alias = ENFORCEMENT_SCENARIOS for backward compat in tests)
TIER1_SCENARIOS = ENFORCEMENT_SCENARIOS

# New import (lazy — wrapped in try/except for fail-open)
from budget_enforce import derive_caps, _load_config as _load_enforce_config

# New function: simulate enforcement at one budget
def simulate_enforcement(
    opt_manifest: dict,
    budget: int,
    config: dict,
    scenario: str,
    section_check: dict,         # existing _check_section_presence() result
) -> dict:
    """Call derive_caps on opt_manifest sections; compute section_at_risk. Returns row dict."""

# New function: run calibration sweep for one issue
def calibrate_issue(
    issue: dict,
    scenario: str,
    opt_manifest: dict,
    section_check: dict,
    budgets: list[int],
    config: dict,
) -> list[dict]:
    """Return one row per budget."""

# Extended eval_issue_scenario return value:
# result dict gains "opt_manifest" key so calibration can reuse it

# New scorecard function
def generate_calibration_scorecard(
    calibration_rows: list[dict],
    budgets: list[int],
    output_dir: str,
) -> str:
    """Write budget-calibration-scorecard-<date>.md. Returns path."""
```

### `simulate_enforcement()` logic

```python
def simulate_enforcement(opt_manifest, budget, config, scenario, section_check):
    sections = opt_manifest.get("sections", {})
    arch_fallback = bool(sections.get("architecture_md", {}).get("fallback", False))
    opt_arch_tokens = int(sections.get("architecture_md", {}).get("tokens", 0))

    result = derive_caps(
        sections=sections,
        budget=budget,
        arch_fallback=arch_fallback,
        config=config,
        scenario=scenario,
    )

    # Section-at-risk: optimizable architecture would be trimmed below current opt slice
    section_at_risk = False
    if not arch_fallback:
        derived_arch = result.derived_caps.get("architecture_md")
        if derived_arch is not None and derived_arch < opt_arch_tokens:
            section_at_risk = True
    # Pre-existing section gaps propagate unconditionally
    if section_check and any(v == "missing" for v in section_check.values()):
        section_at_risk = True

    return {
        "budget": budget,
        "over_budget": result.over_budget,
        "would_trim": result.would_trim,
        "derived_caps": result.derived_caps,
        "section_at_risk": section_at_risk,
        "reserved_tokens": result.reserved_tokens,
        "allowance": result.allowance,
    }
```

### `section_at_risk` semantics

| `arch_fallback` | `derived_arch >= opt_arch_tokens` | `section_at_risk` | Meaning |
|---|---|---|---|
| True | — | False | Architecture in full-doc fallback; reserved, not trimmed by enforcement |
| False | True | False | Cap is generous enough; existing slice fits within derived cap |
| False | False | True | Enforcement would tighten below current slice size; required sections may be dropped |
| Any | — (pre-existing `section_check` "missing") | True | Required section already absent before enforcement; propagated as-is |

### Scorecard columns

Per-scenario summary table:

| Scenario | p50 opt_tokens | p90 opt_tokens | p90+10% headroom | over_budget@22k | over_budget@24k | … | over_budget@40k | section_at_risk@22k | … | Safe budget rec |
|---|---|---|---|---|---|---|---|---|---|---|

The `p50`/`p90` are computed over `opt_tokens` from the *existing* eval pass (not calibration rows) — one row per issue × scenario. The `over_budget@N` and `section_at_risk@N` are fractions (0.0–1.0) across all rows at that budget.

**Safe-budget recommendation algorithm:**

```python
def safe_budget_recommendation(scenario_rows: list[dict], budgets: list[int]) -> str:
    for budget in sorted(budgets):
        rows_at_budget = [r for r in scenario_rows if r["budget"] == budget]
        if not rows_at_budget:
            continue
        over_budget_rate = sum(1 for r in rows_at_budget if r["over_budget"]) / len(rows_at_budget)
        section_at_risk_rate = sum(1 for r in rows_at_budget if r["section_at_risk"]) / len(rows_at_budget)
        if section_at_risk_rate == 0.0 and over_budget_rate <= 0.10:
            return str(budget)
    return "none — widen --budgets"
```

Primary gate: `section_at_risk_rate == 0` (non-negotiable; maps to the epic's "never drop safety-critical content" invariant).  
Secondary gate: `over_budget_rate ≤ 10%` (informational flag kept low; matches the design doc's fail-open framing).  
Tie-break: lowest budget (most aggressive safe floor).

---

## Alternatives Considered

### A1: Separate new script (`budget_calibration_eval.py`) instead of extending `token_opt_eval.py`

**Rejected.** The calibration simulation consumes the existing eval's `opt_manifest` output and reuses `_check_section_presence()` and `safety_verdict()`. A separate script would either duplicate those or import them from `token_opt_eval`, coupling two scripts. Extending in-place keeps all the related eval machinery in one module and the `--calibrate` flag is a clean opt-in gate that leaves the existing baseline unchanged.

### A2: Re-run `assemble_pack()` with the tighter derived caps to get the exact section list

**Rejected.** This would require re-assembling a context pack for every issue × scenario × budget combination — 5 scenarios × 8 budgets × ~22 issues = ~880 assembly calls, each involving ARCHITECTURE.md parsing and token estimation. The simulation approach (calling `derive_caps()` on the existing manifest) is O(1) per row and gives the data T6 needs: whether enforcement would attempt to trim and by how much. Exact post-trim section presence is approximated conservatively by `section_at_risk` (trimming needed → flagged as at-risk). An exact re-assembly pass can be added as a follow-up if the approximation proves insufficient.

### A3: Analytic p90*1.1 recommendation instead of swept-candidate recommendation

**Rejected (per Q3 PO answer).** The recommendation must be one of the evaluated candidate budgets so it reports a safety verdict for a budget that was actually simulated. Reporting `p90*1.1` would recommend a budget where `section_at_risk` was never tested. The `p90_with_headroom` column is emitted as an advisory figure to help the T6 operator see the math, but is not used as the recommendation.

---

## Open Questions (non-blocking)

1. **`section_at_risk` approximation conservatism**: the check (`derived_arch < opt_arch_tokens`) flags rows where *some* trimming would occur, not necessarily where required sections are dropped. For slices that are comfortably within their cap headroom, this may produce false-positive `section_at_risk` flags. Acceptable for a calibration tool — T6 operators can inspect the `derived_caps` column to see how close the clamp is. A more precise check would require re-running the slice (see A2 above).

2. **`conformance` / `code-review` component resolution**: the `_check_section_presence()` verdict depends on `COMPONENT_SECTION_MAP` resolving a component from issue labels. Issues whose component is unresolved or unknown return `{"status": "skipped", ...}` — `section_at_risk` in that case is driven only by the `derived_arch < opt_arch_tokens` path (not the pre-existing-missing path). This is acceptable but means the section-safety gate is weaker for unresolved issues; the scorecard should note the unresolved-component count per scenario.

3. **`--calibrate` default in the bench suite runner**: `dark-factory/bench/run_suite.sh` calls `token_opt_eval.py` via the existing pattern. T5 does not change `run_suite.sh`; `--calibrate` is a separate opt-in for post-T4 calibration runs.

---

## Assumptions

- **[A1]** `budget_enforce.derive_caps()` is importable from the eval's `sys.path` (scripts dir is inserted at `_SCRIPTS_DIR`). T1 ships `budget_enforce.py` there before T5 is implemented.
- **[A2]** The optimized-pack manifest (`context-pack.json`) already contains all fields needed by `derive_caps()`: `sections[<key>].status`, `sections[<key>].tokens`, and `sections.architecture_md.fallback`. T4's telemetry additions land in `context-budget.json`; the `context-pack.json` (produced by `assemble_pack()`) has these fields since T2.
- **[A3]** The eval corpus (bench suite + supplemental issues) is representative enough that p50/p90 token distributions and `over_budget` rates meaningfully reflect production run distributions. Supplemental issues skew toward Dark Factory tickets which may have different component distributions than general app tickets.
- **[A4]** `default_budget_tokens: 30000` in `.claude/skills/refinement/config.yaml` is always included in the default sweep even if it is not in `[22000, 24000, 26000, 28000, 30000, 32000, 36000, 40000]` (it is today, but the merge logic handles future changes).
