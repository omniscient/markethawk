# Liquidity Hunt Scanner — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the broken `liquidity_hunt` scanner with one that correctly identifies off-hours volume anomalies (≥10% UP spike, ≥4× historical off-hours vol, ≥30% of average daily vol) followed by a quiet regular session, emitting two distinct event types: `liquidity_hunt_pre` and `liquidity_hunt_post`.

**Architecture:** New module `backend/app/services/liquidity_hunt.py` houses all logic; pure-Python criteria evaluation is separated from DB queries for testability. The existing `ScannerService._save_event` helper is reused for persistence. Old broken methods are deleted from `scanner.py`; call sites are updated to import directly from the new module.

**Tech Stack:** Python 3.11, SQLAlchemy 2.0 (sync ORM), PostgreSQL, Celery + Redis beat scheduler. Tests use `unittest.mock.MagicMock` for DB sessions, matching the existing test pattern in `backend/tests/services/test_scanner_refactor.py`.

---

## File Map

| Action | Path | Responsibility |
|---|---|---|
| **Create** | `backend/app/services/liquidity_hunt.py` | All scanner logic: defaults, criteria eval, DB helpers, scan loop |
| **Create** | `backend/tests/services/test_liquidity_hunt.py` | All unit tests for the scanner |
| **Modify** | `backend/app/services/scanner.py:248-436` | Delete `run_liquidity_hunt_scan` and `run_liquidity_hunt_scan_for_date` |
| **Modify** | `backend/app/services/event_helpers.py` | Add summary and severity handlers for `liquidity_hunt_pre` / `liquidity_hunt_post` |
| **Modify** | `backend/app/routers/scanner.py:77-78` | Import + call new module instead of `ScannerService` |
| **Modify** | `backend/app/services/__init__.py` | Remove `ScannerService` re-export if scanner.py no longer has the methods (or leave as-is — scanner.py still has other methods) |
| **Modify** | `backend/app/tasks.py:1179,1219-1223` | Update import, update `scanner_map`, add `run_liquidity_hunt_scheduled` task |
| **Modify** | `backend/app/core/celery_app.py` | Add `run-liquidity-hunt-scan-evening` beat schedule at 02:00 UTC Mon–Fri |
| **Create** | `backend/app/alembic/versions/<hash>_seed_liquidity_hunt_config.py` | Idempotent seed of default `ScannerConfig` row |

---

## Task 1: Scaffold test file and implement `DEFAULT_CONFIG` + `_evaluate_criteria`

**Files:**
- Create: `backend/app/services/liquidity_hunt.py`
- Create: `backend/tests/services/test_liquidity_hunt.py`

- [ ] **Step 1: Create the test file with fixtures and first five tests**

Create `backend/tests/services/test_liquidity_hunt.py`:

```python
"""Unit tests for the liquidity_hunt scanner."""
import pytest
from app.services.liquidity_hunt import _evaluate_criteria, DEFAULT_CONFIG

# Baseline fixture representing a ticker with 20 days of history
BASELINES = {
    "avg_pre_vol_20d": 35_000,
    "avg_post_vol_20d": 30_000,
    "avg_regular_vol_20d": 950_000,
    "avg_total_daily_vol_20d": 1_000_000,
    "avg_regular_range_pct_20d": 0.020,   # 2% average daily range
    "days_available": 20,
}

# Kwargs for a clean "pre" fire — all six criteria satisfied
CLEAN_PRE = dict(
    session="pre",
    session_vol=350_000,    # c1: 350k/35k=10x ≥ 4 ✓  c2: 350k/1M=35% ≥ 30% ✓  c6: >50k ✓
    session_high=12.11,     # c3: (12.11-11.00)/11.00 = 10.09% ≥ 10% ✓
    reference_close=11.00,
    regular_vol=900_000,    # c4: 900k/950k = 0.947 ≤ 1.2 ✓
    regular_high=11.20,
    regular_low=10.90,
    regular_open=11.05,     # c5: (11.20-10.90)/11.05=2.71% → ratio 1.36 ≤ 1.5 ✓
    baselines=BASELINES,
    config=None,
)


def test_pre_variant_fires():
    fires, indicators, criteria = _evaluate_criteria(**CLEAN_PRE)
    assert fires is True
    assert indicators["session"] == "pre"
    assert all(criteria.values()), f"All criteria should be True, got {criteria}"


def test_c2_materiality_fails_when_vol_too_small():
    """200k/1M = 20% < 30% — materiality criterion fails."""
    fires, _, criteria = _evaluate_criteria(
        **{**CLEAN_PRE, "session_vol": 200_000}
    )
    assert fires is False
    assert criteria["volume_materiality"] is False


def test_c3_spike_fails_when_less_than_10_pct():
    """6% spike — does not meet the 10% threshold."""
    fires, _, criteria = _evaluate_criteria(
        **{**CLEAN_PRE, "session_high": 11.66}   # (11.66-11.00)/11.00 = 6%
    )
    assert fires is False
    assert criteria["session_spike"] is False


def test_c4_fails_when_regular_vol_exceeds_threshold():
    """2× regular vol — day was not quiet."""
    fires, _, criteria = _evaluate_criteria(
        **{**CLEAN_PRE, "regular_vol": 2_000_000}  # 2M/950k = 2.1 > 1.2
    )
    assert fires is False
    assert criteria["quiet_regular_vol"] is False


def test_c6_fails_when_below_absolute_floor():
    """40k shares < 50k floor."""
    fires, _, criteria = _evaluate_criteria(
        **{**CLEAN_PRE, "session_vol": 40_000}
    )
    assert fires is False
    assert criteria["volume_floor"] is False
```

- [ ] **Step 2: Run the tests — confirm they all fail with ImportError**

```bash
cd backend && python -m pytest tests/services/test_liquidity_hunt.py -v 2>&1 | head -20
```

Expected: `ModuleNotFoundError: No module named 'app.services.liquidity_hunt'`

- [ ] **Step 3: Create `backend/app/services/liquidity_hunt.py` with `DEFAULT_CONFIG` and `_evaluate_criteria`**

