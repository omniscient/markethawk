# F-TRADE-01: Live IBKR Order Hard Guards — Implementation Plan

**Date:** 2026-06-22  
**Issue:** #368  
**Spec:** `docs/superpowers/specs/2026-06-20-live-ibkr-order-hard-guards-design.md`  
**Branch:** `refine/issue-368--security--f-trade-01--live-ibkr-order-p`

---

## Goal

Add four non-bypassable security controls at `place_bracket_order` — the single IBKR live-order chokepoint — so that an API compromise alone cannot trigger a live order. Also enforce `max_position_usd` at both strategy creation and execution time, and add structured observability (Seq WARN log, Prometheus counter, Grafana alert rule).

## Architecture

Single-chokepoint defense-in-depth: all env-level guards (`TRADING_KILL_SWITCH`, `LIVE_TRADING_ARMED`, notional cap, qty cap) fire at the top of `place_bracket_order`, before any IBKR connection opens, below all DB-settable flags and below the executor guard chain in `maybe_execute`. The two existing DB-mutable controls (`AUTO_TRADING_ENABLED` in `maybe_execute`, `paper_mode` in the executor) are preserved and unchanged.

## Tech Stack

Backend: FastAPI, pydantic-settings, SQLAlchemy 2.0 (sync), Redis (fakeredis in tests)  
Observability: Seq (structlog), Prometheus (`prometheus_client`), Grafana alert provisioning  
Tests: pytest, unittest.mock, fakeredis

---

## File Structure

| File | Change |
|------|--------|
| `backend/app/core/config.py` | Add 4 `Settings` fields + `LIVE_TRADING_ARMED` startup validator |
| `backend/tests/conftest.py` | Add `os.environ.setdefault("LIVE_TRADING_ARMED", "false")` |
| `backend/app/core/metrics.py` | Add `live_orders_total` Prometheus Counter |
| `backend/app/providers/ibkr_orders.py` | Add 4 guards + WARN log + counter in `place_bracket_order` |
| `backend/app/services/auto_trade_service.py` | Add `max_position_usd` guard in `maybe_execute` |
| `backend/app/routers/auto_trading.py` | Add `_validate_live_strategy` helper + calls in create/update |
| `grafana/provisioning/alerting/rules.yaml` | Add `LiveOrderPlaced` alert rule |
| `backend/tests/providers/test_ibkr_orders.py` | Tests 1–4: guard unit tests |
| `backend/tests/services/test_auto_trade_service.py` | Tests 5, 8: execution guard + paper invariant |
| `backend/tests/api/test_auto_trading.py` | Tests 6–7: router 422 validation tests |

---

## Task 1 — Add Settings fields for live trading safety controls

**Files:** `backend/app/core/config.py`, `backend/tests/conftest.py`

### Implement: `backend/app/core/config.py`

After line 101 (`IBKR_TRADING_CLIENT_ID: int = 11`), add the new section before the `# ── Email / SMTP` section:

```python
# ── Live trading safety controls ──────────────────────────────────────────────
# LIVE_TRADING_ARMED: must be explicitly True in env to allow real orders.
# Not API-settable — requires container/env access to change.
LIVE_TRADING_ARMED: bool = False
# TRADING_KILL_SWITCH: also checked via os.getenv() at call time for
# real-time halt without restart. Settings field provides startup visibility.
TRADING_KILL_SWITCH: bool = False
MAX_ORDER_NOTIONAL: float = 10_000.0  # USD hard cap per order
MAX_ORDER_QTY: int = 200              # shares hard cap per order
```

Add the following validator after the existing `@field_validator("LOG_LEVEL")` block (before the `@field_validator("ENVIRONMENT")` block):

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

### Implement: `backend/tests/conftest.py`

Per the `backend-patterns.md` memory entry: when adding a `field_validator` to `Settings`, add a matching `setdefault` before app imports. Add after the existing `os.environ.setdefault` block (around line 16, before `import logging as _logging`):

