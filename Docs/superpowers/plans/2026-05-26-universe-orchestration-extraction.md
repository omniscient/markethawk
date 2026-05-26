# Universe Router Orchestration Extraction (Issue #76) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extract ~624 LOC of orchestration logic from `routers/universe.py` into two focused service modules, reducing the router to a thin HTTP adapter (≤400 LOC) without changing any public API surface.

**Architecture:** Two new service files — `services/universe_orchestrator.py` for Celery/Redis coordination and `services/universe_export.py` for ZIP streaming — plus two domain exceptions. Seven extracted route handlers become thin shells: `try: return service.method(...)` / `except UniverseNotFoundError: raise HTTPException(404)`. No Celery tasks, schemas, or endpoint paths change.

**Tech Stack:** FastAPI, SQLAlchemy (sync `Session`), Redis, Celery, Python 3.x.

---

### File Structure

| File | Action | Description |
|------|--------|-------------|
| `backend/app/exceptions.py` | Modify | Add `UniverseNotFoundError`, `UniverseValidationError` |
| `backend/app/services/universe_orchestrator.py` | Create | 6 orchestration methods (discover/sync/quality/normalize) |
| `backend/app/services/universe_export.py` | Create | `export_aggregates` — ZIP streaming, no Celery/Redis |
| `backend/app/services/__init__.py` | Modify | Export the two new modules |
| `backend/app/routers/universe.py` | Modify | Replace 7 handler bodies with thin service delegates |

---

### Task 1: Add domain exceptions to `exceptions.py`

**Files:**
- Modify: `backend/app/exceptions.py`

- [ ] **Step 1: Baseline — confirm the router is currently serving**

```bash
curl -s http://localhost:8000/api/universe/list | python -m json.tool | head -5
```

Expected: JSON array (may be `[]`). HTTP 200.

- [ ] **Step 2: Add `UniverseNotFoundError` and `UniverseValidationError`**

In `backend/app/exceptions.py`, append after the closing brace of `ProviderError`:

```python
class UniverseNotFoundError(MarketHawkError):
    """Raised when a universe_id does not exist in the DB."""

    def __init__(self, universe_id: int):
        super().__init__(
            f"Universe {universe_id} not found",
            is_retryable=False,
            universe_id=universe_id,
        )
        self.universe_id = universe_id


class UniverseValidationError(MarketHawkError):
    """Raised when universe state is invalid for the requested operation."""

    def __init__(self, message: str, universe_id: int | None = None):
        super().__init__(message, is_retryable=False, universe_id=universe_id)
        self.universe_id = universe_id
```

- [ ] **Step 3: Verify backend reloads cleanly**

```bash
docker-compose logs backend --tail=5
```

Expected: No import errors; last line is a uvicorn reload log entry.

- [ ] **Step 4: Smoke-test the import**

```bash
docker-compose exec backend python -c "
from app.exceptions import UniverseNotFoundError, UniverseValidationError
e = UniverseNotFoundError(42)
print('message:', str(e))
v = UniverseValidationError('test', universe_id=42)
print('validation:', str(v))
print('OK')
"
```

Expected:
```
message: Universe 42 not found [universe_id=42]
validation: test [universe_id=42]
OK
```

- [ ] **Step 5: Commit**

```bash
git add backend/app/exceptions.py
git commit -m "feat(universe): add UniverseNotFoundError and UniverseValidationError"
```

---

### Task 2: Create `services/universe_orchestrator.py`

**Files:**
- Create: `backend/app/services/universe_orchestrator.py`

This file owns all Celery task dispatch, Redis state read/write, and multi-service coordination for universes. It extracts six orchestration blocks verbatim from the router, replacing their `HTTPException` raises with `UniverseNotFoundError` / `UniverseValidationError`.

- [ ] **Step 1: Create the file**

Create `backend/app/services/universe_orchestrator.py` with the following content:

```python
"""
Orchestration logic for universe operations: Celery task dispatch,
Redis state management, and multi-service coordination.
"""

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import List, Optional

import redis as redis_lib
from celery.result import AsyncResult
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.celery_app import celery_app
from app.core.config import settings
from app.exceptions import UniverseNotFoundError, UniverseValidationError
from app.models import MonitoredStock, StockUniverse, StockUniverseTicker
from app.models.futures_aggregate import FuturesAggregate
from app.models.stock_aggregate import StockAggregate
from app.models.universe_quality_report import UniverseQualityReport
from app.services.universe_stats import UniverseStatsService
from app.utils.session import get_market_today

logger = logging.getLogger(__name__)

# Celery task and SYMBOL_EXCHANGE_MAP imports are lazy (inside function bodies)
# to match the pattern already in the router and prevent any future circular-import
# cycles (tasks.py imports from app.services, so module-level cross-imports are risky).


def discover_and_refresh(universe_id: int, db: Session) -> dict:
    """
    Refresh stocks in a universe using the Universe Discovery Engine.
    Clears MonitoredStock + StockUniverseTicker, runs DiscoveryService.run_screen(),
    bulk-inserts results, refreshes cached stats.
    Raises UniverseNotFoundError if the universe does not exist.
    """
    from app.services.discovery_service import DiscoveryService

    universe = db.query(StockUniverse).filter(StockUniverse.id == universe_id).first()
    if not universe:
        raise UniverseNotFoundError(universe_id)

    db.query(MonitoredStock).filter(MonitoredStock.universe_id == universe_id).delete()
    db.query(StockUniverseTicker).filter(StockUniverseTicker.universe_id == universe_id).delete()

    service = DiscoveryService(db)
    criteria = universe.criteria or {}
    results = service.run_screen(criteria)

    added_count = 0
    for res in results:
        monitored_stock = MonitoredStock(
            ticker=res["ticker"],
            universe_id=universe_id,
            added_date=get_market_today(),
            is_active=True,
            asset_class=res.get("asset_class", "stocks"),
            data_source=res.get("data_source", "massive"),
            company_name=res["name"],
            sector=res["sector"],
            market_cap=res["market_cap"],
            stock_metadata={
                "source": "discovery_engine",
                "close_price": res["close_price"],
                "volume": res["volume"],
                "primary_exchange": res.get("primary_exchange"),
                "employees": res.get("employees"),
                "sic_code": res.get("sic_code"),
                "description_preview": (res.get("description") or "")[:100] + "..."
                if res.get("description")
                else None,
            },
        )
        db.add(monitored_stock)

        stock_ticker = StockUniverseTicker(
            universe_id=universe_id,
            ticker=res["ticker"],
            asset_class=res.get("asset_class", "stocks"),
            data_source=res.get("data_source", "massive"),
            created_at=datetime.now(timezone.utc).replace(tzinfo=None),
        )
        db.add(stock_ticker)
        added_count += 1

    db.commit()

    stats = UniverseStatsService.compute(universe_id, db)
    universe.cached_ticker_count = stats["ticker_count"]
    universe.cached_aggregate_count = stats["aggregate_count"]
    universe.cached_min_date = stats["min_date"]
    universe.cached_max_date = stats["max_date"]
    universe.cached_timespans = stats["timespans"]
    universe.stats_refreshed_at = datetime.now(timezone.utc).replace(tzinfo=None)
    db.commit()

    return {
        "status": "completed",
        "scanned": "ALL",
        "added": added_count,
        "message": f"Successfully refreshed universe. Added {added_count} assets from Discovery Engine.",
    }


def sync_missing_aggregates(universe_id: int, db: Session) -> dict:
    """
    For every (timespan, multiplier) already recorded in this universe,
    queue a sync from the last stored bar up to today.
    Writes task IDs to Redis universe:{id}:sync key (4-hour TTL).
    """
    from app.services.futures_data import SYMBOL_EXCHANGE_MAP
    from app.tasks import sync_stock_aggregates, sync_futures_aggregates

    stocks = (
        db.query(MonitoredStock)
        .filter(MonitoredStock.universe_id == universe_id, MonitoredStock.is_active == True)
        .all()
    )
    if not stocks:
        return {"status": "skipped", "message": "No active stocks in this universe."}

    now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
    today = now_utc.strftime("%Y-%m-%d")
    stock_tickers = [s.ticker for s in stocks if s.asset_class != "futures"]
    futures_stocks = [s for s in stocks if s.asset_class == "futures"]
    futures_tickers = list({s.ticker for s in futures_stocks})

    task_ids: list = []
    summary: list = []

    if stock_tickers:
        combos = (
            db.query(
                StockAggregate.timespan,
                StockAggregate.multiplier,
                func.max(StockAggregate.timestamp).label("max_ts"),
            )
            .filter(StockAggregate.ticker.in_(stock_tickers))
            .group_by(StockAggregate.timespan, StockAggregate.multiplier)
            .all()
        )
        for combo in combos:
            from_dt = (
                (combo.max_ts + timedelta(seconds=1)) if combo.max_ts else (now_utc - timedelta(days=7))
            )
            if from_dt > now_utc:
                summary.append(f"{combo.timespan}×{combo.multiplier}: already up to date")
                continue
            from_date = from_dt.strftime("%Y-%m-%d")
            for ticker in stock_tickers:
                r = sync_stock_aggregates.delay(
                    ticker=ticker,
                    from_date=from_date,
                    to_date=today,
                    multiplier=combo.multiplier,
                    timespan=combo.timespan,
                )
                task_ids.append(r.id)
            summary.append(
                f"{combo.timespan}×{combo.multiplier}: {len(stock_tickers)} stocks from {from_date}"
            )

    if futures_tickers:
        combos = (
            db.query(
                FuturesAggregate.timespan,
                FuturesAggregate.multiplier,
                func.max(FuturesAggregate.timestamp).label("max_ts"),
            )
            .filter(FuturesAggregate.symbol.in_(futures_tickers))
            .group_by(FuturesAggregate.timespan, FuturesAggregate.multiplier)
            .all()
        )
        stock_map = {s.ticker: s for s in futures_stocks}
        for combo in combos:
            from_dt = (
                (combo.max_ts + timedelta(seconds=1)) if combo.max_ts else (now_utc - timedelta(days=7))
            )
            if from_dt > now_utc:
                summary.append(f"{combo.timespan}×{combo.multiplier} futures: already up to date")
                continue
            from_date = from_dt.strftime("%Y-%m-%d")
            for symbol in futures_tickers:
                s = stock_map.get(symbol)
                metadata = (s.stock_metadata or {}) if s else {}
                exchange = metadata.get("primary_exchange")
                if not exchange or exchange == "Unknown":
                    exchange = SYMBOL_EXCHANGE_MAP.get(symbol)
                if not exchange:
                    logger.warning(f"sync-missing: no exchange for {symbol}, skipping")
                    continue
                r = sync_futures_aggregates.delay(
                    symbol=symbol,
                    exchange=exchange,
                    timespan=combo.timespan,
                    multiplier=combo.multiplier,
                    from_date=from_date,
                    to_date=today,
                )
                task_ids.append(r.id)
            summary.append(
                f"{combo.timespan}×{combo.multiplier}: {len(futures_tickers)} futures from {from_date}"
            )

    if not task_ids:
        return {
            "status": "skipped",
            "message": "No existing aggregate data found to extend — use Sync to do an initial download first.",
        }

    try:
        r = redis_lib.from_url(settings.REDIS_URL)
        r.setex(
            f"universe:{universe_id}:sync",
            14400,
            json.dumps({
                "task_ids": task_ids,
                "total": len(task_ids),
                "started_at": datetime.now(timezone.utc).isoformat(),
            }),
        )
    except Exception as e:
        logger.warning(f"Could not store sync-missing status in Redis: {e}")

    return {"status": "accepted", "queued": len(task_ids), "summary": summary}


def get_sync_status(universe_id: int) -> dict:
    """
    Return the current sync progress for a universe.
    Reads task IDs from Redis, inspects AsyncResult.state for each.
    Clears stale keys older than 4 hours (Celery result TTL boundary).
    """
    r = redis_lib.from_url(settings.REDIS_URL)
    raw = r.get(f"universe:{universe_id}:sync")
    if not raw:
        return {"is_syncing": False, "pending": 0, "success": 0, "failed": 0, "total": 0}

    data = json.loads(raw)
    task_ids = data.get("task_ids", [])
    started_at_str = data.get("started_at")

    if started_at_str:
        try:
            started_at = datetime.fromisoformat(started_at_str).replace(tzinfo=timezone.utc)
            age_hours = (datetime.now(timezone.utc) - started_at).total_seconds() / 3600
            if age_hours > 4:
                r.delete(f"universe:{universe_id}:sync")
                return {"is_syncing": False, "pending": 0, "success": 0, "failed": 0, "total": 0}
        except (ValueError, TypeError):
            pass

    states = [AsyncResult(tid, app=celery_app).state for tid in task_ids]
    pending = sum(1 for s in states if s in ("PENDING", "STARTED", "RETRY"))
    success = sum(1 for s in states if s == "SUCCESS")
    failed = sum(1 for s in states if s in ("FAILURE", "REVOKED"))

    is_syncing = pending > 0
    if not is_syncing:
        r.delete(f"universe:{universe_id}:sync")

    return {
        "is_syncing": is_syncing,
        "total": len(task_ids),
        "pending": pending,
        "success": success,
        "failed": failed,
        "started_at": started_at_str,
        "timespan": data.get("timespan"),
        "from_date": data.get("from_date"),
        "to_date": data.get("to_date"),
    }


def sync_aggregates(
    universe_id: int,
    from_date: str,
    to_date: str,
    multiplier: int,
    timespan: str,
    adjusted: bool,
    sort: str,
    limit: int,
    db: Session,
) -> dict:
    """
    Trigger backfill of aggregates for all stocks in the universe.
    Deduplicates: refuses if a sync is already in progress (pending > 0).
    Writes task IDs to Redis universe:{id}:sync (4-hour TTL).
    """
    from app.services.futures_data import SYMBOL_EXCHANGE_MAP
    from app.tasks import sync_stock_aggregates, sync_futures_aggregates

    stocks = (
        db.query(MonitoredStock)
        .filter(
            MonitoredStock.universe_id == universe_id,
            MonitoredStock.is_active == True,
        )
        .all()
    )

    if not stocks:
        return {"status": "skipped", "message": "No active stocks in this universe."}

    r = redis_lib.from_url(settings.REDIS_URL)
    existing = r.get(f"universe:{universe_id}:sync")
    if existing:
        try:
            data = json.loads(existing)
            states = [
                AsyncResult(tid, app=celery_app).state for tid in data.get("task_ids", [])
            ]
            pending = sum(1 for s in states if s in ("PENDING", "STARTED", "RETRY"))
            if pending > 0:
                return {
                    "status": "rejected",
                    "message": (
                        f"Sync already in progress for universe {universe_id} "
                        f"({pending} tasks pending, started {data.get('started_at')}, "
                        f"timespan={data.get('timespan')}). "
                        f"Wait for it to finish or call /sync/stop first."
                    ),
                    "pending": pending,
                    "started_at": data.get("started_at"),
                    "timespan": data.get("timespan"),
                }
            r.delete(f"universe:{universe_id}:sync")
        except (ValueError, json.JSONDecodeError):
            r.delete(f"universe:{universe_id}:sync")

    stock_count = 0
    futures_count = 0
    queued_futures: set = set()
    task_ids: list = []

    for stock in stocks:
        if stock.asset_class == "futures":
            symbol = stock.ticker
            if symbol in queued_futures:
                continue
            metadata = stock.stock_metadata or {}
            exchange = metadata.get("primary_exchange")
            if not exchange or exchange == "Unknown":
                exchange = SYMBOL_EXCHANGE_MAP.get(symbol)
            if not exchange:
                logger.warning(
                    f"Universe {universe_id}: cannot determine exchange for futures "
                    f"symbol '{symbol}' — skipping aggregate sync."
                )
                continue
            result = sync_futures_aggregates.delay(
                symbol=symbol,
                exchange=exchange,
                timespan=timespan,
                multiplier=multiplier,
                from_date=from_date,
                to_date=to_date,
            )
            task_ids.append(result.id)
            queued_futures.add(symbol)
            futures_count += 1
        else:
            result = sync_stock_aggregates.delay(
                ticker=stock.ticker,
                from_date=from_date,
                to_date=to_date,
                multiplier=multiplier,
                timespan=timespan,
                adjusted=adjusted,
                sort=sort,
                limit=limit,
            )
            task_ids.append(result.id)
            stock_count += 1

    try:
        r.setex(
            f"universe:{universe_id}:sync",
            14400,
            json.dumps({
                "task_ids": task_ids,
                "total": len(task_ids),
                "started_at": datetime.now(timezone.utc).isoformat(),
                "timespan": timespan,
                "from_date": from_date,
                "to_date": to_date,
            }),
        )
    except Exception as e:
        logger.warning(f"Could not store sync status in Redis: {e}")

    parts = []
    if stock_count:
        parts.append(f"{stock_count} stocks ({from_date} to {to_date})")
    if futures_count:
        parts.append(f"{futures_count} futures symbol(s) via IBKR")
    return {
        "status": "accepted",
        "queued": len(task_ids),
        "message": f"Scheduled aggregate sync for {', '.join(parts)}.",
    }


def queue_quality_analysis(universe_id: int, db: Session) -> dict:
    """
    Upsert a pending UniverseQualityReport row (clearing stale snapshot fields)
    and queue the analyze_universe_quality Celery task.
    Raises UniverseNotFoundError if the universe does not exist.
    """
    from app.tasks import analyze_universe_quality

    universe = db.query(StockUniverse).filter(StockUniverse.id == universe_id).first()
    if not universe:
        raise UniverseNotFoundError(universe_id)

    report = (
        db.query(UniverseQualityReport)
        .filter(UniverseQualityReport.universe_id == universe_id)
        .first()
    )
    if not report:
        report = UniverseQualityReport(universe_id=universe_id)
        db.add(report)
    report.status = "pending"
    report.started_at = datetime.now(timezone.utc).replace(tzinfo=None)
    report.generated_at = None
    report.report_data = None
    report.overall_grade = None
    report.overall_score = None
    report.ticker_count = None
    report.error_message = None
    db.commit()

    analyze_universe_quality.delay(universe_id)

    return {"status": "accepted", "message": "Quality analysis queued."}


def queue_normalization(
    universe_id: int,
    target_tickers: Optional[List[str]],
    db: Session,
) -> dict:
    """
    Start (or resume) a normalization run for the universe.
    Accepts target_tickers (already unwrapped from NormalizeRequest by the router)
    to keep the service layer free of Pydantic models.
    Resumes from checkpoint if normalization_status is 'running' or 'error'
    and processed_combos exists.
    Raises UniverseNotFoundError if the universe does not exist.
    Raises UniverseValidationError if no quality analysis has been run yet.
    """
    from app.tasks import normalize_universe_quality

    universe = db.query(StockUniverse).filter(StockUniverse.id == universe_id).first()
    if not universe:
        raise UniverseNotFoundError(universe_id)

    report = (
        db.query(UniverseQualityReport)
        .filter(UniverseQualityReport.universe_id == universe_id)
        .first()
    )

    if not report or not report.report_data:
        raise UniverseValidationError(
            "No quality analysis found. Run 'Analyse' first.",
            universe_id=universe_id,
        )

    resume = bool(
        report.normalization_status in ("running", "error")
        and report.normalization_data
        and report.normalization_data.get("processed_combos")
    )

    report.normalization_status = "pending"
    if not resume:
        report.normalization_data = None
    db.commit()

    normalize_universe_quality.delay(universe_id, resume=resume, target_tickers=target_tickers)

    return {
        "status": "accepted",
        "resume": resume,
        "message": "Normalization queued." + (" Resuming from checkpoint." if resume else ""),
    }
```

