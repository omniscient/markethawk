# Pocket Pivot Scanner — Implementation Plan

**Date:** 2026-06-01
**Issue:** #140
**Spec:** `Docs/superpowers/specs/2026-05-30-pocket-pivot-scanner-design.md`

---

## Goal

Implement the classic Morales/Kacher pocket-pivot scanner: detect trading days where a stock's session volume on an up-day exceeds the highest single down-day volume in the prior 10 trading days. Runs nightly at 02:00 UTC via Celery beat.

## Architecture

**Pattern**: Self-contained module (`pocket_pivot.py`) that self-registers with the scan orchestrator at import time — mirrors `liquidity_hunt.py` and `pre_market_scan.py`.

**Data flow**: Celery beat → `run_pocket_pivot_scheduled` task → `run_pocket_pivot_scan(tickers, db, date)` → `StockAggregate` daily-bar queries → `_save_event()` → `ScannerEvent` row + alert evaluation.

**On-demand**: Already handled by the existing `/api/v1/scanner/run` endpoint once `pocket_pivot` is registered in the orchestrator.

## Tech Stack

- SQLAlchemy ORM (sync `Session`) — `StockAggregate`, `MonitoredStock`, `ScannerConfig`
- Celery beat — nightly `crontab(minute="0", hour="2", day_of_week="1-5")`
- pytest + `unittest.mock` — 12 unit tests using monkeypatching of DB helpers

## File Structure

| File | Change |
|---|---|
| `backend/app/services/pocket_pivot.py` | **NEW** — algorithm + orchestrator self-registration |
| `backend/tests/services/test_pocket_pivot.py` | **NEW** — 12 unit tests |
| `backend/app/alembic/versions/<rev>_seed_pocket_pivot_scanner_config.py` | **NEW** — idempotent seed migration |
| `backend/app/tasks/__init__.py` | **MODIFY** — import + export `run_pocket_pivot_scheduled` |
| `backend/app/tasks/scanning.py` | **MODIFY** — add scheduled task, self-registration import, `scanner_map` entry |
| `backend/app/core/celery_app.py` | **MODIFY** — add beat schedule entry |
| `backend/app/services/scan_orchestrator.py` | **MODIFY** — add `'pocket_pivot'` to `compute_next_run` |

---

## Task 1: Write failing unit tests

**Files:** `backend/tests/services/test_pocket_pivot.py`

### TDD steps

1. **Write the test file** (see code block below)
2. **Verify failure**: `cd backend && python -m pytest tests/services/test_pocket_pivot.py -v 2>&1 | head -20`
   - Expected: `ModuleNotFoundError: No module named 'app.services.pocket_pivot'`
3. **Do not implement yet** — proceed to Task 2