```python
os.environ.setdefault("LIVE_TRADING_ARMED", "false")
```

This also ensures `test_place_bracket_order_not_armed` (Task 3) reliably starts with LIVE_TRADING_ARMED=False regardless of the shell environment.

### Verify

```bash
docker-compose exec backend python -c "
from app.core.config import settings
assert settings.LIVE_TRADING_ARMED == False, f'Expected False, got {settings.LIVE_TRADING_ARMED}'
assert settings.TRADING_KILL_SWITCH == False
assert settings.MAX_ORDER_NOTIONAL == 10_000.0
assert settings.MAX_ORDER_QTY == 200
print('Settings OK')
"
```

Expected: `Settings OK`

### Commit

```bash
git add backend/app/core/config.py backend/tests/conftest.py
git commit -m "feat: add live trading safety Settings fields (LIVE_TRADING_ARMED, TRADING_KILL_SWITCH, MAX_ORDER_NOTIONAL, MAX_ORDER_QTY) (#368)"
```

---

## Task 2 — Add `live_orders_total` Prometheus counter

**File:** `backend/app/core/metrics.py`

### Implement

Append at the end of `backend/app/core/metrics.py` (after the `db_pool_overflow` gauge, currently the last line):

```python
live_orders_total = Counter(
    "live_orders_total",
    "Total live (non-paper) bracket orders placed to IBKR",
    ["symbol", "side"],
)
```

The `Counter` import is already at line 1.

### Verify

```bash
docker-compose exec backend python -c "
from app.core.metrics import live_orders_total
live_orders_total.labels(symbol='AAPL', side='long').inc()
print('Metrics OK')
"
```

Expected: `Metrics OK`

### Commit

```bash
git add backend/app/core/metrics.py
git commit -m "feat: add live_orders_total Prometheus counter for live IBKR bracket orders (#368)"
```

---

## Task 3 — Add non-bypassable guards to `place_bracket_order`

**Files:** `backend/tests/providers/test_ibkr_orders.py`, `backend/app/providers/ibkr_orders.py`

### TDD Step 1: Write failing tests

Append the following class to `backend/tests/providers/test_ibkr_orders.py`:

```python
import asyncio
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestPlaceBracketOrderGuards:
    """Non-bypassable guards at the top of place_bracket_order (R1 / R2)."""

    def _make_manager(self):
        with patch("app.providers.ibkr_orders.IB_INSYNC_AVAILABLE", True):
            from app.providers.ibkr_orders import IBKROrderManager
            return IBKROrderManager.__new__(IBKROrderManager)

    def _armed_settings(self):
        """Settings mock: LIVE_TRADING_ARMED=True, conservative caps."""
        s = MagicMock()
        s.LIVE_TRADING_ARMED = True
        s.TRADING_KILL_SWITCH = False
        s.MAX_ORDER_NOTIONAL = 10_000.0
        s.MAX_ORDER_QTY = 200
        s.IBKR_HOST = "127.0.0.1"
        s.IBKR_PORT = 7496
        s.IBKR_TRADING_CLIENT_ID = 11
        return s

    def _run(self, manager, quantity=10, entry_price=100.0,
             stop_price=95.0, target_price=110.0):
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(
                manager.place_bracket_order(
                    symbol="AAPL", side="long",
                    quantity=quantity, entry_price=entry_price,
                    stop_price=stop_price, target_price=target_price,
                )
            )
        finally:
            loop.close()

    def _attach_ib_mock(self, manager):
        """Wire a disconnected IB mock so _connect never touches the network."""
        ib_mock = MagicMock()
        ib_mock.placeOrder = MagicMock()

        async def fake_connect():
            return ib_mock

        async def fake_disconnect(ib):
            pass

        manager._connect = fake_connect
        manager._disconnect = fake_disconnect
        return ib_mock

    def test_place_bracket_order_kill_switch(self):
        """TRADING_KILL_SWITCH=true must raise PermissionError; placeOrder not called."""
        manager = self._make_manager()
        ib_mock = self._attach_ib_mock(manager)

        with patch.dict(os.environ, {"TRADING_KILL_SWITCH": "true"}):
            with pytest.raises(PermissionError, match="kill switch"):
                self._run(manager)

        ib_mock.placeOrder.assert_not_called()

    def test_place_bracket_order_not_armed(self):
        """LIVE_TRADING_ARMED=False (test default via conftest.py) must raise PermissionError."""
        manager = self._make_manager()
        ib_mock = self._attach_ib_mock(manager)

        # conftest.py sets LIVE_TRADING_ARMED=false; disable kill switch explicitly
        with patch.dict(os.environ, {"TRADING_KILL_SWITCH": ""}):
            with pytest.raises(PermissionError, match="LIVE_TRADING_ARMED"):
                self._run(manager)

        ib_mock.placeOrder.assert_not_called()

    def test_place_bracket_order_notional_cap(self):
        """qty=100 * entry=200.0 → notional=20_000 > 10_000 cap → ValueError."""
        manager = self._make_manager()
        ib_mock = self._attach_ib_mock(manager)

        with patch("app.providers.ibkr_orders.settings", self._armed_settings()):
            with patch.dict(os.environ, {"TRADING_KILL_SWITCH": ""}):
                with pytest.raises(ValueError, match="notional cap"):
                    self._run(manager, quantity=100, entry_price=200.0)

        ib_mock.placeOrder.assert_not_called()

    def test_place_bracket_order_qty_cap(self):
        """qty=300 > 200 cap → ValueError; notional=300*10=3_000 < cap, so only qty fires."""
        manager = self._make_manager()
        ib_mock = self._attach_ib_mock(manager)

        with patch("app.providers.ibkr_orders.settings", self._armed_settings()):
            with patch.dict(os.environ, {"TRADING_KILL_SWITCH": ""}):
                with pytest.raises(ValueError, match="quantity cap"):
                    self._run(manager, quantity=300, entry_price=10.0)

        ib_mock.placeOrder.assert_not_called()
```

### TDD Step 2: Verify tests fail

```bash
docker-compose exec backend python -m pytest \
  tests/providers/test_ibkr_orders.py::TestPlaceBracketOrderGuards -v 2>&1 | tail -15
```

Expected: 4 FAILED (guards not yet implemented).

### TDD Step 3: Implement guards in `place_bracket_order`

**Add `import os` to `backend/app/providers/ibkr_orders.py`** — insert after `from __future__ import annotations` (line 22):

```python
import os
```

**Add guards at the top of `place_bracket_order`** — immediately after the docstring (before line 230 `ib = await self._connect()`):

```python
        # ── Non-bypassable live-order guards (R1 / R2) ───────────────────────────
        # These checks fire before any IBKR connection opens. They cannot be
        # bypassed by flipping API-mutable DB config (AUTO_TRADING_ENABLED, paper_mode).
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
        # ── WARN-level audit log (all guards passed) ──────────────────────────────
        logger.warning(
            "LIVE ORDER PLACEMENT: symbol=%s side=%s qty=%d entry=%s stop=%s target=%s "
            "notional=%.2f order_ref=%s",
            symbol, side, quantity,
            f"{entry_price:.4f}" if entry_price is not None else "MKT",
            stop_price, target_price, notional, order_ref,
        )
        # ── Prometheus counter ────────────────────────────────────────────────────
        from app.core.metrics import live_orders_total
        live_orders_total.labels(symbol=symbol, side=side).inc()
```

The block replaces the first line of the function body `ib = await self._connect()` — that line moves down after the new block.

### TDD Step 4: Verify tests pass

```bash
docker-compose exec backend python -m pytest \
  tests/providers/test_ibkr_orders.py::TestPlaceBracketOrderGuards -v 2>&1 | tail -15
```

Expected: 4 PASSED.

Also run the full ibkr_orders test file to check no regressions:

```bash
docker-compose exec backend python -m pytest tests/providers/test_ibkr_orders.py -v 2>&1 | tail -10
```

Expected: all PASSED.

### Commit

```bash
git add backend/tests/providers/test_ibkr_orders.py backend/app/providers/ibkr_orders.py
git commit -m "feat: add non-bypassable guards to place_bracket_order (kill switch, arming flag, notional/qty caps, WARN log, Prometheus counter) (#368)"
```

---

## Task 4 — Add `max_position_usd` execution-time guard to `maybe_execute`

**Files:** `backend/tests/services/test_auto_trade_service.py`, `backend/app/services/auto_trade_service.py`

### TDD Step 1: Write failing tests

Append the following two classes to `backend/tests/services/test_auto_trade_service.py`:

```python
from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch
import fakeredis
import pytest


class TestMaybeExecuteMaxPositionGuard:
    """Execution-time guard: live strategy with no max_position_usd returns None (R3)."""

    def test_maybe_execute_rejects_live_strategy_without_max_position(self, db):
        from app.models.alert_rule import AlertRule
        from app.models.scanner_event import ScannerEvent
        from app.models.system_config import SystemConfig
        from app.services.auto_trade_service import AutoTradeExecutor

        # AUTO_TRADING_ENABLED=true so it passes the kill-switch check for live strategies
        db.add(SystemConfig(key="AUTO_TRADING_ENABLED", value="true"))
        strat = _strategy(db, paper_mode=False, max_position_usd=None)

        rule = AlertRule(
            name="Live Guard Test",
            auto_trade=True,
            trading_strategy_id=strat.id,
        )
        db.add(rule)
        event = ScannerEvent(
            ticker="AAPL",
            scanner_type="pre_market_volume_spike",
            event_date=date.today(),
            indicators={"last_trade_price": 150.0},
        )
        db.add(event)
        db.flush()

        fake_r = fakeredis.FakeRedis(decode_responses=True)
        executor = AutoTradeExecutor()

        with patch("redis.from_url", return_value=fake_r):
            result = executor.maybe_execute(rule=rule, event=event, db=db)

        assert result is None, "Live strategy missing max_position_usd must be rejected"


class TestPaperOrderNeverCallsPlaceBracketOrder:
    """Paper mode must never invoke place_bracket_order — validates the upstream invariant (R-V-8)."""

    def test_paper_order_never_calls_place_bracket_order(self, db):
        from app.models.alert_rule import AlertRule
        from app.models.scanner_event import ScannerEvent
        from app.services.auto_trade_service import AutoTradeExecutor

        strat = _strategy(db, paper_mode=True, max_position_usd=Decimal("5000.0"))
        rule = AlertRule(
            name="Paper Invariant Test",
            auto_trade=True,
            trading_strategy_id=strat.id,
        )
        db.add(rule)
        event = ScannerEvent(
            ticker="TSLA",
            scanner_type="pre_market_volume_spike",
            event_date=date.today(),
            indicators={"last_trade_price": 200.0},
        )
        db.add(event)
        db.flush()

        fake_r = fakeredis.FakeRedis(decode_responses=True)
        executor = AutoTradeExecutor()

        with patch("redis.from_url", return_value=fake_r):
            with patch(
                "app.providers.ibkr_orders.IBKROrderManager.place_bracket_order",
                new_callable=AsyncMock,
            ) as mock_place:
                executor.maybe_execute(rule=rule, event=event, db=db)

        mock_place.assert_not_called()
```

### TDD Step 2: Verify tests fail

```bash
docker-compose exec backend python -m pytest \
  tests/services/test_auto_trade_service.py::TestMaybeExecuteMaxPositionGuard \
  tests/services/test_auto_trade_service.py::TestPaperOrderNeverCallsPlaceBracketOrder \
  -v 2>&1 | tail -15
```

Expected: `test_maybe_execute_rejects_live_strategy_without_max_position` FAILED (guard not yet implemented); `test_paper_order_never_calls_place_bracket_order` PASSED (paper short-circuit already in place; this test validates the existing invariant).

