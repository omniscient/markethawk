# Implementation Plan: Trend Pullback Daily Scanner

**Date:** 2026-06-11
**Issue:** #299
**Spec:** `docs/superpowers/specs/2026-06-10-trend-pullback-scanner-design.md`
**Goal:** Add `trend_pullback` as a new registered daily scanner that fires on stocks in confirmed uptrends pulling back to their 20-day SMA.
**Arch:** New service `trend_pullback_scan.py` (modeled on `pocket_pivot.py`), wired into the existing scan task, event-helper, and scheduler infrastructure. One expansion to `OutcomeService`. One Alembic seed migration (`down_revision = 'c7d8e9f0a1b2'`, the single current head).
**Tech Stack:** FastAPI backend · SQLAlchemy (sync `Session` + `db.query()` inside `async def` — the established daily-scanner pattern, same as `pocket_pivot.py` and `oversold_bounce_scan.py`; the AsyncSession [AVOID] memory entry applies to API routes, not daily scanner services) · pandas · pytest · Alembic

---

## File Structure

| File | Action |
|---|---|
| `backend/app/services/outcome_service.py` | **Edit** — add `"10d"` to `interval_map` |
| `backend/app/services/event_helpers.py` | **Edit** — add `trend_pullback` to `SUMMARY_GENERATORS` + `SEVERITY_CALCULATORS` |
| `backend/app/services/trend_pullback_scan.py` | **Create** — scanner implementation |
| `backend/app/tasks/scanning.py` | **Edit** — `scanner_map`, import, scheduled task, `_BEAT_SCHEDULED_SCANNER_TYPES` |
| `backend/app/alembic/versions/<seed_hash>_seed_trend_pullback_scanner_config.py` | **Create** — scanner_configs row, `down_revision = 'c7d8e9f0a1b2'` (single current head), `is_active=true` |
| `backend/app/core/celery_app.py` | **Edit** — add `run-trend-pullback-scan-evening` beat_schedule entry |
| `backend/tests/services/test_trend_pullback_scan.py` | **Create** — unit tests |
| `backend/tests/services/test_outcome_service_10d.py` | **Create** — 10d interval test |

---

## Task 1 — Expand `OutcomeService` with `10d` interval

**Files:** `backend/app/services/outcome_service.py`, `backend/tests/services/test_outcome_service_10d.py`

### Step 1.1 — Write failing test

Create `backend/tests/services/test_outcome_service_10d.py`:

```python
"""Verify that OutcomeService.capture_snapshot recognises the '10d' interval key."""

from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest


def _make_snapshot(interval_key: str):
    from app.services.outcome_service import OutcomeService
    from app.models.scanner_outcome_snapshot import ScannerOutcomeSnapshot

    event = MagicMock()
    event.event_date = date(2026, 1, 2)
    event.ticker = "AAPL"
    event.opening_price = Decimal("150.00")

    snap = MagicMock(spec=ScannerOutcomeSnapshot)
    snap.interval_key = interval_key
    snap.reference_price_source = "opening_price"
    snap.status = "pending"

    return event, snap


def test_10d_interval_is_recognised():
    """capture_snapshot must not set status=failed for interval_key='10d'."""
    event, snap = _make_snapshot("10d")

    fake_bar = MagicMock()
    fake_bar.close = 155.0
    fake_bar.high = 158.0
    fake_bar.low = 149.0
    fake_bar.volume = 1_000_000

    db = MagicMock()
    db.query.return_value.filter.return_value.order_by.return_value.all.return_value = [fake_bar]

    with patch("app.services.outcome_service.StockAggregate"):
        from app.services.outcome_service import OutcomeService

        OutcomeService.capture_snapshot(db, snap)

    assert snap.status != "failed", (
        "'10d' interval_key must not produce status='failed'; "
        "add it to interval_map in OutcomeService.capture_snapshot"
    )


def test_unknown_interval_still_fails():
    """Regression: unrecognised intervals must still set status=failed."""
    event, snap = _make_snapshot("30d")
    snap.status = "pending"
    db = MagicMock()

    from app.services.outcome_service import OutcomeService

    OutcomeService.capture_snapshot(db, snap)
    assert snap.status == "failed"
```

Run and verify it **fails** (assertion failure because `"10d"` is not yet in `interval_map`):
```bash
docker-compose exec backend python -m pytest backend/tests/services/test_outcome_service_10d.py -x -q 2>&1 | tail -20
# Expected: FAILED test_10d_interval_is_recognised (status == 'failed')
```

### Step 1.2 — Implement

In `backend/app/services/outcome_service.py` at line 92, add `"10d"` to `interval_map` inside `capture_snapshot`:

```python
        interval_map = {
            "1h": timedelta(hours=1),
            "4h": timedelta(hours=4),
            "eod": timedelta(hours=6, minutes=30),
            "1d": timedelta(days=1),
            "2d": timedelta(days=2),
            "5d": timedelta(days=5),
            "10d": timedelta(days=10),   # <-- ADD: needed by trend_pullback scanner
        }
```

### Step 1.3 — Verify test passes

```bash
docker-compose exec backend python -m pytest backend/tests/services/test_outcome_service_10d.py -x -q 2>&1 | tail -10
# Expected: 2 passed
```

### Step 1.4 — Commit

```bash
git add backend/app/services/outcome_service.py backend/tests/services/test_outcome_service_10d.py
git commit -m "feat(outcome): add 10d interval to OutcomeService.capture_snapshot

Refs #299 — trend_pullback is a 3-10 day swing setup; outcome harness
must capture a 10d snapshot beyond the existing 5d maximum."
```

---

## Task 2 — Add `trend_pullback` to `event_helpers.py`

**Files:** `backend/app/services/event_helpers.py`

### Step 2.1 — Write failing test (inline assertion)

Verify that neither `compute_event_severity` nor `generate_event_summary` currently handles `trend_pullback`:

```bash
docker-compose exec backend python -c "
from app.services.event_helpers import compute_event_severity, generate_event_summary
ind = {'pullback_depth_pct': 5.0, 'rsi5': 25.0}
sev = compute_event_severity('trend_pullback', ind)
print('severity:', sev, '— expected: high')
assert sev == 'high', f'Expected high, got {sev}'
"
# Expected: AssertionError (returns fallback 'medium', not 'high')
```

### Step 2.2 — Implement

In `backend/app/services/event_helpers.py`, add entries to `SUMMARY_GENERATORS` and `SEVERITY_CALCULATORS`. Place them after the `"oversold_bounce"` entry:

**In `SUMMARY_GENERATORS`:**
```python
    "trend_pullback": lambda ind: (
        f"Trend pullback: {ind.get('pullback_depth_pct', 0):.1f}% off swing high, "
        f"RSI({ind.get('rsi5', 0):.0f}), SMA20 tagged"
    ),
```

**In `SEVERITY_CALCULATORS`:**
```python
    "trend_pullback": lambda ind: (
        "high"
        if (ind.get("pullback_depth_pct") or 100) <= 8
        and (ind.get("rsi5") or 100) < 30
        else "medium"
    ),
```

### Step 2.3 — Verify inline

```bash
docker-compose exec backend python -c "
from app.services.event_helpers import compute_event_severity, generate_event_summary
ind_high = {'pullback_depth_pct': 5.0, 'rsi5': 25.0}
ind_medium = {'pullback_depth_pct': 10.0, 'rsi5': 35.0}
ind_medium2 = {'pullback_depth_pct': 6.0, 'rsi5': 32.0}
print(compute_event_severity('trend_pullback', ind_high))    # high
print(compute_event_severity('trend_pullback', ind_medium))  # medium
print(compute_event_severity('trend_pullback', ind_medium2)) # medium
print(generate_event_summary('trend_pullback', ind_high))
"
```

Expected output:
```
high
medium
medium
Trend pullback: 5.0% off swing high, RSI(25), SMA20 tagged
```

### Step 2.4 — Commit

```bash
git add backend/app/services/event_helpers.py
git commit -m "feat(event-helpers): add trend_pullback severity and summary handlers

Refs #299 — severity=high when pullback depth ≤ 8% AND RSI5 < 30, medium otherwise.
Wired through alert_service.save_event → compute_event_severity path."
```

---

## Task 3 — Implement `trend_pullback_scan.py`

**Depends on:** Task 2 committed (Task 3 imports `event_helpers` via `alert_service.save_event`, which must know `trend_pullback` severity/summary)

**Files:** `backend/app/services/trend_pullback_scan.py`, `backend/tests/services/test_trend_pullback_scan.py`

### Step 3.1 — Write failing tests

Create `backend/tests/services/test_trend_pullback_scan.py`:

```python
"""
Unit tests for trend_pullback_scan — criteria-gate and signal scenarios.

All DB I/O is mocked via _get_daily_bars and _save_event.
_save_event is the alias for alert_service.save_event, NOT a local helper.
Tests build pandas-compatible bar fixtures (MagicMock objects with
.open/.high/.low/.close/.volume) and verify the scanner fires or suppresses.
"""

import asyncio
from datetime import date, datetime, timezone
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

_EVENT_DATE = date(2026, 1, 15)  # Thursday


def _bar(
    close: float,
    volume: int = 600_000,
    high_mult: float = 1.005,
    low_mult: float = 0.995,
) -> MagicMock:
    b = MagicMock()
    b.close = close
    b.open = close * 0.999
    b.high = close * high_mult
    b.low = close * low_mult
    b.volume = volume
    b.timestamp = datetime(2026, 1, 15, 14, 30, 0)
    return b


def _rising_series(n: int, start: float = 50.0, step: float = 0.10) -> list:
    """Build n bars with steadily increasing closes — gives uptrend + near-highs."""
    return [_bar(start + i * step) for i in range(n)]


def _pullback_series(n_history: int = 215, pullback_bars: int = 7) -> list:
    """
    Build a bar series that satisfies ALL 6 criteria:

    History (n_history bars): rising from $50.00, step $0.10
      → SMA50 rising, SMA200 valid, near 252d high, all closes > SMA20

    Pullback phase (last pullback_bars):
      - First (pullback_bars-1) bars: close slightly above SMA20.
        high elevated to define 20d swing high.
      - Last bar: low touches SMA20 (the tag event).

    This satisfies:
      - consec_above >= min_days_above_sma (5)
      - last low <= SMA20 * 1.01
      - pullback_depth_pct ~5% (within 3-12%)
      - RSI(5) drops on retreating bars → < 40
      - All closes > SMA50 (no breakdown)
    """
    base = _rising_series(n_history)
    peak_close = base[-1].close

    pullback_closes = [
        peak_close * (1.0 - 0.006 * (i + 1)) for i in range(pullback_bars)
    ]

    pb_bars = []
    for i, c in enumerate(pullback_closes):
        b = MagicMock()
        b.close = c
        b.open = c * 1.001
        b.high = (peak_close * 1.002) if i < 3 else c * 1.002
        b.low = c * 0.990 if i == len(pullback_closes) - 1 else c * 0.997
        b.volume = 600_000
        b.timestamp = datetime(2026, 1, 15, 14, 30, 0)
        pb_bars.append(b)

    return base + pb_bars


def _run_scan(
    bars: list,
    config: dict | None = None,
    tickers: list[str] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any], MagicMock]:
    """Run the scan with mocked DB/save helpers. Returns (results, diagnostics, mock_save)."""
    from app.services.trend_pullback_scan import run_trend_pullback_scan

    tickers = tickers or ["AAPL"]
    diagnostics: dict[str, Any] = {}
    save_return = {"ticker": tickers[0], "id": 1}

    with (
        patch(
            "app.services.trend_pullback_scan._get_daily_bars",
            return_value=bars,
        ),
        patch(
            "app.services.trend_pullback_scan._save_event",
            return_value=save_return,
        ) as mock_save,
        patch("app.services.trend_pullback_scan.scanner_events_total"),
    ):
        results = asyncio.run(
            run_trend_pullback_scan(
                tickers,
                db=MagicMock(),
                start_date=_EVENT_DATE,
                end_date=_EVENT_DATE,
                config=config,
                diagnostics_out=diagnostics,
            )
        )
    return results, diagnostics, mock_save


# ---------------------------------------------------------------------------
# Scenario 1: Clean signal — all six criteria satisfied
# ---------------------------------------------------------------------------
def test_clean_signal_fires():
    bars = _pullback_series()
    results, diag, mock_save = _run_scan(bars)
    assert len(results) == 1, f"Expected 1 event, got {len(results)}"
    assert diag["fired"] == 1
    call_kw = mock_save.call_args.kwargs
    assert call_kw["scanner_type"] == "trend_pullback"
    ind = call_kw["indicators"]
    for key in ("sma20", "sma50", "sma200", "rsi5", "pct_off_252d_high",
                "pullback_depth_pct", "consecutive_days_above_sma20", "atr14",
                "avg_dollar_vol_20d"):
        assert key in ind, f"Missing indicator: {key}"
    crit = call_kw["criteria_met"]
    assert all(crit.values()), f"Expected all criteria True, got {crit}"


# ---------------------------------------------------------------------------
# Scenario 2: Insufficient history (< 210 bars) — skipped as no_data
# ---------------------------------------------------------------------------
def test_insufficient_history_skipped():
    bars = _rising_series(150)
    results, diag, _ = _run_scan(bars)
    assert len(results) == 0
    assert diag["no_data"] == 1


# ---------------------------------------------------------------------------
# Scenario 3: Downtrend — close < SMA50 on the last bar
# ---------------------------------------------------------------------------
def test_downtrend_close_below_sma50_does_not_fire():
    bars = _rising_series(220, start=100.0, step=0.1)
    last = bars[-1]
    last.close = 50.0
    last.low = 49.5
    last.high = 51.0
    results, diag, _ = _run_scan(bars)
    assert len(results) == 0


# ---------------------------------------------------------------------------
# Scenario 4: SMA50 < SMA200 (death cross)
# ---------------------------------------------------------------------------
def test_sma50_below_sma200_does_not_fire():
    bars = [_bar(200.0 - i * 0.2) for i in range(222)]
    results, diag, _ = _run_scan(bars)
    assert len(results) == 0


# ---------------------------------------------------------------------------
# Scenario 5: SMA50 not rising (flat over the last 20 sessions)
# ---------------------------------------------------------------------------
def test_sma50_not_rising_does_not_fire():
    rising = _rising_series(200)
    flat_close = rising[-1].close
    flat = [_bar(flat_close) for _ in range(22)]
    bars = rising + flat
    results, diag, _ = _run_scan(bars)
    assert len(results) == 0


# ---------------------------------------------------------------------------
# Scenario 6: Not near highs — close is > 15% below 252-day high
# ---------------------------------------------------------------------------
def test_not_near_highs_does_not_fire():
    bars = _rising_series(252, start=100.0, step=0.10)
    for _ in range(10):
        bars.append(_bar(bars[-1].close * 0.978))
    results, diag, _ = _run_scan(bars)
    assert len(results) == 0


# ---------------------------------------------------------------------------
# Scenario 7: Fewer than 5 consecutive prior closes above SMA20
# ---------------------------------------------------------------------------
def test_less_than_5_days_above_sma20_does_not_fire():
    bars = _pullback_series(n_history=215, pullback_bars=3)
    results, diag, _ = _run_scan(bars, config={"min_days_above_sma": 5})
    assert len(results) == 0


# ---------------------------------------------------------------------------
# Scenario 8: Pullback too shallow (< 3%)
# ---------------------------------------------------------------------------
def test_pullback_too_shallow_does_not_fire():
    base = _rising_series(220)
    peak = base[-1].close
    pb_bar = MagicMock()
    pb_bar.close = peak * 0.99
    pb_bar.open = peak * 0.995
    pb_bar.high = peak * 1.001
    pb_bar.low = base[-5].close * 0.998
    pb_bar.volume = 600_000
    pb_bar.timestamp = datetime(2026, 1, 15, 14, 30, 0)
    bars = base[:-1] + [pb_bar]
    results, diag, _ = _run_scan(bars, config={"pullback_min_pct": 3, "pullback_max_pct": 12})
    assert len(results) == 0


# ---------------------------------------------------------------------------
# Scenario 9: Pullback too deep (> 12%)
# ---------------------------------------------------------------------------
def test_pullback_too_deep_does_not_fire():
    base = _rising_series(220)
    peak = base[-1].close
    pb_bar = MagicMock()
    pb_bar.close = peak * 0.85
    pb_bar.open = peak * 0.86
    pb_bar.high = peak * 0.87
    pb_bar.low = peak * 0.83
    pb_bar.volume = 600_000
    pb_bar.timestamp = datetime(2026, 1, 15, 14, 30, 0)
    bars = base[:-1] + [pb_bar]
    results, diag, _ = _run_scan(bars, config={"pullback_min_pct": 3, "pullback_max_pct": 12})
    assert len(results) == 0


# ---------------------------------------------------------------------------
# Scenario 10: RSI(5) >= 40 — not reset
# ---------------------------------------------------------------------------
def test_rsi_too_high_does_not_fire():
    bars = _rising_series(222, step=0.50)
    results, diag, _ = _run_scan(bars, config={"rsi_max": 40})
    assert len(results) == 0


# ---------------------------------------------------------------------------
# Scenario 11: Low dollar volume (avg_dollar_vol_20d < $5M)
# ---------------------------------------------------------------------------
def test_low_dollar_volume_does_not_fire():
    bars = _pullback_series()
    for b in bars:
        b.volume = 1_000
    results, diag, _ = _run_scan(bars, config={"min_dollar_vol": 5_000_000})
    assert len(results) == 0


# ---------------------------------------------------------------------------
# Scenario 12: Price below $5
# ---------------------------------------------------------------------------
def test_below_price_floor_does_not_fire():
    bars = [_bar(3.0 + i * 0.01) for i in range(222)]
    results, diag, _ = _run_scan(bars, config={"min_price": 5.0})
    assert len(results) == 0


# ---------------------------------------------------------------------------
# Scenario 13: indicators contain depth/RSI values used for severity computation
# (severity itself is NOT stored in indicators — event_helpers.compute_event_severity
# derives it from indicators["pullback_depth_pct"] and indicators["rsi5"], tested in Task 2)
# ---------------------------------------------------------------------------
def test_severity_inputs_present_in_indicators():
    bars = _pullback_series()
    results, diag, mock_save = _run_scan(bars)
    if len(results) == 1:
        ind = mock_save.call_args.kwargs["indicators"]
        depth = ind.get("pullback_depth_pct")
        rsi5 = ind.get("rsi5")
        assert depth is not None, "pullback_depth_pct must be in indicators for severity computation"
        assert rsi5 is not None, "rsi5 must be in indicators for severity computation"
        assert "severity" not in ind, (
            "severity must NOT be stored in indicators — it is derived by event_helpers"
        )
        from app.services.event_helpers import compute_event_severity
        sev = compute_event_severity("trend_pullback", ind)
        assert sev in ("high", "medium"), f"compute_event_severity returned unexpected value: {sev!r}"


# ---------------------------------------------------------------------------
# Scenario 14: criteria_met booleans present in saved event
# ---------------------------------------------------------------------------
def test_criteria_met_has_required_keys():
    bars = _pullback_series()
    results, diag, mock_save = _run_scan(bars)
    if len(results) == 1:
        crit = mock_save.call_args.kwargs["criteria_met"]
        required = {
            "uptrend", "near_highs", "pullback_in_progress", "orderly",
            "rsi_reset", "liquid",
        }
        assert required == set(crit.keys()), f"Missing keys: {required - set(crit.keys())}"


# ---------------------------------------------------------------------------
# Scenario 15: diagnostics populated for multi-ticker run
# ---------------------------------------------------------------------------
def test_diagnostics_populated():
    bars = _pullback_series()
    tickers = ["AAPL", "MSFT"]
    results, diag, _ = _run_scan(bars, tickers=tickers)
    assert diag["tickers"] == 2
    assert diag["days"] == 1
    assert "evaluated" in diag
    assert "fired" in diag
```