```python
"""
Liquidity Hunt Scanner

Detects off-hours (pre-market or after-market) volume anomalies where:
- Session volume is unusually large relative to the ticker's own history
- Session price spiked ≥10% UP from reference close
- The regular trading session that same day was quiet (normal volume + range)

Two event types are emitted: liquidity_hunt_pre and liquidity_hunt_post.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session
from sqlalchemy import desc

from app.models.stock_aggregate import StockAggregate
from app.models.monitored_stock import MonitoredStock
from app.models.ticker_reference import TickerReference
from app.models.stock_split import StockSplit
from app.services.catalyst_parser import CatalystParser
from app.services.scanner import ScannerService

_ET = ZoneInfo("America/New_York")
_LOG = logging.getLogger(__name__)

DEFAULT_CONFIG: dict[str, float] = {
    "volume_ratio_min": 4.0,           # criterion 1: session vol / 20d avg session vol
    "volume_pct_of_daily_min": 0.30,   # criterion 2: session vol / 20d avg total daily vol
    "spike_pct_min": 0.10,             # criterion 3: (session_high / reference_close) - 1
    "regular_vol_ratio_max": 1.20,     # criterion 4: regular vol / 20d avg regular vol
    "regular_range_ratio_max": 1.50,   # criterion 5: today range% / 20d avg range%
    "session_volume_floor": 50_000,    # criterion 6: absolute minimum shares
}


def _evaluate_criteria(
    session: str,
    session_vol: float,
    session_high: float,
    reference_close: float,
    regular_vol: float,
    regular_high: float,
    regular_low: float,
    regular_open: float,
    baselines: dict[str, Any],
    config: dict[str, Any] | None,
) -> tuple[bool, dict[str, Any], dict[str, bool]]:
    """
    Evaluate all six liquidity-hunt criteria against session metrics.

    Returns (fires, indicators_dict, criteria_met_dict).
    Does not access the database — all inputs are plain Python values.

    session: "pre" or "post" — determines which baseline vol to use.
    reference_close: prior_day_close for "pre"; event_date_regular_close for "post".
    """
    cfg = {**DEFAULT_CONFIG, **(config or {})}

    avg_session_vol = (
        baselines["avg_pre_vol_20d"] if session == "pre" else baselines["avg_post_vol_20d"]
    )
    avg_regular_vol = baselines["avg_regular_vol_20d"]
    avg_total_daily_vol = baselines["avg_total_daily_vol_20d"]
    avg_range_pct = baselines["avg_regular_range_pct_20d"]

    # Criterion 1: volume ratio (trivially satisfied when baseline is zero)
    if avg_session_vol > 0:
        vol_ratio = session_vol / avg_session_vol
        c1 = vol_ratio >= cfg["volume_ratio_min"]
    else:
        vol_ratio = None  # infinite — baseline was zero
        c1 = True

    # Criterion 2: materiality
    vol_pct_of_daily = (
        session_vol / avg_total_daily_vol if avg_total_daily_vol > 0 else 0.0
    )
    c2 = vol_pct_of_daily >= cfg["volume_pct_of_daily_min"]

    # Criterion 3: UP spike
    spike_pct = (
        (session_high - reference_close) / reference_close
        if reference_close > 0 else 0.0
    )
    c3 = spike_pct >= cfg["spike_pct_min"]

    # Criterion 4: quiet regular volume
    regular_vol_ratio = (
        regular_vol / avg_regular_vol if avg_regular_vol > 0 else float("inf")
    )
    c4 = regular_vol_ratio <= cfg["regular_vol_ratio_max"]

    # Criterion 5: quiet regular range
    regular_range_pct = (
        (regular_high - regular_low) / regular_open if regular_open > 0 else 0.0
    )
    regular_range_ratio = (
        regular_range_pct / avg_range_pct if avg_range_pct > 0 else float("inf")
    )
    c5 = regular_range_ratio <= cfg["regular_range_ratio_max"]

    # Criterion 6: absolute floor
    c6 = session_vol >= cfg["session_volume_floor"]

    fires = c1 and c2 and c3 and c4 and c5 and c6

    indicators: dict[str, Any] = {
        "session": session,
        "session_volume": int(session_vol),
        "avg_session_volume_20d": int(avg_session_vol) if avg_session_vol else 0,
        "session_volume_ratio": round(vol_ratio, 2) if vol_ratio is not None else None,
        "session_volume_pct_of_daily": round(vol_pct_of_daily, 4),
        "session_high": float(session_high),
        "reference_close": float(reference_close),
        "session_spike_pct": round(spike_pct, 4),
        "regular_volume": int(regular_vol),
        "avg_regular_volume_20d": int(avg_regular_vol),
        "regular_volume_ratio": round(regular_vol_ratio, 4),
        "regular_range_pct": round(regular_range_pct, 4),
        "avg_regular_range_pct_20d": round(avg_range_pct, 4),
        "regular_range_ratio": round(regular_range_ratio, 4),
    }

    criteria_met: dict[str, bool] = {
        "volume_ratio": c1,
        "volume_materiality": c2,
        "session_spike": c3,
        "quiet_regular_vol": c4,
        "quiet_regular_range": c5,
        "volume_floor": c6,
    }

    return fires, indicators, criteria_met
```

- [ ] **Step 4: Run the five tests — confirm they all pass**

```bash
cd backend && python -m pytest tests/services/test_liquidity_hunt.py -v 2>&1 | tail -15
```

Expected: `5 passed`

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/liquidity_hunt.py backend/tests/services/test_liquidity_hunt.py
git commit -m "feat(scanner): scaffold liquidity_hunt module with _evaluate_criteria and initial tests"
```

---

## Task 2: Remaining `_evaluate_criteria` tests

**Files:**
- Modify: `backend/tests/services/test_liquidity_hunt.py`

- [ ] **Step 1: Add four more tests to the test file**

Append to `backend/tests/services/test_liquidity_hunt.py`:

```python
def test_c5_fails_when_range_too_wide():
    """Intraday range 3x wider than average — day was volatile."""
    fires, _, criteria = _evaluate_criteria(
        **{**CLEAN_PRE, "regular_high": 13.50, "regular_low": 8.50}
        # range = (13.50-8.50)/11.05 = 45.2% → ratio = 45.2%/2% = 22.6 > 1.5
    )
    assert fires is False
    assert criteria["quiet_regular_range"] is False


def test_zero_session_baseline_fires_when_floor_and_materiality_pass():
    """avg_pre_vol_20d=0: ratio criterion is trivially satisfied; other checks carry the load."""
    zero_baselines = {
        **BASELINES,
        "avg_pre_vol_20d": 0,
        "avg_total_daily_vol_20d": 200_000,   # 75k/200k = 37.5% ≥ 30%
        "avg_regular_vol_20d": 190_000,
    }
    fires, indicators, criteria = _evaluate_criteria(
        session="pre",
        session_vol=75_000,       # > 50k floor ✓  and 37.5% of daily ✓
        session_high=12.11,
        reference_close=11.00,
        regular_vol=180_000,      # 180k/190k = 0.95 ≤ 1.2 ✓
        regular_high=11.20,
        regular_low=10.90,
        regular_open=11.05,
        baselines=zero_baselines,
        config=None,
    )
    assert fires is True
    assert criteria["volume_ratio"] is True   # trivially satisfied
    assert indicators["session_volume_ratio"] is None  # signals "infinite"


def test_post_variant_fires():
    """After-market variant uses avg_post_vol_20d and session='post'."""
    fires, indicators, criteria = _evaluate_criteria(
        session="post",
        session_vol=350_000,      # 350k/30k = 11.7x ≥ 4 ✓  350k/1M = 35% ≥ 30% ✓
        session_high=12.11,
        reference_close=11.00,   # today's regular close for post variant
        regular_vol=900_000,
        regular_high=11.20,
        regular_low=10.90,
        regular_open=11.05,
        baselines=BASELINES,
        config=None,
    )
    assert fires is True
    assert indicators["session"] == "post"
    assert all(criteria.values())


def test_c1_fails_for_post_when_after_market_vol_too_low():
    """Post variant: 60k / 30k = 2x < 4x threshold."""
    fires, _, criteria = _evaluate_criteria(
        session="post",
        session_vol=60_000,       # 60k/30k = 2x < 4 ✗  (also: 60k/1M = 6% < 30%)
        session_high=12.11,
        reference_close=11.00,
        regular_vol=900_000,
        regular_high=11.20,
        regular_low=10.90,
        regular_open=11.05,
        baselines=BASELINES,
        config=None,
    )
    assert fires is False
    assert criteria["volume_ratio"] is False
```

- [ ] **Step 2: Run all nine criteria tests**

```bash
cd backend && python -m pytest tests/services/test_liquidity_hunt.py -v 2>&1 | tail -20
```

Expected: `9 passed`

- [ ] **Step 3: Commit**

```bash
git add backend/tests/services/test_liquidity_hunt.py
git commit -m "test(scanner): complete _evaluate_criteria test suite (9 cases)"
```

---

## Task 3: Implement DB helpers — session metrics and reference closes

**Files:**
- Modify: `backend/app/services/liquidity_hunt.py`
- Modify: `backend/tests/services/test_liquidity_hunt.py`

- [ ] **Step 1: Add tests for `_get_session_metrics`, `_get_prior_day_close`, `_get_event_date_regular_close`**

Append to `backend/tests/services/test_liquidity_hunt.py`:

```python
# ─── DB helper tests ───────────────────────────────────────────────────────

from datetime import date as _date, datetime as _datetime, timezone as _tz
from unittest.mock import MagicMock
from app.models.stock_aggregate import StockAggregate
from datetime import timedelta
from app.services.liquidity_hunt import (
    _get_session_metrics,
    _get_prior_day_close,
    _get_event_date_regular_close,
)


