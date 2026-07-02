# Dark Factory — Token Optimization Operator Guide

## Overview

The Dark Factory uses four context-optimization features to reduce input token usage
per run. As of issue #673, all four features are **active by default** and can be
independently disabled via config flags or environment variable overrides.

Rollout phases 1–3 (observe, low-risk optimization, implementation/conformance) landed
via issues #664–#671. This runbook covers phase 4 readiness (operator controls,
savings reporting, and the path to `enforce_budgets: true`).

---

## Active Features

| Feature | Config key | Env override | Effect when enabled |
|---------|-----------|--------------|---------------------|
| Architecture slicing | `token_optimization.architecture.enabled` | `TOKEN_OPTIMIZATION_ARCHITECTURE_ENABLED` | Emits only component-relevant ARCHITECTURE.md sections instead of the full doc |
| Memory top-k | `token_optimization.memory.enabled` | `TOKEN_OPTIMIZATION_MEMORY_ENABLED` | Caps memory retrieval to the top 8 highest-scored entries (≤ 1 500 tokens) |
| Comment digesting | `token_optimization.comments.enabled` | `TOKEN_OPTIMIZATION_COMMENTS_ENABLED` | Collapses raw comment history into a single human-feedback digest for `continue` runs |
| Diff ranking | `token_optimization.diff.enabled` | `TOKEN_OPTIMIZATION_DIFF_ENABLED` | Ranks and truncates the review diff by risk tier; critical files bypass the cap |

---

## Configuration

All flags live in `.claude/skills/refinement/config.yaml` under `token_optimization`:

```yaml
token_optimization:
  enabled: true
  enforce_budgets: false   # phase 4 gate — see below
  architecture:
    enabled: true          # disable → full ARCHITECTURE.md loaded
  memory:
    enabled: true          # disable → all matching memory entries emitted
  comments:
    enabled: true          # disable → raw comment history used
  diff:
    enabled: true          # disable → full diff passed to code-review
```

Environment variables override config values and take precedence. Set them in
`.archon/.env` before the scheduler container starts. The scheduler wires these via
`_set_cfg` at startup.

---

## Disable / Rollback Procedure

To disable a single feature **without restarting** the scheduler:

1. Edit `.archon/.env`:
   ```bash
   TOKEN_OPTIMIZATION_ARCHITECTURE_ENABLED=false
   ```
2. Restart the scheduler so `_set_cfg` picks up the new value:
   ```bash
   docker compose --profile scheduler restart backlog-scheduler
   ```
3. Next factory run will load full ARCHITECTURE.md (fail-safe: content is wider, never dropped).

To disable **all features** at once, set `token_optimization.enabled: false` in config.yaml.
Individual bypass flags are still respected even when the top-level flag is false — they
apply independently to each script.

**Fail-safe semantics:** Every disabled path widens context to the full/original baseline.
Disabling a feature never silently drops content.

---

## Reading the Cost Report

After each factory run, a cost report comment is posted on the issue. When `schema_version: 2`
artifacts are present, the comment includes a savings line:

```
**Context savings: 4.2K tokens (28.5%)**
**Fallbacks:** architecture_md: safety_keyword:migration
```

- **Context savings** = total tokens saved across all optimized sections vs. the unoptimized baseline.
- **Fallbacks** = sections where a safety trigger fired and the full baseline was loaded instead of the optimized version. These are expected and correct behavior (not errors).

If no savings line appears, the `context-budget.json` artifact was absent, or `schema_version` < 2
(older run artifact).

---

## Per-Section Savings Data

The `context-budget.json` artifact (in `$ARTIFACTS_DIR`) includes per-section savings:

```json
{
  "schema_version": 2,
  "savings_tokens": 4200,
  "savings_pct": 28.5,
  "fallback_events": [
    {"section": "architecture_md", "reason": "safety_keyword:migration"}
  ],
  "sections": {
    "architecture_md": {
      "tokens": 1200,
      "baseline_tokens": 5000,
      ...
    },
    "memory_context": {
      "tokens": 800,
      "baseline_tokens": 2400,
      ...
    }
  }
}
```

`baseline_tokens` per section is the unoptimized token count:
- `architecture_md`: full ARCHITECTURE.md token count
- `memory_context`: `uncapped_tokens` from `memory-trace.json` (all matching entries before top-k cap)
- `diff`: `raw_diff_tokens` from `diff-ranking.json` (full diff before ranking/truncation)

---

## Path to Phase 4: `enforce_budgets: true`

Phase 4 (hard budget enforcement) is currently **off** (`enforce_budgets: false`).
To enable:

1. Review `context-budget.json` savings data across ≥ 10 recent runs to confirm the
   savings are consistent and no unexpected fallbacks are occurring.
2. Set in config.yaml:
   ```yaml
   token_optimization:
     enforce_budgets: true
   ```
3. Monitor the next 5 runs for any `budget_exceeded` or `context_loss` signals in
   `context-budget.json`.
4. If a run fails with context-budget enforcement as the root cause, set
   `enforce_budgets: false` to roll back immediately (no restart needed if set via env:
   `TOKEN_OPTIMIZATION_ENFORCE_BUDGETS=false`).

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---------|-------------|-----|
| Cost report shows no savings line | `context-budget.json` absent or schema v1 | Upgrade to schema v2 by running a new factory run; check for `context_budget.py` errors in logs |
| Architecture slice always falls back | Safety keyword in labels or changed files | Expected behavior; check `fallback_reason` in `context-budget.json` |
| Memory returns all entries (ignores top-k) | `TOKEN_OPTIMIZATION_MEMORY_ENABLED=false` | Check `.archon/.env` and restart scheduler |
| Comment digest skipped | `TOKEN_OPTIMIZATION_COMMENTS_ENABLED=false` | Set to `true` in `.archon/.env` and restart |
| Full diff passed to code-review | `TOKEN_OPTIMIZATION_DIFF_ENABLED=false` | Set to `true` in `.archon/.env` and restart |