Run and verify tests **fail** (ImportError — file doesn't exist yet):
```bash
docker-compose exec backend python -m pytest backend/tests/services/test_trend_pullback_scan.py -x -q 2>&1 | tail -10
# Expected: ImportError: cannot import name 'run_trend_pullback_scan'
```

### Step 3.2 — Implement `trend_pullback_scan.py`

> **Session pattern note:** Daily scanner services use sync `Session` + `db.query()` inside `async def` (same as `pocket_pivot.py` and `oversold_bounce_scan.py`). The `[AVOID] sync SQLAlchemy` memory entry targets API routes and ORM lazy loads — it does not apply here.
>
> **`_save_event` note:** `_save_event` is an alias for `alert_service.save_event` (the centralized event persistence function), NOT a local helper. The import is `from app.services.alert_service import save_event as _save_event`. This ensures severity/summary computed by `event_helpers` (Task 2) are applied to every persisted event.

Create `backend/app/services/trend_pullback_scan.py`:

```python
"""
Trend Pullback Scanner

Detects stocks in confirmed uptrends that pull back in an orderly fashion
to the 20-day SMA ("strong stock, routine dip"). Long-only, daily bars.

Runs nightly after close (same scheduling model as pocket_pivot).
Self-registers with the scan orchestrator at import time.
"""

from __future__ import annotations

import logging
import time as _time
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Optional
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
from sqlalchemy.orm import Session

from app.core.metrics import scan_duration_seconds, scanner_events_total
from app.models.stock_aggregate import StockAggregate
from app.services.alert_service import save_event as _save_event
from app.utils.session import get_market_today

_ET = ZoneInfo("America/New_York")
_LOG = logging.getLogger(__name__)

DEFAULT_CONFIG: dict[str, Any] = {
    "trend_sma_fast": 50,
    "trend_sma_slow": 200,
    "sma_rising_lookback": 20,
    "max_pct_off_high": 15,
    "pullback_sma": 20,
    "pullback_sma_tolerance_pct": 1,
    "min_days_above_sma": 5,
    "pullback_min_pct": 3,
    "pullback_max_pct": 12,
    "rsi_period": 5,
    "rsi_max": 40,
    "min_dollar_vol": 5_000_000,
    "min_price": 5.0,
}

_BARS_LOOKBACK = 265  # 260 bars for SMA200 + buffer


def _compute_rsi(series: pd.Series, period: int) -> pd.Series:
    delta = series.diff()
    up = delta.clip(lower=0)
    down = -1 * delta.clip(upper=0)
    ema_up = up.ewm(com=period - 1, adjust=False).mean()
    ema_down = down.ewm(com=period - 1, adjust=False).mean()
    rs = ema_up / ema_down
    return 100 - (100 / (1 + rs))


def _get_daily_bars(db: Session, ticker: str, end_date: date, lookback: int) -> list:
    """
    Fetch up to `lookback` daily bars with timestamp before start-of-next-day ET,
    ordered ascending. Includes the bar for end_date itself.
    """
    end_dt_utc = (
        datetime.combine(end_date + timedelta(days=1), time.min, tzinfo=_ET)
        .astimezone(timezone.utc)
        .replace(tzinfo=None)
    )
    rows = (
        db.query(StockAggregate)
        .filter(
            StockAggregate.ticker == ticker,
            StockAggregate.timespan == "day",
            StockAggregate.timestamp < end_dt_utc,
        )
        .order_by(StockAggregate.timestamp.desc())
        .limit(lookback)
        .all()
    )
    rows.reverse()
    return rows


async def run_trend_pullback_scan(
    tickers: list[str],
    db: Session,
    start_date: date | None = None,
    end_date: date | None = None,
    config: dict | None = None,
    diagnostics_out: dict | None = None,
) -> list[dict[str, Any]]:
    """
    Run the trend pullback scanner over a date range.

    For each (ticker, event_date):
      1. Fetch up to 265 daily bars ending on event_date.
      2. Compute SMA(20/50/200), RSI(5), ATR(14), avg dollar vol, 252d high,
         20d swing high via pandas.
      3. Evaluate all 6 criteria from the spec.
      4. Persist ScannerEvent if all criteria pass (via alert_service.save_event).
    """
    _perf_start = _time.monotonic()

    if start_date is None and end_date is None:
        start_date = end_date = get_market_today()
    elif start_date is None:
        start_date = end_date
    elif end_date is None:
        end_date = start_date

    cfg: dict[str, Any] = {**DEFAULT_CONFIG, **(config or {})}

    results: list[dict[str, Any]] = []
    counts = {
        "no_data": 0,
        "evaluated": 0,
        "fired": 0,
        "errors": 0,
    }

    trading_days = [
        start_date + timedelta(days=i)
        for i in range((end_date - start_date).days + 1)
        if (start_date + timedelta(days=i)).weekday() < 5
    ]

    for event_date in trading_days:
        for ticker in tickers:
            try:
                bars = _get_daily_bars(db, ticker, event_date, _BARS_LOOKBACK)
                if len(bars) < 210:
                    counts["no_data"] += 1
                    continue

                df = pd.DataFrame(
                    [
                        {
                            "open": float(b.open),
                            "high": float(b.high),
                            "low": float(b.low),
                            "close": float(b.close),
                            "volume": float(b.volume),
                        }
                        for b in bars
                    ]
                )

                sma_fast = int(cfg["trend_sma_fast"])
                sma_slow = int(cfg["trend_sma_slow"])
                sma_pull = int(cfg["pullback_sma"])
                rsi_period = int(cfg["rsi_period"])

                df["sma20"] = df["close"].rolling(sma_pull).mean()
                df["sma50"] = df["close"].rolling(sma_fast).mean()
                df["sma200"] = df["close"].rolling(sma_slow).mean()
                df["rsi5"] = _compute_rsi(df["close"], rsi_period)

                df["prev_close"] = df["close"].shift(1)
                df["tr"] = pd.DataFrame(
                    {
                        "hl": df["high"] - df["low"],
                        "hpc": (df["high"] - df["prev_close"]).abs(),
                        "lpc": (df["low"] - df["prev_close"]).abs(),
                    }
                ).max(axis=1)
                df["atr14"] = df["tr"].rolling(14).mean()

                df["typ_price"] = (df["high"] + df["low"] + df["close"]) / 3
                df["dollar_vol"] = df["volume"] * df["typ_price"]
                df["avg_dollar_vol_20d"] = df["dollar_vol"].rolling(20).mean()

                df["high_252d"] = df["high"].rolling(252).max()
                df["swing_high_20d"] = df["high"].rolling(20).max()

                today = df.iloc[-1]

                if (
                    pd.isna(today["sma200"])
                    or pd.isna(today["sma50"])
                    or pd.isna(today["rsi5"])
                ):
                    counts["no_data"] += 1
                    continue

                counts["evaluated"] += 1

                # --- Criterion 1: Established uptrend ---
                sma_rising_lb = int(cfg["sma_rising_lookback"])
                sma50_prev_idx = len(df) - 1 - sma_rising_lb
                sma50_rising = (
                    sma50_prev_idx >= 0
                    and not pd.isna(df.iloc[sma50_prev_idx]["sma50"])
                    and float(today["sma50"]) > float(df.iloc[sma50_prev_idx]["sma50"])
                )
                uptrend = (
                    float(today["close"]) > float(today["sma50"])
                    and float(today["sma50"]) > float(today["sma200"])
                    and sma50_rising
                )

                # --- Criterion 2: Near highs ---
                high_252d = today["high_252d"]
                pct_off_252d_high: float | None = None
                near_highs = False
                if not pd.isna(high_252d) and float(high_252d) > 0:
                    pct_off_252d_high = round(
                        (float(high_252d) - float(today["close"])) / float(high_252d) * 100, 2
                    )
                    near_highs = pct_off_252d_high <= float(cfg["max_pct_off_high"])

                # --- Criterion 3: Pullback in progress ---
                tolerance = float(cfg["pullback_sma_tolerance_pct"]) / 100
                tagged_sma20 = not pd.isna(today["sma20"]) and (
                    float(today["low"]) <= float(today["sma20"]) * (1 + tolerance)
                )

                closes_arr = df["close"].values
                sma20_arr = df["sma20"].values
                consec_above = 0
                for i in range(len(df) - 2, max(len(df) - 62, -1), -1):
                    if np.isnan(closes_arr[i]) or np.isnan(sma20_arr[i]):
                        break
                    if closes_arr[i] > sma20_arr[i]:
                        consec_above += 1
                    else:
                        break

                pullback_in_progress = (
                    tagged_sma20
                    and consec_above >= int(cfg["min_days_above_sma"])
                )

                # --- Criterion 4: Orderly pullback ---
                swing_high = today["swing_high_20d"]
                pullback_depth_pct: float | None = None
                if not pd.isna(swing_high) and float(swing_high) > 0:
                    pullback_depth_pct = round(
                        (float(swing_high) - float(today["close"])) / float(swing_high) * 100, 2
                    )

                orderly_depth = (
                    pullback_depth_pct is not None
                    and float(cfg["pullback_min_pct"])
                    <= pullback_depth_pct
                    <= float(cfg["pullback_max_pct"])
                )

                recent_20 = df.iloc[-20:]
                no_sma50_break = all(
                    float(row["close"]) >= float(row["sma50"])
                    for _, row in recent_20.iterrows()
                    if not pd.isna(row["sma50"])
                )
                orderly = orderly_depth and no_sma50_break

                # --- Criterion 5: RSI reset ---
                rsi_reset = float(today["rsi5"]) < float(cfg["rsi_max"])

                # --- Criterion 6: Liquidity ---
                liquid = (
                    not pd.isna(today["avg_dollar_vol_20d"])
                    and float(today["avg_dollar_vol_20d"]) >= float(cfg["min_dollar_vol"])
                    and float(today["close"]) >= float(cfg["min_price"])
                )

                criteria_met: dict[str, bool] = {
                    "uptrend": uptrend,
                    "near_highs": near_highs,
                    "pullback_in_progress": pullback_in_progress,
                    "orderly": orderly,
                    "rsi_reset": rsi_reset,
                    "liquid": liquid,
                }

                if not all(criteria_met.values()):
                    continue

                severity = (
                    "high"
                    if pullback_depth_pct is not None
                    and pullback_depth_pct <= 8
                    and float(today["rsi5"]) < 30
                    else "medium"
                )

                indicators: dict[str, Any] = {
                    "sma20": round(float(today["sma20"]), 4),
                    "sma50": round(float(today["sma50"]), 4),
                    "sma200": round(float(today["sma200"]), 4),
                    "rsi5": round(float(today["rsi5"]), 2),
                    "pct_off_252d_high": pct_off_252d_high,
                    "pullback_depth_pct": pullback_depth_pct,
                    "consecutive_days_above_sma20": consec_above,
                    "atr14": round(float(today["atr14"]), 4)
                    if not pd.isna(today["atr14"])
                    else None,
                    "avg_dollar_vol_20d": round(float(today["avg_dollar_vol_20d"]), 2),
                    # severity is NOT stored in indicators — alert_service.save_event
                    # derives it from SEVERITY_CALCULATORS["trend_pullback"] (Task 2).
                    # Storing it here would be redundant and invite drift.
                }

                # _save_event = alert_service.save_event; triggers severity/summary via event_helpers
                event_dict = _save_event(
                    db=db,
                    ticker=ticker,
                    event_date=event_date,
                    scanner_type="trend_pullback",
                    indicators=indicators,
                    criteria_met=criteria_met,
                    enrichment={},
                    closing_price=float(today["close"]),
                )
                results.append(event_dict)
                counts["fired"] += 1
                scanner_events_total.labels(scanner_type="trend_pullback").inc()

            except Exception:
                counts["errors"] += 1
                _LOG.exception(
                    "Error in trend_pullback scan for %s on %s", ticker, event_date
                )

    _LOG.info(
        "trend_pullback scan complete: tickers=%d days=%d "
        "no_data=%d evaluated=%d fired=%d errors=%d",
        len(tickers),
        len(trading_days),
        counts["no_data"],
        counts["evaluated"],
        counts["fired"],
        counts["errors"],
    )

    if diagnostics_out is not None:
        diagnostics_out.update(
            {
                "tickers": len(tickers),
                "days": len(trading_days),
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
                "no_data": counts["no_data"],
                "evaluated": counts["evaluated"],
                "fired": counts["fired"],
                "errors": counts["errors"],
            }
        )

    scan_duration_seconds.labels(scanner_type="trend_pullback").observe(
        _time.monotonic() - _perf_start
    )
    return results


async def run_trend_pullback_scan_for_date(
    ticker: str,
    event_date: date,
    db: Session,
) -> list[dict[str, Any]]:
    """Single-ticker single-date wrapper used by run_range_scan's scanner_map."""
    return await run_trend_pullback_scan(
        [ticker], db, start_date=event_date, end_date=event_date
    )


# -- Orchestrator self-registration -------------------------------------------

from app.services.scan_orchestrator import ScannerDescriptor, register  # noqa: E402


async def _orchestrator_run(
    tickers: list,
    db: Any,
    event_date: date,
    scanner_run: Optional[Any] = None,
) -> list[dict]:
    """Adapter: maps the standard ScannerFn signature to run_trend_pullback_scan."""
    return await run_trend_pullback_scan(
        tickers=tickers,
        db=db,
        start_date=event_date,
        end_date=event_date,
    )


register(
    ScannerDescriptor(
        key="trend_pullback",
        display_name="Trend Pullback",
        description=(
            "Stocks in confirmed uptrends (close > SMA50 > SMA200, SMA50 rising) "
            "pulling back in an orderly fashion to the 20-day SMA. "
            "Long-only, daily bars, runs after close."
        ),
        run=_orchestrator_run,
        supports_date_range=True,
    )
)
```

### Step 3.3 — Verify tests pass

```bash
docker-compose exec backend python -m pytest backend/tests/services/test_trend_pullback_scan.py -x -v 2>&1 | tail -25
# Expected: 15 passed
# Fixture tuning: if test_clean_signal_fires fails because not all criteria are True,
# increase pullback_bars in _pullback_series (e.g. to 9) to generate a longer
# pullback period that drops RSI(5) below 40.
```

### Step 3.4 — Commit

```bash
git add backend/app/services/trend_pullback_scan.py backend/tests/services/test_trend_pullback_scan.py
git commit -m "feat(scanner): implement trend_pullback daily scanner

Detects uptrending stocks pulling back to the 20-day SMA. All 6 criteria
(uptrend, near highs, SMA20 tag, orderly pullback, RSI reset, liquidity)
evaluated from daily bars via pandas. Registers with scan orchestrator.
Refs #299."
```

---

## Task 4 — Wire `trend_pullback` into `scanning.py`

**Files:** `backend/app/tasks/scanning.py`

### Step 4.1 — Four edits to `scanning.py`

**Edit A — `_run_range_scan_logic`: add to `scanner_map` and import**

Locate the lazy import block at the top of `_run_range_scan_logic` (around line 77). Add after the pocket_pivot import:

```python
    from app.services.trend_pullback_scan import run_trend_pullback_scan_for_date as _tp_scan
```

Locate the `scanner_map` dict (around line 107). Add the `trend_pullback` entry after `"pocket_pivot"`:

```python
    scanner_map = {
        "pre_market_volume_spike": ScannerService.run_pre_market_scan_for_date,
        "liquidity_hunt": _lh_scan,
        "liquidity_hunt_pre": _lh_scan,
        "liquidity_hunt_post": _lh_scan,
        "oversold_bounce": ScannerService.run_oversold_bounce_scan_for_date,
        "pocket_pivot": _pp_scan,
        "trend_pullback": _tp_scan,   # <-- ADD
    }
```

**Edit B — `_run_universe_scan_logic`: add lazy import for self-registration**

Locate the import block inside `_run_universe_scan_logic` (around line 156). Add after the pocket_pivot import:

```python
        import app.services.trend_pullback_scan  # noqa: F401 — triggers self-registration
```

**Edit C — Add `run_trend_pullback_scheduled` Celery task**

After the `run_pocket_pivot_scheduled` task, add the analogous task:

```python
@celery_app.task(bind=True, max_retries=1, name="app.tasks.run_trend_pullback_scheduled")
def run_trend_pullback_scheduled(self):
    """
    Nightly 02:00 UTC task: run trend_pullback for today's date over all
    active ScannerConfig universes of type 'trend_pullback'.
    """
    from app.models.scanner_config import ScannerConfig
    from app.services.trend_pullback_scan import run_trend_pullback_scan
    from app.utils.session import get_market_today

    _task_name = "run_trend_pullback_scheduled"
    _start = _time.monotonic()
    db: Session = SessionLocal()
    try:
        event_date = get_market_today()
        configs = (
            db.query(ScannerConfig)
            .filter(
                ScannerConfig.scanner_type == "trend_pullback",
                ScannerConfig.is_active.is_(True),
            )
            .all()
        )

        if not configs:
            logger.error(
                "run_trend_pullback_scheduled: no active trend_pullback ScannerConfig "
                "rows found — add a row to scanner_configs with scanner_type='trend_pullback', "
                "is_active=true, and a valid universe_id FK."
            )
            raise RuntimeError("no active trend_pullback scanner configs")

        for cfg in configs:
            if cfg.universe_id is None:
                logger.error(
                    "run_trend_pullback_scheduled: ScannerConfig id=%s has universe_id=NULL",
                    cfg.id,
                )
                raise RuntimeError(f"ScannerConfig id={cfg.id} has universe_id=NULL")

            tickers = [
                ms.ticker
                for ms in db.query(MonitoredStock)
                .filter(
                    MonitoredStock.universe_id == cfg.universe_id,
                    MonitoredStock.is_active.is_(True),
                )
                .all()
            ]
            if not tickers:
                logger.warning(
                    "run_trend_pullback_scheduled: universe_id=%s has no active tickers, "
                    "skipping ScannerConfig id=%s",
                    cfg.universe_id,
                    cfg.id,
                )
                continue

            results = asyncio.run(
                run_trend_pullback_scan(
                    tickers, db, start_date=event_date, end_date=event_date
                )
            )
            logger.info(
                "trend_pullback scheduled scan for universe %s on %s: %d events",
                cfg.universe_id,
                event_date,
                len(results),
            )
        celery_tasks_total.labels(task_name=_task_name, status="success").inc()
    except Exception as exc:
        celery_tasks_total.labels(task_name=_task_name, status="failure").inc()
        logger.exception("run_trend_pullback_scheduled failed: %s", exc)
        raise self.retry(exc=exc)
    finally:
        celery_task_duration_seconds.labels(task_name=_task_name).observe(
            _time.monotonic() - _start
        )
        db.close()
```

**Edit D — Add `"trend_pullback"` to `_BEAT_SCHEDULED_SCANNER_TYPES`**

Locate line 694:

```python
_BEAT_SCHEDULED_SCANNER_TYPES = ["liquidity_hunt", "pocket_pivot"]
```

Change to:

```python
_BEAT_SCHEDULED_SCANNER_TYPES = ["liquidity_hunt", "pocket_pivot", "trend_pullback"]
```

**Edit E — Add beat_schedule entry in `backend/app/core/celery_app.py`**

In `celery_app.conf.beat_schedule`, add after the `"run-pocket-pivot-scan-evening"` entry:

```python
    # Trend pullback scan: runs at 02:00 UTC Mon–Fri (same post-close slot as pocket pivot)
    "run-trend-pullback-scan-evening": {
        "task": "app.tasks.run_trend_pullback_scheduled",
        "schedule": crontab(minute="0", hour="2", day_of_week="1-5"),
    },
```

### Step 4.2 — Verify backend reloads without error

```bash
docker-compose restart backend
sleep 5
docker-compose logs backend --tail=20 | grep -E "error|Error|import|trend_pullback"
# Expected: no import errors; "Application startup complete." present
```

### Step 4.3 — Verify scanner appears in types endpoint

```bash
curl -s http://localhost:8000/api/v1/scanner/types | python -m json.tool | grep trend_pullback
# Expected: "trend_pullback" appears in the list
```

### Step 4.4 — Commit

```bash
git add backend/app/tasks/scanning.py backend/app/core/celery_app.py
git commit -m "feat(tasks): wire trend_pullback into scanner_map, scheduled task, and beat schedule

Adds run_trend_pullback_scheduled Celery task (mirrors run_pocket_pivot_scheduled),
lazy import for orchestrator self-registration, 'trend_pullback' added to
_BEAT_SCHEDULED_SCANNER_TYPES, and run-trend-pullback-scan-evening beat_schedule entry
(02:00 UTC Mon-Fri, same slot as pocket_pivot).
Refs #299."
```

---

## Task 5 — Alembic: seed migration

**Files:**
- `backend/app/alembic/versions/<seed_hash>_seed_trend_pullback_scanner_config.py` (manual)

> **Note:** The migration tree has **one head**: `c7d8e9f0a1b2` (`add_universe_id_to_scanner_configs`). The seed migration uses `down_revision = 'c7d8e9f0a1b2'` directly — no merge migration is needed. The prior seed bug noted in `c7e2a9f4b1d3_activate_pocket_pivot_scanner_config.py` set `is_active=false`; this migration avoids it by seeding `is_active=true`. That same migration also corrected `criteria = '{}'` → `'[]'::json`; this seed uses `'[]'::json` from the start.

### Step 5.1 — Verify single head

```bash
docker-compose exec backend python -m alembic heads
# Expected (1 head): c7d8e9f0a1b2
```

### Step 5.2 — Create seed migration

```bash
docker-compose exec backend python -m alembic revision \
  -m "seed_trend_pullback_scanner_config"
# Expected: creates backend/app/alembic/versions/<seed_hash>_seed_trend_pullback_scanner_config.py
# down_revision will be c7d8e9f0a1b2 (the single current head)
```

Open the generated file and replace the empty `upgrade`/`downgrade` bodies with:

```python
"""seed_trend_pullback_scanner_config

Inserts the scanner_configs row for trend_pullback with is_active=true.
All thresholds are from the spec §1; outcome_config covers 1d/2d/5d/10d.
Columns populated: name (NOT NULL), description, scanner_type (NOT NULL),
parameters (NOT NULL), criteria (NOT NULL, '[]'), is_active, run_frequency,
outcome_config, data_requirements, universe_id (NOT NULL FK → stock_universes.id).

Revision ID: <seed_hash>
Revises: c7d8e9f0a1b2
Create Date: 2026-06-11
"""

import json
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "<seed_hash>"          # filled by alembic
down_revision: str = "c7d8e9f0a1b2"   # single current head
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()

    # Guard: idempotent — skip if already present
    existing = conn.execute(
        sa.text(
            "SELECT id FROM scanner_configs WHERE scanner_type = 'trend_pullback' LIMIT 1"
        )
    ).fetchone()
    if existing:
        return

    # Ensure universe id=1 exists on fresh CI databases (same guard as c7d8e9f0a1b2)
    conn.execute(
        sa.text(
            """
            INSERT INTO stock_universes (id, uuid, name, description, criteria, is_active)
            VALUES (1, gen_random_uuid(), 'Default Universe',
                    'Placeholder created by migration', '{}', true)
            ON CONFLICT (id) DO NOTHING
            """
        )
    )

    conn.execute(
        sa.text(
            """
            INSERT INTO scanner_configs
                (name, description, scanner_type, parameters, criteria,
                 is_active, run_frequency, outcome_config, data_requirements, universe_id)
            VALUES
                (
                    'Trend Pullback (Daily)',
                    'Stocks in confirmed uptrends (close > SMA50 > SMA200, SMA50 rising, '
                    'within 15%% of 252d high) pulling back to the 20-day SMA in an '
                    'orderly way (depth 3-12%%, RSI5 < 40, no close below SMA50).',
                    'trend_pullback',
                    :params,
                    '[]'::json,
                    true,
                    'evening',
                    :outcome_config,
                    :data_requirements,
                    1
                )
            """
        ),
        {
            "params": json.dumps(
                {
                    "trend_sma_fast": 50,
                    "trend_sma_slow": 200,
                    "sma_rising_lookback": 20,
                    "max_pct_off_high": 15,
                    "pullback_sma": 20,
                    "pullback_sma_tolerance_pct": 1,
                    "min_days_above_sma": 5,
                    "pullback_min_pct": 3,
                    "pullback_max_pct": 12,
                    "rsi_period": 5,
                    "rsi_max": 40,
                    "min_dollar_vol": 5_000_000,
                    "min_price": 5.0,
                }
            ),
            "outcome_config": json.dumps(
                {
                    "intervals": ["1d", "2d", "5d", "10d"],
                    "follow_through_threshold_pct": 2.0,
                    "reference_price_source": "opening_price",
                    "extra_metrics": [],
                }
            ),
            "data_requirements": json.dumps(
                {
                    "timespans": [
                        {"timespan": "day", "multiplier": 1, "lookback_days": 265},
                    ]
                }
            ),
        },
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "DELETE FROM scanner_configs WHERE scanner_type = 'trend_pullback' "
            "AND name = 'Trend Pullback (Daily)'"
        )
    )
```

### Step 5.3 — Apply migration and verify

```bash
docker-compose exec backend python -m alembic upgrade head
# Expected:
#   Running upgrade c7d8e9f0a1b2 -> <seed_hash>, seed_trend_pullback_scanner_config
```

Verify the row was inserted:
```bash
docker-compose exec backend python -c "
from app.core.database import SessionLocal
from app.models.scanner_config import ScannerConfig
db = SessionLocal()
cfg = db.query(ScannerConfig).filter(ScannerConfig.scanner_type == 'trend_pullback').first()
print('id:', cfg.id, 'is_active:', cfg.is_active, 'universe_id:', cfg.universe_id)
print('params:', cfg.parameters)
print('outcome_config:', cfg.outcome_config)
db.close()
"
# Expected:
# id: <N> is_active: True universe_id: 1
# params: {trend_sma_fast: 50, trend_sma_slow: 200, ...}
# outcome_config: {intervals: ['1d', '2d', '5d', '10d'], ...}
```

### Step 5.4 — Verify single new head

```bash
docker-compose exec backend python -m alembic current
# Expected: <seed_hash> (head)
```

### Step 5.5 — Verify scanner appears in configs endpoint

```bash
curl -s http://localhost:8000/api/v1/scanner/configs | python -m json.tool | grep -A3 trend_pullback
# Expected: config row with name "Trend Pullback (Daily)", is_active=true
```

### Step 5.6 — Commit

```bash
git add backend/app/alembic/versions/
git commit -m "chore(migrations): seed trend_pullback scanner_configs row

Seed row: is_active=true (avoids prior pocket_pivot is_active=false bug),
down_revision=c7d8e9f0a1b2 (single current head), 13 threshold parameters,
outcome_config (1d/2d/5d/10d), data_requirements, universe_id=1 with
CI-safe ON CONFLICT DO NOTHING guard. criteria='[]'::json per corrected shape.
Refs #299."
```

---

## Task 6 — Live Validation (per CLAUDE.md)

### Step 6.1 — Confirm backend reloaded cleanly

```bash
docker-compose logs backend --tail=15 | grep -E "Application startup|error|ERROR"
# Expected: "Application startup complete." with no errors
```

### Step 6.2 — Hit the scanner configs endpoint

```bash
curl -s http://localhost:8000/api/v1/scanner/configs | python -m json.tool | grep -B2 -A10 trend_pullback
# Expected: full config JSON with is_active=true, 13 parameters, outcome_config with 1d/2d/5d/10d
```

### Step 6.3 — Trigger a historical single-ticker scan

```bash
# POST /run-range (NOT /scan — that endpoint doesn't exist)
# Replace dates with a window that has daily bar data in the DB
curl -s -X POST http://localhost:8000/api/v1/scanner/run-range \
  -H "Content-Type: application/json" \
  -d '{"ticker": "AAPL", "scanner_types": ["trend_pullback"],
       "start_date": "2026-01-01", "end_date": "2026-01-31",
       "fetch_missing_data": false}' | python -m json.tool | head -20
# Expected: HTTP 200, {"task_id": "...", "status": "queued"}
```

Check backend logs for scan execution:
```bash
docker-compose logs backend --tail=30 | grep trend_pullback
# Expected: "trend_pullback scan complete: tickers=1 days=..."
```

### Step 6.4 — Verify alembic is at head

```bash
docker-compose exec backend python -m alembic current
# Expected: <seed_hash> (head)
```

### Step 6.5 — Run full test suite for new tests

```bash
docker-compose exec backend python -m pytest \
  backend/tests/services/test_trend_pullback_scan.py \
  backend/tests/services/test_outcome_service_10d.py -v 2>&1 | tail -20
# Expected: all tests pass
```

### Step 6.6 — Final commit (if any remaining changes)

If there are uncommitted changes after validation:
```bash
git add -p  # stage only intended changes
git commit -m "chore(validation): live-validate trend_pullback scanner — Refs #299"
```

---

## Summary

| Task | Files | Steps | Key Deliverable |
|---|---|---|---|
| 1: 10d interval | `outcome_service.py`, test | 4 | `interval_map["10d"]` recognised |
| 2: event helpers | `event_helpers.py` | 4 | Severity/summary for trend_pullback |
| 3: scanner service | `trend_pullback_scan.py`, test file | 4 | Core logic, 15 unit tests |
| 4: task wiring | `scanning.py`, `celery_app.py` | 5 | scanner_map, scheduled task, beat_schedule entry |
| 5: migrations | seed file | 6 | scanner_configs row, is_active=true, down_revision=c7d8e9f0a1b2 |
| 6: validation | live | 6 | CLAUDE.md compliance |

**Total: 6 tasks, 29 steps**

---

## Memory: Patterns Applied

- **Sync Session**: Daily scanner services (`pocket_pivot.py`, `oversold_bounce_scan.py`) use sync `Session`+`db.query()` inside `async def`. The `[AVOID] sync SQLAlchemy` memory entry targets API routes and ORM lazy loads, not daily scanner services.
- **[PATTERN] `__init__.py` import not required**: `trend_pullback_scan.py` self-registers at import time via `register(...)` at module level; no model file added, so no `__init__.py` edit needed.
- **[FIX] Empty autogenerate migration**: not applicable — this is a data-only seed migration created with `alembic revision` (not `--autogenerate`).
- **[FIX] universe_id FK on fresh DB**: seed migration guards the universe_id=1 row with `ON CONFLICT (id) DO NOTHING` (same pattern as `c7d8e9f0a1b2`).
- **[PATTERN] is_active=true in seed**: the `c7e2a9f4b1d3` migration notes the `is_active=false` bug in the pocket_pivot seed as the issue to avoid; our seed uses `is_active=true` directly.
- **[PATTERN] Single head confirmed**: only `c7d8e9f0a1b2` is the current head; seed uses `down_revision = 'c7d8e9f0a1b2'` directly, no merge migration needed.
- **Celery test pattern**: When testing `run_trend_pullback_scheduled` (bind=True), call `task.run()` with no args, not `task.run(mock_self)`. Patch `get_market_today` at `app.utils.session.get_market_today` (source module), not at the task module level.
