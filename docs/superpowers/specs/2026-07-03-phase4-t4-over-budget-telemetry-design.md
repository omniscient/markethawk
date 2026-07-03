# Phase 4 T4: over_budget Telemetry + Cost-Report Line

**Status:** design
**Date:** 2026-07-03
**Epic:** #713 (Phase 4 budget enforcement)
**Issue:** #717
**Depends on:** T1 (`budget_enforce.py`), T2 (optimizer cap-override reads), T3 (DAG `enforce-budget-*` nodes)
**Design ref:** `docs/superpowers/specs/2026-07-02-token-opt-phase4-enforcement-design.md`

---

## Problem

T1–T3 shipped the derivation engine (`budget_enforce.py`), cap-override reads in all four
optimizers, and the DAG `enforce-budget-*` pre-phase nodes. The enforcement signals —
`over_budget`, `would_trim`, `derived_caps` — are computed but discarded at node exit.
Nothing surfaces them in `context-budget.json` (the per-run artifact) or in the GitHub
cost report. Operators have no visibility into whether a run was over-budget, and the
#672 eval cannot use enforcement telemetry to calibrate per-scenario budgets.

T4 closes this gap: write the three fields (plus their supporting values) back to
`context-budget.json` and add an over-budget line to `post_cost_report()`.

---

## Requirements

1. After T4 merges, every `context-budget.json` produced by a run that went through an
   `enforce-budget-*` DAG node gains six new fields:
   `over_budget`, `would_trim`, `derived_caps`, `scenario_budget`, `reserved_tokens`, `allowance`.
2. The fields are **additive** — existing fields are never removed or renamed.
   `schema_version` stays at 2 (new keys do not break existing readers; consumers
   feature-detect by key presence, not by version number).
3. The write-back happens in **both** observe and enforce modes. T4 is a telemetry
   feature; the calibration data source (observe mode) needs these fields as much as
   enforce mode does.
4. The write-back is **fail-open**: if re-reading or re-writing `context-budget.json`
   fails, the error is swallowed and the node proceeds normally. The load-bearing
   path (writing `token-opt-caps.env` in enforce mode) must not be affected.
5. The write-back must write to the **file** only — not to stdout. In enforce mode
   `budget_enforce.py` stdout is redirected to `token-opt-caps.env`; any JSON written
   to stdout would corrupt the env file.
6. `post_cost_report()` in `entrypoint.sh` reads the new fields and emits exactly one
   of three states (in the `SAVINGS_BLOCK` above the per-node table):
   - **Over-budget** (`over_budget=true`): 
     `**⚠️ Over budget (<scenario>): <reserved_tokens>k reserved / <scenario_budget>k budget — trimmed: <section>→<cap>, ...**`
   - **Trim only** (`over_budget=false`, `would_trim=true`):
     `**Budget trim (<scenario>): est <estimated_input_tokens>k / <scenario_budget>k budget — capped: <section>→<cap>, ...**`
   - **Healthy** (both false): no budget line emitted.
   All token values formatted with `fmt_tokens`. Guard with `|| true` on the whole
   block, matching the existing savings/fallbacks pattern from #673.
7. No changes to `context_budget.py`, no changes to the DAG YAML.
   `budget_enforce.py` is the only script modified.

---

## Architecture

### `budget_enforce.py` — write-back step in `run_cli()`

After `derive_caps()` returns a `BudgetResult`, and **before** the enforce-mode
branch that prints env KEY=VALUE lines to stdout, add a write-back block:

```python
# Augment context-budget.json with enforcement telemetry (both modes).
try:
    with open(args.context_budget_json, encoding="utf-8") as f:
        cb = json.load(f)
    cb["over_budget"]     = result.over_budget
    cb["would_trim"]      = result.would_trim
    cb["derived_caps"]    = result.derived_caps
    cb["scenario_budget"] = args.budget_tokens
    cb["reserved_tokens"] = result.reserved_tokens
    cb["allowance"]       = result.allowance
    with open(args.context_budget_json, "w", encoding="utf-8") as f:
        json.dump(cb, f, indent=2)
    print(
        f"budget_enforce: augmented context-budget.json "
        f"(over_budget={result.over_budget}, would_trim={result.would_trim})",
        file=sys.stderr,
    )
except Exception as exc:
    print(f"budget_enforce: warning — could not augment context-budget.json: {exc}", file=sys.stderr)
```

The enforce-mode env-line block is unchanged and remains after this step.

`run_cli()` returns `result` (already the case in T1); `main()` calls `run_cli()` unchanged.

### `entrypoint.sh` — `post_cost_report()` budget line

After the existing `FALLBACKS_LINE` block (inside the `if [[ "$SCHEMA_VER" -ge 2 ]]`
guard), add:

```bash
local OVER_BUDGET WOULD_TRIM SCENARIO_BUDGET RESERVED_TOKENS ESTIMATED
local DERIVED_CAPS_STR="" BUDGET_LINE=""
OVER_BUDGET=$(jq -r '.over_budget // false' "$BUDGET_FILE" 2>/dev/null || echo "false")
WOULD_TRIM=$(jq -r '.would_trim // false' "$BUDGET_FILE" 2>/dev/null || echo "false")
SCENARIO_BUDGET=$(jq -r '.scenario_budget // 0' "$BUDGET_FILE" 2>/dev/null || echo "0")
RESERVED_TOKENS=$(jq -r '.reserved_tokens // 0' "$BUDGET_FILE" 2>/dev/null || echo "0")
ESTIMATED=$(jq -r '.estimated_input_tokens // 0' "$BUDGET_FILE" 2>/dev/null || echo "0")
SCENARIO=$(jq -r '.scenario // ""' "$BUDGET_FILE" 2>/dev/null || echo "")

# Format derived_caps as "arch→1.5k, memory→750" (skip if missing or empty)
if [ "${SCENARIO_BUDGET:-0}" -gt 0 ] 2>/dev/null; then
  DERIVED_CAPS_STR=$(jq -r '
    (.derived_caps // {}) | to_entries |
    map("\(.key)→\(.value)") | join(", ")
  ' "$BUDGET_FILE" 2>/dev/null || true)
fi

if [ "$OVER_BUDGET" = "true" ] && [ "${SCENARIO_BUDGET:-0}" -gt 0 ] 2>/dev/null; then
  local CAPS_SUFFIX=""
  [ -n "$DERIVED_CAPS_STR" ] && CAPS_SUFFIX=" — trimmed: ${DERIVED_CAPS_STR}"
  BUDGET_LINE="**⚠️ Over budget (${SCENARIO}): $(fmt_tokens "$RESERVED_TOKENS") reserved / $(fmt_tokens "$SCENARIO_BUDGET") budget${CAPS_SUFFIX}**"
elif [ "$WOULD_TRIM" = "true" ] && [ "${SCENARIO_BUDGET:-0}" -gt 0 ] 2>/dev/null; then
  local CAPS_SUFFIX=""
  [ -n "$DERIVED_CAPS_STR" ] && CAPS_SUFFIX=" — capped: ${DERIVED_CAPS_STR}"
  BUDGET_LINE="**Budget trim (${SCENARIO}): est $(fmt_tokens "$ESTIMATED") / $(fmt_tokens "$SCENARIO_BUDGET") budget${CAPS_SUFFIX}**"
fi
```

Then include `$BUDGET_LINE` in `SAVINGS_BLOCK`:

```bash
if [ -n "$SAVINGS_LINE" ] || [ -n "$FALLBACKS_LINE" ] || [ -n "$BUDGET_LINE" ]; then
  SAVINGS_BLOCK="
${SAVINGS_LINE}${SAVINGS_LINE:+
}${FALLBACKS_LINE}${FALLBACKS_LINE:+
}${BUDGET_LINE}"
fi
```

### Testing

Add to `dark-factory/tests/test_budget_enforce.py`:

- **write-back observe mode**: call `run_cli()` with `--mode observe`; assert
  `context-budget.json` now contains `over_budget`, `would_trim`, `derived_caps`,
  `scenario_budget`, `reserved_tokens`, `allowance`; assert stdout is empty (no
  env lines emitted in observe mode).
- **write-back enforce mode**: call with `--mode enforce`; assert same six fields
  in JSON; assert stdout contains at least one `KEY=VALUE` line.
- **fail-open on missing JSON**: call with `--context-budget-json` pointing to a
  non-existent path; assert `run_cli()` exits with `sys.exit(1)` (existing behavior —
  the file-not-found error at read time is raised before the write-back).
- **existing fields preserved**: after write-back, assert `schema_version`,
  `scenario`, `savings_tokens` are unchanged.

---

## Alternatives Considered

**Option B — `context_budget.py` imports `budget_enforce` directly:** Would require
adding `--budget-tokens` and `--config` args to `context_budget.py` and updating the
five `budget-*` DAG nodes. Rejected: fights the T1/T3 architecture, requires more
DAG edits, and conflates measurement (context_budget) with enforcement (budget_enforce).
Option A confines all T4 changes to `budget_enforce.py` and `entrypoint.sh`.

**`schema_version` bump to 3:** Rejected. New keys do not change existing field
semantics; the #672 eval reads `schema_version`, `estimated_input_tokens`,
`savings_tokens` — all unchanged. Forward-compatible additive fields require no
version bump. Consumers that need the new fields detect them by key presence.

---

## Assumptions

- [A1] T1, T2, and T3 are already merged. `budget_enforce.py` exists, the four
  optimizers honor cap-override env vars, and the five `enforce-budget-*` DAG nodes
  invoke `budget_enforce.py` and redirect stdout to `token-opt-caps.env`.
- [A2] The `--context-budget-json` path passed to `budget_enforce.py` by the DAG
  nodes is always writable (same `$ARTIFACTS_DIR`-scoped path that `context_budget.py`
  wrote to).
- [A3] The `fmt_tokens` helper in `post_cost_report()` is already available as a
  local shell function (defined earlier in the function body at line ~314 of
  `entrypoint.sh`).

---

## Open Questions (non-blocking)

- Should `derived_caps` token values also be formatted with `fmt_tokens` in the
  cost-report suffix? (The `jq` string-join gives raw integers; `fmt_tokens` requires
  bash arithmetic.) Keeping raw integers in the suffix is readable at the S/M scale of
  most cap values (750–6000 tokens); this can be polished later without a spec change.