def _make_minute_bar(ticker, ts_utc, open_, high, low, close, volume,
                     is_pre=False, is_after=False):
    b = StockAggregate()
    b.ticker = ticker
    b.timestamp = ts_utc
    b.timespan = "minute"
    b.multiplier = 1
    b.open, b.high, b.low, b.close = open_, high, low, close
    b.volume = volume
    b.is_pre_market = is_pre
    b.is_after_market = is_after
    return b


def _make_day_bar(ticker, ts_utc, close, volume):
    b = StockAggregate()
    b.ticker = ticker
    b.timestamp = ts_utc
    b.timespan = "day"
    b.multiplier = 1
    b.open = b.high = b.low = b.close = close
    b.volume = volume
    b.is_pre_market = False
    b.is_after_market = False
    return b


def _make_db_returning(rows):
    """Return a mock Session whose .query().filter().order_by().all() returns rows."""
    db = MagicMock()
    mock_q = MagicMock()
    mock_q.filter.return_value = mock_q
    mock_q.order_by.return_value = mock_q
    mock_q.limit.return_value = mock_q
    mock_q.all.return_value = rows
    mock_q.first.return_value = rows[0] if rows else None
    db.query.return_value = mock_q
    return db


EVENT_DATE = _date(2025, 6, 10)
# 2025-06-10 09:00 ET = 13:00 UTC
_PRE_TS = _datetime(2025, 6, 10, 8, 0, tzinfo=_tz.utc).replace(tzinfo=None)    # 4 AM ET
_REG_TS = _datetime(2025, 6, 10, 14, 0, tzinfo=_tz.utc).replace(tzinfo=None)   # 10 AM ET
_POST_TS = _datetime(2025, 6, 10, 21, 0, tzinfo=_tz.utc).replace(tzinfo=None)  # 5 PM ET


def test_get_session_metrics_returns_correct_buckets():
    pre_bar = _make_minute_bar("TEST", _PRE_TS, 10.0, 12.0, 9.9, 11.8, 200_000, is_pre=True)
    reg_bar = _make_minute_bar("TEST", _REG_TS, 11.8, 12.1, 11.5, 11.9, 900_000)
    post_bar = _make_minute_bar("TEST", _POST_TS, 11.9, 13.0, 11.8, 12.5, 150_000, is_after=True)

    db = _make_db_returning([pre_bar, reg_bar, post_bar])
    metrics = _get_session_metrics(db, "TEST", EVENT_DATE)

    assert metrics is not None
    assert metrics["pre_vol"] == 200_000
    assert metrics["pre_high"] == 12.0
    assert metrics["regular_vol"] == 900_000
    assert metrics["regular_high"] == 12.1
    assert metrics["regular_low"] == 11.5
    assert metrics["regular_open"] == 11.8
    assert metrics["regular_close"] == 11.9
    assert metrics["post_vol"] == 150_000
    assert metrics["post_high"] == 13.0


def test_get_session_metrics_returns_none_when_no_regular_bars():
    pre_bar = _make_minute_bar("TEST", _PRE_TS, 10.0, 12.0, 9.9, 11.8, 200_000, is_pre=True)
    db = _make_db_returning([pre_bar])
    assert _get_session_metrics(db, "TEST", EVENT_DATE) is None


def test_get_prior_day_close_uses_daily_bar():
    prev_day_ts = _datetime(2025, 6, 9, 20, 0, tzinfo=_tz.utc).replace(tzinfo=None)
    day_bar = _make_day_bar("TEST", prev_day_ts, close=10.50, volume=1_000_000)
    # first() on the query returns a row-like; _get_prior_day_close does .first() on a (close,) scalar
    # We need to mock the scalar query returning (close_value,)
    db = MagicMock()
    mock_q = MagicMock()
    mock_q.filter.return_value = mock_q
    mock_q.order_by.return_value = mock_q
    mock_q.limit.return_value = mock_q
    mock_q.first.return_value = (10.50,)
    db.query.return_value = mock_q

    result = _get_prior_day_close(db, "TEST", EVENT_DATE)
    assert result == 10.50


def test_get_prior_day_close_returns_none_when_no_history():
    db = MagicMock()
    mock_q = MagicMock()
    mock_q.filter.return_value = mock_q
    mock_q.order_by.return_value = mock_q
    mock_q.limit.return_value = mock_q
    mock_q.first.return_value = None
    db.query.return_value = mock_q

    assert _get_prior_day_close(db, "TEST", EVENT_DATE) is None


def test_get_event_date_regular_close():
    db = MagicMock()
    mock_q = MagicMock()
    mock_q.filter.return_value = mock_q
    mock_q.order_by.return_value = mock_q
    mock_q.limit.return_value = mock_q
    mock_q.first.return_value = (11.90,)
    db.query.return_value = mock_q

    result = _get_event_date_regular_close(db, "TEST", EVENT_DATE)
    assert result == 11.90
```

- [ ] **Step 2: Run the new tests — confirm they fail**

```bash
cd backend && python -m pytest tests/services/test_liquidity_hunt.py -k "session_metrics or prior_day or event_date_regular" -v 2>&1 | tail -20
```

Expected: `ImportError` or `AttributeError` for the missing functions.

- [ ] **Step 3: Add the three DB helpers to `liquidity_hunt.py`**

Add after the `_evaluate_criteria` function:

```python
def _get_session_metrics(
    db: Session, ticker: str, event_date: date
) -> dict[str, Any] | None:
    """
    Query all minute bars for event_date. Return per-session aggregates.
    Returns None if no regular-session bars exist (e.g. market holiday).
    """
    day_start_utc = (
        datetime.combine(event_date, time.min, tzinfo=_ET)
        .astimezone(timezone.utc)
        .replace(tzinfo=None)
    )
    day_end_utc = (
        datetime.combine(event_date, time.max, tzinfo=_ET)
        .astimezone(timezone.utc)
        .replace(tzinfo=None)
    )

    rows = (
        db.query(StockAggregate)
        .filter(
            StockAggregate.ticker == ticker,
            StockAggregate.timespan == "minute",
            StockAggregate.timestamp >= day_start_utc,
            StockAggregate.timestamp <= day_end_utc,
        )
        .order_by(StockAggregate.timestamp)
        .all()
    )

    pre = [r for r in rows if r.is_pre_market]
    regular = [r for r in rows if not r.is_pre_market and not r.is_after_market]
    post = [r for r in rows if r.is_after_market]

    if not regular:
        return None

    return {
        "pre_vol": float(sum(r.volume for r in pre)),
        "pre_high": float(max((r.high for r in pre), default=0)),
        "regular_vol": float(sum(r.volume for r in regular)),
        "regular_high": float(max(r.high for r in regular)),
        "regular_low": float(min(r.low for r in regular)),
        "regular_open": float(regular[0].open),
        "regular_close": float(regular[-1].close),
        "post_vol": float(sum(r.volume for r in post)),
        "post_high": float(max((r.high for r in post), default=0)),
    }


def _get_prior_day_close(db: Session, ticker: str, event_date: date) -> float | None:
    """
    Return the regular close of the most recent trading day before event_date.
    Tries timespan='day' bars first; falls back to the last regular minute bar.
    """
    day_start_utc = (
        datetime.combine(event_date, time.min, tzinfo=_ET)
        .astimezone(timezone.utc)
        .replace(tzinfo=None)
    )

    row = (
        db.query(StockAggregate.close)
        .filter(
            StockAggregate.ticker == ticker,
            StockAggregate.timespan == "day",
            StockAggregate.timestamp < day_start_utc,
        )
        .order_by(desc(StockAggregate.timestamp))
        .limit(1)
        .first()
    )
    if row:
        return float(row[0])

    row = (
        db.query(StockAggregate.close)
        .filter(
            StockAggregate.ticker == ticker,
            StockAggregate.timespan == "minute",
            StockAggregate.is_pre_market.is_(False),
            StockAggregate.is_after_market.is_(False),
            StockAggregate.timestamp < day_start_utc,
        )
        .order_by(desc(StockAggregate.timestamp))
        .limit(1)
        .first()
    )
    return float(row[0]) if row else None


