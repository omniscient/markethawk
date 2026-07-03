# Dark Factory — Token Optimization Operator Guide

## Overview

The Dark Factory uses four context-optimization features to reduce input token usage
per run. As of issue #673, all four features are **active by default** and can be
independently disabled via config flags or environment variable overrides.

Rollout phases 1–3 (observe, low-risk optimization, implementation/conformance) landed
via issues #664–#671. Phase 4 (budget enforcement) shipped via #713–#719.
**As of T3b (#733), enforcement is live for conformance, code-review, refine, and plan.**

---

## Active Features

| Feature | Config key | Env override | Effect when enabled |
|---------|-----------|--------------|---------------------|
| Architecture slicing | `token_optimization.architecture.enabled` | `TOKEN_OPTIMIZATION_ARCHITECTURE_ENABLED` | Emits only component-relevant ARCHITECTURE.md sections instead of the full doc |
| Memory top-k | `token_optimization.memory.enabled` | `TOKEN_OPTIMIZATION_MEMORY_ENABLED` | Caps memory retrieval to the top 8 highest-scored entries (≤ 1 500 tokens) |
| Comment digesting | `token_optimization.comments.enabled` | `TOKEN_OPTIMIZATION_COMMENTS_ENABLED` | Collapses raw comment history into a single human-feedback digest for `continue` runs |
| Diff ranking | `token_optimization.diff.enabled` | `TOKEN_OPTIMIZATION_DIFF_ENABLED` | Ranks and truncates the review diff by risk tier; critical files bypass the cap |
| Budget enforcement | `token_optimization.enforce_budgets` + `enforce.<scenario>` | `TOKEN_OPTIMIZATION_ENFORCE_BUDGETS` | Kill-only: `false`/`0`/`no` (case-insensitive) forces observe in all 5 nodes; unset or any other value defers to config |

---

## Configuration

All flags live in `.claude/skills/refinement/config.yaml` under `token_optimization`:

```yaml
token_optimization:
  enabled: true
  enforce_budgets: true    # T6 live — master enforcement gate
  budgets:                 # per-scenario token budgets (provisional from T5 smoke run)
    refine: 30000          # enforced — T3b go-live (#733)
    plan: 30000            # enforced — T3b go-live (#733)
    implement: 30000       # observe-only — enforce: false
    conformance: 22000     # enforced — T6 go-live
    code-review: 22000     # enforced — T6 go-live
  enforce:
    refine: true           # T3b live — #731 scorecard: 0% section_at_risk
    plan: true             # T3b live — #731 scorecard: 0% section_at_risk
    implement: false       # deferred; see Follow-up Path below
    conformance: true      # T6 live
    code-review: true      # T6 live
  architecture:
    enabled: true          # disable → full ARCHITECTURE.md loaded
  memory:
    enabled: true          # disable → all matching memory entries emitted
  comments:
    enabled: true          # disable → raw comment history used
  diff:
    enabled: true          # disable → full diff passed to code-review
```

> **Deploy nuance:** `config.yaml`, workflow files, and command files are **clone-read** —
> every factory run clones the repo fresh, so a commit to `main` takes effect on the
> **next factory run** with no restart or image rebuild required.
> In contrast, `entrypoint.sh` (T4 cost-report line) is **baked into the Docker image**
> and requires an image rebuild to change.

Environment variables for the per-feature `enabled` flags override config values.
Set them in `.archon/.env` before the scheduler container starts; `_set_cfg` wires
them at startup. `TOKEN_OPTIMIZATION_ENFORCE_BUDGETS` is a kill-only override for
the budget enforcement gates (see Rollback — Tier 0 below).

---

## Disable / Rollback Procedure

### Per-feature bypass (architecture, memory, comments, diff)

These features have env overrides wired via `_set_cfg` — hot-changeable without a
config edit:

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

**Fail-safe semantics:** Every disabled path widens context to the full/original baseline.
Disabling a feature never silently drops content.

### Budget enforcement rollback (Tier 0, Tier 1, Tier 2)

Three tiers are available. Tier 0 is instant (no git commit); Tier 1 and Tier 2 are git
commits to `config.yaml` on `main` and take effect on the **next factory run** (no
scheduler restart or image rebuild needed).

**Tier 0 — env kill (fastest, no git commit required):**

Sets `TOKEN_OPTIMIZATION_ENFORCE_BUDGETS=false` in `.archon/.env` so all five
`enforce-budget-*` nodes immediately switch to observe mode on the next factory run.
The env var can only force observe — it cannot force enforcement on.

```bash
# 1. Set the kill switch in the Archon env file
echo "TOKEN_OPTIMIZATION_ENFORCE_BUDGETS=false" >> .archon/.env

# 2. Force-recreate the scheduler so the new env var is injected
docker compose --profile scheduler up -d --force-recreate backlog-scheduler
```

> **Note:** In-flight factory containers are unaffected — the kill-switch only takes effect
> on the **next** factory run. `docker compose restart` does NOT re-read `env_file`, so
> `up -d --force-recreate` is required.

To restore enforcement: remove the line from `.archon/.env` and run `up -d --force-recreate` again.

**Tier 1 — master kill (reverts all enforcement immediately via config):**
```bash
# Option A: direct commit
# In config.yaml, set:   enforce_budgets: false
git commit -am "revert(enforce): disable budget enforcement master gate"
git push origin main

# Option B: git revert the T6 config commit (SHA from git log)
git revert <t6-config-commit-sha>
git push origin main
```

**Tier 2 — targeted (disable a single scenario):**
```bash
# In config.yaml, set:   enforce.<scenario>: false
# e.g. for code-review:
#   enforce:
#     code-review: false
git commit -am "revert(enforce): disable code-review budget enforcement"
git push origin main
```

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

## Budget Enforcement (Phase 4 — Live)

As of T3b (#733), budget enforcement is **active** for `conformance`, `code-review`, `refine`, and `plan`.

| Scenario | Enforce | Budget | Status |
|----------|---------|--------|--------|
| refine | **true** | **30 000** | **enforced (T3b)** |
| plan | **true** | **30 000** | **enforced (T3b)** |
| implement | false | 30 000 | observe-only |
| conformance | **true** | **22 000** | **enforced (T6)** |
| code-review | **true** | **22 000** | **enforced (T6)** |

Budgets for refine and plan were validated by the full-corpus calibration in #731 (Phase 4b T2)
with 0% `section_at_risk_rate` at the 30k budget. Budgets for conformance and code-review were
derived from the T5 smoke run — run `dark-factory/evals/token_opt_eval.py --calibrate` after
accumulating ≥ 10 bench issues to confirm or adjust.

### How enforcement works

A pre-phase `enforce-budget-<scenario>` DAG node runs `budget_enforce.py` before each
scenario's command node. It:

1. Estimates un-trimmable reserved tokens (CLAUDE.md + safety full-doc fallback if active
   + `issue_context` floor).
2. Distributes the remaining allowance across the four optimizable sections proportional
   to their default caps, clamped to each section's floor.
3. In **enforce mode**: exports derived caps as env vars that the optimizers read
   (`TOKEN_OPTIMIZATION_ARCHITECTURE_MAX_TOKENS`, `TOKEN_OPTIMIZATION_MEMORY_MAX_TOKENS`,
   `TOKEN_OPTIMIZATION_DIFF_MAX_REVIEW_TOKENS`, `TOKEN_OPTIMIZATION_COMMENTS_MAX_TOKENS`),
   via `$ARTIFACTS_DIR/token-opt-caps.env`.
4. If the un-trimmable core exceeds the budget, records `over_budget: true` in telemetry
   and proceeds — enforcement **never blocks a run**.

The whole node is fail-open (`|| true`): on any error, no caps are exported and optimizers
use their config defaults.

### Telemetry signals

In `context-budget.json` (`$ARTIFACTS_DIR`):
- `over_budget` — `true` if the un-trimmable reserved context exceeds the scenario budget
- `would_trim` — `true` in observe mode when enforce mode would have tightened caps
- `derived_caps` — computed cap values (enforced or hypothetical)

The cost-report comment surfaces `over_budget` when it fires.

---

## Observe → Enforce Procedure

Use this procedure when promoting a scenario from observe-only to enforced.

**Prerequisites:**
- `over_budget_rate ≤ 10%` across ≥ 10 bench issues at the candidate budget
- `section_at_risk_rate == 0%` (enforcement would not trim any required-by-calibration
  ARCHITECTURE.md section)

Run the calibration eval to check:
```bash
# Inside the factory container
python3 dark-factory/evals/token_opt_eval.py --calibrate \
  --budget <candidate_tokens> --scenario <scenario_name>
```

Per-run `context-budget.json` artifacts hold `sections.architecture_md.tokens` —
collect these to compute the p90 architecture slice size and verify it fits within the
planned `architecture.max_tokens` cap before flipping.

**Flip procedure (when gates pass):**
1. In `config.yaml`, set `budgets.<scenario>: <calibrated_value>` and `enforce.<scenario>: true`.
2. Commit to `main` and push — takes effect on the next factory run.
3. Monitor the next 5 runs for `over_budget` or unexpected `section_at_risk` signals.
4. If issues arise, use the Tier 1 or Tier 2 rollback (see Rollback section).

---

## Path to Phase 4 — Current Status

Phase 4 (budget enforcement) is **mostly live** as of T3b (#733):
- **Conformance and code-review**: enforcement active since T6 (#719).
- **Refine and plan**: enforcement active since T3b (#733) — #731 scorecard gated go-live.
- **Implement**: observe-only — deferred pending calibration.

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

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---------|-------------|-----|
| Cost report shows no savings line | `context-budget.json` absent or schema v1 | Upgrade to schema v2 by running a new factory run; check for `context_budget.py` errors in logs |
| Architecture slice always falls back | Safety keyword in labels or changed files | Expected behavior; check `fallback_reason` in `context-budget.json` |
| Memory returns all entries (ignores top-k) | `TOKEN_OPTIMIZATION_MEMORY_ENABLED=false` | Check `.archon/.env` and restart scheduler |
| Comment digest skipped | `TOKEN_OPTIMIZATION_COMMENTS_ENABLED=false` | Set to `true` in `.archon/.env` and restart |
| Full diff passed to code-review | `TOKEN_OPTIMIZATION_DIFF_ENABLED=false` | Set to `true` in `.archon/.env` and restart |
| `over_budget` fires on conformance / code-review | Reserved context (CLAUDE.md + safety fallback) exceeds 22k budget | Raise `budgets.<scenario>` in config.yaml or use Tier 2 rollback to disable enforcement for that scenario |
| Enforcement seems to have no effect | Per-scenario `enforce` flag is `false`, or `enforce_budgets: false` | Verify config.yaml matches intended state; changes take effect on next factory run (clone-read) |