- [ ] **Step 2: Verify import — confirm no circular import issues**

```bash
docker-compose exec backend python -c "
from app.services.universe_orchestrator import (
    discover_and_refresh, sync_missing_aggregates, get_sync_status,
    sync_aggregates, queue_quality_analysis, queue_normalization,
)
print('OK — all 6 functions imported')
"
```

Expected: `OK — all 6 functions imported`

The Celery task and `SYMBOL_EXCHANGE_MAP` imports are lazy (inside each function body) to prevent circular imports — `tasks.py` imports from `app.services` at module level, so cross-importing at module level is risky.

- [ ] **Step 3: Verify backend reloads**

```bash
docker-compose logs backend --tail=5
```

Expected: No errors.

- [ ] **Step 4: Commit**

```bash
git add backend/app/services/universe_orchestrator.py
git commit -m "feat(universe): add universe_orchestrator service with 6 extracted methods"
```

---

### Task 3: Create `services/universe_export.py` and update `services/__init__.py`

**Files:**
- Create: `backend/app/services/universe_export.py`
- Modify: `backend/app/services/__init__.py`

- [ ] **Step 1: Create `universe_export.py`**

Create `backend/app/services/universe_export.py`:

```python
"""
Export logic for universe aggregate data: DB queries and ZIP streaming.
Follows the universe_stats.py pattern: pure DB queries, no Celery, no Redis.
"""

import csv
import io
import zipfile
from datetime import datetime, timedelta
from typing import List, Optional

from fastapi import HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.exceptions import UniverseNotFoundError
from app.models import StockUniverse, StockUniverseTicker
from app.models.futures_aggregate import FuturesAggregate
from app.models.stock_aggregate import StockAggregate


STOCK_COLS = ["timestamp", "open", "high", "low", "close", "volume", "vwap", "transactions"]
FUTURES_COLS = [
    "timestamp", "open", "high", "low", "close",
    "volume", "vwap", "transactions", "contract_month",
]


def export_aggregates(universe_id: int, request, db: Session) -> StreamingResponse:
    """
    Build and stream a ZIP file containing aggregate (OHLCV) data for the
    requested tickers. `request` is typed as Any (duck-typed) so this service
    does not need to import ExportAggregatesRequest from the router — it accesses
    request.tickers, request.timespan, request.multiplier, request.from_date,
    request.to_date, request.zip_format. ExportAggregatesRequest stays defined
    in routers/universe.py and is passed in by the router handler.
    Raises UniverseNotFoundError if the universe does not exist.
    Raises HTTPException(400) if no tickers are provided.
    """
    universe = db.query(StockUniverse).filter(StockUniverse.id == universe_id).first()
    if not universe:
        raise UniverseNotFoundError(universe_id)

    tickers = request.tickers
    if not tickers:
        raise HTTPException(status_code=400, detail="No tickers selected")

    futures_set = {
        row.ticker
        for row in db.query(StockUniverseTicker.ticker)
        .filter(
            StockUniverseTicker.universe_id == universe_id,
            StockUniverseTicker.ticker.in_(tickers),
            StockUniverseTicker.asset_class == "futures",
        )
        .all()
    }
    stock_tickers = [t for t in tickers if t not in futures_set]
    futures_tickers = [t for t in tickers if t in futures_set]

    def _date_filter(ts_col):
        filters = []
        if request.from_date:
            filters.append(ts_col >= datetime.strptime(request.from_date, "%Y-%m-%d"))
        if request.to_date:
            filters.append(
                ts_col < datetime.strptime(request.to_date, "%Y-%m-%d") + timedelta(days=1)
            )
        return filters

    def _rows_for_stock(ticker):
        q = (
            db.query(StockAggregate)
            .filter(
                StockAggregate.ticker == ticker,
                StockAggregate.timespan == request.timespan,
                StockAggregate.multiplier == request.multiplier,
                *_date_filter(StockAggregate.timestamp),
            )
            .order_by(StockAggregate.timestamp.asc())
        )
        for row in q:
            yield {
                "timestamp": row.timestamp.strftime("%Y-%m-%d %H:%M:%S"),
                "open": float(row.open),
                "high": float(row.high),
                "low": float(row.low),
                "close": float(row.close),
                "volume": int(row.volume),
                "vwap": float(row.vwap) if row.vwap is not None else "",
                "transactions": row.transactions if row.transactions is not None else "",
            }

    def _rows_for_futures(symbol):
        q = (
            db.query(FuturesAggregate)
            .filter(
                FuturesAggregate.symbol == symbol,
                FuturesAggregate.timespan == request.timespan,
                FuturesAggregate.multiplier == request.multiplier,
                *_date_filter(FuturesAggregate.timestamp),
            )
            .order_by(FuturesAggregate.timestamp.asc())
        )
        for row in q:
            yield {
                "timestamp": row.timestamp.strftime("%Y-%m-%d %H:%M:%S"),
                "open": float(row.open),
                "high": float(row.high),
                "low": float(row.low),
                "close": float(row.close),
                "volume": int(row.volume),
                "vwap": float(row.vwap) if row.vwap is not None else "",
                "transactions": row.transactions if row.transactions is not None else "",
                "contract_month": row.contract_month,
            }

    def _write_csv(writer, rows, include_ticker=None):
        for row in rows:
            if include_ticker:
                row = {"ticker": include_ticker, **row}
            writer.writerow(row)

    safe_name = universe.name.replace(" ", "_")
    zip_filename = f"{safe_name}_export.zip"

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        if request.zip_format == "single_csv":
            csv_buf = io.StringIO()
            writer = csv.DictWriter(
                csv_buf, fieldnames=["ticker"] + FUTURES_COLS, extrasaction="ignore"
            )
            writer.writeheader()
            for ticker in stock_tickers:
                _write_csv(writer, _rows_for_stock(ticker), include_ticker=ticker)
            for symbol in futures_tickers:
                _write_csv(writer, _rows_for_futures(symbol), include_ticker=symbol)
            zf.writestr(f"{safe_name}/{safe_name}_aggregates.csv", csv_buf.getvalue())
        else:
            for ticker in stock_tickers:
                csv_buf = io.StringIO()
                writer = csv.DictWriter(csv_buf, fieldnames=STOCK_COLS)
                writer.writeheader()
                _write_csv(writer, _rows_for_stock(ticker))
                zf.writestr(f"{safe_name}/{ticker}.csv", csv_buf.getvalue())
            for symbol in futures_tickers:
                csv_buf = io.StringIO()
                writer = csv.DictWriter(csv_buf, fieldnames=FUTURES_COLS)
                writer.writeheader()
                _write_csv(writer, _rows_for_futures(symbol))
                zf.writestr(f"{safe_name}/{symbol}.csv", csv_buf.getvalue())

    buf.seek(0)

    return StreamingResponse(
        iter([buf.read()]),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{zip_filename}"'},
    )
```