### TDD Step 3: Implement guard in `maybe_execute`

In `backend/app/services/auto_trade_service.py`, locate the `AUTO_TRADING_ENABLED` guard block (lines 119–133). After that block closes (`return None`), add the `max_position_usd` guard:

```python
        # ── 1b. max_position_usd required for live strategies (R3) ─────────────
        if not strategy.paper_mode and strategy.max_position_usd is None:
            logger.error(
                "AutoTradeExecutor: live strategy '%s' (id=%s) has no max_position_usd "
                "— refusing live order for rule %s",
                strategy.name, strategy.id, rule.id,
            )
            return None
```

Insert this block immediately after the closing `return None` of the `AUTO_TRADING_ENABLED` check and before the `# ── 2. Idempotency` comment.

### TDD Step 4: Verify tests pass

```bash
docker-compose exec backend python -m pytest \
  tests/services/test_auto_trade_service.py::TestMaybeExecuteMaxPositionGuard \
  tests/services/test_auto_trade_service.py::TestPaperOrderNeverCallsPlaceBracketOrder \
  -v 2>&1 | tail -15
```

Expected: both PASSED.

Also run the full auto_trade_service test suite for regressions:

```bash
docker-compose exec backend python -m pytest tests/services/test_auto_trade_service.py -v 2>&1 | tail -10
```

Expected: all PASSED.

### Commit

```bash
git add backend/tests/services/test_auto_trade_service.py backend/app/services/auto_trade_service.py
git commit -m "feat: add max_position_usd execution-time guard to maybe_execute; validate paper-mode invariant (test R-V-8) (#368)"
```

---

## Task 5 — Add `max_position_usd` router validation (HTTP 422)

**Files:** `backend/tests/api/test_auto_trading.py`, `backend/app/routers/auto_trading.py`

### TDD Step 1: Write failing tests

Append the following class to `backend/tests/api/test_auto_trading.py`:

```python
class TestStrategyLiveRequiresMaxPosition:
    """Router must return 422 when paper_mode=False and max_position_usd is absent (R3)."""

    def test_create_strategy_live_requires_max_position(self, db: Session):
        resp = client.post(
            "/api/v1/trading/strategies",
            json={
                "name": "Unguarded Live Strategy",
                "paper_mode": False,
                # max_position_usd intentionally omitted
            },
        )
        assert resp.status_code == 422, resp.json()
        assert "max_position_usd" in resp.json().get("detail", "").lower()

    def test_update_strategy_live_requires_max_position(self, db: Session):
        # Create a safe paper strategy first
        strat = _strategy(db, paper_mode=True)
        db.flush()

        # PATCH to live mode without providing max_position_usd → 422
        resp = client.patch(
            f"/api/v1/trading/strategies/{strat.id}",
            json={"paper_mode": False},  # max_position_usd absent; existing value is None
        )
        assert resp.status_code == 422, resp.json()
        assert "max_position_usd" in resp.json().get("detail", "").lower()
```

### TDD Step 2: Verify tests fail

```bash
docker-compose exec backend python -m pytest \
  tests/api/test_auto_trading.py::TestStrategyLiveRequiresMaxPosition -v 2>&1 | tail -10
```

Expected: 2 FAILED.

### TDD Step 3: Implement router validation in `auto_trading.py`

**Add `_validate_live_strategy` helper** before `create_strategy` (before line 86 `@router.post("/strategies", ...)`):

```python
def _validate_live_strategy(paper_mode: bool, max_position_usd) -> None:
    """Raise HTTP 422 if a live strategy has no max_position_usd."""
    if not paper_mode and max_position_usd is None:
        raise HTTPException(
            status_code=422,
            detail="max_position_usd is required when paper_mode=False",
        )
```

**Call in `create_strategy`** — add immediately before `db.add(strategy)` (before line 111):

