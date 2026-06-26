# Plan: Decompose AutoTradeExecutor.maybe_execute()

**Issue:** #630
**Spec:** docs/superpowers/specs/2026-06-26-decompose-auto-trade-executor-design.md
**Date:** 2026-06-26
**Size:** S

## Goal

Extract the 290-line `maybe_execute()` cascade in `backend/app/services/auto_trade_service.py` into six named private methods, making each decision step independently testable. No behavior change. All existing tests pass unmodified.

## Architecture

Six private methods, preserving the pre-lock / inside-lock boundary:

| Method | Steps | Return Type | Lock boundary |
|---|---|---|---|
| `_validate_basics(rule, db)` | 1 + 1b + 1c | `Optional[TradingStrategy]` | pre-lock |
| `_check_idempotency(event, strategy, today, db)` | 2 | `bool` | pre-lock |
| `_validate_quality_gate(event, rule, db)` | 2.5 | `bool` | pre-lock |
| `_validate_concurrency(strategy, today, db)` | 4 + 5 | `bool` | inside lock |
| `_validate_session(event, strategy)` | 6 | `bool` | inside lock |
| `_size_position(event, strategy, db)` | 7–10 | `Optional[PositionCalc]` | inside lock |

Steps 11–12 (order creation + IBKR submit/park) remain inline in `maybe_execute`.

## Tech Stack

- Python service layer (`backend/app/services/auto_trade_service.py`)
- pytest + fakeredis + transaction-rollback `db` fixture (from `conftest.py`)
- No migration, no API change, no model change

## File Structure

| File | Change |
|---|---|
| `backend/app/services/auto_trade_service.py` | Extract 6 methods, add `side: str = ""` field to `PositionCalc`, update `maybe_execute` skeleton |
| `backend/tests/services/test_auto_trade_service.py` | Add `test__validate_basics_killswitch`, `test__validate_basics_no_max_position_usd`, `test__size_position_*` (4 tests) |

---

## Task 1: Extract `_validate_basics` with direct unit tests

**Files:** `backend/app/services/auto_trade_service.py`, `backend/tests/services/test_auto_trade_service.py`

### TDD Steps

**Step 1.1 — Write failing tests.**

Append at the end of `backend/tests/services/test_auto_trade_service.py`:

```python
# ── Direct tests: _validate_basics ────────────────────────────────────────────

def test__validate_basics_killswitch(db: Session):
    """Live strategy with no AUTO_TRADING_ENABLED config → _validate_basics returns None."""
    strategy = _strategy(db, paper_mode=False, max_position_usd=Decimal("10000"))
    rule = _rule(db, strategy)
    # No SystemConfig for AUTO_TRADING_ENABLED → defaults to blocked
    executor = AutoTradeExecutor()
    result = executor._validate_basics(rule, db)
    assert result is None


def test__validate_basics_no_max_position_usd(db: Session):
    """Live strategy with max_position_usd=None → _validate_basics returns None."""
    from app.models.system_config import SystemConfig

    strategy = _strategy(db, paper_mode=False, max_position_usd=None)
    # Enable kill-switch so execution reaches the max_position_usd check
    cfg = SystemConfig(key="AUTO_TRADING_ENABLED", value="true")
    db.add(cfg)
    db.flush()
    rule = _rule(db, strategy)
    executor = AutoTradeExecutor()
    result = executor._validate_basics(rule, db)
    assert result is None
```

**Step 1.2 — Verify tests fail.**

```bash
docker-compose exec backend pytest backend/tests/services/test_auto_trade_service.py::test__validate_basics_killswitch backend/tests/services/test_auto_trade_service.py::test__validate_basics_no_max_position_usd -v
```

Expected: `AttributeError: 'AutoTradeExecutor' object has no attribute '_validate_basics'`

**Step 1.3 — Extract `_validate_basics`.**

In `backend/app/services/auto_trade_service.py`, add `date` to the datetime import:

```python
from datetime import date, datetime, timezone
```

