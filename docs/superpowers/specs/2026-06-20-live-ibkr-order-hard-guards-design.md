# F-TRADE-01: Live IBKR Order Path — Hard Guards Design

**Date:** 2026-06-20
**Status:** Pending review
**Issue:** #368
**Security finding:** F-TRADE-01 — Defensive Security Review 2026-06-12

---

## Overview

MarketHawk can place real bracket orders at Interactive Brokers via `place_bracket_order` in `providers/ibkr_orders.py`. All current guards (kill-switch flag, paper mode, manual approval) are stored in the database and settable via the API. A single misconfiguration (`paper_mode=False` + `AUTO_TRADING_ENABLED=true` + `requires_approval=False`) routes scanner signals straight to live orders with no non-bypassable ceiling on quantity or notional.

This spec defines four layered controls that close the gap:

1. **Env-only arming flag** (`LIVE_TRADING_ARMED`) — cannot be set via the API
2. **Manual emergency kill switch** (`TRADING_KILL_SWITCH`) — env var an operator sets to halt all live order placement instantly
3. **Hard per-order caps** (`MAX_ORDER_NOTIONAL`, `MAX_ORDER_QTY`) — reject orders exceeding absolute limits regardless of strategy config
4. **Structured observability** — WARN-level Seq log, Prometheus counter, Grafana alert rule

All four guards are added at the single non-bypassable chokepoint: the top of `place_bracket_order`, before any call to `ib.placeOrder`.

---

## Problem Statement

**Attack / abuse scenario (from security review):**

All three existing controls live in the database:
- `SystemConfig["AUTO_TRADING_ENABLED"]` — API-settable via `PATCH /api/v1/trading/config`
- `TradingStrategy.paper_mode` — API-settable via `PATCH /api/trading/strategies/{id}`
- `TradingStrategy.requires_approval` — API-settable

An authenticated user (single shared credential in the current single-user design) can flip all three flags via the API, triggering unattended live orders from scanner signals with no absolute limit on size.

**What does NOT exist today:**
- No env-level arming flag (only the API-mutable `AUTO_TRADING_ENABLED`)
- No emergency kill switch (no env var to halt all live placements in seconds)
- No ceiling on per-order quantity or notional in the order layer itself
- No WARN-level audit log or Prometheus counter for live order placement events
- No `max_position_usd` enforcement at strategy creation for live strategies

---

## Requirements

### R1 — Non-bypassable chokepoint (env flags + caps in `place_bracket_order`)

At the top of `place_bracket_order`, before the IBKR connection is opened:

1. **Kill switch:** if `TRADING_KILL_SWITCH` env var is set to `1`, `true`, or `yes` (case-insensitive) → raise `PermissionError("Trading kill switch engaged")`. This is an operator escape hatch; setting it does not require a container restart — `os.getenv()` reads it at call time.

2. **Live arming flag:** if `settings.LIVE_TRADING_ARMED` is `False` (default) → raise `PermissionError("LIVE_TRADING_ARMED is not set — live order placement is disabled")`.

3. **Notional cap:** `notional = quantity * (entry_price or target_price)`. If `notional > settings.MAX_ORDER_NOTIONAL` → raise `ValueError(f"Order exceeds notional cap: {notional:.2f} > {settings.MAX_ORDER_NOTIONAL}")`.

4. **Quantity cap:** if `quantity > settings.MAX_ORDER_QTY` → raise `ValueError(f"Order exceeds quantity cap: {quantity} > {settings.MAX_ORDER_QTY}")`.

Paper orders never reach `place_bracket_order` (they short-circuit in `maybe_execute` at lines 283-294 and in `approve_order` at line 571). No paper-mode branching is needed inside this function.

### R2 — New `Settings` fields in `core/config.py`

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `LIVE_TRADING_ARMED` | `bool` | `False` | Must be explicitly set to `True` in env to allow live order placement. Not settable via API. |
| `TRADING_KILL_SWITCH` | `bool` | `False` | Read via `os.getenv()` at call time (not from `Settings`) so it can be set without restart. Also add as a `Settings` field for startup visibility. |
| `MAX_ORDER_NOTIONAL` | `float` | `10_000.0` | Max USD notional per order. Conservative default; override via env for larger live accounts. |
| `MAX_ORDER_QTY` | `int` | `200` | Max shares per order. Conservative default. |

