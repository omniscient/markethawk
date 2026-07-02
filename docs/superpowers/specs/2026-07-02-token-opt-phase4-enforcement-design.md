# Token Optimization Phase 4 T1: budget_enforce.py — per-scenario budget derivation

**Status:** design
**Date:** 2026-07-02
**Epic:** #713 (Dark Factory token optimization Phase 4 — budget enforcement)
**Issue:** #714
**Build constraint:** Dark Factory scripts only — no app code changes.

## Problem

Epic #663 built the token-optimization machinery (architecture slicing, memory top-k, diff ranking, comment digesting), but the `enforce_budgets` config key and `default_budget_tokens` value are deliberately inert — nothing reads them. Phase 4 activates them. T1 lays the foundation: a new `budget_enforce.py` that, given a scenario's budget and measured section token counts, computes how to distribute the remaining "allowance" across the trimmable sections. No DAG wiring yet (T2/T3) — pure derivation and unit tests only.

## Requirements

From the issue and epic #713:

- New pure-stdlib module `dark-factory/scripts/budget_enforce.py`
- Accepts a scenario, its budget (default 30k tokens), and section token estimates (from context-budget.json)
- Computes the **reserved** (un-trimmable) set: CLAUDE.md always; `architecture_md` when it is in full-doc safety fallback; `issue_context` at a configurable floor
- Computes `allowance = max(0, budget - reserved_total)`
- Distributes allowance across the **optimizable** sections proportionally to their default caps, clamped to `[floor, default]`
- Sets `over_budget=True` when `reserved_total >= budget`
- Two modes: **observe** (compute, emit nothing) vs **enforce** (also print derived caps as sourceable `KEY=VALUE` lines to stdout)
- Pure derivation only — no DAG/optimizer wiring (T2/T3), no telemetry in context-budget.json (T4), no env-file write (T3)
- Unit tests only — no integration tests against live factory runs
- Reuses `token_estimate.py`; reads fallback status from the `sections.architecture_md.fallback` field already computed by `context_budget.py`

### Section floors and defaults (all config-driven)

| Section | Env var exported | Default cap | Floor |
|---------|-----------------|-------------|-------|
| arch (when not in fallback) | `TOKEN_OPTIMIZATION_ARCHITECTURE_MAX_TOKENS` | 3000 | 1500 |
| memory | `TOKEN_OPTIMIZATION_MEMORY_MAX_TOKENS` | 1500 | 750 |
| comments | `TOKEN_OPTIMIZATION_COMMENTS_MAX_TOKENS` | 2000 | 1000 |
| diff | `TOKEN_OPTIMIZATION_DIFF_MAX_REVIEW_TOKENS` | 6000 | 3000 |

Floors are 50% of defaults, giving each optimizer a meaningful minimum even under a tight budget. With the 30k budget and CLAUDE.md (~18k reserved), allowance ≈ 10k — between the floor sum (6250) and default sum (12500) — so the proportional-clamp distribution is exercised rather than pinning to one extreme.

`issue_context` floor: **2000 tokens** (config-driven). A fixed floor rather than a percentage — this is the irreducible problem statement; it must survive regardless of budget tightness. 2000 tokens (~8000 chars) covers a typical issue body + epic context block.

## Architecture / approach

### Module shape

```python
# dark-factory/scripts/budget_enforce.py
from __future__ import annotations

# Pure dataclass — no external deps beyond stdlib
@dataclass
class BudgetResult:
    scenario: str
    budget_tokens: int
    reserved_tokens: int
    allowance_tokens: int
    over_budget: bool
    # sections that went into reserved (name -> tokens)
    reserved_breakdown: dict[str, int]
    # sections that got derived caps (name -> derived_cap)
    # absent when section is reserved / not applicable for scenario
    derived_caps: dict[str, int]
    # which sections are optimizable for this result
    optimizable_sections: list[str]
```

### Core pure function