Add the method to the `AutoTradeExecutor` class, between `_validate_basics` and `submit_existing_order` (after `maybe_execute`, before `submit_existing_order` at line ~384). The method body is the code currently at lines 104–149 of `maybe_execute`:

```python
def _validate_basics(
    self, rule: AlertRule, db: Session
) -> Optional[TradingStrategy]:
    """Steps 1 + 1b + 1c: guard checks, strategy load, kill-switch, max_position_usd."""
    if not rule.auto_trade or not rule.trading_strategy_id:
        return None

    strategy = (
        db.query(TradingStrategy)
        .filter(
            TradingStrategy.id == rule.trading_strategy_id,
            TradingStrategy.is_active == True,
        )
        .first()
    )
    if not strategy:
        logger.debug(
            f"AutoTradeExecutor: strategy {rule.trading_strategy_id} "
            f"not found or inactive — skipping"
        )
        return None

    # Global kill-switch only blocks live orders, not paper.
    if not strategy.paper_mode:
        cfg = (
            db.query(SystemConfig)
            .filter(SystemConfig.key == "AUTO_TRADING_ENABLED")
            .first()
        )
        if not cfg or cfg.value.lower() != "true":
            logger.info(
                "AutoTradeExecutor: AUTO_TRADING_ENABLED is off — "
                "blocking live order for rule %s",
                rule.id,
            )
            return None

    # max_position_usd required and must be positive for live strategies
    if not strategy.paper_mode and (
        strategy.max_position_usd is None or float(strategy.max_position_usd) <= 0
    ):
        logger.error(
            "AutoTradeExecutor: live strategy '%s' (id=%s) has no valid max_position_usd "
            "(None or <= 0) — refusing live order for rule %s",
            strategy.name,
            strategy.id,
            rule.id,
        )
        return None

    return strategy
```

Replace the inline code in `maybe_execute` (lines 104–149) with a delegation call:

```python
def maybe_execute(
    self,
    rule: AlertRule,
    event: ScannerEvent,
    db: Session,
) -> Optional[AutoTradeOrder]:
    """
    Entry point called from evaluate_scanner_alerts Celery task.

    Returns the AutoTradeOrder that was created (any status), or None if
    execution was skipped for any reason.
    """
    # ── 1 + 1b + 1c. Basic guards, strategy load, kill-switch ───────
    strategy = self._validate_basics(rule, db)
    if strategy is None:
        return None

    # ── 2. Idempotency — one order per symbol/strategy/day ───────────
    today = datetime.now(timezone.utc).date()
    existing = (
        db.query(AutoTradeOrder)
        ...
```

(The remainder of `maybe_execute` — idempotency, quality gate, Redis lock, concurrency, session, sizing, order creation — is unchanged at this step.)

**Step 1.4 — Verify new tests pass.**

```bash
docker-compose exec backend pytest backend/tests/services/test_auto_trade_service.py::test__validate_basics_killswitch backend/tests/services/test_auto_trade_service.py::test__validate_basics_no_max_position_usd -v
```

Expected: both PASSED.

**Step 1.5 — Verify full test file still passes.**

```bash
docker-compose exec backend pytest backend/tests/services/test_auto_trade_service.py -v
```

Expected: all tests pass (no regressions).

**Step 1.6 — Commit.**

```bash
git add backend/app/services/auto_trade_service.py backend/tests/services/test_auto_trade_service.py
git commit -m "refactor(#630): extract _validate_basics + direct tests"
```

---

## Task 2: Extract `_check_idempotency` and `_validate_quality_gate`

**Files:** `backend/app/services/auto_trade_service.py`

No new direct tests — behavior is covered by existing `test_maybe_execute_idempotent_second_call_returns_none` and `test_quality_gate_*` tests.

### TDD Steps

**Step 2.1 — Verify baseline.** Before touching the code, confirm all existing tests still pass (should from Task 1):

```bash
docker-compose exec backend pytest backend/tests/services/test_auto_trade_service.py -v
```

**Step 2.2 — Extract `_check_idempotency`.**

Add method to `AutoTradeExecutor` (below `_validate_basics`):