Note: `TRADING_KILL_SWITCH` is also checked via `os.getenv()` directly (not only through `settings`) so that setting the env var while the process is running (e.g. via Docker `exec`) takes effect immediately without restarting the container. The `Settings` field provides startup-time visibility in logs.

### R3 — `max_position_usd` required for live strategies

**At router level (strategy creation and update):**

`POST /api/trading/strategies` and `PATCH /api/trading/strategies/{id}` must reject with HTTP 422 when the resulting merged state has `paper_mode=False` and `max_position_usd` is null/absent. The check must evaluate the *post-merge* state (not just the payload) to handle partial updates correctly.

**At execution time in `maybe_execute` (security-critical guard):**

After the existing guard chain (`AUTO_TRADING_ENABLED` check, idempotency check, Redis lock), add:

```python
if not strategy.paper_mode and strategy.max_position_usd is None:
    logger.error(
        "AutoTradeExecutor: live strategy '%s' has no max_position_usd — "
        "refusing to place order for rule %s", strategy.name, rule.id
    )
    return None
```

This catches pre-existing bad rows that predate the router validation.

### R4 — Structured observability

**WARN-level Seq log (in `place_bracket_order`, after all guards pass):**

```python
logger.warning(
    "LIVE ORDER PLACEMENT: symbol=%s side=%s qty=%d entry=%s stop=%s target=%s "
    "notional=%.2f order_ref=%s",
    symbol, side, quantity, entry_price or "MKT", stop_price, target_price,
    notional, order_ref,
)
```

**Prometheus counter (`core/metrics.py`):**

```python
live_orders_total = Counter(
    "live_orders_total",
    "Total live (non-paper) orders placed to IBKR",
    ["symbol", "side"],
)
```

Increment in `place_bracket_order` after the guards pass, before `ib.placeOrder`.

**Grafana alert rule (`grafana/provisioning/alerting/rules.yaml`):**

Add a new rule `LiveOrderPlaced` that fires when `rate(live_orders_total[1m]) > 0`. Use a 1-minute evaluation interval with no grace period. Alert POSTs to `/api/v1/alerts/infrastructure` (same sink as the existing IBKR disconnect and Celery failure rules).

### R5 — `update_trading_config` exclusion

`LIVE_TRADING_ARMED` must **not** appear in the allowed update keys for `PATCH /api/v1/trading/config`. Audit `routers/auto_trading.py` to confirm the config update handler only touches `SystemConfig` keys — env-only settings are not mutable via this endpoint.

---

## Chosen Approach

**Single-chokepoint defense-in-depth at the IBKR call layer.**

All four guards are added together at the top of `place_bracket_order`. This is the only function in the codebase that calls `ib.placeOrder`. The guards are:

- Below all DB-settable flags (`AUTO_TRADING_ENABLED`, `paper_mode`, `requires_approval`)
- Below the executor's guard chain in `maybe_execute`
- Below the Celery task dispatcher

This means they cannot be bypassed by flipping API-mutable configs. An attacker who can reach the API cannot disable `LIVE_TRADING_ARMED` or `TRADING_KILL_SWITCH` — those require env/shell access.

`AUTO_TRADING_ENABLED` is preserved as the API-settable toggle for day-to-day operator control in `maybe_execute`. `LIVE_TRADING_ARMED` is a distinct deployment-level arming switch. Both must be true for a live order to reach IBKR. This is explicit two-factor deployment-level control.

---

## Alternatives Considered

### Alt A: Add all guards in `maybe_execute` (executor layer only)

**Rejected.** `maybe_execute` is the right place for operational controls (`AUTO_TRADING_ENABLED`, position limits, daily trade counts). But it reads from the database, meaning DB-mutable values can be set via the API. Adding env flags to `maybe_execute` would work but would leave `place_bracket_order` unguarded — a future caller could bypass the executor entirely and call the provider directly. The chokepoint value is that `place_bracket_order` is the minimal perimeter: anything that reaches it is live money.

### Alt B: Replace `AUTO_TRADING_ENABLED` with `LIVE_TRADING_ARMED`

**Rejected.** `AUTO_TRADING_ENABLED` is the operator's convenient day-to-day toggle (e.g., disable trading ahead of earnings, reenable afterward) without needing shell access. Removing it would make routine operational control harder. The two flags serve distinct layers: `AUTO_TRADING_ENABLED` is the operational toggle; `LIVE_TRADING_ARMED` is the deployment-level arming switch.