```python
"""Unit tests for the pocket_pivot scanner — 12 scenarios from spec Section 9."""

import asyncio
from datetime import date
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_EVENT_DATE = date(2026, 1, 15)  # Thursday
_TICKERS = ["AAPL"]

_EMPTY_ENRICHMENT: dict[str, Any] = {
    "market_cap": None,
    "outstanding_shares": None,
    "recent_split_date": None,
    "catalyst_tags": [],
    "catalyst_summary": None,
}


def _bar(close: float, volume: int = 200_000) -> MagicMock:
    """Create a minimal bar mock (close + volume)."""
    b = MagicMock()
    b.close = close
    b.volume = volume
    return b


def _make_lookback(closes: list[float], volumes: list[int]) -> list[MagicMock]:
    """Build ascending lookback bars from parallel close/volume lists."""
    return [_bar(c, v) for c, v in zip(closes, volumes)]


# 11-bar fixture: bars[0] = context, bars[1..10] = 10 lookback days.
# Down days: bars[2]=280K, bars[4]=240K, bars[6]=260K, bars[9]=200K → max=280K
_STANDARD_LOOKBACK = _make_lookback(
    closes=[10.00, 10.50, 10.20, 10.40, 10.10, 10.30, 10.00, 10.20, 10.40, 10.30, 10.50],
    volumes=[150_000, 150_000, 280_000, 170_000, 240_000, 180_000, 260_000, 150_000, 130_000, 200_000, 160_000],
)


def _run_scan(
    today_bar: dict | None,
    prior_close: float | None,
    lookback_bars: list,
    enrichment: dict | None = None,
    config: dict | None = None,
    tickers: list[str] = _TICKERS,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Run pocket_pivot scan with mocked DB helpers. Returns (results, diagnostics)."""
    from app.services.pocket_pivot import run_pocket_pivot_scan

    enrichment = enrichment or _EMPTY_ENRICHMENT
    diagnostics: dict[str, Any] = {}

    save_return = {"ticker": tickers[0]} if today_bar else {}

    with (
        patch("app.services.pocket_pivot._get_today_bar", return_value=today_bar),
        patch("app.services.pocket_pivot._get_prior_close", return_value=prior_close),
        patch("app.services.pocket_pivot._get_lookback_bars", return_value=lookback_bars),
        patch("app.services.pocket_pivot._get_enrichment", return_value=enrichment),
        patch("app.services.pocket_pivot._save_event", return_value=save_return) as mock_save,
        patch("app.services.pocket_pivot.scanner_events_total"),
    ):
        results = asyncio.run(
            run_pocket_pivot_scan(
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
# Scenario 1: Clean pocket pivot — all criteria satisfied
# ---------------------------------------------------------------------------
def test_clean_pocket_pivot_fires():
    today = {"close": 14.72, "volume": 350_000}  # 350K > 280K (max down-day)
    results, diag, mock_save = _run_scan(today, prior_close=14.15, lookback_bars=_STANDARD_LOOKBACK)
    assert len(results) == 1
    assert diag["fired"] == 1
    # Verify indicators in _save_event call
    indicators = mock_save.call_args.kwargs["indicators"]
    assert indicators["today_close"] == 14.72
    assert indicators["prior_close"] == 14.15
    assert indicators["today_volume"] == 350_000
    assert indicators["max_down_day_vol"] == 280_000
    assert abs(indicators["volume_over_max_down_pct"] - 0.25) < 0.001
    assert indicators["down_days_in_lookback"] == 4
    assert indicators["lookback_days_available"] == 10
    assert indicators["split_in_lookback"] is False
    assert mock_save.call_args.kwargs["scanner_type"] == "pocket_pivot"


# ---------------------------------------------------------------------------
# Scenario 2: Down day — up-day check fails
# ---------------------------------------------------------------------------
def test_down_day_does_not_fire():
    today = {"close": 13.50, "volume": 350_000}  # 13.50 < prior_close=14.15 → down day
    results, diag, _ = _run_scan(today, prior_close=14.15, lookback_bars=_STANDARD_LOOKBACK)
    assert len(results) == 0
    assert diag["fired"] == 0
    assert diag["evaluated"] == 0


# ---------------------------------------------------------------------------
# Scenario 3: Volume below max down-day — volume criterion fails
# ---------------------------------------------------------------------------
def test_volume_below_max_down_day_does_not_fire():
    today = {"close": 14.72, "volume": 200_000}  # 200K < 280K (max down-day)
    results, diag, _ = _run_scan(today, prior_close=14.15, lookback_bars=_STANDARD_LOOKBACK)
    assert len(results) == 0
    assert diag["fired"] == 0


# ---------------------------------------------------------------------------
# Scenario 4: Volume exactly equals max down-day — strict inequality requires >
# ---------------------------------------------------------------------------
def test_volume_equals_max_down_day_does_not_fire():
    today = {"close": 14.72, "volume": 280_000}  # 280K == 280K — strict > fails
    results, diag, _ = _run_scan(today, prior_close=14.15, lookback_bars=_STANDARD_LOOKBACK)
    assert len(results) == 0
    assert diag["fired"] == 0


# ---------------------------------------------------------------------------
# Scenario 5: Below price floor ($4.50 < $5.00)
# ---------------------------------------------------------------------------
def test_below_price_floor_does_not_fire():
    today = {"close": 4.50, "volume": 350_000}  # up day but below price floor
    results, diag, _ = _run_scan(today, prior_close=4.20, lookback_bars=_STANDARD_LOOKBACK)
    assert len(results) == 0
    assert diag["fired"] == 0


# ---------------------------------------------------------------------------
# Scenario 6: Below volume floor (80K shares < 100K floor)
# Requires max_down_day_vol < 80K so volume criterion passes before floor check.
# Use a lookback where all down-day volumes are 60K.
# ---------------------------------------------------------------------------
def test_below_volume_floor_does_not_fire():
    lookback = _make_lookback(
        closes=[10.00, 10.50, 10.20, 10.40, 10.10, 10.30, 10.00, 10.20, 10.40, 10.30, 10.50],
        volumes=[50_000, 50_000, 60_000, 50_000, 60_000, 50_000, 55_000, 50_000, 50_000, 55_000, 50_000],
    )
    today = {"close": 14.72, "volume": 80_000}  # 80K > 60K (volume criterion passes), 80K < 100K (floor fails)
    results, diag, _ = _run_scan(today, prior_close=14.15, lookback_bars=lookback)
    assert len(results) == 0
    assert diag["fired"] == 0


# ---------------------------------------------------------------------------
# Scenario 7: Fewer than 5 prior trading days of data
# _get_lookback_bars returns 4 bars → len < min_lookback_days + 1 → skip
# ---------------------------------------------------------------------------
def test_insufficient_lookback_days_does_not_fire():
    short_lookback = _make_lookback(
        closes=[10.00, 10.20, 10.10, 10.30],
        volumes=[200_000, 180_000, 220_000, 190_000],
    )
    today = {"close": 14.72, "volume": 350_000}
    results, diag, _ = _run_scan(today, prior_close=14.15, lookback_bars=short_lookback)
    assert len(results) == 0
    assert diag["no_baseline"] == 1


# ---------------------------------------------------------------------------
# Scenario 8: No down days in lookback — all prior 10 days were up days
# ---------------------------------------------------------------------------
def test_no_down_days_does_not_fire():
    # 11 strictly ascending bars → all 10 lookback days are up days
    all_up = _make_lookback(
        closes=[10.00, 10.10, 10.20, 10.30, 10.40, 10.50, 10.60, 10.70, 10.80, 10.90, 11.00],
        volumes=[200_000] * 11,
    )
    today = {"close": 11.20, "volume": 350_000}
    results, diag, _ = _run_scan(today, prior_close=11.00, lookback_bars=all_up)
    assert len(results) == 0
    assert diag["no_down_days"] == 1


# ---------------------------------------------------------------------------
# Scenario 9: Stock split within lookback window → fires with split_in_lookback=True
# ---------------------------------------------------------------------------
def test_split_in_lookback_fires_with_flag():
    enrichment = {
        **_EMPTY_ENRICHMENT,
        "recent_split_date": "2026-01-05",  # 10 days before event_date 2026-01-15, within 28 days
    }
    today = {"close": 14.72, "volume": 350_000}
    results, diag, mock_save = _run_scan(
        today, prior_close=14.15, lookback_bars=_STANDARD_LOOKBACK, enrichment=enrichment
    )
    assert len(results) == 1
    indicators = mock_save.call_args.kwargs["indicators"]
    assert indicators["split_in_lookback"] is True


# ---------------------------------------------------------------------------
# Scenario 10: Near IPO with exactly 5 prior days — proceeds with lookback_days_available=5
# 6 bars total: bars[0]=context, bars[1..5]=5 lookback days; some are down days.
# ---------------------------------------------------------------------------
def test_near_ipo_with_5_days_fires():
    # bars[0]=context(10.50), bars[1]=10.60 UP, bars[2]=10.40 DOWN(280K),
    # bars[3]=10.50 UP, bars[4]=10.30 DOWN(240K), bars[5]=10.50 UP
    ipo_lookback = _make_lookback(
        closes=[10.50, 10.60, 10.40, 10.50, 10.30, 10.50],
        volumes=[150_000, 150_000, 280_000, 180_000, 240_000, 160_000],
    )
    today = {"close": 14.72, "volume": 350_000}  # 350K > 280K ✓
    results, diag, mock_save = _run_scan(today, prior_close=14.15, lookback_bars=ipo_lookback)
    assert len(results) == 1
    indicators = mock_save.call_args.kwargs["indicators"]
    assert indicators["lookback_days_available"] == 5


# ---------------------------------------------------------------------------
# Scenario 11: Missing today's daily bar → skip, counted in no_today_bar
# ---------------------------------------------------------------------------
def test_missing_today_bar_does_not_fire():
    results, diag, _ = _run_scan(
        today_bar=None, prior_close=14.15, lookback_bars=_STANDARD_LOOKBACK
    )
    assert len(results) == 0
    assert diag["no_today_bar"] == 1


# ---------------------------------------------------------------------------
# Scenario 12: diagnostics_out populated — 3 tickers, 2 fire, 1 fails volume criterion
# ---------------------------------------------------------------------------
def test_diagnostics_populated_correctly():
    from app.services.pocket_pivot import run_pocket_pivot_scan

    tickers = ["AAPL", "MSFT", "GOOG"]

    def today_bar_side_effect(db, ticker, event_date):
        # All 3 tickers have today's bar
        return {"close": 14.72, "volume": 350_000}

    def prior_close_side_effect(db, ticker, event_date):
        return 14.15  # all are up days

    def lookback_side_effect(db, ticker, event_date, lookback_days):
        return _STANDARD_LOOKBACK

    def enrichment_side_effect(db, ticker, event_date):
        return _EMPTY_ENRICHMENT

    save_count = 0

    def save_side_effect(db, ticker, **kwargs):
        nonlocal save_count
        if ticker == "GOOG":
            # GOOG: volume criterion fails (we force volume <= max_down for GOOG via config override)
            # but our mocks return the same today_bar for all tickers.
            # Solution: make GOOG fail at the volume criterion by returning a different today_bar.
            pass
        save_count += 1
        return {"ticker": ticker}

    # Use a different approach: return different today_bar per ticker
    def today_bar_per_ticker(db, ticker, event_date):
        if ticker == "GOOG":
            # volume = 280K = max_down_day_vol → strict > fails (no fire)
            return {"close": 14.72, "volume": 280_000}
        return {"close": 14.72, "volume": 350_000}

    diagnostics: dict[str, Any] = {}

    with (
        patch("app.services.pocket_pivot._get_today_bar", side_effect=today_bar_per_ticker),
        patch("app.services.pocket_pivot._get_prior_close", side_effect=prior_close_side_effect),
        patch("app.services.pocket_pivot._get_lookback_bars", side_effect=lookback_side_effect),
        patch("app.services.pocket_pivot._get_enrichment", side_effect=enrichment_side_effect),
        patch("app.services.pocket_pivot._save_event", return_value={"ticker": "X"}),
        patch("app.services.pocket_pivot.scanner_events_total"),
    ):
        results = asyncio.run(
            run_pocket_pivot_scan(
                tickers,
                db=MagicMock(),
                start_date=_EVENT_DATE,
                end_date=_EVENT_DATE,
                diagnostics_out=diagnostics,
            )
        )

    assert len(results) == 2
    assert diagnostics["evaluated"] == 3  # all 3 had data and were up days
    assert diagnostics["fired"] == 2      # GOOG fails volume criterion
    assert diagnostics["tickers"] == 3
    assert diagnostics["days"] == 1
```