```python
def _check_idempotency(
    self,
    event: ScannerEvent,
    strategy: TradingStrategy,
    today: date,
    db: Session,
) -> bool:
    """Step 2: one order per symbol/strategy/day. Returns True to proceed, False to skip."""
    existing = (
        db.query(AutoTradeOrder)
        .filter(
            AutoTradeOrder.symbol == event.ticker,
            AutoTradeOrder.trading_strategy_id == strategy.id,
            AutoTradeOrder.event_date == today,
        )
        .first()
    )
    if existing:
        logger.debug(
            f"AutoTradeExecutor: order already exists for "
            f"{event.ticker}/strategy={strategy.id}/{today} id={existing.id} — skipping"
        )
        return False
    return True
```

Replace the inline idempotency block in `maybe_execute` (the `existing = db.query(...)` block) with:

```python
    # ── 2. Idempotency ───────────────────────────────────────────────
    today = datetime.now(timezone.utc).date()
    if not self._check_idempotency(event, strategy, today, db):
        return None
```

**Step 2.3 — Extract `_validate_quality_gate`.**

Add method to `AutoTradeExecutor` (below `_check_idempotency`):

```python
def _validate_quality_gate(
    self, event: ScannerEvent, rule: AlertRule, db: Session
) -> bool:
    """Step 2.5: strict quality gate. Returns True to proceed, False to skip."""
    try:
        universe_id = self._resolve_universe_id(event, db)
        gate_policy = (
            QualityGatePolicy.strict
            if universe_id is not None
            else QualityGatePolicy.off
        )
        _gate_req = SimpleNamespace(
            policy=gate_policy.value,
            universe_id=universe_id,
            scanner_type=event.scanner_type,
            ticker=event.ticker,
            requirements=None,
        )
        assessment = QualityGateService.assess(db, _gate_req)
    except Exception as exc:
        logger.warning(
            "quality_gate_service_error: ticker=%s event=%s rule=%s error=%s"
            " — failing closed",
            event.ticker,
            event.id,
            rule.id,
            exc,
        )
        return False

    gate_ok = self._gate_passes(assessment, db)
    bypass_used = assessment.verdict == "skipped" and gate_ok
    if not gate_ok:
        logger.warning(
            "quality_gate_refused: ticker=%s event=%s rule=%s"
            " verdict=%s issues=%s warnings=%s bypass_used=%s",
            event.ticker,
            event.id,
            rule.id,
            assessment.verdict,
            assessment.issues,
            assessment.warnings,
            bypass_used,
        )
        return False
    if bypass_used:
        logger.warning(
            "quality_gate_bypass_used: ticker=%s event=%s rule=%s"
            " verdict=skipped bypass=QUALITY_GATE_SKIP_BYPASS",
            event.ticker,
            event.id,
            rule.id,
        )
    return True
```

Replace the inline quality gate block in `maybe_execute` (the `try: universe_id = ...` through `if bypass_used: logger.warning(...)`) with:

```python
    # ── 2.5. Data quality gate ───────────────────────────────────────
    if not self._validate_quality_gate(event, rule, db):
        return None
```

**Step 2.4 — Verify all tests pass.**

```bash
docker-compose exec backend pytest backend/tests/services/test_auto_trade_service.py -v
```

Expected: all tests pass.

**Step 2.5 — Commit.**

```bash
git add backend/app/services/auto_trade_service.py
git commit -m "refactor(#630): extract _check_idempotency + _validate_quality_gate"
```

---

## Task 3: Extract `_validate_concurrency` and `_validate_session`

**Files:** `backend/app/services/auto_trade_service.py`

No new direct tests — behavior is covered by existing integration tests through `maybe_execute`.

### TDD Steps

**Step 3.1 — Extract `_validate_concurrency`.**

Add method to `AutoTradeExecutor` (below `_validate_quality_gate`):