### Alt C: Runtime daily-loss kill switch

**Deferred.** The issue's attack scenario mentions "no daily-loss kill switch" but the explicit remediation list does not include one. No daily realized-P&L aggregation plumbing exists today. Implementing correct intraday-loss rollup (trading-day timezone boundary, partial fills, paper-vs-live separation) is a separate M/L ticket. The manual `TRADING_KILL_SWITCH` env flag (R1) delivers the immediate operational halt capability. File a follow-up ticket.

---

## Implementation Plan

All changes fit in the declared size:M (1–4 hours).

### 1. `backend/app/core/config.py`

Add to `Settings`:
```python
# ── Live trading safety controls ───────────────────────────────────────
# LIVE_TRADING_ARMED: must be explicitly set True in env to allow real orders.
# Not API-settable — requires container/env access to change.
LIVE_TRADING_ARMED: bool = False
TRADING_KILL_SWITCH: bool = False  # startup-time visibility; also checked via os.getenv
MAX_ORDER_NOTIONAL: float = 10_000.0   # USD hard cap per order
MAX_ORDER_QTY: int = 200              # shares hard cap per order
```

Add validator to warn at startup when `LIVE_TRADING_ARMED` is True:
```python
@field_validator("LIVE_TRADING_ARMED")
@classmethod
def warn_live_trading_armed(cls, v: bool) -> bool:
    if v:
        import logging
        logging.getLogger(__name__).warning(
            "LIVE_TRADING_ARMED=True — live order placement is ENABLED at the env level."
        )
    return v
```

Also add validator test in `backend/tests/conftest.py` (`os.environ.setdefault` calls for new fields with valid values, following the existing pattern in backend-patterns.md).

### 2. `backend/app/providers/ibkr_orders.py`

At the top of `place_bracket_order`, before `ib = await self._connect()`:

```python
import os

# ── Non-bypassable live-order guards ─────────────────────────────
if os.getenv("TRADING_KILL_SWITCH", "").lower() in ("1", "true", "yes"):
    raise PermissionError("Trading kill switch engaged — refusing to place order")
if not settings.LIVE_TRADING_ARMED:
    raise PermissionError(
        "LIVE_TRADING_ARMED is not set — live order placement is disabled. "
        "Set LIVE_TRADING_ARMED=true in the environment to enable."
    )
notional = quantity * (entry_price if entry_price is not None else target_price)
if notional > settings.MAX_ORDER_NOTIONAL:
    raise ValueError(
        f"Order exceeds notional cap: {notional:.2f} > {settings.MAX_ORDER_NOTIONAL}"
    )
if quantity > settings.MAX_ORDER_QTY:
    raise ValueError(
        f"Order exceeds quantity cap: {quantity} > {settings.MAX_ORDER_QTY}"
    )
# ── WARN-level audit log (guards passed) ─────────────────────────
logger.warning(
    "LIVE ORDER PLACEMENT: symbol=%s side=%s qty=%d entry=%s stop=%s target=%s "
    "notional=%.2f order_ref=%s",
    symbol, side, quantity,
    f"{entry_price:.4f}" if entry_price is not None else "MKT",
    stop_price, target_price, notional, order_ref,
)
# ── Prometheus counter ────────────────────────────────────────────
from app.core.metrics import live_orders_total
live_orders_total.labels(symbol=symbol, side=side).inc()
```

### 3. `backend/app/core/metrics.py`

```python
live_orders_total = Counter(
    "live_orders_total",
    "Total live (non-paper) bracket orders placed to IBKR",
    ["symbol", "side"],
)
```

### 4. `backend/app/services/auto_trade_service.py`

In `maybe_execute`, after the `AUTO_TRADING_ENABLED` check (step 1, ~line 120), add:

```python
# Execution-time guard: live strategies must have max_position_usd set
if not strategy.paper_mode and strategy.max_position_usd is None:
    logger.error(
        "AutoTradeExecutor: live strategy '%s' (id=%s) has no max_position_usd "
        "— refusing live order for rule %s",
        strategy.name, strategy.id, rule.id,
    )
    return None
```

### 5. `backend/app/routers/auto_trading.py`

In the strategy create and update handlers, after applying the payload, validate merged state:

```python
def _validate_live_strategy(paper_mode: bool, max_position_usd) -> None:
    if not paper_mode and max_position_usd is None:
        raise HTTPException(
            status_code=422,
            detail="max_position_usd is required when paper_mode=False"
        )
```

Call this before `db.commit()` in both `create_strategy` and `update_strategy`. For partial updates, evaluate the merged value: `paper_mode_effective = payload.get("paper_mode", strategy.paper_mode)`.

### 6. `grafana/provisioning/alerting/rules.yaml`

Add new alert group alongside existing rules:

```yaml
- name: LiveTrading
  rules:
    - alert: LiveOrderPlaced
      expr: rate(live_orders_total[1m]) > 0
      for: 0m
      labels:
        severity: critical
      annotations:
        summary: "Live IBKR order placed"
        description: "A live bracket order was submitted to IBKR. Symbol: {{ $labels.symbol }}, Side: {{ $labels.side }}"
```

---

## Verification

### Unit tests

1. `test_place_bracket_order_kill_switch` — with `TRADING_KILL_SWITCH=true` in env, call `place_bracket_order`; assert `PermissionError` is raised and `ib.placeOrder` is never called (mock IBKR).
2. `test_place_bracket_order_not_armed` — with `settings.LIVE_TRADING_ARMED = False`, assert `PermissionError`.
3. `test_place_bracket_order_notional_cap` — quantity=100, entry=200.0 (notional=20_000 > 10_000 default), assert `ValueError`.
4. `test_place_bracket_order_qty_cap` — quantity=300 (> 200 default), assert `ValueError`.
5. `test_maybe_execute_rejects_live_strategy_without_max_position` — mock strategy with `paper_mode=False, max_position_usd=None`; assert `maybe_execute` returns `None`.
6. `test_create_strategy_live_requires_max_position` — POST a strategy with `paper_mode=False, max_position_usd=None`; assert HTTP 422.
7. `test_update_strategy_live_requires_max_position` — PATCH an existing strategy setting `paper_mode=False` without `max_position_usd`; assert HTTP 422.

### Integration tests

8. `test_paper_order_never_calls_place_bracket_order` — strategy with `paper_mode=True`; run full `maybe_execute`; mock `IBKROrderManager.place_bracket_order` and assert it is never called. (This validates the paper-mode invariant that makes the in-function guards safe to treat as live-only.)

---

## Open Questions (non-blocking)

1. **`TRADING_KILL_SWITCH` restart behavior:** `os.getenv()` reads the live env — setting it via `docker exec -e` or a Docker update may not propagate to the running process. Document in `ENV_VARIABLES.md` that the supported use is to set the var and restart the container; `docker exec` env injection is unreliable across Linux process models.

2. **`live_orders_total` cardinality:** The label set `{symbol, side}` is low-cardinality (a handful of live orders per day). If usage scales, evaluate dropping `symbol` label to keep Prometheus cardinality bounded.

3. **Grafana `for: 0m` latency:** A zero-second `for` fires immediately on first scrape. Given that the scrape interval is typically 15s, the alert may lag up to 15s after placement. This is acceptable for a post-hoc audit alert (it is not a pre-trade gate).

---

## Assumptions

- ⚠️ `LIVE_TRADING_ARMED` defaults `False` — live trading in the current deployment is paper-only. Any container currently running live trades must explicitly set this env var before this change goes live, or live order submission will break.
- ⚠️ The conservative defaults (`MAX_ORDER_NOTIONAL=10_000`, `MAX_ORDER_QTY=200`) are tighter than the current default position-sizing behavior (which can produce ~1000 shares / $50k notional on a $50 stock with default risk params). Live accounts that currently trade larger sizes must set these env vars to appropriate values before deployment.
- Paper orders never reach `place_bracket_order` (validated by integration test R-V-8). The guards in `place_bracket_order` are intentionally live-only.
- No migration is required — the `max_position_usd` column already exists on `trading_strategies`.

---

## Out of Scope

- Runtime daily-loss auto-halt kill switch (requires daily P&L aggregation not yet built — file separate ticket referencing this one)
- Multi-user / RBAC changes (single-user platform)
- IBKR port security (paper vs live port assignment is a separate infrastructure concern)
- Changes to `poll_auto_trade_fills` or the fill-tracking pipeline