def _get_event_date_regular_close(
    db: Session, ticker: str, event_date: date
) -> float | None:
    """
    Return the last regular-session minute close on event_date itself.
    Used as the reference close for the post-market variant.
    """
    day_start_utc = (
        datetime.combine(event_date, time.min, tzinfo=_ET)
        .astimezone(timezone.utc)
        .replace(tzinfo=None)
    )
    reg_end_utc = (
        datetime.combine(event_date, time(16, 0), tzinfo=_ET)  # 4:00 PM ET (regular close)
        .astimezone(timezone.utc)
        .replace(tzinfo=None)
    )

    row = (
        db.query(StockAggregate.close)
        .filter(
            StockAggregate.ticker == ticker,
            StockAggregate.timespan == "minute",
            StockAggregate.is_pre_market.is_(False),
            StockAggregate.is_after_market.is_(False),
            StockAggregate.timestamp >= day_start_utc,
            StockAggregate.timestamp < reg_end_utc,
        )
        .order_by(desc(StockAggregate.timestamp))
        .limit(1)
        .first()
    )
    return float(row[0]) if row else None
```

- [ ] **Step 4: Run the DB helper tests — confirm they pass**

```bash
cd backend && python -m pytest tests/services/test_liquidity_hunt.py -k "session_metrics or prior_day or event_date_regular" -v 2>&1 | tail -20
```

Expected: `5 passed`

- [ ] **Step 5: Run the full test file to make sure nothing broke**

```bash
cd backend && python -m pytest tests/services/test_liquidity_hunt.py -v 2>&1 | tail -15
```

Expected: `14 passed`

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/liquidity_hunt.py backend/tests/services/test_liquidity_hunt.py
git commit -m "feat(scanner): add session-metrics and reference-close DB helpers"
```

---

## Task 4: Implement `_get_rolling_baselines`

**Files:**
- Modify: `backend/app/services/liquidity_hunt.py`
- Modify: `backend/tests/services/test_liquidity_hunt.py`

- [ ] **Step 1: Add tests for `_get_rolling_baselines`**

Append to `backend/tests/services/test_liquidity_hunt.py`:

```python
from app.services.liquidity_hunt import _get_rolling_baselines


def _make_history(ticker, event_date, n_days, pre_vol, regular_vol, post_vol,
                  regular_high_pct=0.01):
    """
    Generate n_days of fake minute-bar history before event_date.
    regular_high_pct: regular high = regular_open * (1 + regular_high_pct).
    Each day gets one pre bar, one regular bar, one post bar at 08:00/14:00/21:00 UTC.
    """
    from zoneinfo import ZoneInfo
    _ET2 = ZoneInfo("America/New_York")
    bars = []
    for i in range(1, n_days + 1):
        d = event_date - timedelta(days=i)
        pre_ts = _datetime.combine(d, _datetime.min.time(), tzinfo=_ET2).replace(
            hour=8).astimezone(_tz.utc).replace(tzinfo=None)
        reg_ts = pre_ts.replace(hour=14)
        post_ts = pre_ts.replace(hour=21)

        bars.append(_make_minute_bar(ticker, pre_ts, 10.0, 10.5, 9.8, 10.3, pre_vol, is_pre=True))
        bars.append(_make_minute_bar(ticker, reg_ts, 10.3, 10.3 * (1 + regular_high_pct),
                                     10.3 * (1 - regular_high_pct), 10.2, regular_vol))
        bars.append(_make_minute_bar(ticker, post_ts, 10.2, 10.4, 10.1, 10.3, post_vol, is_after=True))
    return bars


def test_get_rolling_baselines_returns_correct_averages():
    bars = _make_history("TEST", EVENT_DATE, n_days=20,
                         pre_vol=40_000, regular_vol=800_000, post_vol=25_000)
    db = _make_db_returning(bars)
    result = _get_rolling_baselines(db, "TEST", EVENT_DATE)

    assert result is not None
    assert result["days_available"] == 20
    assert abs(result["avg_pre_vol_20d"] - 40_000) < 100
    assert abs(result["avg_regular_vol_20d"] - 800_000) < 100
    assert abs(result["avg_post_vol_20d"] - 25_000) < 100
    assert result["avg_total_daily_vol_20d"] > 800_000  # pre + regular + post


def test_get_rolling_baselines_returns_none_when_fewer_than_10_days():
    bars = _make_history("TEST", EVENT_DATE, n_days=8,
                         pre_vol=40_000, regular_vol=800_000, post_vol=25_000)
    db = _make_db_returning(bars)
    result = _get_rolling_baselines(db, "TEST", EVENT_DATE)
    assert result is None


def test_get_rolling_baselines_uses_at_most_20_days():
    """Even with 25 days of history, only the most recent 20 are averaged."""
    bars = _make_history("TEST", EVENT_DATE, n_days=25,
                         pre_vol=40_000, regular_vol=800_000, post_vol=25_000)
    db = _make_db_returning(bars)
    result = _get_rolling_baselines(db, "TEST", EVENT_DATE)
    assert result["days_available"] == 20
```

- [ ] **Step 2: Run the new tests — confirm they fail**

```bash
cd backend && python -m pytest tests/services/test_liquidity_hunt.py -k "rolling_baselines" -v 2>&1 | tail -15
```

Expected: `ImportError` for `_get_rolling_baselines`.

- [ ] **Step 3: Add `_get_rolling_baselines` to `liquidity_hunt.py`**

Add after `_get_event_date_regular_close`:

```python
def _get_rolling_baselines(
    db: Session, ticker: str, event_date: date
) -> dict[str, Any] | None:
    """
    Compute 20-day rolling session averages from minute bars prior to event_date.
    Returns None if fewer than 10 trading days of data are available.
    """
    day_start_utc = (
        datetime.combine(event_date, time.min, tzinfo=_ET)
        .astimezone(timezone.utc)
        .replace(tzinfo=None)
    )
    lookback_start_utc = (
        datetime.combine(event_date - timedelta(days=45), time.min, tzinfo=_ET)
        .astimezone(timezone.utc)
        .replace(tzinfo=None)
    )

    rows = (
        db.query(StockAggregate)
        .filter(
            StockAggregate.ticker == ticker,
            StockAggregate.timespan == "minute",
            StockAggregate.timestamp >= lookback_start_utc,
            StockAggregate.timestamp < day_start_utc,
        )
        .order_by(StockAggregate.timestamp)
        .all()
    )

    if not rows:
        return None

    # Group rows by ET calendar date
    daily: dict[date, dict[str, list]] = defaultdict(
        lambda: {"pre": [], "post": [], "regular": []}
    )
    for r in rows:
        ts_et = r.timestamp.replace(tzinfo=timezone.utc).astimezone(_ET)
        d = ts_et.date()
        if r.is_pre_market:
            daily[d]["pre"].append(r)
        elif r.is_after_market:
            daily[d]["post"].append(r)
        else:
            daily[d]["regular"].append(r)

    # Keep only days that have regular-session bars; take the 20 most recent
    trading_days = sorted(
        [d for d, sess in daily.items() if sess["regular"]]
    )[-20:]

    if len(trading_days) < 10:
        return None

    pre_vols, post_vols, regular_vols, total_vols, range_pcts = [], [], [], [], []

    for d in trading_days:
        sess = daily[d]
        pv = float(sum(r.volume for r in sess["pre"]))
        rv = float(sum(r.volume for r in sess["regular"]))
        ov = float(sum(r.volume for r in sess["post"]))
        pre_vols.append(pv)
        post_vols.append(ov)
        regular_vols.append(rv)
        total_vols.append(pv + rv + ov)

        reg = sess["regular"]
        if reg:
            h = float(max(r.high for r in reg))
            l = float(min(r.low for r in reg))
            o = float(reg[0].open)
            if o > 0:
                range_pcts.append((h - l) / o)

    n = len(trading_days)
    return {
        "avg_pre_vol_20d": sum(pre_vols) / n,
        "avg_post_vol_20d": sum(post_vols) / n,
        "avg_regular_vol_20d": sum(regular_vols) / n,
        "avg_total_daily_vol_20d": sum(total_vols) / n,
        "avg_regular_range_pct_20d": sum(range_pcts) / len(range_pcts) if range_pcts else 0.0,
        "days_available": n,
    }
```

