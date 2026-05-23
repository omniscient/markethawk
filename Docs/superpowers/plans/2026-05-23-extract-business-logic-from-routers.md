# Extract Business Logic from Scanner, Universe, and Stocks Routers

**Date:** 2026-05-23  
**Issue:** #62  
**Spec:** `Docs/superpowers/specs/2026-05-23-extract-business-logic-from-routers-design.md`

---

## Goal

Move domain logic (concurrency guard, date defaulting, ticker count validation, universe stats, asset class check, data enrichment) out of three FastAPI route handlers into service classes. After this refactor the three business logic units are exercisable via plain function calls — no HTTP client needed.

## Architecture

Pure extraction — no behaviour changes, no DB schema changes. Routers become thin HTTP-to-module adapters. Three tasks, each following TDD (write failing test → verify fail → implement → verify pass → commit).

## Tech Stack

FastAPI, SQLAlchemy (sync `Session`), pytest, `unittest.mock`

---

## File Structure

| File | Change |
|------|--------|
| `backend/app/services/scanner.py` | Add 4 static methods to `ScannerService` |
| `backend/app/services/universe_stats.py` | **New** — `UniverseStatsService.compute()` |
| `backend/app/services/__init__.py` | Export `UniverseStatsService` |
| `backend/app/services/stock_data.py` | Add `is_futures_ticker()` and `get_historical_enriched()`; add 2 top-level imports |
| `backend/app/routers/scanner.py` | Delete `_last_completed_weekday()`; thin `run_scanner()` |
| `backend/app/routers/universe.py` | Delete `_compute_universe_stats()`; update 2 call sites |
| `backend/app/routers/stocks.py` | Delete `_is_futures_ticker()`; thin `get_historical_data()`; update 3 other call sites |
| `backend/tests/services/test_scanner_service_methods.py` | **New** — unit tests for 4 scanner service methods |
| `backend/tests/services/test_universe_stats_service.py` | **New** — unit tests for `UniverseStatsService.compute()` |
| `backend/tests/services/test_stock_data_service_methods.py` | **New** — unit tests for `is_futures_ticker()` and `get_historical_enriched()` |

---

## Task 1 — ScannerService: 4 static methods + thin `run_scanner()`

**Files:** `backend/app/services/scanner.py`, `backend/app/routers/scanner.py`, `backend/tests/services/test_scanner_service_methods.py`

### Step 1.1 — Write failing tests

Create `backend/tests/services/test_scanner_service_methods.py`:

```python
import json
from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from app.services.scanner import ScannerService


class TestDefaultScanDate:
    def test_returns_friday_when_today_is_saturday(self):
        with patch("app.services.scanner.get_market_today", return_value=date(2026, 5, 23)):
            result = ScannerService.default_scan_date()
        assert result == date(2026, 5, 22)

    def test_returns_friday_when_today_is_monday(self):
        # Monday — must skip Sunday AND Saturday
        with patch("app.services.scanner.get_market_today", return_value=date(2026, 5, 25)):
            result = ScannerService.default_scan_date()
        assert result == date(2026, 5, 22)

    def test_returns_yesterday_when_today_is_tuesday(self):
        with patch("app.services.scanner.get_market_today", return_value=date(2026, 5, 26)):
            result = ScannerService.default_scan_date()
        assert result == date(2026, 5, 25)


class TestCheckConcurrency:
    def test_returns_none_when_no_key(self):
        mock_r = MagicMock()
        mock_r.get.return_value = None
        with patch("redis.Redis.from_url", return_value=mock_r):
            result = ScannerService.check_concurrency(
                "redis://localhost", 1, "pre_market_volume_spike"
            )
        assert result is None

    def test_returns_dict_when_key_exists(self):
        payload = {"scan_id": "abc", "task_ids": ["t1"], "started_at": "2026-05-23T10:00:00Z"}
        mock_r = MagicMock()
        mock_r.get.return_value = json.dumps(payload)
        with patch("redis.Redis.from_url", return_value=mock_r):
            result = ScannerService.check_concurrency(
                "redis://localhost", 1, "pre_market_volume_spike"
            )
        assert result == payload

    def test_clears_and_returns_none_for_corrupt_key(self):
        mock_r = MagicMock()
        mock_r.get.return_value = "not-json{"
        with patch("redis.Redis.from_url", return_value=mock_r):
            result = ScannerService.check_concurrency(
                "redis://localhost", 1, "pre_market_volume_spike"
            )
        assert result is None
        mock_r.delete.assert_called_once_with("universe:1:scan:pre_market_volume_spike")


class TestResolveDateRange:
    def test_defaults_both_to_last_weekday_when_none(self):
        with patch("app.services.scanner.get_market_today", return_value=date(2026, 5, 26)):
            start, end = ScannerService.resolve_date_range(None, None)
        assert start == date(2026, 5, 25)
        assert end == date(2026, 5, 25)

    def test_defaults_end_to_start_when_only_start_given(self):
        start, end = ScannerService.resolve_date_range(date(2026, 5, 20), None)
        assert start == date(2026, 5, 20)
        assert end == date(2026, 5, 20)

    def test_passthrough_explicit_range(self):
        start, end = ScannerService.resolve_date_range(date(2026, 5, 20), date(2026, 5, 22))
        assert start == date(2026, 5, 20)
        assert end == date(2026, 5, 22)

    def test_raises_value_error_on_inverted_range(self):
        with pytest.raises(ValueError, match="end_date"):
            ScannerService.resolve_date_range(date(2026, 5, 22), date(2026, 5, 20))


class TestCountActiveTickers:
    def test_returns_count_from_db(self):
        db = MagicMock()
        mock_q = MagicMock()
        mock_q.filter.return_value = mock_q
        mock_q.count.return_value = 42
        db.query.return_value = mock_q
        assert ScannerService.count_active_tickers(db, universe_id=1) == 42

    def test_returns_zero_for_empty_universe(self):
        db = MagicMock()
        mock_q = MagicMock()
        mock_q.filter.return_value = mock_q
        mock_q.count.return_value = 0
        db.query.return_value = mock_q
        assert ScannerService.count_active_tickers(db, universe_id=99) == 0
```

### Step 1.2 — Verify tests fail

```bash
cd /workspace/markethawk/backend && python -m pytest tests/services/test_scanner_service_methods.py -v 2>&1 | head -20
# Expected: AttributeError — ScannerService has no attribute 'default_scan_date'
```

### Step 1.3 — Add 4 static methods to `ScannerService`

In `backend/app/services/scanner.py`, add the following block **after** `calculate_day_metrics` (ends around line 160) and **before** `_get_batch_enrichment_data`:

```python
    @staticmethod
    def default_scan_date() -> date:
        """Most recent completed trading weekday."""
        from datetime import timedelta as _td
        d = get_market_today() - _td(days=1)
        while d.weekday() >= 5:
            d -= _td(days=1)
        return d

    @staticmethod
    def check_concurrency(redis_url: str, universe_id: int, scanner_type: str) -> Optional[dict]:
        """Returns in-flight scan state dict if one exists, else None.
        On corrupt Redis key: clears it and returns None.
        """
        import json
        import redis as _redis
        r = _redis.Redis.from_url(redis_url, decode_responses=True)
        state_key = f"universe:{universe_id}:scan:{scanner_type}"
        existing = r.get(state_key)
        if existing:
            try:
                return json.loads(existing)
            except json.JSONDecodeError:
                r.delete(state_key)
        return None

    @staticmethod
    def resolve_date_range(
        start_date: Optional[date],
        end_date: Optional[date],
    ) -> tuple[date, date]:
        """Apply date defaults and validate ordering.
        Raises ValueError if end_date < start_date.
        """
        resolved_start = start_date or ScannerService.default_scan_date()
        resolved_end = end_date or resolved_start
        if resolved_end < resolved_start:
            raise ValueError("end_date must not be before start_date")
        return resolved_start, resolved_end

    @staticmethod
    def count_active_tickers(db: Session, universe_id: int) -> int:
        """Count active tickers in a universe. Returns count (may be 0)."""
        return (
            db.query(MonitoredStock)
            .filter(
                MonitoredStock.universe_id == universe_id,
                MonitoredStock.is_active.is_(True),
            )
            .count()
        )
```

