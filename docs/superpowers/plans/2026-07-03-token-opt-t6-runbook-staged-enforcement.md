# Phase 4 T6: Runbook Update + Staged Enforcement Flip — Implementation Plan

**Issue:** #719  
**Epic:** #713 (Phase 4 budget enforcement)  
**Spec:** `docs/superpowers/specs/2026-07-03-token-opt-t6-runbook-staged-enforcement-design.md`  
**Date:** 2026-07-03  
**Size:** S (< 1 hour)

---

## Goal

Flip budget enforcement live for conformance and code-review (the two scenarios T5 calibration confirmed at 0% `section_at_risk`), and update the operator runbook with the enforcement lifecycle, corrected two-tier rollback procedure, deploy nuance callout, and follow-up path for the deferred scenarios (refine/plan/implement).

No code changes. Config + doc only.

---

## Architecture

- **`.claude/skills/refinement/config.yaml`** — flip `enforce_budgets: true`, set `budgets.conformance: 22000`, `budgets.code-review: 22000`, `enforce.conformance: true`, `enforce.code-review: true`.
- **`docs/agents/dark-factory-token-optimization.md`** — add Budget Enforcement section, Observe→Enforce Procedure section, two-tier Rollback extension, Deploy Nuance callout, Follow-up Path section, update Path to Phase 4 section, update config snippet to reflect live values, note provisional-22k.

These are the only two files touched. The enforce-budget DAG nodes read both values directly from the cloned `config.yaml` on every factory run, so the commit to main takes effect on the next run with no image rebuild or scheduler restart.

---

## File Structure

| File | Change |
|------|--------|
| `.claude/skills/refinement/config.yaml` | Flip 3 flags, update 2 budget values |
| `docs/agents/dark-factory-token-optimization.md` | Add 3 new sections, extend 2 existing sections, update config snippet |

---

## Task 1 — Flip enforcement config in `config.yaml`

**Files:** `.claude/skills/refinement/config.yaml`

### Step 1.1 — Verify current state (baseline)

```bash
grep -A 20 "^token_optimization:" .claude/skills/refinement/config.yaml | grep -E "enforce_budgets|conformance|code-review"
```

Expected output (pre-change):
```
  enforce_budgets: false      # false = measure-only ...
    conformance: 30000
    code-review: 30000
    conformance: false
    code-review: false
```

### Step 1.2 — Apply config edits

Edit `.claude/skills/refinement/config.yaml`, `token_optimization` block:

```yaml
# Line ~107 — flip master gate
  enforce_budgets: true       # true = hard enforcement for flagged scenarios; no env override — see runbook rollback procedure

# Lines ~113–114 — set provisional budgets from T5 smoke-run
  budgets:
    refine: 30000
    plan: 30000
    implement: 30000
    conformance: 22000        # T5 safe-budget rec (provisional, 2-issue smoke run — update after full-corpus calibration)
    code-review: 22000        # T5 safe-budget rec (provisional, 2-issue smoke run — update after full-corpus calibration)

# Lines ~118–120 — flip enforcement for calibrated-safe scenarios
  enforce:
    refine: false             # deferred — section_at_risk 50% (architecture.max_tokens < real arch slice size)
    plan: false               # deferred — section_at_risk 50% (architecture.max_tokens < real arch slice size)
    implement: false          # deferred — operational follow-up per Phase 4 design
    conformance: true         # live — T5 calibration: 0% section_at_risk, 0% over_budget at 22k
    code-review: true         # live — T5 calibration: 0% section_at_risk, 0% over_budget at 22k
```

### Step 1.3 — Verify changes

```bash
grep -A 20 "^token_optimization:" .claude/skills/refinement/config.yaml | grep -E "enforce_budgets|conformance|code-review"
```

Expected output (post-change):
```
  enforce_budgets: true
    conformance: 22000
    code-review: 22000
    conformance: true
    code-review: true
```

### Step 1.4 — Commit

```bash
git add .claude/skills/refinement/config.yaml
git commit -m "feat(#719): T6 — flip enforce_budgets + conformance/code-review enforcement live"
```

---

## Task 2 — Update operator runbook

