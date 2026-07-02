# Dark Factory Token Optimization — Phase 4: Budget Enforcement

**Status:** design
**Date:** 2026-07-02
**Epic:** (this document is the epic-level design; see child tickets)
**Predecessor:** #663 (token optimization — observe → optimize; enforcement deferred)
**Builds on:** context_budget.py telemetry (#664), per-feature slimming (#665–#670), the rollout guardrails + `token_optimization` config (#673), the eval regression-guard (#672)

---

## Problem

Epic #663 shipped the full token-optimization machinery — architecture slicing, top-k memory, comment digesting, diff ranking — plus per-feature kill-switches, `baseline_tokens`/savings telemetry, and an offline eval regression-guard. Enforcement was **deliberately deferred**: the config keys `enforce_budgets: false` and `default_budget_tokens: 24000` exist but are **inert** — nothing reads them. `context_budget.py` measures `estimated_input_tokens` and `utilization_pct` against the **200,000-token model window**, not against any per-scenario budget, and takes no action when a scenario assembles bloated context.

Phase 4 turns those inert flags into a working **per-scenario budget enforcer**, following the epic's stated `observe → compare → optimize → enforce` progression.

## Goals & non-goals

**Goals**
- Enforce a per-scenario token budget by tightening the *already-optimizable* context sections to fit.
- **Never drop safety-critical content and never hard-block a run** — enforcement is fail-open.
- Emit an `over_budget` signal (telemetry + cost report) when the un-trimmable core cannot fit.
- Roll out staged: ship OFF, calibrate from real data, flip scenarios one at a time.

**Non-goals**
- No new context-injection path: enforcement reuses the shipped optimizers, it does not replace how agents load context.
- No hard rejection / run-blocking on over-budget.
- Not addressing the Max-5h *session-window* exhaustion problem (that is per-window, cumulative-across-runs; a separate concern from per-run context size).

## Core decisions (settled in brainstorming)

1. **Enforce action = trim-then-flag.** Tighten the four optimizable sections to fit; if the un-trimmable core (CLAUDE.md + any safety full-doc fallback + issue-context floor) still exceeds budget, proceed and record `over_budget`. Never drop safety content; never block.
2. **Rollout = staged observe-then-enforce.** Ship all code with `enforce_budgets: false` + `over_budget`/`would_trim` telemetry first; calibrate per-scenario budgets from `baseline_tokens` data + the extended #672 eval; then flip `enforce` per scenario (refine/plan/code-review first).
3. **Mechanism = pre-phase derivation + cap overrides.** A single deterministic pre-phase pass derives tighter per-feature `max_tokens` and hands them to the existing optimizers via env overrides.
4. **Starting budget = 30,000 tokens** (per-scenario default; `CLAUDE.md` alone is ~18k, so 24k was too tight). Individual scenarios refine off this during calibration.

## Architecture

### The enforcement step — `budget_enforce.py`

A new pure-stdlib script `dark-factory/scripts/budget_enforce.py`, invoked by a new pre-phase `bash:` node `enforce-budget-<phase>` inserted **immediately before** each scenario's `command:` node — mirroring the existing `budget-<phase>` telemetry nodes (`|| true` non-fatal, `${CLONE_DIR:-.}` path, `when:`-gated on intent, `depends_on` on the command node). It reuses `token_estimate.py` and the same section-probing logic as `context_budget.py`; it imports `architecture_slice` to know whether `architecture_md` is in safety full-doc fallback for this issue.

**Single deterministic pass:**
1. `reserved` = estimated tokens of the un-trimmable sections for this scenario: `CLAUDE.md` (always full); `architecture_md` **iff** it resolves to safety full-doc fallback for this issue; a configured floor for `issue_context`.
2. `allowance = max(0, budget − reserved)`.
3. Distribute `allowance` across the four optimizable sections active in this scenario (architecture slice, memory, diff, comments) **proportional to their default caps**, each clamped to `[floor, default]` → **derived `max_tokens`** per section.
4. Export the derived caps as per-feature env overrides the optimizers read:
   `TOKEN_OPTIMIZATION_ARCHITECTURE_MAX_TOKENS`, `TOKEN_OPTIMIZATION_MEMORY_MAX_TOKENS`, `TOKEN_OPTIMIZATION_DIFF_MAX_REVIEW_TOKENS`, `TOKEN_OPTIMIZATION_COMMENTS_MAX_TOKENS`.
5. If `reserved ≥ budget`: set derived caps to their floors and mark `over_budget = true`.

**Two modes** (gated by `enforce_budgets` AND the per-scenario `enforce` toggle):
- **Observe** (default): compute everything, record `would_trim`/`derived_caps`/`over_budget` in telemetry, but **do not export** caps — nothing changes. This is the calibration data source.
- **Enforce**: also export the derived caps so the optimizers honor them.

Env-override export mechanism: the pre-phase node writes the derived caps to a sourced env file (`$ARTIFACTS_DIR/token-opt-caps.env`) that the command phase sources, consistent with how `$ARTIFACTS_DIR`-scoped state already flows between DAG nodes.

### Optimizer changes (cap-override reads)

Each of the four optimizers gains a `max_tokens` env-override read, mirroring the `enabled` env-override pattern #673 established:
- `architecture_slice.py` — honor `TOKEN_OPTIMIZATION_ARCHITECTURE_MAX_TOKENS` for the slice budget.
- `memory_retrieve.py` — honor `TOKEN_OPTIMIZATION_MEMORY_MAX_TOKENS` for the top-k token cap.
- `diff_rank.py` — honor `TOKEN_OPTIMIZATION_DIFF_MAX_REVIEW_TOKENS` for `max_review_tokens`.
- `comment_digest.py` — honor `TOKEN_OPTIMIZATION_COMMENTS_MAX_TOKENS`.

When the override is unset, they use the config value (current behavior).

## Safety model

Enforcement is **structurally incapable of dropping safety content**: it only lowers the `max_tokens` the four optimizers *aim for*, and each optimizer's existing safety carve-outs are **cap-immune** —
- `architecture_slice`: safety-sensitive issues → full-doc fallback, which ignores the slice cap (and is counted in `reserved`, not trimmed).
- `diff_rank`: the critical tier (auth/trading/migrations/`dark-factory/`/hotspots) is always emitted in full, bypassing `max_review_tokens`.
- `memory_retrieve`: fails open to the full uncapped markdown on any error.
- `CLAUDE.md`: never sliced; always in `reserved`.

`over_budget` is informational only (never blocks). The whole node is fail-open (`|| true`); on any error, no caps are exported and the optimizers use their config defaults — i.e., current behavior.

## Rollout & calibration

- **4a — build, ship OFF:** all code lands with `enforce_budgets: false`; observe-mode telemetry (`over_budget`, `would_trim`, `derived_caps`) accrues on every run.
- **4b — calibrate:** extend the #672 eval to compute, per historical bench issue × scenario, what enforcement *would* do at candidate budgets — specifically whether it would force a required ARCHITECTURE.md section below its floor and whether `over_budget` fires. Set per-scenario budgets from that + real-run telemetry.
- **4c — staged flip:** enable `enforce_budgets` + per-scenario `enforce` for **refine / plan / code-review first** (lower blast radius), observe, then **implement / conformance**. Each flip is documented in the operator runbook (`docs/agents/dark-factory-token-optimization.md`, from #673).

## Config shape

Under `token_optimization` in `.claude/skills/refinement/config.yaml`:

```yaml
token_optimization:
  enforce_budgets: false            # global master switch (existing)
  default_budget_tokens: 30000      # per-scenario default (raised from 24000)
  budgets:                          # NEW — per-scenario overrides of the default
    refine: 30000
    plan: 30000
    implement: 30000
    conformance: 30000
    code-review: 30000
  enforce:                          # NEW — per-scenario enforcement toggle (staged flip)
    refine: false
    plan: false
    implement: false
    conformance: false
    code-review: false
  # ... existing per-feature enabled/max_tokens blocks unchanged ...
```

All env-overridable per the #673 convention. Budgets/toggles are baked config (image rebuild to change defaults; env overrides are hot-changeable).

## Testing

- **`budget_enforce.py` unit tests:** derivation math (reserved / allowance / proportional distribution / floor+default clamps); `over_budget` when `reserved ≥ budget`; observe-mode exports nothing vs enforce-mode exports caps; fail-open on malformed inputs.
- **Optimizer override tests:** each of the four honors its `max_tokens` env override; safety carve-outs remain cap-immune under a tightened cap.
- **#672 eval extension:** at a candidate budget, enforcement drops no component-required ARCHITECTURE.md section (reuses the section-presence verdict).
- **DAG:** the new `enforce-budget-*` nodes are non-fatal + `when`-gated; the `check_workflow_dag.py` OR-join validator (from #668) covers them.

## Decomposition (6 tickets)

| # | Ticket | Scope |
|---|--------|-------|
| T1 | `budget_enforce.py` + derivation | Core script: reserved/allowance/distribution/floors, `over_budget`, observe-vs-enforce modes, unit tests. Foundation. |
| T2 | Optimizer cap-override reads | Add `max_tokens` env-override to architecture_slice / memory_retrieve / diff_rank / comment_digest + tests (incl. safety carve-outs stay cap-immune). |
| T3 | DAG wiring + config | Insert `enforce-budget-<phase>` pre-phase nodes; add `budgets` + `enforce` per-scenario config; env-file cap export/source. |
| T4 | `over_budget` telemetry + cost report | `context_budget.py` gains `over_budget`/`would_trim`/`derived_caps`; cost-report line for over-budget + what was trimmed. |
| T5 | #672 eval extension (calibration/safety) | Simulate enforcement at candidate budgets over bench issues; assert no required-section loss; emit a budget-calibration scorecard. |
| T6 | Runbook + staged flip | Update the operator runbook; set calibrated budgets; flip enforcement on refine/plan/code-review; document the observe-then-flip procedure for implement/conformance. |

Foundation-first order: **T1 → T2 → T3/T4 (parallel) → T5 → T6.**

## Open items / operational notes

- Budgets are estimates (chars ÷ 4), so `over_budget` and derived caps are approximate — acceptable, since the flag is informational and enforcement is fail-open.
- Like #673, the `enforce-budget-*` node reads baked `config.yaml`; env overrides are hot-changeable, default changes need an image rebuild.
- T6's staged flip of implement/conformance is intentionally left as an operational decision gated on 4b calibration data, not forced in this epic.