`MonitoredStock` is already imported at the top of `scanner.py`. `get_market_today`, `Optional`, `date`, `Session` are all already in scope.

### Step 1.4 — Verify tests pass

```bash
cd /workspace/markethawk/backend && python -m pytest tests/services/test_scanner_service_methods.py -v
# Expected: 11 passed
```

### Step 1.5 — Thin `run_scanner()` in the router

In `backend/app/routers/scanner.py`:

**a) Delete** `_last_completed_weekday()` (lines 40–46, the entire helper function).

**b) Add** `ScannerService` to imports. Change line 35 from:
```python
from app.services import StockDataService
```
to:
```python
from app.services import StockDataService
from app.services.scanner import ScannerService
```

**c) Replace** the body of `run_scanner()` with the following (keeping the docstring unchanged):

```python
@router.post("/run", response_model=ScannerRunAsyncResponse, status_code=202)
def run_scanner(
    request: ScannerRunRequest,
    db: Session = Depends(get_db),
):
    """Enqueue a scan and return immediately.

    Progress is delivered via WS /api/scanner/ws/runs/{task_id} or polled at
    GET /api/scanner/runs/{scan_id}/status. Final events are persisted to the
    DB and queryable through /api/scanner/results once status='completed'.

    Returns 409 if a scan with the same (universe_id, scanner_type) is already
    in flight — the response includes the live task_id so the client can
    reattach instead of starting a duplicate.
    """
    from app.core.config import settings as _settings
    from app.tasks import run_universe_scan

    if not request.universe_id:
        raise HTTPException(
            status_code=400,
            detail="universe_id is required (per-ticker scans go through /run-range)",
        )

    in_flight = ScannerService.check_concurrency(
        _settings.REDIS_URL, request.universe_id, request.scanner_type
    )
    if in_flight:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "A scan is already running for this universe and scanner type",
                "scan_id": in_flight.get("scan_id"),
                "task_id": (in_flight.get("task_ids") or [None])[0],
                "started_at": in_flight.get("started_at"),
            },
        )

    try:
        start_date, end_date = ScannerService.resolve_date_range(
            request.start_date, request.end_date
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    ticker_count = ScannerService.count_active_tickers(db, request.universe_id)
    if ticker_count == 0:
        raise HTTPException(
            status_code=400, detail="No tickers found in the selected universe"
        )

    scan_id = str(uuid.uuid4())
    scanner_run = ScannerRun(
        uuid=uuid.UUID(scan_id),
        scanner_type=request.scanner_type,
        universe_id=request.universe_id,
        status="queued",
        stocks_scanned=ticker_count,
        scan_start_date=start_date,
        scan_end_date=end_date,
    )
    db.add(scanner_run)
    db.commit()
    db.refresh(scanner_run)

    async_result = run_universe_scan.delay(
        scan_id=scan_id,
        scanner_type=request.scanner_type,
        universe_id=request.universe_id,
        start_date_iso=start_date.isoformat(),
        end_date_iso=end_date.isoformat(),
    )

    scanner_run.celery_task_id = async_result.id
    db.commit()

    started_at = scanner_run.created_at
    if started_at and started_at.tzinfo is None:
        started_at = started_at.replace(tzinfo=timezone.utc)

    return ScannerRunAsyncResponse(
        scan_id=scan_id,
        task_id=async_result.id,
        started_at=started_at,
        scanner_type=request.scanner_type,
        universe_id=request.universe_id,
        scan_start_date=start_date,
        scan_end_date=end_date,
        status="queued",
    )
```

The `import json` and `import redis as _redis` lines that were inside the old `run_scanner()` are gone — they now live inside `ScannerService.check_concurrency()`.

### Step 1.6 — Verify scanner API tests still pass

```bash
cd /workspace/markethawk/backend && python -m pytest tests/api/test_scanner.py -v
# Expected: all passing
```

### Step 1.7 — Commit

```bash
git add backend/app/services/scanner.py \
        backend/app/routers/scanner.py \
        backend/tests/services/test_scanner_service_methods.py
git commit -m "refactor(scanner): extract concurrency guard, date defaults, and ticker count into ScannerService

Moves _last_completed_weekday(), the Redis guard, date range defaulting, and
ticker count query out of run_scanner() into four static methods on ScannerService.
Router body shrinks to ~30 lines; all logic is now callable without HTTP."
```