```python
    _validate_live_strategy(paper_mode=strategy.paper_mode, max_position_usd=strategy.max_position_usd)
```

**Call in `update_strategy`** — add after the `for key, value in payload.items()` loop and before `s.updated_at = utc_now()` (before line 139):

```python
    _validate_live_strategy(paper_mode=s.paper_mode, max_position_usd=s.max_position_usd)
```

The merged state after `setattr` is used: `s.paper_mode` and `s.max_position_usd` reflect the post-update values. For a partial PATCH that sets `paper_mode=False` without `max_position_usd`, if `s.max_position_usd` was `None` before the patch, it remains `None` after, and the validation fires. ✓

### TDD Step 4: Verify tests pass

```bash
docker-compose exec backend python -m pytest \
  tests/api/test_auto_trading.py::TestStrategyLiveRequiresMaxPosition -v 2>&1 | tail -10
```

Expected: 2 PASSED.

Run the full `test_auto_trading.py` to check regressions:

```bash
docker-compose exec backend python -m pytest tests/api/test_auto_trading.py -v 2>&1 | tail -10
```

Expected: all PASSED.

### Commit

```bash
git add backend/tests/api/test_auto_trading.py backend/app/routers/auto_trading.py
git commit -m "feat: enforce max_position_usd required for live strategies at router level (HTTP 422) (#368)"
```

---

## Task 6 — Audit `update_trading_config` exclusion (R5)

**File:** `backend/app/routers/auto_trading.py` (verification only, no code change expected)

### Verify

Confirm `LIVE_TRADING_ARMED` is not in the `allowed` set of `update_trading_config`:

```bash
grep -A 3 'allowed = {' backend/app/routers/auto_trading.py
```

Expected output:
```
allowed = {"AUTO_TRADING_ENABLED", "PAPER_ACCOUNT_SIZE"}
```

`LIVE_TRADING_ARMED` is absent — the env-only arming flag cannot be mutated via this API endpoint. ✓

Also confirm `get_trading_config` does not expose it:

```bash
grep -A 3 "keys = \[" backend/app/routers/auto_trading.py
```

Expected: keys list contains only `AUTO_TRADING_ENABLED` and `PAPER_ACCOUNT_SIZE`. ✓

No code change required. R5 is already satisfied.

---

## Task 7 — Add `LiveOrderPlaced` Grafana alert rule

**File:** `grafana/provisioning/alerting/rules.yaml`

### Implement

Append a new group to the `groups:` list at the end of `grafana/provisioning/alerting/rules.yaml` (after the last existing rule, `scan-high-failed-ticker-ratio`):

```yaml
  - name: LiveTrading
    orgId: 1
    folder: MarketHawk
    interval: 1m
    rules:
      - uid: live-order-placed
        title: Live Order Placed
        condition: C
        for: 0m
        annotations:
          summary: >
            A live bracket order was submitted to IBKR.
            Symbol: {{ $labels.symbol }}, Side: {{ $labels.side }}
        labels:
          severity: critical
        data:
          - refId: B
            relativeTimeRange:
              from: 60
              to: 0
            datasourceUid: prometheus
            model:
              expr: rate(live_orders_total[1m])
              refId: B
          - refId: C
            relativeTimeRange:
              from: 60
              to: 0
            datasourceUid: "-- Grafana --"
            model:
              type: math
              expression: $B > 0
```

Note: `for: 0m` means no grace period — fires immediately on first evaluation interval where rate > 0. With the default 15s Prometheus scrape interval, the alert may lag up to 15s after order placement (acceptable for a post-hoc audit alert — this is not a pre-trade gate).

### Validate YAML syntax

```bash
python3 -c "
import yaml
with open('grafana/provisioning/alerting/rules.yaml') as f:
    doc = yaml.safe_load(f)
groups = doc['groups']
names = [g['name'] for g in groups]
assert 'LiveTrading' in names, f'LiveTrading group missing; found: {names}'
lt = next(g for g in groups if g['name'] == 'LiveTrading')
assert lt['rules'][0]['uid'] == 'live-order-placed'
print(f'YAML OK — {len(groups)} groups total, LiveTrading rule present')
"
```