```python
def _validate_concurrency(
    self, strategy: TradingStrategy, today: date, db: Session
) -> bool:
    """Steps 4 + 5: daily trade count + open position count. Returns True to proceed."""
    today_start = datetime.combine(today, datetime.min.time())
    today_count = (
        db.query(AutoTradeOrder)
        .filter(
            AutoTradeOrder.trading_strategy_id == strategy.id,
            AutoTradeOrder.created_at >= today_start,
            AutoTradeOrder.status.notin_(["rejected", "error", "cancelled"]),
        )
        .count()
    )
    if today_count >= strategy.max_trades_per_day:
        logger.info(
            f"AutoTradeExecutor: daily limit reached for strategy "
            f"'{strategy.name}' ({today_count}/{strategy.max_trades_per_day}) — skipping"
        )
        return False

    open_count = (
        db.query(AutoTradeOrder)
        .filter(
            AutoTradeOrder.trading_strategy_id == strategy.id,
            AutoTradeOrder.status.in_(
                ["submitted", "open", "pending_approval", "pending"]
            ),
        )
        .count()
    )
    if open_count >= strategy.max_concurrent_positions:
        logger.info(
            f"AutoTradeExecutor: max concurrent positions reached for strategy "
            f"'{strategy.name}' ({open_count}/{strategy.max_concurrent_positions}) — skipping"
        )
        return False

    return True
```

Replace the inline steps 4+5 block in `maybe_execute` (inside the `try:`) with:

```python
        # ── 4+5. Concurrency checks ──────────────────────────────────
        if not self._validate_concurrency(strategy, today, db):
            return None
```

**Step 3.2 — Extract `_validate_session`.**

Add method to `AutoTradeExecutor` (below `_validate_concurrency`):

```python
def _validate_session(
    self, event: ScannerEvent, strategy: TradingStrategy
) -> bool:
    """Step 6: session eligibility. Returns True to proceed, False to skip."""
    event_session = (event.metadata_ or {}).get("session", "regular")
    allowed = strategy.allowed_sessions or ["regular"]
    if event_session not in allowed:
        logger.info(
            f"AutoTradeExecutor: session '{event_session}' not in "
            f"allowed_sessions={allowed} — skipping"
        )
        return False
    return True
```

Replace the inline step 6 block in `maybe_execute` with:

```python
        # ── 6. Session eligibility ───────────────────────────────────
        if not self._validate_session(event, strategy):
            return None
```

**Step 3.3 — Verify all tests pass.**

```bash
docker-compose exec backend pytest backend/tests/services/test_auto_trade_service.py -v
```

Expected: all tests pass.

**Step 3.4 — Commit.**

```bash
git add backend/app/services/auto_trade_service.py
git commit -m "refactor(#630): extract _validate_concurrency + _validate_session"
```

---

## Task 4: Extract `_size_position` with direct unit tests + finalize `maybe_execute`

**Files:** `backend/app/services/auto_trade_service.py`, `backend/tests/services/test_auto_trade_service.py`

This task also adds `side: str = ""` to `PositionCalc` so steps 11–12 can reference `calc.side` after the extraction.

### TDD Steps

**Step 4.1 — Write failing tests.**

Append at the end of `backend/tests/services/test_auto_trade_service.py`:

```python
# ── Direct tests: _size_position ──────────────────────────────────────────────

def test__size_position_no_trigger_price(db: Session):
    """_size_position returns None when _extract_trigger_price returns None."""
    from unittest.mock import patch

    strategy = _strategy(db)
    event = _event(db)
    executor = AutoTradeExecutor()
    with patch.object(executor, "_extract_trigger_price", return_value=None):
        result = executor._size_position(event, strategy, db)
    assert result is None


def test__size_position_undetermined_side(db: Session):
    """_size_position returns None when _determine_side returns None."""
    # short_only strategy + long-biased scanner → side=None
    strategy = _strategy(db, direction="short_only")
    event = _event(db, scanner_type="pre_market_volume_spike")
    executor = AutoTradeExecutor()
    with patch.object(executor, "_get_account_equity", return_value=100_000.0):
        result = executor._size_position(event, strategy, db)
    assert result is None


def test__size_position_zero_equity(db: Session):
    """_size_position returns None when account equity is 0."""
    strategy = _strategy(db)
    event = _event(db)
    executor = AutoTradeExecutor()
    with patch.object(executor, "_get_account_equity", return_value=0.0):
        result = executor._size_position(event, strategy, db)
    assert result is None


def test__size_position_zero_quantity(db: Session):
    """_size_position returns None when calculated quantity is 0."""
    # trigger_price=100000 + risk_per_trade_pct=0.001% → quantity = floor(1.0/2000) = 0
    strategy = _strategy(db, risk_per_trade_pct=Decimal("0.001"))
    event = _event(db, indicators={"last_trade_price": 100000.0})
    executor = AutoTradeExecutor()
    with patch.object(executor, "_get_account_equity", return_value=100_000.0):
        result = executor._size_position(event, strategy, db)
    assert result is None
```