---

## Task 2 — UniverseStatsService: new file + thin router

**Files:** `backend/app/services/universe_stats.py` (new), `backend/app/services/__init__.py`, `backend/app/routers/universe.py`, `backend/tests/services/test_universe_stats_service.py` (new)

### Step 2.1 — Write failing tests

Create `backend/tests/services/test_universe_stats_service.py`:

```python
from unittest.mock import MagicMock


def _make_empty_db():
    """Mock DB that returns zero counts and empty lists for all universe queries."""
    db = MagicMock()
    mock_q = MagicMock()
    mock_q.filter.return_value = mock_q
    mock_q.scalar.return_value = 0
    mock_q.all.return_value = []
    mock_q.first.return_value = (0, None, None)
    mock_q.distinct.return_value = mock_q
    db.query.return_value = mock_q
    return db


class TestUniverseStatsServiceExists:
    def test_module_importable(self):
        from app.services.universe_stats import UniverseStatsService
        assert callable(UniverseStatsService.compute)

    def test_compute_returns_expected_keys(self):
        from app.services.universe_stats import UniverseStatsService
        result = UniverseStatsService.compute(universe_id=1, db=_make_empty_db())
        assert set(result.keys()) == {
            "ticker_count", "aggregate_count", "min_date", "max_date", "timespans"
        }

    def test_compute_empty_universe_returns_zeros(self):
        from app.services.universe_stats import UniverseStatsService
        result = UniverseStatsService.compute(universe_id=1, db=_make_empty_db())
        assert result["ticker_count"] == 0
        assert result["aggregate_count"] == 0
        assert result["min_date"] is None
        assert result["max_date"] is None
        assert result["timespans"] == []
```

### Step 2.2 — Verify tests fail

```bash
cd /workspace/markethawk/backend && python -m pytest tests/services/test_universe_stats_service.py -v 2>&1 | head -15
# Expected: ModuleNotFoundError: No module named 'app.services.universe_stats'
```

### Step 2.3 — Create `backend/app/services/universe_stats.py`

```python
from sqlalchemy.orm import Session
from sqlalchemy import func


class UniverseStatsService:
    @staticmethod
    def compute(universe_id: int, db: Session) -> dict:
        """Aggregate stats for one universe.

        Returns: {ticker_count, aggregate_count, min_date, max_date, timespans: list[str]}
        Queries StockAggregate and FuturesAggregate directly.
        No caching — callers are responsible for persisting results to cached columns.
        """
        from app.models import StockUniverseTicker
        from app.models.stock_aggregate import StockAggregate
        from app.models.futures_aggregate import FuturesAggregate

        ticker_count = (
            db.query(func.count(StockUniverseTicker.id))
            .filter(StockUniverseTicker.universe_id == universe_id)
            .scalar()
        ) or 0

        futures_tickers = [
            row.ticker
            for row in db.query(StockUniverseTicker.ticker)
            .filter(
                StockUniverseTicker.universe_id == universe_id,
                StockUniverseTicker.asset_class == "futures",
            )
            .all()
        ]
        stock_tickers = [
            row.ticker
            for row in db.query(StockUniverseTicker.ticker)
            .filter(
                StockUniverseTicker.universe_id == universe_id,
                StockUniverseTicker.asset_class != "futures",
            )
            .all()
        ]

        count_aggs = 0
        min_date = None
        max_date = None

        if stock_tickers:
            stock_stats = (
                db.query(
                    func.count(StockAggregate.id),
                    func.min(StockAggregate.timestamp),
                    func.max(StockAggregate.timestamp),
                )
                .filter(StockAggregate.ticker.in_(stock_tickers))
                .first()
            )
            if stock_stats and stock_stats[0]:
                count_aggs += stock_stats[0]
                min_date = (
                    stock_stats[1] if min_date is None
                    else (min(min_date, stock_stats[1]) if stock_stats[1] else min_date)
                )
                max_date = (
                    stock_stats[2] if max_date is None
                    else (max(max_date, stock_stats[2]) if stock_stats[2] else max_date)
                )

        if futures_tickers:
            futures_stats = (
                db.query(
                    func.count(FuturesAggregate.id),
                    func.min(FuturesAggregate.timestamp),
                    func.max(FuturesAggregate.timestamp),
                )
                .filter(FuturesAggregate.symbol.in_(futures_tickers))
                .first()
            )
            if futures_stats and futures_stats[0]:
                count_aggs += futures_stats[0]
                min_date = (
                    futures_stats[1] if min_date is None
                    else (min(min_date, futures_stats[1]) if futures_stats[1] else min_date)
                )
                max_date = (
                    futures_stats[2] if max_date is None
                    else (max(max_date, futures_stats[2]) if futures_stats[2] else max_date)
                )

        timespans_set: set = set()
        if stock_tickers:
            for row in (
                db.query(StockAggregate.timespan, StockAggregate.multiplier)
                .filter(StockAggregate.ticker.in_(stock_tickers))
                .distinct()
                .all()
            ):
                label = f"{row.multiplier}{row.timespan}" if row.multiplier > 1 else row.timespan
                timespans_set.add(label)
        if futures_tickers:
            for row in (
                db.query(FuturesAggregate.timespan, FuturesAggregate.multiplier)
                .filter(FuturesAggregate.symbol.in_(futures_tickers))
                .distinct()
                .all()
            ):
                label = f"{row.multiplier}{row.timespan}" if row.multiplier > 1 else row.timespan
                timespans_set.add(label)

        return {
            "ticker_count": ticker_count,
            "aggregate_count": count_aggs,
            "min_date": min_date,
            "max_date": max_date,
            "timespans": sorted(timespans_set),
        }
```