- [ ] **Step 2: Update `services/__init__.py` to export the new modules**

In `backend/app/services/__init__.py`, change:

```python
"""
Services package.
"""

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

to:

```python
"""
Services package.
"""

from app.services.stock_data import StockDataService
from app.services.scanner import ScannerService
from app.services import journal_service
from app.services.futures_data import FuturesDataService
from app.services.universe_stats import UniverseStatsService
from app.services import universe_orchestrator, universe_export

__all__ = [
    "StockDataService",
    "ScannerService",
    "journal_service",
    "FuturesDataService",
    "UniverseStatsService",
    "universe_orchestrator",
    "universe_export",
]
```

- [ ] **Step 3: Verify import**

```bash
docker-compose exec backend python -c "
from app.services.universe_export import export_aggregates
from app.services import universe_orchestrator, universe_export
print('OK')
"
```

Expected: `OK`

- [ ] **Step 4: Verify backend reloads**

```bash
docker-compose logs backend --tail=5
```

Expected: No errors.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/universe_export.py backend/app/services/__init__.py
git commit -m "feat(universe): add universe_export service module"
```

---

### Task 4: Refactor `routers/universe.py` — replace 7 handler bodies with service delegates

**Files:**
- Modify: `backend/app/routers/universe.py`

This task performs the actual extraction. Each of the 7 orchestration-heavy handlers is reduced to a thin shell. Eleven handlers (create, update, delete, list, by-ticker, refresh-stats, sync/fundamentals, sync/details, sync/stop, sync/metrics, stocks, quality-report, delete-aggregates) are left untouched.