**Step 4.2 — Verify tests fail.**

```bash
docker-compose exec backend pytest backend/tests/services/test_auto_trade_service.py::test__size_position_no_trigger_price backend/tests/services/test_auto_trade_service.py::test__size_position_undetermined_side backend/tests/services/test_auto_trade_service.py::test__size_position_zero_equity backend/tests/services/test_auto_trade_service.py::test__size_position_zero_quantity -v
```

Expected: `AttributeError: 'AutoTradeExecutor' object has no attribute '_size_position'`

**Step 4.3 — Add `side` field to `PositionCalc`.**

Update the `PositionCalc` dataclass definition (around line 56):

```python
@dataclass
class PositionCalc:
    quantity: int
    entry: float  # adjusted limit price, or None for market
    stop: float
    target: float
    risk_amount_usd: float
    stop_distance: float  # $ per share from entry to stop
    side: str = ""  # "long" or "short"; populated by _size_position
```

The `side` default of `""` preserves backward compatibility with `submit_existing_order`, which constructs `PositionCalc` from an existing order without needing to pass `side` (it uses `order.side` directly when calling `_submit_to_ibkr`).

**Step 4.4 — Extract `_size_position`.**

Add method to `AutoTradeExecutor` (below `_validate_session`):

```python
def _size_position(
    self,
    event: ScannerEvent,
    strategy: TradingStrategy,
    db: Session,
) -> Optional[PositionCalc]:
    """Steps 7–10: trigger price, side, equity, position calc. Returns None on any early-exit."""
    trigger_price = self._extract_trigger_price(event)
    if not trigger_price or trigger_price <= 0:
        logger.warning(
            f"AutoTradeExecutor: could not extract trigger price from "
            f"event {event.id} {event.ticker} — skipping"
        )
        return None

    side = self._determine_side(event, strategy)
    if not side:
        logger.info(
            f"AutoTradeExecutor: direction constraint blocks trade "
            f"for {event.ticker} — skipping"
        )
        return None

    account_equity = self._get_account_equity(strategy, db)
    if account_equity <= 0:
        logger.warning(
            "AutoTradeExecutor: could not determine account equity — skipping"
        )
        return None

    calc = self._calculate_position(strategy, trigger_price, side, account_equity)
    if calc.quantity <= 0:
        logger.info(
            f"AutoTradeExecutor: calculated quantity=0 for "
            f"{event.ticker} — risk too small or price too high, skipping"
        )
        return None

    calc.side = side
    return calc
```

**Step 4.5 — Replace steps 7–10 in `maybe_execute` and reference `calc.side` in step 11.**

Replace the inline steps 7–10 block (the trigger_price / side / account_equity / calc block) with:

```python
        # ── 7–10. Position sizing ────────────────────────────────────
        calc = self._size_position(event, strategy, db)
        if calc is None:
            return None

        # ── 11. Create AutoTradeOrder ────────────────────────────────
        initial_status = (
            "pending_approval" if strategy.requires_approval else "pending"
        )
        order = AutoTradeOrder(
            alert_rule_id=rule.id,
            scanner_event_id=event.id,
            trading_strategy_id=strategy.id,
            symbol=event.ticker,
            side=calc.side,
            event_date=today,
            status=initial_status,
            trigger_price=Decimal(str(round(trigger_price, 4))),
            ...
```