**Commit**: _not yet — proceed to Task 2 first_

---

## Task 2: Implement the core scanner module

**Files:** `backend/app/services/pocket_pivot.py`

### TDD steps

1. **Create the file** with the implementation below
2. **Run tests**: `cd backend && python -m pytest tests/services/test_pocket_pivot.py -v`
   - Expected: all 12 pass
3. **Commit**:
   ```bash
   git add backend/app/services/pocket_pivot.py backend/tests/services/test_pocket_pivot.py
   git commit -m "feat(scanner): add pocket pivot scanner service and unit tests"
   ```

```python
"""
Pocket Pivot Scanner

Detects up-days where session volume exceeds the highest down-day volume
in the prior 10 trading days (classic Morales/Kacher pocket pivot).

Runs nightly at 02:00 UTC Mon-Fri via Celery beat (same slot as liquidity_hunt).
Self-registers with the scan orchestrator at import time.
"""

from __future__ import annotations

import logging
import time as _time
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Optional
from zoneinfo import ZoneInfo

from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.core.metrics import scan_duration_seconds, scanner_events_total
from app.models.monitored_stock import MonitoredStock
from app.models.stock_aggregate import StockAggregate
from app.models.stock_split import StockSplit
from app.models.ticker_reference import TickerReference
from app.services.alert_service import save_event as _save_event
from app.services.catalyst_parser import CatalystParser
from app.utils.session import get_market_today

_ET = ZoneInfo("America/New_York")
_LOG = logging.getLogger(__name__)

DEFAULT_CONFIG: dict[str, Any] = {
    "lookback_days": 10,       # prior trading days examined for down-day volumes
    "min_lookback_days": 5,    # minimum classifiable days required to proceed
    "price_floor": 5.00,       # minimum closing price (USD)
    "volume_floor": 100_000,   # minimum session volume (shares)
}


def _get_today_bar(db: Session, ticker: str, event_date: date) -> dict[str, Any] | None:
    """Fetch the daily bar for ticker on event_date. Returns None if not found."""
    day_start_utc = (
        datetime.combine(event_date, time.min, tzinfo=_ET)
        .astimezone(timezone.utc)
        .replace(tzinfo=None)
    )
    day_end_utc = (
        datetime.combine(event_date + timedelta(days=1), time.min, tzinfo=_ET)
        .astimezone(timezone.utc)
        .replace(tzinfo=None)
    )
    row = (
        db.query(StockAggregate)
        .filter(
            StockAggregate.ticker == ticker,
            StockAggregate.timespan == "day",
            StockAggregate.timestamp >= day_start_utc,
            StockAggregate.timestamp < day_end_utc,
        )
        .first()
    )
    if row is None:
        return None
    return {"close": float(row.close), "volume": int(row.volume)}


def _get_prior_close(db: Session, ticker: str, event_date: date) -> float | None:
    """Fetch the most recent daily-bar close strictly before event_date."""
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
    return float(row[0]) if row else None


def _get_lookback_bars(
    db: Session, ticker: str, event_date: date, lookback_days: int
) -> list:
    """
    Fetch up to lookback_days+1 daily bars before event_date (ascending).
    The first bar provides a prior-close for classifying the oldest lookback day.
    """
    day_start_utc = (
        datetime.combine(event_date, time.min, tzinfo=_ET)
        .astimezone(timezone.utc)
        .replace(tzinfo=None)
    )
    rows = (
        db.query(StockAggregate)
        .filter(
            StockAggregate.ticker == ticker,
            StockAggregate.timespan == "day",
            StockAggregate.timestamp < day_start_utc,
        )
        .order_by(desc(StockAggregate.timestamp))
        .limit(lookback_days + 1)
        .all()
    )
    rows.reverse()  # ascending: oldest first
    return rows


def _classify_down_days(bars: list, lookback_days: int) -> list[int]:
    """
    Return volumes of down days within the lookback window.

    bars is in ascending order (oldest first). The function takes the last
    lookback_days bars as the window. Each bar is compared to its immediate
    predecessor in the full bars list. Bars with no predecessor are skipped.
    """
    if len(bars) < 2:
        return []
    lookback_bars = bars[-lookback_days:]
    down_volumes: list[int] = []
    for i, bar in enumerate(lookback_bars):
        preceding_idx = len(bars) - len(lookback_bars) + i - 1
        if preceding_idx < 0:
            continue
        preceding_close = float(bars[preceding_idx].close)
        if float(bar.close) < preceding_close:
            down_volumes.append(int(bar.volume))
    return down_volumes


def _get_enrichment(db: Session, ticker: str, event_date: date) -> dict[str, Any]:
    """Fetch split, market-cap, float, and catalyst enrichment. Mirrors liquidity_hunt."""
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
    outstanding = (
        float(ref.share_class_shares_outstanding)
        if ref and ref.share_class_shares_outstanding
        else None
    )
    return {
        "market_cap": float(monitored.market_cap)
        if monitored and monitored.market_cap
        else None,
        "outstanding_shares": outstanding,
        "recent_split_date": recent_split.execution_date.isoformat()
        if recent_split
        else None,
        "catalyst_tags": cat.get("tags", []),
        "catalyst_summary": cat.get("summary"),
    }


async def run_pocket_pivot_scan(
    tickers: list[str],
    db: Session,
    start_date: date | None = None,
    end_date: date | None = None,
    config: dict | None = None,
    diagnostics_out: dict | None = None,
) -> list[dict[str, Any]]:
    """
    Run the pocket pivot scanner over a date range.

    For each (ticker, event_date):
      1. Fetch today's daily bar (close, volume).
      2. Fetch prior day's close; check up-day condition.
      3. Fetch lookback bars; classify down days.
      4. Check volume criterion (today_vol > max_down_day_vol, strict).
      5. Apply materiality floors (price, volume).
      6. Persist ScannerEvent if all criteria pass.
    """
    _perf_start = _time.monotonic()

    if start_date is None and end_date is None:
        start_date = end_date = get_market_today()
    elif start_date is None:
        start_date = end_date
    elif end_date is None:
        end_date = start_date

    cfg: dict[str, Any] = {**DEFAULT_CONFIG, **(config or {})}
    lookback_days: int = int(cfg["lookback_days"])
    min_lookback_days: int = int(cfg["min_lookback_days"])
    price_floor: float = float(cfg["price_floor"])
    volume_floor: int = int(cfg["volume_floor"])

    results: list[dict[str, Any]] = []
    counts = {
        "no_today_bar": 0,
        "no_prior_close": 0,
        "no_baseline": 0,
        "no_down_days": 0,
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
                today = _get_today_bar(db, ticker, event_date)
                if today is None:
                    counts["no_today_bar"] += 1
                    continue

                prior_close = _get_prior_close(db, ticker, event_date)
                if prior_close is None:
                    counts["no_prior_close"] += 1
                    continue

                # Up-day check
                if today["close"] < prior_close:
                    continue

                # Lookback bars: need min_lookback_days classifiable bars (+1 context)
                lookback_bars = _get_lookback_bars(db, ticker, event_date, lookback_days)
                if len(lookback_bars) < min_lookback_days + 1:
                    counts["no_baseline"] += 1
                    continue

                down_volumes = _classify_down_days(lookback_bars, lookback_days)
                if not down_volumes:
                    counts["no_down_days"] += 1
                    continue

                # All required data confirmed — count as evaluated before criteria checks
                # (matches liquidity_hunt.py convention: evaluated = "had data to assess")
                counts["evaluated"] += 1

                max_down_day_vol = max(down_volumes)

                # Volume criterion (strict) and materiality floors
                if today["volume"] <= max_down_day_vol:
                    continue
                if today["close"] < price_floor:
                    continue
                if today["volume"] < volume_floor:
                    continue

                try:
                    enrichment = _get_enrichment(db, ticker, event_date)
                except Exception:
                    _LOG.warning(
                        "Enrichment failed for %s on %s; proceeding with empty enrichment",
                        ticker,
                        event_date,
                        exc_info=True,
                    )
                    enrichment = {
                        "market_cap": None,
                        "outstanding_shares": None,
                        "recent_split_date": None,
                        "catalyst_tags": [],
                        "catalyst_summary": None,
                    }

                lookback_days_available = min(len(lookback_bars) - 1, lookback_days)

                split_in_lookback = False
                if enrichment.get("recent_split_date"):
                    split_dt = date.fromisoformat(enrichment["recent_split_date"])
                    if (event_date - split_dt).days <= 28:
                        split_in_lookback = True

                up_day_pct = round(
                    (today["close"] - prior_close) / prior_close, 4
                ) if prior_close > 0 else 0.0
                volume_over_max_down_pct = round(
                    today["volume"] / max_down_day_vol - 1.0, 4
                )

                indicators: dict[str, Any] = {
                    "today_close": today["close"],
                    "prior_close": prior_close,
                    "up_day_pct": up_day_pct,
                    "today_volume": today["volume"],
                    "max_down_day_vol": max_down_day_vol,
                    "volume_over_max_down_pct": volume_over_max_down_pct,
                    "down_days_in_lookback": len(down_volumes),
                    "lookback_days_available": lookback_days_available,
                    "volume_floor": volume_floor,
                    "price_floor": price_floor,
                    "split_in_lookback": split_in_lookback,
                }

                criteria_met: dict[str, bool] = {
                    "up_day": True,
                    "volume_over_max_down": True,
                    "price_floor": True,
                    "volume_floor": True,
                }

                event_dict = _save_event(
                    db=db,
                    ticker=ticker,
                    event_date=event_date,
                    scanner_type="pocket_pivot",
                    indicators=indicators,
                    criteria_met=criteria_met,
                    enrichment=enrichment,
                    previous_close=prior_close,
                    closing_price=today["close"],
                )
                results.append(event_dict)
                counts["fired"] += 1
                scanner_events_total.labels(scanner_type="pocket_pivot").inc()

            except Exception:
                counts["errors"] += 1
                _LOG.exception(
                    "Error in pocket_pivot scan for %s on %s", ticker, event_date
                )

    _LOG.info(
        "pocket_pivot scan complete: tickers=%d days=%d "
        "dropped=(no_today_bar:%d no_prior_close:%d no_baseline:%d no_down_days:%d) "
        "evaluated=%d fired=%d errors=%d",
        len(tickers),
        len(trading_days),
        counts["no_today_bar"],
        counts["no_prior_close"],
        counts["no_baseline"],
        counts["no_down_days"],
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
                "no_today_bar": counts["no_today_bar"],
                "no_prior_close": counts["no_prior_close"],
                "no_baseline": counts["no_baseline"],
                "no_down_days": counts["no_down_days"],
                "evaluated": counts["evaluated"],
                "fired": counts["fired"],
                "errors": counts["errors"],
            }
        )

    scan_duration_seconds.labels(scanner_type="pocket_pivot").observe(
        _time.monotonic() - _perf_start
    )
    return results


# ── Orchestrator self-registration ────────────────────────────────────────────

from app.services.scan_orchestrator import ScannerDescriptor, register  # noqa: E402


async def _orchestrator_run(
    tickers: list,
    db: Any,
    event_date: date,
    scanner_run: Optional[Any] = None,
) -> list[dict]:
    """Adapter: maps the standard ScannerFn signature to run_pocket_pivot_scan."""
    return await run_pocket_pivot_scan(
        tickers=tickers,
        db=db,
        start_date=event_date,
        end_date=event_date,
    )


register(
    ScannerDescriptor(
        key="pocket_pivot",
        display_name="Pocket Pivot",
        description=(
            "Detects up-days where session volume exceeds the highest "
            "down-day volume in the prior 10 trading days "
            "(classic Morales/Kacher pocket pivot)."
        ),
        run=_orchestrator_run,
        supports_date_range=True,
    )
)
```