```python
def derive_caps(
    sections: dict,          # context-budget.json "sections" field
    budget: int,             # per-scenario budget in tokens
    arch_fallback: bool,     # True = architecture_md is full-doc (reserved)
    config: dict,            # parsed token_optimization block from config.yaml
) -> BudgetResult:
    ...
```

`sections` is the dict from `context-budget.json` — each key is a section name, value has `tokens` and optionally `fallback`. The function does no I/O.

### Reserved set computation

1. **CLAUDE.md**: always reserved. Tokens = `sections.get("claude_md", {}).get("tokens", 0)`
2. **architecture_md**: reserved iff `arch_fallback is True`. When reserved, contributes its full token count; when not reserved, enters the optimizable pool.
3. **issue_context floor**: always reserved at `max(sections.get("issue_context", {}).get("tokens", 0), ISSUE_CONTEXT_FLOOR)` where `ISSUE_CONTEXT_FLOOR` comes from config (`token_optimization.issue_context.reserve_tokens`, default 2000).

`reserved_total = sum of the above`

### Optimizable set and proportional distribution

Optimizable sections (when the scenario includes them):
- `architecture_md` (only when `arch_fallback is False`)
- `memory_context`
- `diff`
- `comments`

Sections absent from the context-budget.json sections dict (e.g. `diff` is absent in `refine` scenario) are skipped — only distribute among sections actually present.

```python
total_default = sum(DEFAULT_CAPS[s] for s in optimizable)
for s in optimizable:
    raw = allowance * (DEFAULT_CAPS[s] / total_default) if total_default > 0 else FLOORS[s]
    derived_caps[s] = clamp(int(raw), FLOORS[s], DEFAULT_CAPS[s])
```

No guarantee that `sum(derived_caps) == allowance` after clamping — that is acceptable. The clamping prevents any section from getting a nonsensical allocation (near-zero or above its default).

When `over_budget is True` (reserved_total >= budget): `allowance = 0`, all optimizable sections get their floor value. Enforcement proceeds — this is informational, never blocking.

### CLI interface

```
python3 budget_enforce.py \
  --context-budget-json /path/to/context-budget.json \
  --budget-tokens 30000 \
  --mode observe|enforce \
  [--config /path/to/config.yaml]
```

`--context-budget-json` must exist and contain the `sections` dict and `scenario`. The `arch_fallback` flag is read from `sections.architecture_md.fallback` (already computed by `context_budget.py`).

### Output: enforce mode (stdout)

Prints sourceable `KEY=VALUE` lines for each section in the optimizable set:

```
TOKEN_OPTIMIZATION_ARCHITECTURE_MAX_TOKENS=2200
TOKEN_OPTIMIZATION_MEMORY_MAX_TOKENS=900
TOKEN_OPTIMIZATION_COMMENTS_MAX_TOKENS=1000
TOKEN_OPTIMIZATION_DIFF_MAX_REVIEW_TOKENS=3000
```

Only sections present in the optimizable set for that scenario/fallback combination are emitted. Human-readable status (what it *would* trim, `over_budget`, etc.) goes to **stderr** — keeping stdout a clean machine-consumable payload for T3's `source` call.

### Output: observe mode (stdout)

No stdout output. Computation runs internally; unit tests call `derive_caps()` directly to assert on the `BudgetResult`.

### Config schema additions

Add to `config.yaml` under `token_optimization`:

```yaml
token_optimization:
  issue_context:
    reserve_tokens: 2000      # minimum tokens reserved for issue body
  architecture:
    max_tokens: 3000
    min_tokens: 1500          # floor when distributing allowance
  memory:
    max_tokens: 1500
    min_tokens: 750
  comments:
    max_tokens: 2000
    min_tokens: 1000
  diff:
    max_review_tokens: 6000
    min_review_tokens: 3000   # matches naming: max/min_review_tokens for diff
```

`budget_enforce.py` reads these at startup; falls back to the table above if keys are absent (fail-open, no crash).