- [ ] **Step 4: Run rolling-baselines tests**

```bash
cd backend && python -m pytest tests/services/test_liquidity_hunt.py -k "rolling_baselines" -v 2>&1 | tail -15
```

Expected: `3 passed`

- [ ] **Step 5: Run full test suite**

```bash
cd backend && python -m pytest tests/services/test_liquidity_hunt.py -v 2>&1 | tail -15
```

Expected: `17 passed`

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/liquidity_hunt.py backend/tests/services/test_liquidity_hunt.py
git commit -m "feat(scanner): add _get_rolling_baselines with 20-day session averages"
```

---

## Task 5: Implement the main scan loop

**Files:**
- Modify: `backend/app/services/liquidity_hunt.py`
- Modify: `backend/tests/services/test_liquidity_hunt.py`

- [ ] **Step 1: Add scan-loop integration tests**

Append to `backend/tests/services/test_liquidity_hunt.py`:

```python
import asyncio
from unittest.mock import patch, MagicMock
from app.services.liquidity_hunt import run_liquidity_hunt_scan


# Shared baselines for scan-loop tests
_SCAN_BASELINES = {
    "avg_pre_vol_20d": 35_000,
    "avg_post_vol_20d": 30_000,
    "avg_regular_vol_20d": 950_000,
    "avg_total_daily_vol_20d": 1_000_000,
    "avg_regular_range_pct_20d": 0.020,
    "days_available": 20,
}

# Metrics for a day where both pre and regular are "clean"
_CLEAN_METRICS = {
    "pre_vol": 350_000, "pre_high": 12.11,
    "regular_vol": 900_000, "regular_high": 11.20,
    "regular_low": 10.90, "regular_open": 11.05, "regular_close": 11.10,
    "post_vol": 350_000, "post_high": 12.11,
}


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _mock_enrichment():
    return {
        "market_cap": 500_000_000,
        "outstanding_shares": 50_000_000,
        "recent_split_date": None,
        "catalyst_tags": [],
        "catalyst_summary": None,
    }


def test_scan_fires_liquidity_hunt_pre():
    """Clean pre-market hunt: both pre and post criteria checked; pre fires."""
    db = MagicMock()
    with patch("app.services.liquidity_hunt._get_session_metrics", return_value=_CLEAN_METRICS), \
         patch("app.services.liquidity_hunt._get_prior_day_close", return_value=11.00), \
         patch("app.services.liquidity_hunt._get_event_date_regular_close", return_value=11.10), \
         patch("app.services.liquidity_hunt._get_rolling_baselines", return_value=_SCAN_BASELINES), \
         patch("app.services.liquidity_hunt._get_enrichment", return_value=_mock_enrichment()), \
         patch("app.services.scanner.ScannerService._save_event", return_value={"id": 1}) as mock_save:

        results = _run(run_liquidity_hunt_scan(
            ["TEST"], db, start_date=EVENT_DATE, end_date=EVENT_DATE
        ))

    saved_types = [c.kwargs["scanner_type"] for c in mock_save.call_args_list]
    assert "liquidity_hunt_pre" in saved_types
    assert len(results) >= 1


def test_scan_fires_both_variants():
    """Both pre and post qualify on the same day — two separate events."""
    db = MagicMock()
    with patch("app.services.liquidity_hunt._get_session_metrics", return_value=_CLEAN_METRICS), \
         patch("app.services.liquidity_hunt._get_prior_day_close", return_value=11.00), \
         patch("app.services.liquidity_hunt._get_event_date_regular_close", return_value=11.10), \
         patch("app.services.liquidity_hunt._get_rolling_baselines", return_value=_SCAN_BASELINES), \
         patch("app.services.liquidity_hunt._get_enrichment", return_value=_mock_enrichment()), \
         patch("app.services.scanner.ScannerService._save_event", return_value={"id": 1}) as mock_save:

        _run(run_liquidity_hunt_scan(
            ["TEST"], db, start_date=EVENT_DATE, end_date=EVENT_DATE
        ))

    saved_types = [c.kwargs["scanner_type"] for c in mock_save.call_args_list]
    assert "liquidity_hunt_pre" in saved_types
    assert "liquidity_hunt_post" in saved_types


def test_scan_skips_ticker_when_sparse_history():
    """No events emitted when _get_rolling_baselines returns None."""
    db = MagicMock()
    with patch("app.services.liquidity_hunt._get_session_metrics", return_value=_CLEAN_METRICS), \
         patch("app.services.liquidity_hunt._get_prior_day_close", return_value=11.00), \
         patch("app.services.liquidity_hunt._get_event_date_regular_close", return_value=11.10), \
         patch("app.services.liquidity_hunt._get_rolling_baselines", return_value=None), \
         patch("app.services.liquidity_hunt._get_enrichment", return_value=_mock_enrichment()), \
         patch("app.services.scanner.ScannerService._save_event") as mock_save:

        results = _run(run_liquidity_hunt_scan(
            ["TEST"], db, start_date=EVENT_DATE, end_date=EVENT_DATE
        ))

    mock_save.assert_not_called()
    assert results == []


def test_scan_skips_ticker_when_no_prior_close():
    """No events when prior_day_close is unavailable."""
    db = MagicMock()
    with patch("app.services.liquidity_hunt._get_session_metrics", return_value=_CLEAN_METRICS), \
         patch("app.services.liquidity_hunt._get_prior_day_close", return_value=None), \
         patch("app.services.liquidity_hunt._get_event_date_regular_close", return_value=11.10), \
         patch("app.services.liquidity_hunt._get_rolling_baselines", return_value=_SCAN_BASELINES), \
         patch("app.services.liquidity_hunt._get_enrichment", return_value=_mock_enrichment()), \
         patch("app.services.scanner.ScannerService._save_event") as mock_save:

        results = _run(run_liquidity_hunt_scan(
            ["TEST"], db, start_date=EVENT_DATE, end_date=EVENT_DATE
        ))

    mock_save.assert_not_called()
    assert results == []


def test_split_in_lookback_flag():
    """Recent split within 28 days of event_date sets split_in_lookback=True in indicators."""
    from datetime import timedelta
    split_date = EVENT_DATE - timedelta(days=10)
    enrichment_with_split = {**_mock_enrichment(), "recent_split_date": split_date.isoformat()}
    db = MagicMock()
    with patch("app.services.liquidity_hunt._get_session_metrics", return_value=_CLEAN_METRICS), \
         patch("app.services.liquidity_hunt._get_prior_day_close", return_value=11.00), \
         patch("app.services.liquidity_hunt._get_event_date_regular_close", return_value=11.10), \
         patch("app.services.liquidity_hunt._get_rolling_baselines", return_value=_SCAN_BASELINES), \
         patch("app.services.liquidity_hunt._get_enrichment", return_value=enrichment_with_split), \
         patch("app.services.scanner.ScannerService._save_event", return_value={"id": 1}) as mock_save:

        _run(run_liquidity_hunt_scan(
            ["TEST"], db, start_date=EVENT_DATE, end_date=EVENT_DATE
        ))

    # Check that at least one _save_event call had split_in_lookback=True in indicators
    indicators_list = [c.kwargs["indicators"] for c in mock_save.call_args_list]
    assert any(ind.get("split_in_lookback") is True for ind in indicators_list)