Also add a single-ticker/date wrapper after `run_pocket_pivot_scan` (needed by `run_range_scan`'s hardcoded `scanner_map`):

```python
async def run_pocket_pivot_scan_for_date(
    ticker: str,
    event_date: date,
    db: Session,
) -> list[dict[str, Any]]:
    """Single-ticker single-date wrapper used by run_range_scan's scanner_map."""
    return await run_pocket_pivot_scan(
        [ticker], db, start_date=event_date, end_date=event_date
    )
```

**Verification:**
```bash
cd backend && python -m pytest tests/services/test_pocket_pivot.py -v
# Expected: 12 passed
```

**Commit:**
```bash
git add backend/app/services/pocket_pivot.py backend/tests/services/test_pocket_pivot.py
git commit -m "feat(scanner): add pocket pivot scanner service and unit tests"
```

---

## Task 3: Add Celery scheduled task, self-registration import, and scanner_map entry

**Files:** `backend/app/tasks/__init__.py`, `backend/app/tasks/scanning.py`

### TDD steps

1. **Run existing tests to establish baseline**: `cd backend && python -m pytest tests/ -v --tb=short -q`
2. **Apply changes** (four edits across two files):
   - Update `tasks/__init__.py` to import/export `run_pocket_pivot_scheduled`
   - Add `import app.services.pocket_pivot` inside `run_universe_scan` function body
   - Add `"pocket_pivot"` to `run_range_scan`'s `scanner_map`
   - Add `run_pocket_pivot_scheduled` task at end of `scanning.py`
3. **Run tests again**: same command — expected: no regressions
4. **Commit**

#### Edit 0 — update `backend/app/tasks/__init__.py`

Celery discovers tasks via `include=["app.tasks"]`, which imports `app/tasks/__init__.py`. The scheduled task must be imported there.

Find:
```python
from app.tasks.scanning import (
    evaluate_scanner_alerts,
    run_liquidity_hunt_scheduled,
    run_range_scan,
    run_universe_scan,
)
```

Replace with:
```python
from app.tasks.scanning import (
    evaluate_scanner_alerts,
    run_liquidity_hunt_scheduled,
    run_pocket_pivot_scheduled,
    run_range_scan,
    run_universe_scan,
)
```

Then find the scanning section of `__all__`:
```python
    # scanning
    "evaluate_scanner_alerts",
    "run_range_scan",
    "run_liquidity_hunt_scheduled",
    "run_universe_scan",
```

Replace with:
```python
    # scanning
    "evaluate_scanner_alerts",
    "run_range_scan",
    "run_liquidity_hunt_scheduled",
    "run_pocket_pivot_scheduled",
    "run_universe_scan",
```

#### Edit 1 — add self-registration import inside `run_universe_scan` function body

These imports are **inside the `run_universe_scan` function body** (not at module level — Celery tasks use lazy imports to avoid circular dependencies). Find this block:

```python
    import app.services.liquidity_hunt  # noqa: F401
    import app.services.oversold_bounce_scan  # noqa: F401
    import app.services.pre_market_scan  # noqa: F401 — triggers self-registration
```

Replace with:
```python
    import app.services.liquidity_hunt  # noqa: F401
    import app.services.oversold_bounce_scan  # noqa: F401
    import app.services.pre_market_scan  # noqa: F401 — triggers self-registration
    import app.services.pocket_pivot  # noqa: F401 — triggers self-registration
```

#### Edit 2 — add `pocket_pivot` to `run_range_scan`'s `scanner_map`

`run_range_scan` has a hardcoded `scanner_map` for the legacy single-ticker range endpoint. Find:

```python
        from app.services.liquidity_hunt import run_liquidity_hunt_scan_for_date as _lh_scan
```

Replace with:
```python
        from app.services.liquidity_hunt import run_liquidity_hunt_scan_for_date as _lh_scan
        from app.services.pocket_pivot import run_pocket_pivot_scan_for_date as _pp_scan
```

Then find the `scanner_map` dict:
```python
        scanner_map = {
            "pre_market_volume_spike": ScannerService.run_pre_market_scan_for_date,
            "liquidity_hunt": _lh_scan,
            "liquidity_hunt_pre": _lh_scan,
            "liquidity_hunt_post": _lh_scan,
            "oversold_bounce": ScannerService.run_oversold_bounce_scan_for_date,
        }
```

Replace with:
```python
        scanner_map = {
            "pre_market_volume_spike": ScannerService.run_pre_market_scan_for_date,
            "liquidity_hunt": _lh_scan,
            "liquidity_hunt_pre": _lh_scan,
            "liquidity_hunt_post": _lh_scan,
            "oversold_bounce": ScannerService.run_oversold_bounce_scan_for_date,
            "pocket_pivot": _pp_scan,
        }
```

#### Edit 3 — add scheduled task at end of `scanning.py`

Append after the last task in the file:

```python
@celery_app.task(
    bind=True, max_retries=1, name="app.tasks.run_pocket_pivot_scheduled"
)
def run_pocket_pivot_scheduled(self):
    """
    Nightly 02:00 UTC task: run pocket_pivot for today's date over all active
    ScannerConfig universes of type 'pocket_pivot'.
    """
    from app.models.scanner_config import ScannerConfig
    from app.services.pocket_pivot import run_pocket_pivot_scan
    from app.utils.session import get_market_today

    _task_name = "run_pocket_pivot_scheduled"
    _start = _time.monotonic()
    db: Session = SessionLocal()
    try:
        event_date = get_market_today()
        configs = (
            db.query(ScannerConfig)
            .filter(
                ScannerConfig.scanner_type == "pocket_pivot",
                ScannerConfig.is_active.is_(True),
            )
            .all()
        )

        for cfg in configs:
            universe_id = cfg.parameters.get("universe_id")
            if not universe_id:
                logger.warning(
                    "pocket_pivot ScannerConfig %s has no universe_id", cfg.id
                )
                continue

            tickers = [
                ms.ticker
                for ms in db.query(MonitoredStock)
                .filter(
                    MonitoredStock.universe_id == universe_id,
                    MonitoredStock.is_active.is_(True),
                )
                .all()
            ]
            if not tickers:
                continue

            results = asyncio.run(
                run_pocket_pivot_scan(
                    tickers, db, start_date=event_date, end_date=event_date
                )
            )
            logger.info(
                "pocket_pivot scheduled scan for universe %s on %s: %d events",
                universe_id,
                event_date,
                len(results),
            )
        celery_tasks_total.labels(task_name=_task_name, status="success").inc()
    except Exception as exc:
        celery_tasks_total.labels(task_name=_task_name, status="failure").inc()
        logger.exception("run_pocket_pivot_scheduled failed: %s", exc)
        raise self.retry(exc=exc)
    finally:
        celery_task_duration_seconds.labels(task_name=_task_name).observe(
            _time.monotonic() - _start
        )
        db.close()
```

**Verification:**
```bash
cd backend && python -m pytest tests/ -q --tb=short 2>&1 | tail -5
# Expected: no new failures
```

**Commit:**
```bash
git add backend/app/tasks/__init__.py backend/app/tasks/scanning.py
git commit -m "feat(scanner): add run_pocket_pivot_scheduled task and scanner_map entry"
```

---

## Task 4: Register nightly beat schedule

**Files:** `backend/app/core/celery_app.py`

### TDD steps

1. **Read the file** (already reviewed)
2. **Apply edit** — add entry to `beat_schedule` after the liquidity hunt entry
3. **Verify syntax**: `cd backend && python -c "from app.core.celery_app import celery_app; print('OK')"`
4. **Commit**

In `backend/app/core/celery_app.py`, find:
```python
    # Liquidity hunt scan: runs at 02:00 UTC Mon–Fri
    # After-market closes 20:00 ET; 02:00 UTC = 21:00 EST (winter) / 22:00 EDT (summer) — always post-close.
    "run-liquidity-hunt-scan-evening": {
        "task": "app.tasks.run_liquidity_hunt_scheduled",
        "schedule": crontab(minute="0", hour="2", day_of_week="1-5"),
    },
```

Add immediately after:
```python
    # Pocket pivot scan: runs at 02:00 UTC Mon–Fri (same post-close slot as liquidity hunt)
    "run-pocket-pivot-scan-evening": {
        "task": "app.tasks.run_pocket_pivot_scheduled",
        "schedule": crontab(minute="0", hour="2", day_of_week="1-5"),
    },
```

**Verification:**
```bash
cd backend && python -c "from app.core.celery_app import celery_app; print(list(celery_app.conf.beat_schedule.keys()))"
# Expected output includes 'run-pocket-pivot-scan-evening'
```

**Commit:**
```bash
git add backend/app/core/celery_app.py
git commit -m "feat(scheduler): register pocket pivot nightly Celery beat job at 02:00 UTC"
```

---

## Task 5: Update orchestrator compute_next_run

**Files:** `backend/app/services/scan_orchestrator.py`

### TDD steps

1. **Apply edit** — add `'pocket_pivot'` to the scheduled-type set in `compute_next_run`
2. **Run orchestrator tests**: `cd backend && python -m pytest tests/services/test_scan_orchestrator.py -v`
3. **Verify manually**:
   ```bash
   cd backend && python -c "
   from app.services.scan_orchestrator import compute_next_run
   print(compute_next_run('pocket_pivot'))  # should print a datetime
   print(compute_next_run('oversold_bounce'))  # should print None
   "
   ```
4. **Commit**

In `backend/app/services/scan_orchestrator.py`, find:
```python
    if scanner_type not in {
        "liquidity_hunt",
        "liquidity_hunt_pre",
        "liquidity_hunt_post",
    }:
        return None
```

Replace with:
```python
    if scanner_type not in {
        "liquidity_hunt",
        "liquidity_hunt_pre",
        "liquidity_hunt_post",
        "pocket_pivot",
    }:
        return None
```

**Verification:**
```bash
cd backend && python -m pytest tests/services/test_scan_orchestrator.py -v
# Expected: all pass (no regressions)
```

**Commit:**
```bash
git add backend/app/services/scan_orchestrator.py
git commit -m "feat(orchestrator): add pocket_pivot to compute_next_run scheduled types"
```

---

## Task 6: Alembic seed migration

**Files:** `backend/app/alembic/versions/<rev>_seed_pocket_pivot_scanner_config.py`

### TDD steps

1. **Generate the migration file** (the repo has two Alembic heads; `--head` pins to the correct branch):
   ```bash
   cd backend && python -m alembic revision --head 0b4b1c3739b4 -m "seed_pocket_pivot_scanner_config"
   # Note the generated revision ID (e.g. f1b2c3d4e567)
   ```
2. **Open the generated file** and replace its content with the implementation below  
   (substituting the actual `revision` and `down_revision` values printed by alembic)
3. **Apply the migration**:
   ```bash
   cd backend && python -m alembic upgrade head
   # Expected: Running upgrade <prev> -> <rev>, seed_pocket_pivot_scanner_config
   ```
4. **Verify**:
   ```bash
   docker-compose exec backend python -c "
   from app.core.database import SessionLocal
   from app.models.scanner_config import ScannerConfig
   db = SessionLocal()
   cfg = db.query(ScannerConfig).filter(ScannerConfig.scanner_type == 'pocket_pivot').first()
   print(cfg.name, cfg.parameters)
   db.close()
   "
   # Expected: Pocket Pivot (Evening) {'lookback_days': 10, 'min_lookback_days': 5, ...}
   ```
5. **Confirm idempotency** (re-run upgrade — should be a no-op):
   ```bash
   cd backend && python -m alembic upgrade head
   # Expected: no error, no new rows inserted
   ```
6. **Commit**:
   ```bash
   git add backend/app/alembic/versions/<rev>_seed_pocket_pivot_scanner_config.py
   git commit -m "feat(migration): seed default pocket_pivot ScannerConfig row"
   ```

```python
"""seed_pocket_pivot_scanner_config

Revision ID: <generated-by-alembic>
Revises: 0b4b1c3739b4
Create Date: 2026-06-01 ...

"""

import json
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers — filled in by alembic
revision: str = "<generated-by-alembic>"
down_revision: Union[str, None] = "0b4b1c3739b4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    existing = conn.execute(
        sa.text(
            "SELECT id FROM scanner_configs WHERE scanner_type = 'pocket_pivot' LIMIT 1"
        )
    ).fetchone()
    if existing:
        return

    conn.execute(
        sa.text("""
            INSERT INTO scanner_configs
                (name, description, scanner_type, parameters, criteria, is_active, run_frequency)
            VALUES
                (
                    'Pocket Pivot (Evening)',
                    'Detects up-days where session volume exceeds the highest down-day volume in the prior 10 trading days (classic Morales/Kacher pocket pivot).',
                    'pocket_pivot',
                    :params,
                    :criteria,
                    false,
                    'evening'
                )
        """),
        {
            "params": json.dumps(
                {
                    "lookback_days": 10,
                    "min_lookback_days": 5,
                    "price_floor": 5.00,
                    "volume_floor": 100000,
                }
            ),
            "criteria": json.dumps({}),
        },
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "DELETE FROM scanner_configs WHERE scanner_type = 'pocket_pivot' AND name = 'Pocket Pivot (Evening)'"
        )
    )
```

> **Note:** `is_active` defaults to `false` so the nightly job skips it until an admin explicitly enables it for a specific universe by setting `universe_id` in `parameters` and flipping `is_active = true`. This matches the liquidity_hunt seed pattern.

---

## Integration Validation (post-commit)

Per `CLAUDE.md` development rules — after all commits:

1. **Confirm backend reloaded:**
   ```bash
   docker-compose logs backend --tail=10
   # Expected: no import errors, no tracebacks
   ```

2. **Verify orchestrator registration:**
   ```bash
   curl -s http://localhost:8000/api/v1/scanner/types | python -m json.tool | grep pocket_pivot
   # Expected: "pocket_pivot" in the list
   ```

3. **Run an on-demand scan** against a known historical date with a ticker likely to have pocket pivots:
   ```bash
   curl -s -X POST http://localhost:8000/api/v1/scanner/run \
     -H "Content-Type: application/json" \
     -d '{"scanner_type": "pocket_pivot", "universe_id": 1, "start_date": "2025-11-01", "end_date": "2025-11-30"}' \
     | python -m json.tool
   ```

4. **Confirm ScannerEvent rows exist** with the correct indicator shape:
   ```bash
   docker-compose exec backend python -c "
   from app.core.database import SessionLocal
   from app.models.scanner_event import ScannerEvent
   db = SessionLocal()
   events = db.query(ScannerEvent).filter(ScannerEvent.scanner_type == 'pocket_pivot').limit(3).all()
   for e in events:
       print(e.ticker, e.event_date, e.indicators.keys())
   db.close()
   "
   # Expected: indicators has today_close, today_volume, max_down_day_vol, etc.
   ```

5. **Check Flower for scheduled task registration** at `http://localhost:5555`.

---

## Summary

| Task | Files | Steps |
|---|---|---|
| 1 | `test_pocket_pivot.py` | Write 12 failing tests |
| 2 | `pocket_pivot.py` | Implement scanner; all 12 tests pass |
| 3 | `tasks/__init__.py` + `scanning.py` | Add scheduled task, self-reg import, `scanner_map` entry, `__init__` export |
| 4 | `celery_app.py` | Register beat schedule entry |
| 5 | `scan_orchestrator.py` | Add `pocket_pivot` to `compute_next_run` |
| 6 | `alembic/versions/<rev>_...py` | Seed migration + `alembic upgrade head` |

**Total tasks:** 6  
**Total steps:** 21