Expected: `YAML OK — 2 groups total, LiveTrading rule present`

### Commit

```bash
git add grafana/provisioning/alerting/rules.yaml
git commit -m "feat: add LiveOrderPlaced Grafana alert rule for live IBKR order monitoring (#368)"
```

---

## Task 8 — Full test suite validation

### Run all 8 spec-required tests

```bash
docker-compose exec backend python -m pytest \
  tests/providers/test_ibkr_orders.py::TestPlaceBracketOrderGuards \
  tests/services/test_auto_trade_service.py::TestMaybeExecuteMaxPositionGuard \
  tests/services/test_auto_trade_service.py::TestPaperOrderNeverCallsPlaceBracketOrder \
  tests/api/test_auto_trading.py::TestStrategyLiveRequiresMaxPosition \
  -v 2>&1
```

Expected output:
```
tests/providers/test_ibkr_orders.py::TestPlaceBracketOrderGuards::test_place_bracket_order_kill_switch PASSED
tests/providers/test_ibkr_orders.py::TestPlaceBracketOrderGuards::test_place_bracket_order_not_armed PASSED
tests/providers/test_ibkr_orders.py::TestPlaceBracketOrderGuards::test_place_bracket_order_notional_cap PASSED
tests/providers/test_ibkr_orders.py::TestPlaceBracketOrderGuards::test_place_bracket_order_qty_cap PASSED
tests/services/test_auto_trade_service.py::TestMaybeExecuteMaxPositionGuard::test_maybe_execute_rejects_live_strategy_without_max_position PASSED
tests/services/test_auto_trade_service.py::TestPaperOrderNeverCallsPlaceBracketOrder::test_paper_order_never_calls_place_bracket_order PASSED
tests/api/test_auto_trading.py::TestStrategyLiveRequiresMaxPosition::test_create_strategy_live_requires_max_position PASSED
tests/api/test_auto_trading.py::TestStrategyLiveRequiresMaxPosition::test_update_strategy_live_requires_max_position PASSED

8 passed
```

### Regression check: run related test modules

```bash
docker-compose exec backend python -m pytest \
  tests/providers/test_ibkr_orders.py \
  tests/services/test_auto_trade_service.py \
  tests/api/test_auto_trading.py \
  tests/test_settings.py \
  -v --tb=short 2>&1 | tail -20
```

Expected: all PASSED.

---

## Implementation Notes

### `os.getenv()` vs `settings.TRADING_KILL_SWITCH`

The kill switch check in `place_bracket_order` uses `os.getenv("TRADING_KILL_SWITCH", "")` directly (not `settings.TRADING_KILL_SWITCH`) so that setting the env var in the running container (e.g. `docker exec -e TRADING_KILL_SWITCH=true …`) takes effect immediately without restarting. `settings.TRADING_KILL_SWITCH` provides startup-time visibility in logs. The `Settings` field has no validator — it just records the value at startup.

### `LIVE_TRADING_ARMED` deployment warning

`LIVE_TRADING_ARMED` defaults `False`. Any container that currently places live orders must set `LIVE_TRADING_ARMED=true` in its env before deploying this change — live order submission will be blocked otherwise. Document in `ENV_VARIABLES.md`.

### Conservative default caps

`MAX_ORDER_NOTIONAL=10_000` and `MAX_ORDER_QTY=200` are tighter than current default sizing behavior (default risk params can produce ~1000 shares / $50k notional on a $50 stock). Live accounts trading larger sizes must override these via env before deployment.

### No migration required

`max_position_usd` column already exists on `trading_strategies`. No Alembic migration needed.

### Grafana alert latency

`for: 0m` fires immediately, but Prometheus scrape interval (typically 15s) adds up to 15s lag. This is acceptable — the alert is a post-hoc audit notification, not a pre-trade gate.