```

- [ ] **Step 2: Run the new tests — confirm they fail**

```bash
cd backend && python -m pytest tests/services/test_liquidity_hunt.py -k "scan_fires or scan_skips or split_in_lookback" -v 2>&1 | tail -20
```

Expected: `ImportError` for `run_liquidity_hunt_scan` and `_get_enrichment`.

- [ ] **Step 3: Add `_get_enrichment`, `run_liquidity_hunt_scan`, and `run_liquidity_hunt_scan_for_date` to `liquidity_hunt.py`**

Add at the bottom of `liquidity_hunt.py`:

```python
def _get_enrichment(
    db: Session, ticker: str, event_date: date
) -> dict[str, Any]:
    """Fetch catalyst, split, market-cap, and float enrichment for one ticker."""
    monitored = db.query(MonitoredStock).filter(MonitoredStock.ticker == ticker).first()
    ref = db.query(TickerReference).filter(TickerReference.ticker == ticker).first()
    six_months_prior = event_date - timedelta(days=180)
    recent_split = (
        db.query(StockSplit)
        .filter(
            StockSplit.ticker == ticker,
            StockSplit.execution_date <= event_date,
            StockSplit.execution_date >= six_months_prior,
        )
        .order_by(desc(StockSplit.execution_date))
        .first()
    )
    cat = CatalystParser.analyze(ticker, event_date, db)
    outstanding = float(ref.share_class_shares_outstanding) if ref and ref.share_class_shares_outstanding else None
    return {
        "market_cap": float(monitored.market_cap) if monitored and monitored.market_cap else None,
        "outstanding_shares": outstanding,
        "recent_split_date": recent_split.execution_date.isoformat() if recent_split else None,
        "catalyst_tags": cat.get("tags", []),
        "catalyst_summary": cat.get("summary"),
    }


def _build_indicators(
    session: str,
    base_indicators: dict[str, Any],
    regular_open: float,
    regular_close: float,
    enrichment: dict[str, Any],
    event_date: date,
    session_vol: float,
) -> dict[str, Any]:
    """Merge base indicators with opening/closing prices, float rotation, and split flag."""
    indicators = {
        **base_indicators,
        "opening_price": regular_open,
        "closing_price": regular_close,
        "split_in_lookback": False,
    }

    # Flag if a stock split occurred within the ~28-calendar-day lookback window
    if enrichment.get("recent_split_date"):
        split_dt = date.fromisoformat(enrichment["recent_split_date"])
        if (event_date - split_dt).days <= 28:
            indicators["split_in_lookback"] = True

    # Float rotation
    if enrichment.get("outstanding_shares") and enrichment["outstanding_shares"] > 0:
        indicators["float_rotation_pct"] = round(
            session_vol / enrichment["outstanding_shares"] * 100, 4
        )

    return indicators


async def run_liquidity_hunt_scan(
    tickers: list[str],
    db: Session,
    start_date: date | None = None,
    end_date: date | None = None,
    config: dict | None = None,
) -> list[dict[str, Any]]:
    """
    Run liquidity_hunt_pre and liquidity_hunt_post scans over a date range.

    For each (ticker, date):
      1. Fetch today's session metrics from minute bars.
      2. Fetch reference closes (prior day + today's regular close).
      3. Compute 20-day rolling baselines.
      4. Evaluate pre-market criteria → save event if fires.
      5. Evaluate post-market criteria → save event if fires.
    """
    from datetime import timedelta

    if start_date is None and end_date is None:
        from app.utils.session import get_market_today
        today = get_market_today()
        start_date = end_date = today
    elif start_date is None:
        start_date = end_date
    elif end_date is None:
        end_date = start_date

    results: list[dict[str, Any]] = []

    trading_days = [
        start_date + timedelta(days=i)
        for i in range((end_date - start_date).days + 1)
        if (start_date + timedelta(days=i)).weekday() < 5
    ]

    for event_date in trading_days:
        for ticker in tickers:
            try:
                # Step 1: today's session metrics
                session_metrics = _get_session_metrics(db, ticker, event_date)
                if session_metrics is None:
                    continue

                # Step 2: reference closes
                prior_day_close = _get_prior_day_close(db, ticker, event_date)
                if prior_day_close is None:
                    continue

                event_date_regular_close = _get_event_date_regular_close(db, ticker, event_date)

                # Step 3: rolling baselines
                baselines = _get_rolling_baselines(db, ticker, event_date)
                if baselines is None:
                    continue

                # Step 4: enrichment (split flag, catalyst, float)
                enrichment = _get_enrichment(db, ticker, event_date)

                # Evaluate pre-market variant
                fires_pre, base_ind_pre, criteria_pre = _evaluate_criteria(
                    session="pre",
                    session_vol=session_metrics["pre_vol"],
                    session_high=session_metrics["pre_high"],
                    reference_close=prior_day_close,
                    regular_vol=session_metrics["regular_vol"],
                    regular_high=session_metrics["regular_high"],
                    regular_low=session_metrics["regular_low"],
                    regular_open=session_metrics["regular_open"],
                    baselines=baselines,
                    config=config,
                )
                if fires_pre:
                    indicators_pre = _build_indicators(
                        "pre", base_ind_pre,
                        session_metrics["regular_open"],
                        session_metrics["regular_close"],
                        enrichment, event_date,
                        session_metrics["pre_vol"],
                    )
                    event_dict = ScannerService._save_event(
                        db=db,
                        ticker=ticker,
                        event_date=event_date,
                        scanner_type="liquidity_hunt_pre",
                        indicators=indicators_pre,
                        criteria_met=criteria_pre,
                        enrichment=enrichment,
                        previous_close=prior_day_close,
                        opening_price=session_metrics["regular_open"],
                        closing_price=session_metrics["regular_close"],
                    )
                    results.append(event_dict)

                # Evaluate post-market variant (skip if no event_date regular close)
                if event_date_regular_close is not None:
                    fires_post, base_ind_post, criteria_post = _evaluate_criteria(
                        session="post",
                        session_vol=session_metrics["post_vol"],
                        session_high=session_metrics["post_high"],
                        reference_close=event_date_regular_close,
                        regular_vol=session_metrics["regular_vol"],
                        regular_high=session_metrics["regular_high"],
                        regular_low=session_metrics["regular_low"],
                        regular_open=session_metrics["regular_open"],
                        baselines=baselines,
                        config=config,
                    )
                    if fires_post:
                        indicators_post = _build_indicators(
                            "post", base_ind_post,
                            session_metrics["regular_open"],
                            session_metrics["regular_close"],
                            enrichment, event_date,
                            session_metrics["post_vol"],
                        )
                        event_dict = ScannerService._save_event(
                            db=db,
                            ticker=ticker,
                            event_date=event_date,
                            scanner_type="liquidity_hunt_post",
                            indicators=indicators_post,
                            criteria_met=criteria_post,
                            enrichment=enrichment,
                            previous_close=event_date_regular_close,
                            opening_price=session_metrics["regular_open"],
                            closing_price=session_metrics["regular_close"],
                        )
                        results.append(event_dict)

            except Exception:
                _LOG.exception("Error in liquidity_hunt scan for %s on %s", ticker, event_date)

    db.commit()
    return results


async def run_liquidity_hunt_scan_for_date(
    ticker: str,
    event_date: date,
    db: Session,
) -> list[dict[str, Any]]:
    """Convenience wrapper for single-ticker single-date scans (used by tasks scanner_map)."""
    return await run_liquidity_hunt_scan(
        [ticker], db, start_date=event_date, end_date=event_date
    )
```

- [ ] **Step 4: Run the scan-loop tests**

```bash
cd backend && python -m pytest tests/services/test_liquidity_hunt.py -k "scan_fires or scan_skips or split_in_lookback" -v 2>&1 | tail -20
```

Expected: `5 passed`

- [ ] **Step 5: Run the full test suite**

```bash
cd backend && python -m pytest tests/services/test_liquidity_hunt.py -v 2>&1 | tail -15
```

Expected: `22 passed`

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/liquidity_hunt.py backend/tests/services/test_liquidity_hunt.py
git commit -m "feat(scanner): implement run_liquidity_hunt_scan main loop with pre/post variants"
```

---

## Task 6: Update `event_helpers.py` for the two new scanner types

**Files:**
- Modify: `backend/app/services/event_helpers.py`

