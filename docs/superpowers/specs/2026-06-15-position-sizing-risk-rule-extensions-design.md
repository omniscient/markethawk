# Position Sizing and Risk Rule Extension Points — Design

**Date:** 2026-06-15
**Issue:** #444 (parent: #438)
**Status:** Pending review

## Overview

The current auto-trade decision path has position sizing math hardcoded inside
`AutoTradeExecutor._calculate_position()` and risk guards inlined inside
`maybe_execute()`. This spec introduces two registry-backed extension points:

1. **Sizing model registry** — callable implementations of the fixed-percent
   sizing logic, resolvable by key. The existing math becomes `"fixed_pct"`,
   the built-in default.
2. **Risk rule registry** — ordered callable rules that evaluate a proposed order
   before it is persisted or submitted, returning `allow / block / warn`.

The feature is purely additive. All existing `TradingStrategy` fields continue to
drive default sizing; all existing guard checks remain in place. No existing order
flow or broker integration changes.

---

## Requirements

Distilled from acceptance criteria and Q&A:

1. **Sizing model registry.** A global `_SIZING_REGISTRY` keyed by string. The
   existing `_calculate_position()` logic is wrapped as the `"fixed_pct"` built-in
   and registered at module load.

2. **Per-strategy model selection.** `TradingStrategy` gains a nullable
   `sizing_model_key` column (VARCHAR 100, NULL default). `NULL` resolves to
   `"fixed_pct"`. One Alembic migration; no existing row data needs updating.

3. **Risk rule registry.** A global `_RISK_RULE_REGISTRY` ordered dict keyed by
   rule name. All registered rules run before order persistence, in insertion order.

4. **Rich rule context.** Each rule receives:
   `(order_proposal: PositionCalc, strategy: TradingStrategy, event: ScannerEvent, db: Session) → RuleDecision`

5. **Decision outcomes.**
   - `allow` — proceed unchanged.
   - `block` — do not persist the order; set `status="rejected"`,
     `rejection_reason=f"risk_rule[{rule_name}]: {reason}"`, return `None`.
   - `warn` — persist with `status="pending_approval"` (overrides
     `strategy.requires_approval=False`), record reason in `rejection_reason`.

6. **Block is terminal.** On the first `block` outcome, stop evaluating remaining
   rules and exit with the blocked decision. This mirrors the guard check pattern
   already in `maybe_execute()`.

7. **Backward compatibility.** All existing strategies with `sizing_model_key=NULL`
   produce byte-for-byte identical behavior to the pre-feature code path.

8. **Tests required:**
   - Default sizing compatibility (NULL key → `"fixed_pct"` → same output as old `_calculate_position()`).
   - Custom sizing model (non-null key → custom callable used).
   - Custom blocking risk rule (registered blocker → `status="rejected"`, reason recorded).

---

## Architecture

### New module: `app/services/trading_extensions.py`

Mirrors the scanner and screener registry pattern
(`scan_orchestrator._REGISTRY` / `discovery_service._SCREENER_REGISTRY`).

```
backend/app/services/trading_extensions.py   ← new; registries + protocols + built-in defaults
backend/app/services/auto_trade_service.py   ← modified; calls resolver + evaluate_risk_rules
backend/app/models/trading_strategy.py       ← modified; add sizing_model_key column
alembic/versions/<hash>_trading_strategy_sizing_model_key.py  ← new migration
backend/tests/services/test_trading_extensions.py             ← new tests
```

#### Protocols and types

```python
# trading_extensions.py

from typing import Protocol, Literal
from dataclasses import dataclass

class SizingModelFn(Protocol):
    def __call__(
        self,
        strategy: "TradingStrategy",
        trigger_price: float,
        side: str,
        account_equity: float,
    ) -> "PositionCalc": ...

class RiskRuleFn(Protocol):
    def __call__(
        self,
        order_proposal: "PositionCalc",
        strategy: "TradingStrategy",
        event: "ScannerEvent",
        db: "Session",
    ) -> "RuleDecision": ...

@dataclass(frozen=True)
class RuleDecision:
    outcome: Literal["allow", "block", "warn"]
    reason: str
    rule_name: str
```

#### Registries and public API

```python
_SIZING_REGISTRY: dict[str, SizingModelFn] = {}
_RISK_RULE_REGISTRY: dict[str, RiskRuleFn] = {}   # insertion order = execution order

def register_sizing_model(key: str, fn: SizingModelFn) -> None: ...
def register_risk_rule(key: str, fn: RiskRuleFn) -> None: ...
def resolve_sizing_model(key: str) -> SizingModelFn: ...  # KeyError if not found
def evaluate_risk_rules(
    order_proposal: PositionCalc,
    strategy: TradingStrategy,
    event: ScannerEvent,
    db: Session,
) -> RuleDecision | None:
    """
    Run all registered rules in insertion order.
    Returns the first block/warn decision, or None (all allow).
    Stops at the first block — does not evaluate remaining rules.
    """
    warn_decision: RuleDecision | None = None
    for rule_fn in _RISK_RULE_REGISTRY.values():
        decision = rule_fn(order_proposal, strategy, event, db)
        if decision.outcome == "block":
            return decision
        if decision.outcome == "warn" and warn_decision is None:
            warn_decision = decision  # capture first warn, keep evaluating
    return warn_decision  # None if all allow, RuleDecision(warn) otherwise
```