**Files:** `docs/agents/dark-factory-token-optimization.md`

This task makes five distinct changes to the runbook in a single edit pass, committed together.

### Step 2.1 — Verify sections that need adding are absent

```bash
grep -c "## Budget Enforcement\|## Observe → Enforce\|## Follow-up Path\|Tier 1\|Deploy Nuance" \
  docs/agents/dark-factory-token-optimization.md
```

Expected output: `0` (none of these headings or phrases exist yet).

### Step 2.2 — Change A: Update the Configuration section config snippet

Replace the existing config block in the **Configuration** section (lines ~30–42) with one that reflects the live enforcement state and includes the `budgets`/`enforce` subsections:

```markdown
## Configuration

All flags live in `.claude/skills/refinement/config.yaml` under `token_optimization`:

```yaml
token_optimization:
  enabled: true
  enforce_budgets: true    # enforcement live for conformance + code-review (T6)
  default_budget_tokens: 30000
  budgets:
    refine: 30000          # observe-only
    plan: 30000            # observe-only
    implement: 30000       # observe-only
    conformance: 22000     # enforced — provisional from T5 smoke run
    code-review: 22000     # enforced — provisional from T5 smoke run
  enforce:
    refine: false          # deferred — see Follow-up Path
    plan: false            # deferred — see Follow-up Path
    implement: false       # deferred — operational follow-up
    conformance: true      # enforcement live
    code-review: true      # enforcement live
  architecture:
    enabled: true          # disable → full ARCHITECTURE.md loaded
  memory:
    enabled: true          # disable → all matching memory entries emitted
  comments:
    enabled: true          # disable → raw comment history used
  diff:
    enabled: true          # disable → full diff passed to code-review
```

Environment variables override individual feature flags (e.g. `TOKEN_OPTIMIZATION_ARCHITECTURE_ENABLED`).
**No env override exists for `enforce_budgets` or per-scenario `enforce`/`budgets`** — see Rollback below.
```

### Step 2.3 — Change B: Add **Budget Enforcement** section (after Configuration)

Insert immediately after the Configuration section, before Disable / Rollback Procedure:

```markdown
---

## Budget Enforcement

Phase 4 hard budget enforcement is **live** for `conformance` and `code-review`. All other scenarios (`refine`, `plan`, `implement`) remain in **observe-only** mode.

| Scenario | Status | Budget | Why |
|----------|--------|--------|-----|
| `conformance` | **Enforced** | 22 000 tokens | T5 calibration: 0% `section_at_risk`, 0% `over_budget` |
| `code-review` | **Enforced** | 22 000 tokens | T5 calibration: 0% `section_at_risk`, 0% `over_budget` |
| `refine` | Observe-only | 30 000 tokens | `section_at_risk` 50% — blocked on `architecture.max_tokens` recalibration |
| `plan` | Observe-only | 30 000 tokens | Same as `refine` |
| `implement` | Observe-only | 30 000 tokens | Operational follow-up per Phase 4 design |

> **Provisional budgets:** The 22 000 token cap for conformance/code-review is derived from a 2-issue smoke run (T5). Run the full bench-corpus calibration (`token_opt_eval.py --calibrate`) to confirm or revise these values before treating them as stable.

### Telemetry signals

The `context-budget.json` artifact (`$ARTIFACTS_DIR/context-budget.json`) contains three enforcement signals per run:

| Field | Meaning |
|-------|---------|
| `over_budget` | Total token usage exceeded the scenario budget after enforcement |
| `would_trim` | Enforcement reduced at least one section below its natural size |
| `section_at_risk` | A section's cap is below its real uncapped size (enforcement would trim it on every run) |

`section_at_risk` is the key health signal for un-enforced scenarios. A non-zero rate on a deferred scenario tells you enforcement is not yet safe to flip.
```

### Step 2.4 — Change C: Add **Observe → Enforce Procedure** section (after Budget Enforcement)

Insert immediately after the Budget Enforcement section:

```markdown
---

## Observe → Enforce Procedure

To promote a scenario from observe-only to enforced:

1. **Run full-corpus calibration** (not just a smoke run):
   ```bash
   # Inside the factory container
   python dark-factory/evals/token_opt_eval.py --calibrate
   ```
   Results land in `token-opt-eval-<date>.json` under `calibration_results`.

2. **Check the gate thresholds** for the target scenario:
   - `section_at_risk_rate == 0%` — enforcement will not trim any section on any issue.
   - `over_budget_rate ≤ 10%` at the target budget — the budget headroom is adequate.

3. **Set the budget and flip the enforce flag** in `.claude/skills/refinement/config.yaml`:
   ```yaml
   token_optimization:
     budgets:
       <scenario>: <calibrated-safe-budget>
     enforce:
       <scenario>: true
   ```

4. **Commit to main.** The DAG nodes read `config.yaml` from a fresh clone on every factory run — the change takes effect on the **next run**, no image rebuild or scheduler restart required.

5. **Confirm on the next enforced run:** check `context-budget.json` for `would_trim`, `over_budget`, and `section_at_risk`. If `over_budget` fires, lower the budget or investigate; if `section_at_risk` fires, re-examine the per-feature cap (see Follow-up Path below).
```

### Step 2.5 — Change D: Extend **Disable / Rollback Procedure** with two-tier enforcement rollback + Deploy Nuance

Replace the existing Disable / Rollback Procedure section with the expanded version:

```markdown
---

## Disable / Rollback Procedure

### Rolling back a feature flag (architecture, memory, comments, diff)

To disable a single optimization feature:

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

### Rolling back budget enforcement (Tier 1 / Tier 2)

Enforcement gates (`enforce_budgets`, per-scenario `enforce`) are **clone-read from `config.yaml`** — the factory does a fresh `git clone` on every run and reads them via inline Python from the cloned file. **No env override exists** for these flags. The `TOKEN_OPTIMIZATION_ENFORCE_BUDGETS` comment in the config header is a stale claim from issue #673 that Phase 4 never wired up; relying on `.archon/.env` for enforcement rollback would strand an operator mid-incident.

Both rollback tiers are git commits to `config.yaml` on main. They take effect on the **next factory run** with no scheduler restart or image rebuild.

**Tier 1 — master kill (fastest, affects all scenarios):**
```bash
# Option A: flip the gate directly
# In .claude/skills/refinement/config.yaml:
#   enforce_budgets: false
git add .claude/skills/refinement/config.yaml
git commit -m "fix: emergency rollback — disable enforcement master gate"
git push origin main
```
Or:
```bash
# Option B: revert the T6 config commit
git revert <T6-config-commit-sha>
git push origin main
```

**Tier 2 — targeted (one scenario):**
```bash
# In .claude/skills/refinement/config.yaml:
#   enforce:
#     conformance: false   # (or code-review: false)
git add .claude/skills/refinement/config.yaml
git commit -m "fix: disable enforcement for conformance scenario"
git push origin main
```

> **Open question (follow-up ticket candidate):** Per-scenario env overrides (`TOKEN_OPTIMIZATION_ENFORCE_CONFORMANCE`, `TOKEN_OPTIMIZATION_ENFORCE_CODE_REVIEW`, etc.) would enable hot single-scenario rollback without a file edit. Not yet wired. File a follow-up ticket if hot per-scenario rollback becomes an operational need.

### Deploy nuance: clone-read vs baked

| Component | Lifecycle | Takes effect |
|-----------|-----------|-------------|
| `config.yaml` | Clone-read (fresh `git clone` per run) | Next factory run — commit to main, no rebuild |
| Workflow YAML / command files | Clone-read | Next factory run — commit to main, no rebuild |
| `entrypoint.sh` (T4 cost-report savings line) | Baked into Docker image | Requires image rebuild + redeploy |

If a new config change seems ignored, confirm it is in `config.yaml` (clone-read) not `entrypoint.sh` (baked). If the T4 cost-report savings line is missing from a run, check whether the image was rebuilt after T4 landed.
```

### Step 2.6 — Change E: Update **Path to Phase 4** section + add **Follow-up Path** section

Replace the Path to Phase 4 section and append the Follow-up Path section after it:

```markdown
---

## Path to Phase 4: `enforce_budgets: true`

Phase 4 hard budget enforcement is **live** as of T6 (issue #719). Enforcement is active for `conformance` and `code-review`; `refine`, `plan`, and `implement` remain in observe-only mode pending calibration data. See **Follow-up Path** below for the unlock criteria.

---

## Follow-up Path (deferred scenarios)

### refine / plan — blocked on `section_at_risk`

T5 calibration shows 50% `section_at_risk` at ALL budgets for refine/plan. Root cause: `architecture.max_tokens: 3000` is lower than real arch slice sizes (3–4k+), so the enforce-budget cap would trim architecture context on every affected issue — directly contradicting the "Never drop safety-critical content" goal.

To unlock:

1. Measure the actual arch slice sizes across recent runs — look at `sections.architecture_md.tokens` in per-run `context-budget.json` artifacts:
   ```bash
   # Sample the last 20 runs; adjust $ARTIFACTS_DIR to the factory's artifact root
   python3 -c "
   import glob, json
   sizes = []
   for f in sorted(glob.glob('$ARTIFACTS_DIR/*/context-budget.json'))[-20:]:
       d = json.load(open(f))
       t = d.get('sections', {}).get('architecture_md', {}).get('tokens', 0)
       if t: sizes.append(t)
   sizes.sort()
   p90 = sizes[int(len(sizes)*0.9)] if sizes else 'no data'
   print(f'p90 arch slice size: {p90} tokens (across {len(sizes)} runs)')
   "
   ```
2. Raise `architecture.max_tokens` in config.yaml above the p90 value as a **separate, data-driven change** (do not bundle with the enforcement flip).
3. Re-run calibration to confirm `section_at_risk_rate == 0%` for refine/plan:
   ```bash
   python dark-factory/evals/token_opt_eval.py --calibrate
   ```
4. Follow the Observe → Enforce Procedure above to flip `enforce.refine` and `enforce.plan`.

### implement — operational follow-up

Per the original Phase 4 design, `implement` enforcement is gated on sustained observation of conformance/code-review enforcement in production. After ≥ 10 enforced conformance/code-review runs without incidents, run full-corpus calibration for implement and follow the Observe → Enforce Procedure.
```

### Step 2.7 — Verify all new sections exist

```bash
grep -c "## Budget Enforcement\|## Observe → Enforce\|## Follow-up Path\|Tier 1 — master kill\|Deploy nuance\|clone-read" \
  docs/agents/dark-factory-token-optimization.md
```

Expected output: at least `6` matches.

```bash
grep "enforce_budgets:" docs/agents/dark-factory-token-optimization.md
```

Expected: lines showing `enforce_budgets: true` in the config snippet (old `false` value replaced).

### Step 2.8 — Commit

```bash
git add docs/agents/dark-factory-token-optimization.md
git commit -m "docs(#719): T6 runbook — Budget Enforcement, Observe→Enforce, two-tier Rollback, Deploy Nuance, Follow-up Path"
```

---

## Final Verification

```bash
# Confirm config values
python3 -c "
import yaml
cfg = yaml.safe_load(open('.claude/skills/refinement/config.yaml'))
to = cfg['token_optimization']
print('enforce_budgets:', to['enforce_budgets'])
print('budgets.conformance:', to['budgets']['conformance'])
print('budgets.code-review:', to['budgets']['code-review'])
print('enforce.conformance:', to['enforce']['conformance'])
print('enforce.code-review:', to['enforce']['code-review'])
"
```

Expected:
```
enforce_budgets: True
budgets.conformance: 22000
budgets.code-review: 22000
enforce.conformance: True
enforce.code-review: True
```

```bash
# Confirm runbook has all required sections
for section in "## Budget Enforcement" "## Observe → Enforce Procedure" "Tier 1 — master kill" "Tier 2 — targeted" "Deploy nuance: clone-read" "## Follow-up Path" "section_at_risk"; do
  count=$(grep -c "$section" docs/agents/dark-factory-token-optimization.md 2>/dev/null || echo 0)
  echo "$section: $count"
done
```

Expected: each line shows ≥ 1.
