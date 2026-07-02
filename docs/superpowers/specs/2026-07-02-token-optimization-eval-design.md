# Token Optimization Quality & Safety Evaluation — Design Spec

**Date:** 2026-07-02
**Status:** Spec generated — pending review
**Issue:** [#672](https://github.com/omniscient/markethawk/issues/672)
**Epic:** [#663](https://github.com/omniscient/markethawk/issues/663) — Dark Factory token optimization

---

## Overview

The Dark Factory token optimization epic (#663) introduced component-scoped ARCHITECTURE.md slicing,
diff line caps, and memory retrieval caps to reduce per-run context tokens. Before enforcing hard
token budgets, this evaluation proves that optimized context packs retain the same safety-critical
content as baseline (unoptimized) packs, and quantifies the savings by scenario.

The output is a **reusable Python evaluation script** (`dark-factory/evals/token_opt_eval.py`) that
can be re-run whenever `context_budget.py` or `architecture_slice.py` changes, and a **committed
markdown scorecard** that closes the acceptance criteria for this issue.

---

## Problem Statement

The slicing, capping, and digesting introduced in #663 reduce context tokens, but without a
systematic check, a future change to `context_budget.py` or `architecture_slice.py` could silently
drop safety-critical rules (e.g. the migration gate, the backend-reload validation step) or
issue-specific ARCHITECTURE.md sections from a context pack. There is no regression guard for this
today.

---

## Requirements

From the issue body and Q&A:

1. **Token savings measurement**: For at least 5 historical issues, compute baseline tokens (all #663
   optimizations disabled) vs. optimized tokens (current code) for Tier 1 scenarios
   (`refine`, `plan`, `implement`).

2. **Safety-critical rule verification**: For every evaluated issue and scenario, assert a curated
   list of safety-critical rule strings is present in the optimized context pack. Failures surface as
   explicit regressions, not silent drops.

3. **Section coverage verification**: For every evaluated issue, log which ARCHITECTURE.md sections
   the slicer included and omitted, and assert that the component-required sections are present.

4. **Both-pack baseline check**: Run safety checks on the baseline pack first, so a string missing
   from both packs is flagged as a pre-existing gap (not a regression introduced by optimization).

5. **Scorecard**: Per-issue, per-scenario table of: baseline tokens, optimized tokens, savings %,
   and safety check pass/fail matrix. Recommend which scenarios are safe to enforce first.

6. **Evaluation set**: 10 bench suite issues as the primary corpus (backbone), supplemented with
   scope-spillover issues (#579, #564, #523, #503) for large-input coverage and factory-regression
   issues (#632, #673, #695–#700) for safety-rule verification.

---

## Architecture / Approach

### Approach A — Offline eval script (chosen)

A single Python script `dark-factory/evals/token_opt_eval.py` that:

1. Reads `dark-factory/bench/suite.json` to get the 10 bench issue numbers.
2. Fetches issue metadata (labels, body) via `gh issue view` for each issue plus the supplemental
   set.
3. For each issue, calls `build_budget()` from `context_budget.py` **twice** per Tier 1 scenario:
   - **Baseline**: forces `architecture_md` to full-doc fallback by passing no labels/files/component
     to `slice_architecture()` (triggers `component_unresolved` fallback path in
     `architecture_slice.py:336`), and sets diff line cap to ∞.
   - **Optimized**: normal invocation with issue labels forwarded to `infer_component()`.
4. For each output context pack, runs:
   - **(a) String presence checks**: assert each entry in a curated `SAFETY_RULES` list is present
     in the assembled `context-pack.md` text.
   - **(b) Section presence checks**: assert the component-required ARCHITECTURE.md sections
     (from `COMPONENT_SECTION_MAP` in `architecture_slice.py`) are all present in the pack text.
5. Emits `dark-factory/evals/results/token-opt-eval-<date>.json` (machine-readable) and
   `dark-factory/evals/reports/token-opt-scorecard-<date>.md` (human-readable).

### Baseline vs. Optimized token comparison

The dominant token savings source in #663 is architecture slicing. CLAUDE.md is included in full in
both baseline and optimized packs (no CLAUDE.md slicing exists yet), so CLAUDE.md tokens are
constant across rows. The per-scenario deltas break down as:

| Scenario | Baseline section that changes | How baseline is forced |
|----------|-------------------------------|------------------------|
| `refine` | `architecture_md` (full doc) | `slice_architecture()` called with no labels/component |
| `plan`   | `architecture_md` (full doc) | same |
| `implement` | `architecture_md` (full doc) | same |

Tier 2 scenarios (`continue`, `conformance`, `code-review`) are scored only for issues that
plausibly reached that stage and labeled as diff-cap savings (a different mechanism than doc slicing).

### Safety-critical rule list (SAFETY_RULES)

Derived from CLAUDE.md "Development Rules" section:

```python
SAFETY_RULES = [
    "alembic upgrade head",
    "alembic revision --autogenerate",
    "npx tsc --noEmit",
    "docker-compose logs backend",
    "models/__init__.py",          # new-model registration requirement
    "Import and add it to",        # new-model import step
    "curl",                        # endpoint validation step
]
```

Each rule is checked as a substring of the assembled context pack text. A rule missing from the
baseline pack is flagged `gap:pre-existing`. A rule present in baseline but absent from optimized
is flagged `gap:regression`.

### Section presence check

For each issue, the slicer infers a component (backend/frontend/dark-factory/infrastructure) from
its labels. The eval verifies that `COMPONENT_SECTION_MAP[component]` entries (from
`architecture_slice.py`) are all present in the optimized pack text as `## <section>` headings.
Omitted sections are logged per issue. Any omitted section that appears in the component map is
flagged as an unexpected drop.

### Output artifacts

```
dark-factory/evals/
  token_opt_eval.py             # reusable eval script (committed)
  results/
    token-opt-eval-YYYY-MM-DD.json   # machine-readable (gitignored via results/)
  reports/
    token-opt-scorecard-YYYY-MM-DD.md  # committed one-time report for this issue
```

The `results/` directory is gitignored (like `dark-factory/bench/results/`). The scorecard report
is committed.

### Scorecard format

```
## Token Savings Scorecard — 2026-07-02

### Per-issue Savings (Tier 1: refine / plan / implement)

| Issue | Size | Component | Baseline (tokens) | Optimized (tokens) | Savings % | Safety |
|-------|------|-----------|-------------------|--------------------|-----------|--------|
| #224  | S    | dark-factory | 48,200         | 28,100             | -41.7%    | ✅ PASS |
...

### Safety Check Details

| Rule | #224 baseline | #224 optimized | ... |
|------|---------------|----------------|-----|
| `alembic upgrade head` | present | present | ... |
...

### Section Coverage

| Issue | Component | Sections kept | Sections omitted |
|-------|-----------|---------------|------------------|
...

### Recommendations

Scenarios safe to enforce (hard budget) first: ...
Scenarios requiring further review: ...
```

---

## Alternatives Considered

### B — Light bench replay (actual factory runs)

Run the factory pipeline for each bench task (like `bench/run_suite.sh`) and capture context budgets
mid-run. This would validate quality end-to-end (oracle tests pass with optimized context).

**Rejected**: Size:M scope and token cost constraints. A 10-issue × 3-scenario replay costs $8–$15
and takes 30–60 min. The eval script approach answers the same safety questions deterministically
for free.

### C — Manual one-time analysis only

Hand-run `context_budget.py` for a few issues, write a markdown report by hand.

**Rejected**: Not repeatable. The next `context_budget.py` change would require re-doing the
analysis manually. The issue's acceptance criteria implies this should be a repeatable gate
(parallel to the bench suite for harness changes).

---

## Open Questions

1. **Diff and memory caps in baseline**: The baseline definition in Q1 calls for "uncapped diff/memory"
   too. For issues where historical diffs are not stored in the artifacts directory, the diff section
   will show `status: dropped` in both baseline and optimized — making it an equal comparison. This
   is acceptable for the initial scorecard; the diff cap evaluation can be added in a follow-up when
   larger issues with stored diffs are used.

2. **`continue` scenario in Tier 2**: Scoring `continue` requires a `comment-digest.md` artifact,
   which is generated mid-run. For the initial eval, `continue` is scored only for issues where a
   digest file can be reconstructed (or faked with raw comments). This is deferred unless a clean
   approach emerges.

3. **factory-regression issues as safety corpus**: Issues #695–#700 have `needs-discussion` labels —
   they may not have enough stored context to reconstruct a meaningful context pack. The eval script
   should skip an issue gracefully if its issue body or labels are insufficient, logging a `skipped`
   row.

---

## Assumptions

- [A1] The architecture slicer's `component_unresolved` fallback correctly represents a "no
  optimization" baseline for the `architecture_md` section. Other sections (CLAUDE.md, skill_prompts,
  issue_context) are unchanged between baseline and optimized — confirmed by `_SECTION_REGISTRY` in
  `context_budget.py`.

- [A2] The 10 bench suite issues in `suite.json` have publicly accessible issue data via
  `gh issue view`, since they are closed merged issues on the `omniscient/markethawk` repo.

- [A3] The `SAFETY_RULES` string list is a reasonable proxy for "safety-critical rules" for an
  initial evaluation. It can be expanded in future runs without changing the script interface.

- [A4] Saving the report under `dark-factory/evals/reports/` (committed) and results JSON under
  `dark-factory/evals/results/` (gitignored) follows the precedent of
  `dark-factory/evals/memory-quality-report.md` and `dark-factory/bench/results/` (gitignored).