- [ ] **Step 1: Add service imports at the top of `universe.py`**

After line 25 (`from app.services.universe_stats import UniverseStatsService`), add:

```python
from app.exceptions import UniverseNotFoundError, UniverseValidationError
from app.services import universe_orchestrator, universe_export
```

- [ ] **Step 2: Remove the unused `StockDataService` import**

Remove line 24:
```python
from app.services import StockDataService
```

`StockDataService` is imported but not used anywhere in this router. Removing it eliminates a dead import.

- [ ] **Step 3: Replace `refresh_universe` handler (L264–343, ~80 LOC → 6 LOC)**

Replace the full body of `refresh_universe`:

Old (full function, lines 264–343):
```python
@router.post("/{universe_id}/refresh")
def refresh_universe(
    universe_id: int,
    db: Session = Depends(get_db),
):
    """
    Refresh stocks in a universe using the Universe Discovery Engine.
    Efficiently queries local cache of 10,000+ stocks.
    """
    universe = db.query(StockUniverse).filter(StockUniverse.id == universe_id).first()
    if not universe:
        raise HTTPException(status_code=404, detail="Universe not found")

    # Clear existing stocks for this universe
    db.query(MonitoredStock).filter(MonitoredStock.universe_id == universe_id).delete()
    db.query(StockUniverseTicker).filter(StockUniverseTicker.universe_id == universe_id).delete()
    
    # Use Discovery Service
    service = DiscoveryService(db)
    criteria = universe.criteria or {}
    
    # Execute Screen
    results = service.run_screen(criteria)
    
    added_count = 0
    
    # Bulk insert (or optimized loop)
    for res in results:
        monitored_stock = MonitoredStock(
            ticker=res["ticker"],
            universe_id=universe_id,
            added_date=get_market_today(),
            is_active=True,
            asset_class=res.get("asset_class", "stocks"),
            data_source=res.get("data_source", "massive"),
            company_name=res["name"],
            sector=res["sector"],
            market_cap=res["market_cap"],
            stock_metadata={
                "source": "discovery_engine",
                "close_price": res["close_price"],
                "volume": res["volume"],
                "primary_exchange": res.get("primary_exchange"),
                "employees": res.get("employees"),
                "sic_code": res.get("sic_code"),
                "description_preview": (res.get("description") or "")[:100] + "..." if res.get("description") else None
            }
        )
        db.add(monitored_stock)
        
        # Also populate StockUniverseTicker for persistent ticker list
        stock_ticker = StockUniverseTicker(
            universe_id=universe_id,
            ticker=res["ticker"],
            asset_class=res.get("asset_class", "stocks"),
            data_source=res.get("data_source", "massive"),
            created_at=datetime.now(timezone.utc).replace(tzinfo=None)
        )
        db.add(stock_ticker)

        added_count += 1
        
    db.commit()

    # Refresh cached stats now that tickers changed
    stats = UniverseStatsService.compute(universe_id, db)
    universe.cached_ticker_count = stats["ticker_count"]
    universe.cached_aggregate_count = stats["aggregate_count"]
    universe.cached_min_date = stats["min_date"]
    universe.cached_max_date = stats["max_date"]
    universe.cached_timespans = stats["timespans"]
    universe.stats_refreshed_at = datetime.now(timezone.utc).replace(tzinfo=None)
    db.commit()

    return {
        "status": "completed",
        "scanned": "ALL",  # We scanned the whole DB effectively
        "added": added_count,
        "message": f"Successfully refreshed universe. Added {added_count} assets from Discovery Engine.",
    }
```