The built-in `"fixed_pct"` model is registered at the bottom of
`trading_extensions.py` and wraps the existing `_calculate_position()` logic
extracted verbatim from `auto_trade_service.py`. No built-in risk rules are
registered initially — the registry starts empty.

#### Changes to `auto_trade_service.py`

Step 10 in `maybe_execute()` changes from a direct `_calculate_position()` call to:

```python
# Step 10. Position sizing (registry-backed)
from app.services.trading_extensions import resolve_sizing_model, evaluate_risk_rules

sizing_key = strategy.sizing_model_key or "fixed_pct"
try:
    sizing_fn = resolve_sizing_model(sizing_key)
except KeyError:
    logger.error("Unknown sizing model key %r — falling back to fixed_pct", sizing_key)
    sizing_fn = resolve_sizing_model("fixed_pct")
calc = sizing_fn(strategy, trigger_price, side, account_equity)
if calc.quantity <= 0:
    ...  # unchanged early-exit
```

Risk rule evaluation is inserted between step 10 (calc) and step 11 (order creation):

```python
# Step 10b. Risk rule evaluation
rule_decision = evaluate_risk_rules(calc, strategy, event, db)
if rule_decision is not None:
    prefix = f"risk_rule[{rule_decision.rule_name}]: {rule_decision.reason}"
else:
    prefix = None

if rule_decision is not None and rule_decision.outcome == "block":
    # Persist with status="rejected" for audit trail and idempotency.
    initial_status = "rejected"
    rejection_reason_for_order = prefix
elif rule_decision is not None and rule_decision.outcome == "warn":
    # Force human review regardless of strategy.requires_approval.
    initial_status = "pending_approval"
    rejection_reason_for_order = prefix
else:
    initial_status = "pending_approval" if strategy.requires_approval else "pending"
    rejection_reason_for_order = None
```

The `AutoTradeOrder` constructor receives `status=initial_status` and
`rejection_reason=rejection_reason_for_order`. For `block` outcomes the
order is persisted but broker submission is skipped and the function returns
the order immediately after commit.

Persisting a `rejected` order creates an audit trail and engages the
existing idempotency guard: a subsequent alert for the same
`(symbol, strategy, event_date)` will find the `rejected` row and skip
re-evaluation, preventing a day's worth of retries against a persistently
failing rule. If a rule is expected to be transient (e.g., "overexposed at
this hour"), implementors should prefer `warn` so a human can release the
order via the approval endpoint.

#### Migration

```
ALTER TABLE trading_strategies ADD COLUMN sizing_model_key VARCHAR(100) NULL;
```

Generated by `alembic revision --autogenerate`. NULL existing rows resolve to
`"fixed_pct"` in code — no data migration needed.

### Self-registration convention

Built-in defaults register at the bottom of `trading_extensions.py` (guaranteed
present when the module loads). Custom sizing models and risk rules self-register
at the bottom of their own modules and are triggered by explicit imports — same
pattern as `app/tasks/scanning.py` importing scanner modules with `# noqa: F401`
to fire `scan_orchestrator.register()` calls. Any custom extension module must be
imported somewhere in the task/startup path to activate.

---

## Alternatives Considered

### Alt A: Inline registries in `auto_trade_service.py`
`auto_trade_service.py` is already 740 lines and mixes orchestration with multiple
service functions. Adding registries, protocol types, and resolver helpers would
push it past 900 lines and make test isolation harder. Rejected in favour of a
dedicated module that mirrors the scanner and screener patterns.

### Alt B: SystemConfig-based global sizing model
Using `SystemConfig.key="SIZING_MODEL"` picks a model globally for all strategies.
This cannot vary per strategy and contradicts "resolved by key" in the acceptance
criteria. Rejected.

### Alt C: Deferred key resolution (registry only, always use default)
Ship the registry infrastructure but always resolve to `"fixed_pct"` in v1 (no
`sizing_model_key` column, no migration). Satisfies the letter of "resolved by
key" but makes the registry a no-op until a follow-up issue. Product owner
confirmed this is the wrong interpretation — per-strategy selection is the intent.
Rejected.

---

## Open Questions (non-blocking)

1. **Per-strategy risk rule filtering.** Currently all registered rules run for every
   strategy. If future rules need to be strategy-scoped (e.g., apply only to
   `paper_mode=True` strategies), rules should use `strategy` field inspection inside
   the callable. No protocol change needed — this is already possible with the
   rich signature.

2. **Warn reason field.** `rejection_reason` (Text) is reused for both blocked and
   warned orders, with a `risk_rule[name]:` prefix for disambiguation. If multiple
   warnings accumulate, only the first is recorded. A future `warnings JSONB` column
   could collect all; deferred.

3. **UI exposure.** `AutoTradeOrder.rejection_reason` is already returned in the
   `/api/v1/trading/orders` list response (field visible in `OrdersPanel`). No
   frontend change needed to surface risk-rule messages in the existing orders table.

---

## Assumptions

- The `feature:extensions` label signals this is v1 of a longer extension arc;
  the registry needs to work but does not need dynamic reloading, versioning, or
  hot-registration without restart.
- `AutoTradeOrder` is not persisted for `block` outcomes (consistent with existing
  guard returns). If the product later needs an audit trail of blocked attempts,
  that is a separate issue.
- `app/tasks/trading.py` imports `auto_trade_service`, which will import
  `trading_extensions` transitively — no additional import forcing needed for
  the built-in `"fixed_pct"` model to be registered at task startup.
- Python's `dict` insertion order (guaranteed since 3.7) provides the deterministic
  rule execution order required by the acceptance criteria.