- [ ] **Step 1: Add entries to `SUMMARY_GENERATORS` and `SEVERITY_CALCULATORS`**

In `backend/app/services/event_helpers.py`, replace:

```python
    "liquidity_hunt": lambda ind: f"Liquidity hunt, {ind.get('relative_volume', 0):.1f}x RVOL, {ind.get('gap_pct', 0):+.1f}% gap",
```

with:

```python
    "liquidity_hunt_pre": lambda ind: (
        f"Pre-mkt liquidity hunt: {ind.get('session_volume_ratio') or '∞'}x session vol, "
        f"{ind.get('session_spike_pct', 0)*100:+.1f}% spike"
    ),
    "liquidity_hunt_post": lambda ind: (
        f"Post-mkt liquidity hunt: {ind.get('session_volume_ratio') or '∞'}x session vol, "
        f"{ind.get('session_spike_pct', 0)*100:+.1f}% spike"
    ),
```

And replace:

```python
    "liquidity_hunt": lambda ind: (
        "high" if ind.get('relative_volume', 0) > 4
        else "medium" if ind.get('relative_volume', 0) > 2
        else "low"
    ),
```

with:

```python
    "liquidity_hunt_pre": lambda ind: (
        "high" if (ind.get('session_volume_ratio') or 0) > 8
        else "medium" if (ind.get('session_volume_ratio') or 0) > 4
        else "low"
    ),
    "liquidity_hunt_post": lambda ind: (
        "high" if (ind.get('session_volume_ratio') or 0) > 8
        else "medium" if (ind.get('session_volume_ratio') or 0) > 4
        else "low"
    ),
```

- [ ] **Step 2: Verify no syntax errors**

```bash
cd backend && python -c "from app.services.event_helpers import generate_event_summary, compute_event_severity; print('OK')"
```

Expected: `OK`

- [ ] **Step 3: Quick smoke test**

```bash
cd backend && python -c "
from app.services.event_helpers import generate_event_summary, compute_event_severity
ind = {'session_volume_ratio': 7.1, 'session_spike_pct': 0.12}
print(generate_event_summary('liquidity_hunt_pre', ind))
print(compute_event_severity('liquidity_hunt_pre', ind))
print(generate_event_summary('liquidity_hunt_post', ind))
print(compute_event_severity('liquidity_hunt_post', ind))
"
```

Expected output (example):
```
Pre-mkt liquidity hunt: 7.1x session vol, +12.0% spike
medium
Post-mkt liquidity hunt: 7.1x session vol, +12.0% spike
medium
```

- [ ] **Step 4: Commit**

```bash
git add backend/app/services/event_helpers.py
git commit -m "feat(scanner): add liquidity_hunt_pre/post summary and severity handlers"
```

---

## Task 7: Delete old methods from `scanner.py` and update the router

**Files:**
- Modify: `backend/app/services/scanner.py`
- Modify: `backend/app/routers/scanner.py`

- [ ] **Step 1: Delete the old methods from `scanner.py`**

In `backend/app/services/scanner.py`, delete everything from line 247 to line 436 (the `run_liquidity_hunt_scan` static method) and from line 682 to line 687 (the `run_liquidity_hunt_scan_for_date` static method).

The deleted block starts at:
```python
    @staticmethod
    async def run_liquidity_hunt_scan(
        tickers: List[str], db: Session,
        start_date: date = None, end_date: date = None
    ) -> List[Dict[str, Any]]:
```
and ends after its `return results` at line 436.

The second deleted block is:
```python
    @staticmethod
    async def run_liquidity_hunt_scan_for_date(
        ticker: str, event_date: date, db: Session
    ) -> List[Dict[str, Any]]:
        return await ScannerService.run_liquidity_hunt_scan(
            [ticker], db, start_date=event_date, end_date=event_date
        )
```

- [ ] **Step 2: Update the router import and call site**

In `backend/app/routers/scanner.py`, add to the imports at the top:

```python
from app.services.liquidity_hunt import run_liquidity_hunt_scan
```

Replace lines 77–78:

```python
        if request.scanner_type == "liquidity_hunt":
            results = await ScannerService.run_liquidity_hunt_scan(tickers, db)
```

with:

```python
        if request.scanner_type in ("liquidity_hunt", "liquidity_hunt_pre", "liquidity_hunt_post"):
            results = await run_liquidity_hunt_scan(tickers, db)
```

- [ ] **Step 3: Update the `scanner_type` filter on line 230 in `scanner.py` router**

In `backend/app/routers/scanner.py`, find the line:

```python
        .filter(ScannerEvent.scanner_type.in_(['pre_market_volume_spike', 'liquidity_hunt']))
```

Replace with:

```python
        .filter(ScannerEvent.scanner_type.in_([
            'pre_market_volume_spike', 'liquidity_hunt',
            'liquidity_hunt_pre', 'liquidity_hunt_post',
        ]))
```

- [ ] **Step 4: Verify backend imports cleanly**

```bash
cd backend && python -c "from app.services.scanner import ScannerService; from app.routers.scanner import router; print('OK')"
```

Expected: `OK`

- [ ] **Step 5: Run full test suite to confirm nothing broken**

```bash
cd backend && python -m pytest tests/ -v --tb=short 2>&1 | tail -25
```

Expected: all pre-existing tests pass; 22 liquidity_hunt tests pass.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/scanner.py backend/app/routers/scanner.py
git commit -m "refactor(scanner): move liquidity_hunt logic to dedicated module; update router"
```

---

## Task 8: Update `tasks.py` — scanner_map and scheduled task

**Files:**
- Modify: `backend/app/tasks.py`

- [ ] **Step 1: Update the import inside `run_range_scan`**

In `backend/app/tasks.py`, the `run_range_scan` task has a local import at line 1179:

```python
    from app.services.scanner import ScannerService
```

Add below it:

```python
    from app.services.liquidity_hunt import run_liquidity_hunt_scan_for_date as _lh_scan
```

- [ ] **Step 2: Update `scanner_map` in `run_range_scan`**

Replace lines 1219–1223:

```python
        scanner_map = {
            "pre_market_volume_spike": ScannerService.run_pre_market_scan_for_date,
            "liquidity_hunt": ScannerService.run_liquidity_hunt_scan_for_date,
            "oversold_bounce": ScannerService.run_oversold_bounce_scan_for_date,
        }
```

with:

```python
        scanner_map = {
            "pre_market_volume_spike": ScannerService.run_pre_market_scan_for_date,
            "liquidity_hunt": _lh_scan,
            "liquidity_hunt_pre": _lh_scan,
            "liquidity_hunt_post": _lh_scan,
            "oversold_bounce": ScannerService.run_oversold_bounce_scan_for_date,
        }
```

- [ ] **Step 3: Add `run_liquidity_hunt_scheduled` Celery task**

Add after the last `@celery_app.task` in `tasks.py` (currently the `run_range_scan` function at the end):

```python
@celery_app.task(bind=True, max_retries=1)
def run_liquidity_hunt_scheduled(self):
    """
    Nightly 21:00 ET task: run liquidity_hunt_pre and liquidity_hunt_post
    for today's date over all active ScannerConfig universes of type 'liquidity_hunt'.
    """
    import asyncio
    from app.utils.session import get_market_today
    from app.services.liquidity_hunt import run_liquidity_hunt_scan
    from app.models.scanner_config import ScannerConfig
    from app.models.monitored_stock import MonitoredStock

    db: Session = SessionLocal()
    try:
        event_date = get_market_today()
        configs = (
            db.query(ScannerConfig)
            .filter(
                ScannerConfig.scanner_type == "liquidity_hunt",
                ScannerConfig.is_active.is_(True),
            )
            .all()
        )

        for cfg in configs:
            universe_id = cfg.parameters.get("universe_id")
            if not universe_id:
                logging.warning("liquidity_hunt ScannerConfig %s has no universe_id", cfg.id)
                continue

            tickers = [
                ms.ticker
                for ms in db.query(MonitoredStock).filter(
                    MonitoredStock.universe_id == universe_id,
                    MonitoredStock.is_active.is_(True),
                ).all()
            ]
            if not tickers:
                continue

            results = asyncio.run(
                run_liquidity_hunt_scan(tickers, db, start_date=event_date, end_date=event_date)
            )
            logging.info(
                "liquidity_hunt scheduled scan for universe %s on %s: %d events",
                universe_id, event_date, len(results),
            )
    except Exception as exc:
        logging.exception("run_liquidity_hunt_scheduled failed: %s", exc)
        raise self.retry(exc=exc)
    finally:
        db.close()