New:
```python
@router.post("/{universe_id}/refresh")
def refresh_universe(
    universe_id: int,
    db: Session = Depends(get_db),
):
    """Refresh stocks in a universe using the Universe Discovery Engine."""
    try:
        return universe_orchestrator.discover_and_refresh(universe_id, db)
    except UniverseNotFoundError:
        raise HTTPException(status_code=404, detail="Universe not found")
```

- [ ] **Step 4: Replace `sync_missing_aggregates` handler (L346–464, ~118 LOC → 4 LOC)**

Replace the full body of `sync_missing_aggregates`:

Old (lines 346–464 — full function with all the json/redis/celery imports and body):
```python
@router.post("/{universe_id}/sync-missing")
def sync_missing_aggregates(
    universe_id: int,
    db: Session = Depends(get_db),
):
    """
    For every (timespan, multiplier) already recorded in this universe,
    queue a sync from the last stored bar up to today.
    Handles all timespans (minute, hour, day, etc.) in one click.
    """
    import json
    import redis as redis_lib
    from app.tasks import sync_stock_aggregates, sync_futures_aggregates
    from app.services.futures_data import SYMBOL_EXCHANGE_MAP
    from app.models.futures_aggregate import FuturesAggregate
    from app.core.config import settings
    from sqlalchemy import func
    ... (rest of ~100 LOC body)
```

New:
```python
@router.post("/{universe_id}/sync-missing")
def sync_missing_aggregates(
    universe_id: int,
    db: Session = Depends(get_db),
):
    """For every recorded (timespan, multiplier), queue a sync from last bar to today."""
    return universe_orchestrator.sync_missing_aggregates(universe_id, db)
```

- [ ] **Step 5: Replace `get_universe_sync_status` handler (L467–523, ~56 LOC → 3 LOC)**

Old (lines 467–523 — full function with json/redis/celery imports):
```python
@router.get("/{universe_id}/sync-status")
def get_universe_sync_status(universe_id: int):
    """
    Return the current sync progress for a universe.
    Reads task IDs stored by sync-aggregates and checks Celery task states.
    """
    import json
    import redis as redis_lib
    from datetime import timezone
    from celery.result import AsyncResult
    from app.core.celery_app import celery_app
    from app.core.config import settings
    ... (rest of ~50 LOC body)
```