### Unit tests (`dark-factory/tests/test_budget_enforce.py`)

Follow the pure-pytest pattern of existing tests (`test_context_budget.py`, `test_diff_rank.py` — no mocking framework, just plain Python):

- Reserved breakdown: CLAUDE.md always present; arch reserved when `arch_fallback=True`, excluded from optimizable when reserved
- `allowance = max(0, budget - reserved)` — zero when over-budget
- `over_budget=True` when `reserved >= budget`
- Proportional distribution: verify each section's derived cap is in `[floor, default]`
- Arch not in fallback → included in optimizable, gets a derived cap
- Arch in fallback → excluded from optimizable, no cap emitted
- Sections absent from context-budget.json → skipped in distribution
- Floor enforcement: when allowance is very small, all optimizable sections get their floor
- Observe mode: `derive_caps()` returns a `BudgetResult` without side effects
- Enforce mode (CLI captured via capsys): correct `KEY=VALUE` lines on stdout, nothing else
- Config-driven floors: override defaults via config dict; missing keys fall back to hardcoded defaults
- `over_budget` + enforce: all sections get floor values; env lines are still emitted

## Alternatives considered

### A. Integrate budget derivation into context_budget.py

`context_budget.py` already reads all section token counts and could compute derived caps directly. Rejected: violates single-responsibility; `context_budget.py` is a telemetry probe, not an enforcement node. T4 adds `over_budget`/`would_trim`/`derived_caps` telemetry fields to context_budget.json — that field addition is the T4-scope touch to context_budget.py, not enforcement logic.

### B. Emit a `budget-enforce.json` sidecar

Write a JSON file alongside context-budget.json for downstream consumption. Rejected: the derivation telemetry (`over_budget`, `would_trim`, `derived_caps`) belongs in context_budget.json — a second competing artifact is redundant. The env-file (`token-opt-caps.env`) written by T3 is the actual consumption artifact; the JSON can be recovered from context_budget.json in T4. Keeping T1 artifact-free makes it purely testable via its Python API.

### C. Accept section token counts as individual CLI flags

`--claude-md-tokens 4500 --arch-tokens 2800 --arch-fallback ...` instead of reading context-budget.json. Rejected: verbose for T3 shell scripting; reading from the existing artifact is cleaner. The pure-function API is what unit tests exercise; the CLI is a thin reader wrapper.

## Open questions (non-blocking)

- **Scenario-specific budget overrides**: The epic mentions per-scenario `budgets` config in T3. T1 uses a single `default_budget_tokens` value; per-scenario override lookup can be added in T3 when the full config structure is settled.
- **Arch cap when in fallback**: When `arch_fallback=True`, arch is reserved and no cap is exported. T2's architecture_slice env-override read will never be reached in that path (full doc is loaded unconditionally). Confirmed in `architecture_slice.py:153–163`: `_is_architecture_enabled()` returns False → full doc, bypassing any cap. Consistent.
- **Rounding**: `int(raw)` truncates. Rounding mode doesn't materially matter at token granularity; truncation is simpler and matches `token_estimate.py`'s existing `int(len(text) / 4.0)` truncation.

## Assumptions

- [A1] Context-budget.json is always written by `context_budget.py` before `budget_enforce.py` runs in T3's DAG. T1 requires the JSON as input; it does not run standalone before context-budget.json exists except in unit tests.
- [A2] Starting budget remains 30,000 tokens per scenario for T1 testing (the config still has 24,000 — the updated value is set in T6). T1 unit tests use explicit `--budget-tokens` values; the default in code can be 30,000.
- [A3] The four `TOKEN_OPTIMIZATION_*` env var names are the same ones `architecture_slice.py`, `memory_retrieve.py`, `diff_rank.py`, and `comment_digest.py` will read after T2 adds env-override support. T1 defines the names; T2 wires them.
- [A4] `over_budget` is purely informational in T1. No code path blocks or alerts; the `|| true` fail-open wrapper is a T3 DAG concern.