Wait — `trigger_price` is no longer a local variable after extraction. Replace with `calc.entry or ...` or store it.

**Correction:** After `_size_position` returns `calc`, the `trigger_price` used in step 11 for `AutoTradeOrder.trigger_price` is not directly on `PositionCalc`. We have two options:

Option A — read `trigger_price` from the event attributes the same way `_extract_trigger_price` does:

Option B — extract `trigger_price` before calling `_size_position`, keeping it as a local variable:

The cleanest approach (Option B) is to call `_extract_trigger_price` once at the top of the `try` block as a local:

```python
        # ── 7–10. Position sizing ────────────────────────────────────
        # _size_position calls _extract_trigger_price internally; a second call
        # here is cheap (pure dict lookup) and keeps step 11's trigger_price reference clean.
        trigger_price = self._extract_trigger_price(event) or 0.0
        calc = self._size_position(event, strategy, db)
        if calc is None:
            return None
```

Alternatively, add `trigger_price: float = 0.0` to `PositionCalc` so `_size_position` can surface it. But that expands the dataclass further.

**Preferred (minimal change):** Call `_extract_trigger_price` once before `_size_position` and store in a local. `_size_position` calls it a second time internally (O(1) dict lookup — negligible). This keeps `maybe_execute` readable and avoids expanding `PositionCalc` with `trigger_price`.

The final `maybe_execute` after all four tasks:

```python
def maybe_execute(
    self,
    rule: AlertRule,
    event: ScannerEvent,
    db: Session,
) -> Optional[AutoTradeOrder]:
    """
    Entry point called from evaluate_scanner_alerts Celery task.

    Returns the AutoTradeOrder that was created (any status), or None if
    execution was skipped for any reason.
    """
    # ── 1 + 1b + 1c. Basic guards, strategy load, kill-switch ───────
    strategy = self._validate_basics(rule, db)
    if strategy is None:
        return None

    # ── 2. Idempotency ───────────────────────────────────────────────
    today = datetime.now(timezone.utc).date()
    if not self._check_idempotency(event, strategy, today, db):
        return None

    # ── 2.5. Data quality gate ───────────────────────────────────────
    if not self._validate_quality_gate(event, rule, db):
        return None

    # ── 3. Redis distributed lock ────────────────────────────────────
    redis_client = redis.from_url(settings.REDIS_URL, decode_responses=True)
    lock_key = f"auto_trade_lock:{event.ticker}:{strategy.id}:{today}"
    acquired = redis_client.set(lock_key, "1", nx=True, ex=30)
    if not acquired:
        logger.debug(f"AutoTradeExecutor: lock contention on {lock_key} — skipping")
        return None

    try:
        # ── 4+5. Concurrency checks ──────────────────────────────────
        if not self._validate_concurrency(strategy, today, db):
            return None

        # ── 6. Session eligibility ───────────────────────────────────
        if not self._validate_session(event, strategy):
            return None

        # ── 7–10. Position sizing ────────────────────────────────────
        trigger_price = self._extract_trigger_price(event) or 0.0
        calc = self._size_position(event, strategy, db)
        if calc is None:
            return None

        # ── 11. Create AutoTradeOrder ────────────────────────────────
        initial_status = (
            "pending_approval" if strategy.requires_approval else "pending"
        )
        order = AutoTradeOrder(
            alert_rule_id=rule.id,
            scanner_event_id=event.id,
            trading_strategy_id=strategy.id,
            symbol=event.ticker,
            side=calc.side,
            event_date=today,
            status=initial_status,
            trigger_price=Decimal(str(round(trigger_price, 4))),
            entry_price_target=Decimal(str(round(calc.entry, 4)))
            if calc.entry
            else None,
            calculated_stop=Decimal(str(round(calc.stop, 4))),
            calculated_target=Decimal(str(round(calc.target, 4))),
            quantity=calc.quantity,
            risk_amount_usd=Decimal(str(round(calc.risk_amount_usd, 2))),
            is_paper=strategy.paper_mode,
        )
        db.add(order)
        db.commit()
        db.refresh(order)

        logger.info(
            f"AutoTradeExecutor: order created id={order.id} "
            f"{calc.side.upper()} {calc.quantity}x {event.ticker} "
            f"entry~{trigger_price:.2f} stop={calc.stop:.2f} target={calc.target:.2f} "
            f"risk=${calc.risk_amount_usd:.0f} status={initial_status} "
            f"paper={strategy.paper_mode}"
        )

        # ── 12. Submit or park ───────────────────────────────────────
        if strategy.requires_approval:
            return order

        if strategy.paper_mode:
            order.status = "submitted"
            order.broker_order_id = f"PAPER-{order.id}"
            order.broker_stop_id = f"PAPER-STOP-{order.id}"
            order.broker_target_id = f"PAPER-TGT-{order.id}"
            db.commit()
            logger.info(
                f"AutoTradeExecutor: paper order submitted id={order.id} "
                f"(no real IBKR call)"
            )
            return order

        # Live order — submit bracket to IBKR
        self._submit_to_ibkr(order, calc, db)
        return order

    except Exception as exc:
        logger.exception(
            f"AutoTradeExecutor: unexpected error for rule={rule.id} "
            f"event={event.id} ticker={event.ticker}: {exc}"
        )
        return None
    finally:
        redis_client.delete(lock_key)
```