New:
```python
@router.get("/{universe_id}/sync-status")
def get_universe_sync_status(universe_id: int):
    """Return the current sync progress for a universe."""
    return universe_orchestrator.get_sync_status(universe_id)
```

- [ ] **Step 6: Replace `export_universe_aggregates` handler (L526–662, ~139 LOC → 7 LOC)**

Old (lines 526–662 — full function with io/csv/zipfile imports):
```python
@router.post("/{universe_id}/export-aggregates")
def export_universe_aggregates(
    universe_id: int,
    request: "ExportAggregatesRequest",
    db: Session = Depends(get_db),
):
    """
    Stream a ZIP file containing aggregate (OHLCV) data for the requested tickers.
    ...
    """
    import io
    import csv
    import zipfile
    from fastapi.responses import StreamingResponse
    from app.models.futures_aggregate import FuturesAggregate
    from sqlalchemy import and_
    ... (rest of ~130 LOC body)
```

New (also change the string annotation `"ExportAggregatesRequest"` → direct reference `ExportAggregatesRequest`, since the class is defined before this handler):
```python
@router.post("/{universe_id}/export-aggregates")
def export_universe_aggregates(
    universe_id: int,
    request: ExportAggregatesRequest,
    db: Session = Depends(get_db),
):
    """Stream a ZIP file containing aggregate (OHLCV) data for the requested tickers."""
    try:
        return universe_export.export_aggregates(universe_id, request, db)
    except UniverseNotFoundError:
        raise HTTPException(status_code=404, detail="Universe not found")
```

- [ ] **Step 7: Replace `sync_universe_aggregates` handler (L682–825, ~143 LOC → 10 LOC)**

Old (lines 682–825):
```python
@router.post("/{universe_id}/sync-aggregates")
def sync_universe_aggregates(
    universe_id: int,
    background_tasks: BackgroundTasks,
    from_date: str,
    to_date: str,
    multiplier: int = 1,
    timespan: str = "minute",
    adjusted: bool = True,
    sort: str = "asc",
    limit: int = 50000,
    db: Session = Depends(get_db),
):
    """...Trigger backfill..."""
    from app.tasks import sync_stock_aggregates, sync_futures_aggregates
    from app.services.futures_data import SYMBOL_EXCHANGE_MAP
    ... (rest of ~130 LOC body)
```

New (`background_tasks` is removed — it was injected but never used in the function body; this is not a public API change):
```python
@router.post("/{universe_id}/sync-aggregates")
def sync_universe_aggregates(
    universe_id: int,
    from_date: str,
    to_date: str,
    multiplier: int = 1,
    timespan: str = "minute",
    adjusted: bool = True,
    sort: str = "asc",
    limit: int = 50000,
    db: Session = Depends(get_db),
):
    """Trigger backfill of aggregates for all stocks in the universe."""
    return universe_orchestrator.sync_aggregates(
        universe_id, from_date, to_date, multiplier, timespan, adjusted, sort, limit, db
    )
```

- [ ] **Step 8: Replace `trigger_quality_analysis` handler (L830–867, ~37 LOC → 6 LOC)**

Old (lines 830–867):
```python
@router.post("/{universe_id}/analyze-quality")
def trigger_quality_analysis(
    universe_id: int,
    db: Session = Depends(get_db),
):
    """...Queue a background data-quality analysis..."""
    from app.tasks import analyze_universe_quality
    from app.models.universe_quality_report import UniverseQualityReport
    ... (rest of ~30 LOC body)
```

New:
```python
@router.post("/{universe_id}/analyze-quality")
def trigger_quality_analysis(
    universe_id: int,
    db: Session = Depends(get_db),
):
    """Queue a background data-quality analysis. Poll GET .../quality-report for results."""
    try:
        return universe_orchestrator.queue_quality_analysis(universe_id, db)
    except UniverseNotFoundError:
        raise HTTPException(status_code=404, detail="Universe not found")
```

- [ ] **Step 9: Replace `trigger_normalization` handler (L954–1006, ~52 LOC → 9 LOC)**

Old (lines 954–1006):
```python
@router.post("/{universe_id}/normalize")
def trigger_normalization(
    universe_id: int,
    request: Optional[NormalizeRequest] = None,
    db: Session = Depends(get_db),
):
    """...Start (or resume) a normalization run..."""
    from app.tasks import normalize_universe_quality
    from app.models.universe_quality_report import UniverseQualityReport
    ... (rest of ~45 LOC body)
```

New:
```python
@router.post("/{universe_id}/normalize")
def trigger_normalization(
    universe_id: int,
    request: Optional[NormalizeRequest] = None,
    db: Session = Depends(get_db),
):
    """Start (or resume) a normalization run. Poll GET .../quality-report for status."""
    target_tickers = request.target_tickers if request else None
    try:
        return universe_orchestrator.queue_normalization(universe_id, target_tickers, db)
    except UniverseNotFoundError:
        raise HTTPException(status_code=404, detail="Universe not found")
    except UniverseValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))
```

- [ ] **Step 10: Check whether `BackgroundTasks` import is still needed**

`BackgroundTasks` is still used by three untouched handlers (`sync_fundamental_data`, `sync_ticker_details`, `sync_daily_metrics`). Keep the import.

- [ ] **Step 11: Remove dead code to reach the ≤400 LOC target**

After extraction, two blocks become dead and must be removed:

**a) Remove `import logging` (line 5)** — all `logger.warning(...)` calls moved to `universe_orchestrator.py`. The router no longer uses `logging` directly.