### Step 2.4 — Export from `backend/app/services/__init__.py`

Add `UniverseStatsService` alongside the existing exports:

```python
from app.services.stock_data import StockDataService
from app.services.scanner import ScannerService
from app.services import journal_service
from app.services.futures_data import FuturesDataService
from app.services.universe_stats import UniverseStatsService

__all__ = [
    "StockDataService",
    "ScannerService",
    "journal_service",
    "FuturesDataService",
    "UniverseStatsService",
]
```

### Step 2.5 — Verify tests pass

```bash
cd /workspace/markethawk/backend && python -m pytest tests/services/test_universe_stats_service.py -v
# Expected: 3 passed
```

### Step 2.6 — Update `backend/app/routers/universe.py`

**a) Add import** after line 24 (with other service imports):
```python
from app.services.universe_stats import UniverseStatsService
```

**b) Delete** `_compute_universe_stats()` (lines 117–211, the entire private function).

**c) In `refresh_universe_stats`** (the POST `/{universe_id}/refresh-stats` handler), change:
```python
    stats = _compute_universe_stats(universe_id, db)
```
to:
```python
    stats = UniverseStatsService.compute(universe_id, db)
```

**d) In `refresh_universe`** (the POST `/{universe_id}/refresh` handler, near the bottom), change:
```python
    stats = _compute_universe_stats(universe_id, db)
```
to:
```python
    stats = UniverseStatsService.compute(universe_id, db)
```

### Step 2.7 — Verify universe API tests still pass

```bash
cd /workspace/markethawk/backend && python -m pytest tests/api/test_universe.py -v
# Expected: all passing
```

### Step 2.8 — Commit

```bash
git add backend/app/services/universe_stats.py \
        backend/app/services/__init__.py \
        backend/app/routers/universe.py \
        backend/tests/services/test_universe_stats_service.py
git commit -m "refactor(universe): extract _compute_universe_stats into UniverseStatsService.compute()

Moves ~95-line aggregate query block out of the universe router into a dedicated
UniverseStatsService. Both call sites (refresh-stats, refresh) updated. Private
function deleted from router."
```

---

## Task 3 — StockDataService: `is_futures_ticker()` + `get_historical_enriched()` + thin router

**Files:** `backend/app/services/stock_data.py`, `backend/app/routers/stocks.py`, `backend/tests/services/test_stock_data_service_methods.py` (new)

### Step 3.1 — Write failing tests

Create `backend/tests/services/test_stock_data_service_methods.py`:

```python
from datetime import datetime, timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd

from app.services.stock_data import StockDataService


# ── helpers ────────────────────────────────────────────────────────────────

def _mock_db_futures_lookup(is_futures: bool):
    db = MagicMock()
    mock_q = MagicMock()
    mock_q.filter.return_value = mock_q
    mock_q.first.return_value = MagicMock() if is_futures else None
    db.query.return_value = mock_q
    return db


def _make_df(rows=10):
    base = datetime(2026, 1, 1)
    ts = [base + timedelta(days=i) for i in range(rows)]
    return pd.DataFrame(
        {
            "Open": np.ones(rows) * 100.0,
            "High": np.ones(rows) * 110.0,
            "Low": np.ones(rows) * 90.0,
            "Close": np.ones(rows) * 105.0,
            "Volume": np.ones(rows, dtype=int) * 10000,
            "vwap": np.ones(rows) * 102.0,
            "transactions": np.ones(rows, dtype=int) * 500,
        },
        index=pd.DatetimeIndex(ts, name="Date"),
    )


# ── is_futures_ticker ──────────────────────────────────────────────────────

def test_is_futures_ticker_true():
    assert StockDataService.is_futures_ticker(_mock_db_futures_lookup(True), "ES") is True


def test_is_futures_ticker_false():
    assert StockDataService.is_futures_ticker(_mock_db_futures_lookup(False), "AAPL") is False


# ── get_historical_enriched ────────────────────────────────────────────────

def test_enriched_returns_empty_when_no_data():
    db = _mock_db_futures_lookup(False)
    with patch.object(StockDataService, "get_historical_from_db", return_value=pd.DataFrame()):
        result = StockDataService.get_historical_enriched(db, "AAPL", "30d", "day", 1)
    assert result.empty


def test_enriched_coerces_decimal_to_float():
    db = _mock_db_futures_lookup(False)
    df = _make_df(5)
    df["Close"] = df["Close"].map(lambda x: Decimal(str(round(float(x), 2))))
    with patch.object(StockDataService, "get_historical_from_db", return_value=df):
        result = StockDataService.get_historical_enriched(db, "AAPL", "30d", "day", 1)
    assert result["Close"].dtype == float


def test_enriched_no_indicators_for_day_timespan():
    db = _mock_db_futures_lookup(False)
    df = _make_df(10)
    with patch.object(StockDataService, "get_historical_from_db", return_value=df), \
         patch("app.services.stock_data.ChartIndicatorsService") as mock_ci:
        StockDataService.get_historical_enriched(db, "AAPL", "30d", "day", 1)
    mock_ci.add_indicators.assert_not_called()


def test_enriched_adds_indicators_for_minute_under_limit():
    db = _mock_db_futures_lookup(False)
    df = _make_df(100)
    with patch.object(StockDataService, "get_historical_from_db", return_value=df), \
         patch("app.services.stock_data.ChartIndicatorsService") as mock_ci:
        mock_ci.add_indicators.return_value = df
        StockDataService.get_historical_enriched(db, "AAPL", "30d", "minute", 1)
    mock_ci.add_indicators.assert_called_once_with(df, is_intraday=True)


def test_enriched_no_indicators_for_minute_over_limit():
    db = _mock_db_futures_lookup(False)
    df = _make_df(3001)  # INDICATOR_ROW_LIMIT = 3000
    with patch.object(StockDataService, "get_historical_from_db", return_value=df), \
         patch("app.services.stock_data.ChartIndicatorsService") as mock_ci:
        StockDataService.get_historical_enriched(db, "AAPL", "30d", "minute", 1)
    mock_ci.add_indicators.assert_not_called()


def test_enriched_truncates_at_max_datapoints():
    db = _mock_db_futures_lookup(False)
    df = _make_df(500_001)  # MAX_DATAPOINTS = 500_000
    with patch.object(StockDataService, "get_historical_from_db", return_value=df):
        result = StockDataService.get_historical_enriched(db, "AAPL", "all", "day", 1)
    assert len(result) == 500_000


def test_enriched_dispatches_to_futures_path():
    db = _mock_db_futures_lookup(True)
    df = _make_df(5)
    with patch.object(StockDataService, "get_futures_historical_from_db", return_value=df) as mock_fut, \
         patch.object(StockDataService, "get_historical_from_db") as mock_stock:
        StockDataService.get_historical_enriched(db, "ES", "30d", "day", 1)
    mock_fut.assert_called_once()
    mock_stock.assert_not_called()
```