**Step 4.6 — Verify new `_size_position` tests pass.**

```bash
docker-compose exec backend pytest backend/tests/services/test_auto_trade_service.py::test__size_position_no_trigger_price backend/tests/services/test_auto_trade_service.py::test__size_position_undetermined_side backend/tests/services/test_auto_trade_service.py::test__size_position_zero_equity backend/tests/services/test_auto_trade_service.py::test__size_position_zero_quantity -v
```

Expected: all 4 PASSED.

**Step 4.7 — Verify full test suite.**

```bash
docker-compose exec backend pytest backend/tests/services/test_auto_trade_service.py -v
```

Expected: all tests pass (including all pre-existing `test_maybe_execute_*`, `test_quality_gate_*`, `test_calculate_position_*`, `test_determine_side_*`).

**Step 4.8 — Regression sweep.**

```bash
docker-compose exec backend pytest backend/tests/ -v --tb=short
```

Expected: no regressions in sibling test suites.

**Step 4.9 — TypeScript guard (no frontend changes, but required per CLAUDE.md).**

```bash
docker-compose exec frontend npx tsc --noEmit
```

Expected: 0 errors.

**Step 4.10 — Backend reload confirmation.**

```bash
docker-compose logs backend --tail=10
```

Expected: no startup errors; most recent reload line shows the service up.

**Step 4.11 — Commit.**

```bash
git add backend/app/services/auto_trade_service.py backend/tests/services/test_auto_trade_service.py
git commit -m "refactor(#630): extract _size_position + finalize maybe_execute skeleton"
```

---

## Validation Checklist

- [ ] `pytest backend/tests/services/test_auto_trade_service.py` — all existing tests pass unmodified
- [ ] `pytest backend/tests/` — no regression in sibling tests
- [ ] 6 new tests pass: `test__validate_basics_killswitch`, `test__validate_basics_no_max_position_usd`, `test__size_position_*` (4)
- [ ] `npx tsc --noEmit` — 0 TypeScript errors
- [ ] Backend logs show clean reload
- [ ] `maybe_execute` body is ≤ 50 lines; each extracted method is ≤ 30 lines

## Task Summary

| # | Task | New Tests | Key Change |
|---|---|---|---|
| 1 | Extract `_validate_basics` | 2 | Steps 1+1b+1c → private method |
| 2 | Extract `_check_idempotency` + `_validate_quality_gate` | 0 | Steps 2+2.5 → private methods |
| 3 | Extract `_validate_concurrency` + `_validate_session` | 0 | Steps 4+5+6 → private methods |
| 4 | Extract `_size_position` + finalize wiring | 4 | Steps 7–10 → private method; `side` field on `PositionCalc`; final `maybe_execute` skeleton |
