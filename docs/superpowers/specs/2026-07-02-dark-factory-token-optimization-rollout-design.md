# Dark Factory Token Optimization — Rollout Guardrails

**Status:** design
**Date:** 2026-07-02
**Issue:** #673
**Epic:** #663 (Dark Factory token optimization: scenario-specific context budgeting and prompt slimming)
**Size:** S

## Problem

Epic #663 shipped four token optimization features across issues #664–#671 (all CLOSED):
architecture slicing (`architecture_slice.py`), memory top-k retrieval (`memory_retrieve.py`),
comment digesting (`comment_digest.py`), and diff ranking (`diff_rank.py`). All four are
**already wired into live Archon commands and the workflow YAML** — they alter prompt content
on every factory run today.

Three gaps remain before the rollout can be considered complete:

1. **No per-feature disable flags.** The `token_optimization:` block in `config.yaml` has a
   global `enabled` flag and a `enforce_budgets` flag, but no independent on/off switch for
   each optimization. An operator who wants to disable only architecture slicing (e.g., to
   A/B test a conformance failure) must edit Python source.

2. **No token savings visibility.** `context_budget.py` emits per-phase `context-budget.json`
   artifacts that record *optimized* token counts, but not what the unoptimized count would
   have been. The cost report comment on GitHub issues shows input/output tokens but no savings
   delta. Fallback events (e.g., architecture slice reverting to full doc on a safety keyword)
   are only observable via artifact inspection.

3. **No operator documentation.** There is no reference for which features are active, how to
   read the rollout phase, how to roll back, or what the path to `enforce_budgets: true` looks
   like.

## Current rollout phase

The four rollout phases from the issue body map to the actual state as follows:

| Phase | Description | Status |
|-------|-------------|--------|
| 1 | observe only — emit artifacts, no prompt changes | **Passed** (#664) |
| 2 | optimize low-risk phases (refine/plan/review) | **Active** (#665–#668, #670–#671) |
| 3 | optimize implementation/conformance with comparison evidence | **Active** (#666–#669) |
| 4 | enforce hard budgets per scenario | **Deferred** — flip `enforce_budgets: true` operationally |

Phase 4 is an operational decision (config flag + observation period), not a code change. This
spec covers the guardrails needed to safely reach and navigate phase 4.

## Requirements

1. **R1 — Per-feature flags.** Each optimization must have an independent `enabled: true/false`
   key in `config.yaml` with a matching `TOKEN_OPTIMIZATION_<FEATURE>_ENABLED` env override.
   Disabling a feature must widen context to the pre-optimization baseline, never silently drop
   content.

2. **R2 — Baseline tokens in context-budget.json.** Each optimized context section must record
   both its optimized token count and a `baseline_tokens` field (what would have been loaded
   without the optimization). The schema version bumps from 1 to 2.

3. **R3 — Savings + fallbacks in cost report.** The per-run GitHub cost report comment must
   include a "Context savings: N tokens (X% vs. baseline)" summary and a "Fallbacks:" line
   listing any optimization that reverted to full/un-optimized behavior. Both must degrade
   gracefully when budget artifacts are missing (matching the existing `|| true` guards).

4. **R4 — Fail-safe disable semantics.** Every `enabled: false` code path must route through
   an existing or new fallback branch that injects the full/original context, not omit the
   section. This matches the existing `SliceResult(fallback=True)` pattern in
   `architecture_slice.py`.

5. **R5 — Operator docs.** A new `docs/agents/dark-factory-token-optimization.md` file
   covering: active features and their config knobs, per-feature disable procedure, how to
   read the cost report savings row, the path to phase 4 (enforce), and rollback to
   pre-optimization baseline.

## Architecture / approach

### Per-feature flags in config.yaml

Add `enabled: true` under each sub-section of `token_optimization:`:

```yaml
token_optimization:
  enabled: true                              # global measurement toggle (existing)
  enforce_budgets: false                     # budget enforcement toggle (existing)
  architecture:
    enabled: true                            # NEW — env: TOKEN_OPTIMIZATION_ARCHITECTURE_ENABLED
    mode: slice
    max_tokens: 3000
  memory:
    enabled: true                            # NEW — env: TOKEN_OPTIMIZATION_MEMORY_ENABLED
    mode: top_k
    max_entries: 8
    max_tokens: 1500
  comments:
    enabled: true                            # NEW — env: TOKEN_OPTIMIZATION_COMMENTS_ENABLED
    digest_after_factory_marker: true
    max_tokens: 2000
  diff:
    enabled: true                            # NEW — env: TOKEN_OPTIMIZATION_DIFF_ENABLED
    max_review_tokens: 6000
```

Follow the existing `scheduler.sh` `_set_cfg` env-override pattern (lines ~82–95) for the
four new env vars.

### Per-feature bypass code changes

Each feature requires a bypass branch; complexity varies:

**Architecture** (`architecture_slice.py`): Lowest-cost change — the existing full-doc fallback
already serves this. Add a config-read at the top of `slice_architecture()` and force the
`_full_doc_result(... fallback_reason="feature_disabled")` path when
`architecture.enabled: false`. No new output format needed.

**Diff** (`diff_rank.py`): `diff_rank.py` already reads config (L87-108). Add an `enabled`
check in `load_config()` return value and branch at the top of `build_ranked_diff()` to return
the raw (or `fmt_hunk_filter`-only) diff without truncation when disabled.

**Memory** (`memory_retrieve.py`): Does not read config YAML today. Add a minimal config read
for `token_optimization.memory.enabled`; when `false`, bypass the top-k and token-cap logic in
`format_index_output()` and return all entries.

**Comments** (`comment_digest.py`): Does not read config YAML; the disable is a DAG-level
change. In `.archon/workflows/archon-dark-factory.yaml` (line ~134 where `comment_digest.py`
is invoked), gate the invocation on `TOKEN_OPTIMIZATION_COMMENTS_ENABLED` (already available
in the container env from `_set_cfg`). When disabled, the raw `comments` field from `issue.json`
is passed directly (existing pre-digest path).

### Baseline tokens in context-budget.json (schema v2)

Each section entry in `context_budget.py` that performs optimization must add a `baseline_tokens`
field alongside `tokens`:

- `architecture_md` — `baseline_tokens` = token estimate of the full ARCHITECTURE.md (always
  available as the fallback text, already computed inside `_full_doc_result`).
- `memory_context` — `baseline_tokens` = token estimate of all entries (before top-k cap);
  best-effort from `memory-trace.json`'s `entries_total` count × average entry size, or omitted
  if unavailable.
- `comment_digest` — `baseline_tokens` = token estimate of raw comments passed in (available
  before digesting).
- `diff` — `baseline_tokens` = token estimate of the full un-ranked diff.

Top-level additions to the JSON artifact:
```json
{
  "schema_version": 2,
  "baseline_input_tokens": 47200,
  "estimated_input_tokens": 31400,
  "savings_tokens": 15800,
  "savings_pct": 33.5,
  ...
}
```

Schema version bump is required; downstream consumers should tolerate missing `baseline_*`
fields from v1 artifacts.

### Cost report savings row (entrypoint.sh)

In `post_cost_report()`, after assembling the per-run `context-budget.json` aggregate:

1. Sum `baseline_input_tokens` and `estimated_input_tokens` across all phase artifacts.
2. Render a line beneath the subtotal row:
   ```
   Context savings: 15.8K tokens (33% vs. baseline)
   ```
3. Collect sections where `fallback: true` (or equivalent skip events) and render:
   ```
   Fallbacks: architecture_md → full doc (safety_keyword:performance)
   ```
   If no fallbacks: render `Fallbacks: none` (or omit the line — keep the common case quiet).
4. Both additions are wrapped in `|| true` fallback guards; missing or unreadable
   `context-budget.json` artifacts produce no extra output (current behavior preserved).

### Operator docs

New file `docs/agents/dark-factory-token-optimization.md`. Sections:

- **What's active** — list of optimizations, which issue shipped each, current phase (2/3)
- **Reading the cost report** — annotated example of the savings row and fallbacks line
- **Feature flag reference** — config.yaml knobs and env overrides for each feature
- **Per-feature rollback** — how to set `enabled: false` for one feature without affecting others
- **Full rollback** — `TOKEN_OPTIMIZATION_ENABLED=false` in `.archon/.env` (all features bypass)
- **Path to phase 4 (enforce)** — flip `enforce_budgets: true` once savings are confirmed stable; what enforcement means (runs that exceed budget are flagged in the cost report, not truncated)

## Alternatives considered

### Alternative 1 — `mode: full` as the disable mechanism

Use `mode: full` instead of `enabled: false` to signal "use full context." Rejected: three of
the four scripts (`memory_retrieve.py`, `comment_digest.py`, `architecture_slice.py`) do not
read the `mode` field today, so this would require the same new code paths with less
intuitive semantics. `enabled: false` matches the `epic_autopilot.enabled`,
`conflict_resolution.enabled`, etc. pattern already in the codebase.

### Alternative 2 — separate aggregated savings report doc

Generate a periodic summary document comparing runs with and without optimizations. Rejected
for size: S scope — the existing per-run cost report comment already serves as a report. A
batch aggregation tool is a separate issue.

### Alternative 3 — deferred per-feature flags (docs + schema only)

Ship operator docs and the config schema change without wiring the `enabled` checks into the
scripts. Rejected: the acceptance criterion explicitly requires independent disable capability,
and without code changes the flags would be inert documentation.

## Open questions (non-blocking)

- **Memory baseline accuracy:** The `memory-trace.json` file (when present) records
  `entries_selected_total` and `entries_dropped_by_cap_total`. The count of dropped entries
  is known but per-entry sizes are not stored — the baseline token estimate will be
  approximate. This is acceptable for a savings summary row; exact numbers would require
  changing `memory_retrieve.py` to emit full-corpus size before capping.

- **Phase 4 timing:** `enforce_budgets: true` is an operational decision. The spec does not
  set a date or evidence threshold; the operator doc should describe the observation criteria
  (N consecutive runs with savings% stable, no quality regressions flagged) but leave the
  decision to the operator.

## Assumptions

- **[Assumption]** The `_set_cfg` pattern in `scheduler.sh` (lines ~82–95) can directly
  accommodate four new `TOKEN_OPTIMIZATION_<FEATURE>_ENABLED` vars without needing a separate
  dispatch path. Verify before touching `scheduler.sh`.

- **[Assumption]** `TOKEN_OPTIMIZATION_COMMENTS_ENABLED` is available as an env var in the
  Archon workflow YAML execution context via the standard `.archon/.env` → container env chain.
  If not, the comments disable must instead be implemented inside `comment_digest.py` itself
  with a CLI `--skip` flag.

- **[Assumption]** Schema v2 consumers (the cost-report reader in `entrypoint.sh`) will
  always check `schema_version` before reading `baseline_input_tokens`. V1 artifacts produced
  before this change are common; the reader must degrade gracefully.

## Files changed (expected)

| File | Change |
|------|--------|
| `.claude/skills/refinement/config.yaml` | Add `enabled: true` under each feature sub-section |
| `dark-factory/scripts/context_budget.py` | Add `baseline_tokens` per section; bump `schema_version` to 2; add `savings_tokens`/`savings_pct` top-level |
| `dark-factory/scripts/architecture_slice.py` | Read `architecture.enabled`; force `_full_doc_result` when false |
| `dark-factory/scripts/diff_rank.py` | Read `diff.enabled`; bypass truncation when false |
| `dark-factory/scripts/memory_retrieve.py` | Add config YAML read for `memory.enabled`; bypass top-k cap when false |
| `.archon/workflows/archon-dark-factory.yaml` | Gate `comment_digest.py` invocation on `TOKEN_OPTIMIZATION_COMMENTS_ENABLED` |
| `dark-factory/entrypoint.sh` | Extend `post_cost_report()` to render savings row and fallbacks line |
| `dark-factory/scheduler.sh` | Add `_set_cfg` entries for four new env vars |
| `docs/agents/dark-factory-token-optimization.md` | New operator runbook |