### Step 3.2 — Verify tests fail

```bash
cd /workspace/markethawk/backend && python -m pytest tests/services/test_stock_data_service_methods.py -v 2>&1 | head -20
# Expected: AttributeError — StockDataService has no attribute 'is_futures_ticker'
```

### Step 3.3 — Add top-level imports to `backend/app/services/stock_data.py`

In `stock_data.py`, extend the import block (currently ending at line 20) to add:

```python
from app.models.monitored_stock import MonitoredStock
from app.services.chart_indicators import ChartIndicatorsService
```

The `ChartIndicatorsService` top-level import is needed so that `patch("app.services.stock_data.ChartIndicatorsService")` works in tests. Verify there is no circular import by checking that `chart_indicators.py` does not import from `stock_data.py`.

```bash
grep -r "from app.services.stock_data\|import stock_data" /workspace/markethawk/backend/app/services/chart_indicators.py
# Expected: no output (no circular dependency)
```

### Step 3.4 — Add `is_futures_ticker()` and `get_historical_enriched()` to `StockDataService`

Append the following two methods inside the `StockDataService` class in `backend/app/services/stock_data.py`, after the closing `return []` of `get_pre_market_movers` (around line 552). Add them before the end of the class (there is no top-level `return` after the class body — just add them as the last two `@staticmethod` blocks inside the class):

```python
    @staticmethod
    def is_futures_ticker(db: Session, ticker: str) -> bool:
        """Return True if ticker is tracked as futures asset class."""
        return (
            db.query(MonitoredStock.id)
            .filter(
                MonitoredStock.ticker == ticker,
                MonitoredStock.asset_class == "futures",
                MonitoredStock.is_active == True,
            )
            .first()
            is not None
        )

    @staticmethod
    def get_historical_enriched(
        db: Session,
        ticker: str,
        period: str,
        timespan: str,
        multiplier: int,
    ) -> pd.DataFrame:
        """Fetch, coerce, and optionally enrich with indicators.

        - Dispatches to get_historical_from_db or get_futures_historical_from_db
        - Applies pd.to_numeric() coercion (Decimal → float, required by orjson + indicators)
        - Applies MAX_DATAPOINTS guardrail
        - Applies INDICATOR_ROW_LIMIT guard and calls ChartIndicatorsService.add_indicators()
        - Returns empty DataFrame on no data
        Router remains responsible for compact serialization.
        """
        is_futures = StockDataService.is_futures_ticker(db, ticker)
        if is_futures:
            data = StockDataService.get_futures_historical_from_db(
                db, ticker, period, timespan, multiplier
            )
        else:
            data = StockDataService.get_historical_from_db(
                db, ticker, period, timespan, multiplier
            )

        if data.empty:
            return data

        exclude_cols = ["Date", "marker_type", "contract_month"]
        for col in data.columns:
            if col not in exclude_cols:
                data[col] = pd.to_numeric(data[col], errors="coerce")

        MAX_DATAPOINTS = 500000
        if len(data) > MAX_DATAPOINTS:
            data = data.tail(MAX_DATAPOINTS)

        INDICATOR_ROW_LIMIT = 3000
        if timespan in ["minute", "hour"] and len(data) <= INDICATOR_ROW_LIMIT:
            data = ChartIndicatorsService.add_indicators(data, is_intraday=True)

        return data
```

### Step 3.5 — Verify tests pass

```bash
cd /workspace/markethawk/backend && python -m pytest tests/services/test_stock_data_service_methods.py -v
# Expected: 8 passed
```

### Step 3.6 — Update `backend/app/routers/stocks.py`

**a) Delete** `_is_futures_ticker()` helper (lines 20–32, entire function).

**b) Replace** the body of `get_historical_data()` with the thinned version below. The compact serialization block (all the `reset_index` / `mapping` / `ORJSONResponse` logic) stays in the router — it is HTTP-layer concern:

```python
@router.get("/historical/{ticker}")
def get_historical_data(
    ticker: str,
    period: str = "30d",
    timespan: str = "day",
    multiplier: int = 1,
    format: str = "row",  # "row" (default) or "columnar"
    db: Session = Depends(get_db),
):
    """Get historical stock data from DB."""
    ticker = ticker.upper()
    try:
        data = StockDataService.get_historical_enriched(db, ticker, period, timespan, multiplier)

        if data.empty:
            return {
                "ticker": ticker,
                "period": period,
                "timespan": timespan,
                "multiplier": multiplier,
                "data_points": 0,
                "data": [],
            }

        # Vectorized serialization — avoid per-row Python loops over large DataFrames.
        data = data.reset_index()
        date_col = "Date" if "Date" in data.columns else "timestamp"

        # COMPACT FORMAT OPTIMIZATION:
        # 1. Convert Timestamps to Unix Epoch (seconds)
        data["t"] = (pd.to_datetime(data[date_col], utc=True).astype('int64') // 10**9)

        # 2. Map other columns to short keys
        mapping = {
            "Open": "o", "High": "h", "Low": "l", "Close": "c",
            "Volume": "v", "vwap": "w", "transactions": "n",
            "vwap_intraday": "wi", "marker_type": "mt", "contract_month": "cm"
        }

        compact_data = {}
        compact_data["t"] = data["t"].tolist()

        for col, short in mapping.items():
            if col in data.columns:
                if col == "marker_type":
                    data[col] = data[col].where(data[col].notna() & (data[col] != ""), other=None)
                compact_data[short] = data[col].tolist()

        # PERFORMANCE OPTIMIZATION:
        # Always return columnar format for this endpoint as it's significantly more efficient.
        return ORJSONResponse({
            "ticker": ticker,
            "period": period,
            "timespan": timespan,
            "multiplier": multiplier,
            "data_points": len(data),
            "format": "columnar_compact",
            "data": compact_data,
        })

    except HTTPException:
        raise
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Error fetching data: {str(e)}")
```

**c) Update the three remaining call sites** that still reference `_is_futures_ticker`.

`_is_futures_ticker` appears in four places total in `stocks.py`. Step 3.6b replaces the entire body of `get_historical_data()`, which eliminates the call at line 47. The three call sites that remain after that body replacement are:

In `refresh_stock_data` (line ~144):
```python
        if _is_futures_ticker(db, ticker):
```
→
```python
        if StockDataService.is_futures_ticker(db, ticker):
```

In `get_stock_detail_consolidated` (line ~179):
```python
        if _is_futures_ticker(db, ticker):
```
→
```python
        if StockDataService.is_futures_ticker(db, ticker):
```

In `sync_missing_stock_aggregates` (line ~307):
```python
    is_futures = _is_futures_ticker(db, ticker)
```
→
```python
    is_futures = StockDataService.is_futures_ticker(db, ticker)
```

After completing Steps 3.6a, 3.6b, and 3.6c, confirm `_is_futures_ticker` appears zero times in `stocks.py`:
```bash
grep "_is_futures_ticker" /workspace/markethawk/backend/app/routers/stocks.py
# Expected: no output
```

### Step 3.7 — Verify stocks API tests still pass

```bash
cd /workspace/markethawk/backend && python -m pytest tests/api/test_stocks.py -v
# Expected: all passing
```

### Step 3.8 — Commit

```bash
git add backend/app/services/stock_data.py \
        backend/app/routers/stocks.py \
        backend/tests/services/test_stock_data_service_methods.py
git commit -m "refactor(stocks): extract is_futures_ticker and get_historical_enriched into StockDataService

Moves _is_futures_ticker(), numeric coercion, MAX_DATAPOINTS guardrail, and
indicator gating out of the stocks router into two new static methods on
StockDataService. Four call sites in the router updated. Compact serialization
stays in the router (HTTP concern)."
```

---

## Final Verification

Run all three changed test suites together to confirm nothing regressed:

```bash
cd /workspace/markethawk/backend && python -m pytest \
  tests/services/test_scanner_service_methods.py \
  tests/services/test_universe_stats_service.py \
  tests/services/test_stock_data_service_methods.py \
  tests/api/test_scanner.py \
  tests/api/test_universe.py \
  tests/api/test_stocks.py \
  -v
# Expected: all passing
```