```

- [ ] **Step 4: Verify imports**

```bash
cd backend && python -c "from app.tasks import run_liquidity_hunt_scheduled; print('OK')"
```

Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add backend/app/tasks.py
git commit -m "feat(scanner): add run_liquidity_hunt_scheduled task and update scanner_map"
```

---

## Task 9: Add beat schedule to `celery_app.py`

**Files:**
- Modify: `backend/app/core/celery_app.py`

- [ ] **Step 1: Add the beat schedule entry**

The existing schedule in `celery_app.py` uses raw UTC hours (e.g., `hour='1'` for 1 AM UTC = ~8 PM ET).
21:00 ET = 02:00 UTC in winter (EST, UTC-5); 01:00 UTC in summer (EDT, UTC-4).
Using `hour='2'` fires at 9 PM EST / 10 PM EDT — always after after-market closes at 8 PM ET.

In `backend/app/core/celery_app.py`, inside `celery_app.conf.beat_schedule`, add after the existing entries:

```python
    # Liquidity hunt scan: runs at 21:00 ET (02:00 UTC) Mon–Fri
    # After-market closes 20:00 ET; 1-hour buffer for delayed aggregate ingestion.
    # 02:00 UTC = 21:00 EST (winter) / 22:00 EDT (summer) — always post-close.
    'run-liquidity-hunt-scan-evening': {
        'task': 'app.tasks.run_liquidity_hunt_scheduled',
        'schedule': crontab(minute='0', hour='2', day_of_week='1-5'),
    },
```

- [ ] **Step 2: Verify celery_app imports cleanly**

```bash
cd backend && python -c "from app.core.celery_app import celery_app; print(list(celery_app.conf.beat_schedule.keys()))"
```

Expected output includes `'run-liquidity-hunt-scan-evening'`:
```
['poll-news-weekdays', 'sync-stock-splits-nightly', 'poll-auto-trade-fills', 'run-liquidity-hunt-scan-evening']
```

- [ ] **Step 3: Commit**

```bash
git add backend/app/core/celery_app.py
git commit -m "feat(scheduler): add nightly liquidity_hunt beat schedule at 02:00 UTC"
```

---

## Task 10: Alembic migration — seed default `ScannerConfig` row

**Files:**
- Create: `backend/app/alembic/versions/<hash>_seed_liquidity_hunt_config.py`

- [ ] **Step 1: Generate a new migration file**

```bash
cd backend && python -m alembic revision --autogenerate -m "seed_liquidity_hunt_scanner_config"
```

Expected: new file created in `backend/app/alembic/versions/` ending in `_seed_liquidity_hunt_scanner_config.py`.

- [ ] **Step 2: Replace the auto-generated body with an idempotent seed**

Open the generated file. Replace the `upgrade()` and `downgrade()` functions with:

```python
import sqlalchemy as sa
from alembic import op

def upgrade() -> None:
    conn = op.get_bind()
    # Idempotent: only insert if no 'liquidity_hunt' config exists yet
    existing = conn.execute(
        sa.text("SELECT id FROM scanner_configs WHERE scanner_type = 'liquidity_hunt' LIMIT 1")
    ).fetchone()
    if existing:
        return

    conn.execute(
        sa.text("""
            INSERT INTO scanner_configs
                (name, description, scanner_type, parameters, criteria, is_active, run_frequency)
            VALUES
                (
                    'Liquidity Hunt (Evening)',
                    'Detects pre/post-market volume anomalies with a quiet regular session.',
                    'liquidity_hunt',
                    '{
                        "volume_ratio_min": 4.0,
                        "volume_pct_of_daily_min": 0.30,
                        "spike_pct_min": 0.10,
                        "regular_vol_ratio_max": 1.20,
                        "regular_range_ratio_max": 1.50,
                        "session_volume_floor": 50000
                    }'::jsonb,
                    '{}'::jsonb,
                    true,
                    'evening'
                )
        """)
    )


def downgrade() -> None:
    op.execute(
        "DELETE FROM scanner_configs WHERE scanner_type = 'liquidity_hunt' AND name = 'Liquidity Hunt (Evening)'"
    )
```

- [ ] **Step 3: Apply the migration**

```bash
cd backend && python -m alembic upgrade head
```

Expected: migration runs without error.

- [ ] **Step 4: Verify the row was inserted**

```bash
docker-compose exec backend python -c "
from app.core.database import SessionLocal
from app.models.scanner_config import ScannerConfig
db = SessionLocal()
cfg = db.query(ScannerConfig).filter(ScannerConfig.scanner_type == 'liquidity_hunt').first()
print('name:', cfg.name)
print('parameters:', cfg.parameters)
db.close()
"
```

Expected: prints the config name and the default threshold parameters.

- [ ] **Step 5: Confirm backend reloaded cleanly**

```bash
docker-compose logs backend --tail=10
```

Expected: no errors; `Application startup complete` visible if it restarted.

- [ ] **Step 6: Commit**

```bash
git add backend/app/alembic/versions/
git commit -m "chore(db): seed default liquidity_hunt ScannerConfig row"
```

---

## Task 11: Integration validation

**No file changes — validation only.**

- [ ] **Step 1: Confirm backend is healthy**

```bash
curl -s http://localhost:8000/api/health | python -m json.tool
```

Expected: `{"status": "healthy"}` or similar.

- [ ] **Step 2: Run the on-demand scanner endpoint for a known historical date**

Pick a ticker and date from your data. Replace `TICKER` and `YYYY-MM-DD`:

```bash
curl -s -X POST http://localhost:8000/api/scanner/run \
  -H "Content-Type: application/json" \
  -d '{"scanner_type": "liquidity_hunt", "tickers": ["TICKER"]}' \
  | python -m json.tool
```

- [ ] **Step 3: Confirm response shape**

The response should include events with `scanner_type` of `liquidity_hunt_pre` or `liquidity_hunt_post` and each event's `indicators` should contain:

```json
{
  "session": "pre",
  "session_volume": ...,
  "avg_session_volume_20d": ...,
  "session_volume_ratio": ...,
  "session_volume_pct_of_daily": ...,
  "session_high": ...,
  "reference_close": ...,
  "session_spike_pct": ...,
  "regular_volume": ...,
  "avg_regular_volume_20d": ...,
  "regular_volume_ratio": ...,
  "regular_range_pct": ...,
  "avg_regular_range_pct_20d": ...,
  "regular_range_ratio": ...,
  "opening_price": ...,
  "closing_price": ...,
  "split_in_lookback": false
}
```

- [ ] **Step 4: Use the range-scan endpoint to find historical signals**

```bash
curl -s -X POST http://localhost:8000/api/scanner/run \
  -H "Content-Type: application/json" \
  -d '{
    "scanner_type": "liquidity_hunt",
    "tickers": ["TICKER"],
    "start_date": "2025-01-01",
    "end_date": "2025-12-31"
  }' | python -m json.tool
```

If events are returned, open a chart for the ticker on the event date and visually confirm:
- Pre-market or after-market high was ≥10% above the reference close.
- That day's regular session was unremarkable — no large candles, no volume blow-out.

- [ ] **Step 5: Final full test suite run**

```bash
cd backend && python -m pytest tests/ -v --tb=short 2>&1 | tail -30
```

Expected: all tests pass.

- [ ] **Step 6: Final commit**

```bash
git add -A
git commit -m "feat(scanner): liquidity hunt scanner redesign — pre/post variants, 6-criteria model, nightly schedule"
```