**b) Remove `timedelta` from the datetime import (line 6)** — after extraction, `timedelta` is used only in the moved handlers (sync_missing, export). Change:
```python
from datetime import datetime, timedelta, timezone
```
to:
```python
from datetime import datetime, timezone
```

**c) Remove the `COMMON_STOCKS` constant (lines 39–44):**
```python
# Common stocks for scanning (Mock "All Stocks" source)
# In production, this would be replaced by a real market screener API
COMMON_STOCKS = [
    "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "TSLA", "META", "BRK-B", "TSM", "UNH",
    "JNJ", "JPM", "V", "PG", "MA", "HD", "CVX", "MRK", "ABBV", "PEP",
    "KO", "LLY", "BAC", "COST", "AVGO", "TMO", "DIS", "WMT", "CSCO", "ACN",
]
```
`COMMON_STOCKS` is defined but never referenced anywhere in the router. Removing it eliminates 7 lines.

- [ ] **Step 12: Verify backend reloads and check LOC**

```bash
docker-compose logs backend --tail=5
wc -l backend/app/routers/universe.py
```

Expected: No errors. LOC ≤ 400. If the count is still above 400, consolidate redundant blank lines (the file has several consecutive blank lines) until the target is met.

- [ ] **Step 13: Commit**

```bash
git add backend/app/routers/universe.py
git commit -m "refactor(universe): replace 7 handler bodies with thin service delegates"
```

---

### Task 5: Validate all affected endpoints with curl

**Files:** (none — validation only)

Per CLAUDE.md: confirm the backend reloaded, then curl every affected endpoint.

- [ ] **Step 1: Confirm backend is up**

```bash
docker-compose logs backend --tail=10
curl -s http://localhost:8000/api/health | python -m json.tool
```

Expected: Health endpoint returns `{"status": "ok"}` or similar.

- [ ] **Step 2: Get a valid universe ID**

```bash
UNIVERSE_ID=$(curl -s http://localhost:8000/api/universe/list \
  | python -c "import sys,json; d=json.load(sys.stdin); print(d[0]['id'] if d else 'NONE')")
echo "Universe ID: $UNIVERSE_ID"
```

If the list is empty, create a universe first:

```bash
UNIVERSE_ID=$(curl -s -X POST http://localhost:8000/api/universe/create \
  -H "Content-Type: application/json" \
  -d '{"name":"Test Universe","description":"Plan validation","criteria":{}}' \
  | python -c "import sys,json; print(json.load(sys.stdin)['id'])")
echo "Created universe: $UNIVERSE_ID"
```

- [ ] **Step 3: Validate GET /api/universe/list (untouched handler — regression check)**

```bash
curl -s "http://localhost:8000/api/universe/list" | python -m json.tool | head -10
```

Expected: JSON array, HTTP 200.

- [ ] **Step 4: Validate GET /api/universe/{id}/sync-status**

```bash
curl -s "http://localhost:8000/api/universe/$UNIVERSE_ID/sync-status" | python -m json.tool
```

Expected: JSON with keys `is_syncing`, `pending`, `success`, `failed`, `total`. HTTP 200.

- [ ] **Step 5: Validate GET /api/universe/{id}/quality-report**

```bash
curl -s "http://localhost:8000/api/universe/$UNIVERSE_ID/quality-report" | python -m json.tool
```

Expected: Quality report JSON or `null`. HTTP 200.

- [ ] **Step 6: Validate POST /api/universe/{id}/sync-missing**

```bash
curl -s -X POST "http://localhost:8000/api/universe/$UNIVERSE_ID/sync-missing" \
  | python -m json.tool
```

Expected: JSON with `status` key (`"accepted"` or `"skipped"`). HTTP 200.

- [ ] **Step 7: Validate POST /api/universe/{id}/analyze-quality**

```bash
curl -s -X POST "http://localhost:8000/api/universe/$UNIVERSE_ID/analyze-quality" \
  | python -m json.tool
```

Expected: `{"status": "accepted", "message": "Quality analysis queued."}`. HTTP 200.

- [ ] **Step 8: Validate 404 on non-existent universe (refresh, analyze-quality, normalize)**

```bash
curl -s -o /dev/null -w "%{http_code}" -X POST "http://localhost:8000/api/universe/999999/refresh"
curl -s -o /dev/null -w "%{http_code}" -X POST "http://localhost:8000/api/universe/999999/analyze-quality"
curl -s -o /dev/null -w "%{http_code}" -X POST "http://localhost:8000/api/universe/999999/normalize"
```

Expected: `404` for all three.

- [ ] **Step 9: Validate 400 on normalize without prior analysis**

If `$UNIVERSE_ID` has no quality report (just created), normalize should return 400:

```bash
curl -s -X POST "http://localhost:8000/api/universe/$UNIVERSE_ID/normalize" \
  | python -m json.tool
```

Expected: `{"detail": "No quality analysis found. Run 'Analyse' first."}` with HTTP 400.

(If a report exists from Step 7's background task, the endpoint will return `{"status": "accepted", ...}` — both are correct.)

- [ ] **Step 10: Validate POST /api/universe/{id}/sync-aggregates**

```bash
curl -s -X POST \
  "http://localhost:8000/api/universe/$UNIVERSE_ID/sync-aggregates?from_date=2024-01-01&to_date=2024-01-02&timespan=day" \
  | python -m json.tool
```

Expected: JSON with `status` key (`"accepted"`, `"skipped"`, or `"rejected"`). HTTP 200.

- [ ] **Step 11: Confirm final LOC and report**

```bash
wc -l backend/app/routers/universe.py
```

Expected: ≤ 400.

```bash
echo "Extraction complete. Router LOC: $(wc -l < backend/app/routers/universe.py)"
```
