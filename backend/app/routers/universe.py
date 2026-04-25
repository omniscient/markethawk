"""
Universe router - CRUD operations for stock universes.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from app.utils.session import get_market_today
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models import StockUniverse, MonitoredStock, StockUniverseTicker
from app.models.stock_aggregate import StockAggregate
from app.schemas import (
    StockUniverseCreate,
    StockUniverseUpdate,
    StockUniverseResponse,
    MonitoredStockResponse,
)
from app.services import StockDataService

router = APIRouter(prefix="/api/universe", tags=["universe"])


class ExportAggregatesRequest(BaseModel):
    tickers: List[str]
    timespan: str = "day"
    multiplier: int = 1
    from_date: Optional[str] = None
    to_date: Optional[str] = None
    zip_format: str = "per_ticker"  # "per_ticker" | "single_csv"

# Common stocks for scanning (Mock "All Stocks" source)
# In production, this would be replaced by a real market screener API
COMMON_STOCKS = [
    "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "TSLA", "META", "BRK-B", "TSM", "UNH",
    "JNJ", "JPM", "V", "PG", "MA", "HD", "CVX", "MRK", "ABBV", "PEP",
    "KO", "LLY", "BAC", "COST", "AVGO", "TMO", "DIS", "WMT", "CSCO", "ACN",
]


@router.post("/create", response_model=StockUniverseResponse)
def create_stock_universe(
    universe: StockUniverseCreate,
    db: Session = Depends(get_db),
):
    """Create a new stock universe."""
    db_universe = StockUniverse(**universe.dict())
    db.add(db_universe)
    db.commit()
    db.refresh(db_universe)

    return db_universe


@router.put("/{universe_id}", response_model=StockUniverseResponse)
def update_stock_universe(
    universe_id: int,
    universe_update: StockUniverseUpdate,
    db: Session = Depends(get_db),
):
    """Update a stock universe."""
    db_universe = (
        db.query(StockUniverse).filter(StockUniverse.id == universe_id).first()
    )
    if not db_universe:
        raise HTTPException(status_code=404, detail="Universe not found")

    update_data = universe_update.dict(exclude_unset=True)
    for key, value in update_data.items():
        setattr(db_universe, key, value)

    db.commit()
    db.refresh(db_universe)
    return db_universe


@router.delete("/{universe_id}")
def delete_stock_universe(
    universe_id: int,
    db: Session = Depends(get_db),
):
    """Delete (soft delete) a stock universe."""
    universe = db.query(StockUniverse).filter(StockUniverse.id == universe_id).first()
    if not universe:
        raise HTTPException(status_code=404, detail="Universe not found")

    universe.is_active = False
    db.commit()
    return {"message": "Universe deleted successfully"}


def _compute_universe_stats(universe_id: int, db: Session) -> dict:
    """
    Run the heavy aggregate queries for one universe and return a stats dict.
    Called by refresh-stats; not used in the list endpoint anymore.
    """
    from sqlalchemy import func
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
            min_date = stock_stats[1] if min_date is None else min(min_date, stock_stats[1]) if stock_stats[1] else min_date
            max_date = stock_stats[2] if max_date is None else max(max_date, stock_stats[2]) if stock_stats[2] else max_date

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
            min_date = futures_stats[1] if min_date is None else min(min_date, futures_stats[1]) if futures_stats[1] else min_date
            max_date = futures_stats[2] if max_date is None else max(max_date, futures_stats[2]) if futures_stats[2] else max_date

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
        from app.models.futures_aggregate import FuturesAggregate
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


@router.get("/list", response_model=List[StockUniverseResponse])
def list_stock_universes(
    include_stats: bool = True,
    db: Session = Depends(get_db),
):
    """
    List all active stock universes.

    - include_stats=true (default): returns cached aggregate stats (ticker count,
      bar count, date range, timespans). Stats are pre-computed; call
      POST /{id}/refresh-stats to update them after a sync.
    - include_stats=false: returns only identity fields (id, name, description,
      criteria). Use this for dropdowns/selects that don't need stats.
    """
    universes = db.query(StockUniverse).filter(StockUniverse.is_active == True).all()

    results = []
    for universe in universes:
        universe_data = StockUniverseResponse.from_orm(universe)

        if include_stats:
            # Read from cached columns — zero heavy queries
            universe_data.ticker_count = universe.cached_ticker_count or 0
            universe_data.aggregate_count = universe.cached_aggregate_count or 0
            universe_data.min_aggregate_date = universe.cached_min_date
            universe_data.max_aggregate_date = universe.cached_max_date
            universe_data.available_timespans = universe.cached_timespans or []
            universe_data.stats_refreshed_at = universe.stats_refreshed_at
        else:
            universe_data.ticker_count = 0
            universe_data.aggregate_count = 0
            universe_data.min_aggregate_date = None
            universe_data.max_aggregate_date = None
            universe_data.available_timespans = []

        results.append(universe_data)

    return results


@router.post("/{universe_id}/refresh-stats", response_model=StockUniverseResponse)
def refresh_universe_stats(
    universe_id: int,
    db: Session = Depends(get_db),
):
    """
    Recompute and persist aggregate stats for this universe.
    Call after syncing aggregates or refreshing tickers to update the cache.
    """
    universe = db.query(StockUniverse).filter(StockUniverse.id == universe_id).first()
    if not universe:
        raise HTTPException(status_code=404, detail="Universe not found")

    stats = _compute_universe_stats(universe_id, db)

    universe.cached_ticker_count = stats["ticker_count"]
    universe.cached_aggregate_count = stats["aggregate_count"]
    universe.cached_min_date = stats["min_date"]
    universe.cached_max_date = stats["max_date"]
    universe.cached_timespans = stats["timespans"]
    universe.stats_refreshed_at = datetime.now(timezone.utc).replace(tzinfo=None)
    db.commit()
    db.refresh(universe)

    universe_data = StockUniverseResponse.from_orm(universe)
    universe_data.ticker_count = universe.cached_ticker_count or 0
    universe_data.aggregate_count = universe.cached_aggregate_count or 0
    universe_data.min_aggregate_date = universe.cached_min_date
    universe_data.max_aggregate_date = universe.cached_max_date
    universe_data.available_timespans = universe.cached_timespans or []
    universe_data.stats_refreshed_at = universe.stats_refreshed_at
    return universe_data


from fastapi import BackgroundTasks
from app.services.discovery_service import DiscoveryService

@router.post("/sync/fundamentals")
def sync_fundamental_data(
    background_tasks: BackgroundTasks,
    delay: float = 15.0, # Default to 15s (Free Tier)
    db: Session = Depends(get_db),
):
    """Trigger background sync of fundamental data from Polygon."""
    service = DiscoveryService(db)
    background_tasks.add_task(service.sync_fundamental_data, delay_seconds=delay)
    return {"status": "accepted", "message": f"Fundamental sync started in background (delay={delay}s)"}

@router.post("/sync/details")
def sync_ticker_details(
    background_tasks: BackgroundTasks,
    delay: float = 15.0, # Default to 15s (Free Tier)
    resync: bool = False,
    db: Session = Depends(get_db),
):
    """
    Trigger background sync of ticker details (Description, etc).
    delay: Seconds to wait between requests (15.0=Free, 0.2=Paid)
    resync: Set to true to force re-crawling all tickers even if recently updated.
    """
    service = DiscoveryService(db)
    background_tasks.add_task(service.sync_ticker_details_crawler, delay, resync)
    return {"status": "accepted", "message": f"Ticker details sync started in background (delay={delay}s, resync={resync})"}



@router.post("/sync/stop")
def stop_sync(
    db: Session = Depends(get_db),
):
    """
    Stops any running sync process by setting a Stop Flag in Redis and purging the queue.
    """
    from app.core.celery_app import celery_app
    from app.core.config import settings
    import redis

    # 1. Set Stop Flag in Redis
    # Tasks check this flag before scheduling the next iteration
    try:
        r = redis.from_url(settings.REDIS_URL)
        r.setex("CRAWLER_STOP_FLAG", 60, "1") # Set flag for 60 seconds (enough to catch running tasks)
        redis_status = "Flag set."
    except Exception as e:
        redis_status = f"Redis error: {e}"

    # 2. Purge all pending tasks (Classic method)
    purged_count = celery_app.control.purge()
    
    return {
        "status": "stopped", 
        "message": f"Stop signal sent ({redis_status}). {purged_count} pending tasks removed."
    }

@router.post("/sync/metrics")
def sync_daily_metrics(
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """Trigger background update of daily technical metrics."""
    service = DiscoveryService(db)
    background_tasks.add_task(service.update_daily_metrics_snapshot)
    return {"status": "accepted", "message": "Daily metrics update started in background"}


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
    stats = _compute_universe_stats(universe_id, db)
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

    stocks = (
        db.query(MonitoredStock)
        .filter(MonitoredStock.universe_id == universe_id, MonitoredStock.is_active == True)
        .all()
    )
    if not stocks:
        return {"status": "skipped", "message": "No active stocks in this universe."}

    now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
    today = now_utc.strftime("%Y-%m-%d")
    stock_tickers  = [s.ticker for s in stocks if s.asset_class != "futures"]
    futures_stocks = [s for s in stocks if s.asset_class == "futures"]
    futures_tickers = list({s.ticker for s in futures_stocks})

    task_ids: list = []
    summary: list = []

    # --- Stocks: group by (timespan, multiplier), get per-group max timestamp ---
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
            from_dt = (combo.max_ts + timedelta(seconds=1)) if combo.max_ts else (now_utc - timedelta(days=7))
            # Only skip if from_dt is genuinely in the future (nothing new can exist yet)
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
            summary.append(f"{combo.timespan}×{combo.multiplier}: {len(stock_tickers)} stocks from {from_date}")

    # --- Futures: same logic against FuturesAggregate ---
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
            from_dt = (combo.max_ts + timedelta(seconds=1)) if combo.max_ts else (now_utc - timedelta(days=7))
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
            summary.append(f"{combo.timespan}×{combo.multiplier}: {len(futures_tickers)} futures from {from_date}")

    if not task_ids:
        return {"status": "skipped", "message": "No existing aggregate data found to extend — use Sync to do an initial download first."}

    # Store in Redis for sync-status polling
    try:
        r = redis_lib.from_url(settings.REDIS_URL)
        r.setex(
            f"universe:{universe_id}:sync",
            14400,
            json.dumps({"task_ids": task_ids, "total": len(task_ids), "started_at": datetime.now(timezone.utc).isoformat()}),
        )
    except Exception as e:
        logger.warning(f"Could not store sync-missing status in Redis: {e}")

    return {"status": "accepted", "queued": len(task_ids), "summary": summary}


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

    r = redis_lib.from_url(settings.REDIS_URL)
    raw = r.get(f"universe:{universe_id}:sync")
    if not raw:
        return {"is_syncing": False, "pending": 0, "success": 0, "failed": 0, "total": 0}

    data = json.loads(raw)
    task_ids = data.get("task_ids", [])
    started_at_str = data.get("started_at")

    # If the sync key is older than 4 hours, consider it stale and clear it.
    # Celery task results expire from the result backend (default 24h), after which
    # AsyncResult.state returns "PENDING" for completed tasks — making them look stuck.
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
    # "PENDING" from AsyncResult can mean either "waiting to run" or "result expired/unknown".
    # Only treat as truly pending if the task was submitted recently (within the stale window above).
    pending = sum(1 for s in states if s in ("PENDING", "STARTED", "RETRY"))
    success = sum(1 for s in states if s == "SUCCESS")
    failed  = sum(1 for s in states if s in ("FAILURE", "REVOKED"))

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


@router.post("/{universe_id}/export-aggregates")
def export_universe_aggregates(
    universe_id: int,
    request: "ExportAggregatesRequest",
    db: Session = Depends(get_db),
):
    """
    Stream a ZIP file containing aggregate (OHLCV) data for the requested tickers.

    zip_format:
      "per_ticker" — one CSV per ticker inside the ZIP
      "single_csv" — all tickers combined into one CSV (ticker column added)
    """
    import io
    import csv
    import zipfile
    from fastapi.responses import StreamingResponse
    from app.models.futures_aggregate import FuturesAggregate
    from sqlalchemy import and_

    universe = db.query(StockUniverse).filter(StockUniverse.id == universe_id).first()
    if not universe:
        raise HTTPException(status_code=404, detail="Universe not found")

    tickers = request.tickers
    if not tickers:
        raise HTTPException(status_code=400, detail="No tickers selected")

    # Determine which requested tickers are futures vs stocks
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
    stock_tickers   = [t for t in tickers if t not in futures_set]
    futures_tickers = [t for t in tickers if t in futures_set]

    def _date_filter(model, ts_col, from_date, to_date):
        filters = []
        if from_date:
            filters.append(ts_col >= datetime.strptime(from_date, "%Y-%m-%d"))
        if to_date:
            # inclusive end-of-day
            filters.append(ts_col < datetime.strptime(to_date, "%Y-%m-%d") + timedelta(days=1))
        return filters

    STOCK_COLS   = ["timestamp", "open", "high", "low", "close", "volume", "vwap", "transactions"]
    FUTURES_COLS = ["timestamp", "open", "high", "low", "close", "volume", "vwap", "transactions", "contract_month"]

    def _rows_for_stock(ticker):
        from app.models.stock_aggregate import StockAggregate
        q = db.query(StockAggregate).filter(
            StockAggregate.ticker == ticker,
            StockAggregate.timespan == request.timespan,
            StockAggregate.multiplier == request.multiplier,
            *_date_filter(StockAggregate, StockAggregate.timestamp, request.from_date, request.to_date),
        ).order_by(StockAggregate.timestamp.asc())
        for row in q:
            yield {
                "timestamp": row.timestamp.strftime("%Y-%m-%d %H:%M:%S"),
                "open":  float(row.open),
                "high":  float(row.high),
                "low":   float(row.low),
                "close": float(row.close),
                "volume": int(row.volume),
                "vwap":  float(row.vwap) if row.vwap is not None else "",
                "transactions": row.transactions if row.transactions is not None else "",
            }

    def _rows_for_futures(symbol):
        q = db.query(FuturesAggregate).filter(
            FuturesAggregate.symbol == symbol,
            FuturesAggregate.timespan == request.timespan,
            FuturesAggregate.multiplier == request.multiplier,
            *_date_filter(FuturesAggregate, FuturesAggregate.timestamp, request.from_date, request.to_date),
        ).order_by(FuturesAggregate.timestamp.asc())
        for row in q:
            yield {
                "timestamp": row.timestamp.strftime("%Y-%m-%d %H:%M:%S"),
                "open":  float(row.open),
                "high":  float(row.high),
                "low":   float(row.low),
                "close": float(row.close),
                "volume": int(row.volume),
                "vwap":  float(row.vwap) if row.vwap is not None else "",
                "transactions": row.transactions if row.transactions is not None else "",
                "contract_month": row.contract_month,
            }

    def _write_csv(writer, fieldnames, rows, include_ticker=None):
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
            all_cols = ["ticker"] + STOCK_COLS  # futures get same columns (contract_month appended)
            writer = csv.DictWriter(csv_buf, fieldnames=["ticker"] + FUTURES_COLS, extrasaction="ignore")
            writer.writeheader()
            for ticker in stock_tickers:
                _write_csv(writer, STOCK_COLS, _rows_for_stock(ticker), include_ticker=ticker)
            for symbol in futures_tickers:
                _write_csv(writer, FUTURES_COLS, _rows_for_futures(symbol), include_ticker=symbol)
            zf.writestr(f"{safe_name}/{safe_name}_aggregates.csv", csv_buf.getvalue())
        else:
            # per-ticker
            for ticker in stock_tickers:
                csv_buf = io.StringIO()
                writer = csv.DictWriter(csv_buf, fieldnames=STOCK_COLS)
                writer.writeheader()
                _write_csv(writer, STOCK_COLS, _rows_for_stock(ticker))
                zf.writestr(f"{safe_name}/{ticker}.csv", csv_buf.getvalue())
            for symbol in futures_tickers:
                csv_buf = io.StringIO()
                writer = csv.DictWriter(csv_buf, fieldnames=FUTURES_COLS)
                writer.writeheader()
                _write_csv(writer, FUTURES_COLS, _rows_for_futures(symbol))
                zf.writestr(f"{safe_name}/{symbol}.csv", csv_buf.getvalue())

    buf.seek(0)

    return StreamingResponse(
        iter([buf.read()]),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{zip_filename}"'},
    )


@router.get("/{universe_id}/stocks", response_model=List[MonitoredStockResponse])
def get_universe_stocks(
    universe_id: int,
    db: Session = Depends(get_db),
):
    """List all stocks in a universe."""
    stocks = (
        db.query(MonitoredStock)
        .filter(
            MonitoredStock.universe_id == universe_id,
            MonitoredStock.is_active == True,
        )
        .all()
    )
    return stocks


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
    """
    Trigger backfill of aggregates for all stocks in the universe.
    Stocks use the Polygon (Massive) provider; futures use IBKR via FuturesDataService.
    """
    from app.tasks import sync_stock_aggregates, sync_futures_aggregates
    from app.services.futures_data import SYMBOL_EXCHANGE_MAP

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

    import json
    import redis as redis_lib
    from app.core.config import settings

    stock_count = 0
    futures_count = 0
    queued_futures: set = set()
    task_ids: list = []

    for stock in stocks:
        if stock.asset_class == "futures":
            symbol = stock.ticker
            if symbol in queued_futures:
                continue

            # Resolve exchange: stored metadata → known symbol map → skip
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

    # Store task IDs in Redis so the frontend can poll sync progress
    try:
        r = redis_lib.from_url(settings.REDIS_URL)
        r.setex(
            f"universe:{universe_id}:sync",
            14400,  # 4-hour TTL
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


# ── Data Quality ─────────────────────────────────────────────────────────────

@router.post("/{universe_id}/analyze-quality")
def trigger_quality_analysis(
    universe_id: int,
    db: Session = Depends(get_db),
):
    """
    Queue a background data-quality analysis for the universe.
    Returns immediately; poll GET .../quality-report for results.
    """
    from app.tasks import analyze_universe_quality
    from app.models.universe_quality_report import UniverseQualityReport

    universe = db.query(StockUniverse).filter(StockUniverse.id == universe_id).first()
    if not universe:
        raise HTTPException(status_code=404, detail="Universe not found")

    # Upsert a "pending" record so the frontend can show a spinner immediately
    report = db.query(UniverseQualityReport).filter(
        UniverseQualityReport.universe_id == universe_id
    ).first()
    if not report:
        report = UniverseQualityReport(universe_id=universe_id)
        db.add(report)
    report.status = "pending"
    report.started_at = datetime.now(timezone.utc).replace(tzinfo=None)
    db.commit()

    analyze_universe_quality.delay(universe_id)

    return {"status": "accepted", "message": "Quality analysis queued."}


class DeleteAggregatesRequest(BaseModel):
    ticker: str
    asset_class: str  # "stocks" | "futures"
    # Optional: if omitted, ALL timespans for the ticker are deleted
    timespan: Optional[str] = None
    multiplier: Optional[int] = None


@router.delete("/{universe_id}/aggregates")
def delete_ticker_aggregates(
    universe_id: int,
    request: DeleteAggregatesRequest,
    db: Session = Depends(get_db),
):
    """
    Delete aggregate bars for a ticker and remove it from the universe.

    If timespan/multiplier are provided, only that specific combination is
    deleted.  If omitted, ALL bars for the ticker are removed.
    The ticker is always removed from StockUniverseTicker.
    """
    from app.models.futures_aggregate import FuturesAggregate

    if request.asset_class == "futures":
        q = db.query(FuturesAggregate).filter(FuturesAggregate.symbol == request.ticker)
        if request.timespan is not None:
            q = q.filter(
                FuturesAggregate.timespan == request.timespan,
                FuturesAggregate.multiplier == request.multiplier,
            )
        deleted = q.delete(synchronize_session=False)
    else:
        q = db.query(StockAggregate).filter(StockAggregate.ticker == request.ticker)
        if request.timespan is not None:
            q = q.filter(
                StockAggregate.timespan == request.timespan,
                StockAggregate.multiplier == request.multiplier,
            )
        deleted = q.delete(synchronize_session=False)

    # Always remove from universe membership
    db.query(StockUniverseTicker).filter(
        StockUniverseTicker.universe_id == universe_id,
        StockUniverseTicker.ticker == request.ticker,
    ).delete(synchronize_session=False)

    db.commit()
    return {"deleted_bars": deleted, "ticker": request.ticker, "removed_from_universe": True}


@router.get("/{universe_id}/quality-report")
def get_quality_report(
    universe_id: int,
    db: Session = Depends(get_db),
):
    """Return the latest quality report for a universe (or null if none exists)."""
    from app.models.universe_quality_report import UniverseQualityReport

    report = db.query(UniverseQualityReport).filter(
        UniverseQualityReport.universe_id == universe_id
    ).first()

    if not report:
        return None

    return {
        "universe_id": universe_id,
        "status": report.status,
        "overall_grade": report.overall_grade,
        "overall_score": float(report.overall_score) if report.overall_score is not None else None,
        "ticker_count": report.ticker_count,
        "started_at": report.started_at.isoformat() if report.started_at else None,
        "generated_at": report.generated_at.isoformat() if report.generated_at else None,
        "report_data": report.report_data,
        "error_message": report.error_message,
        "normalization_status": report.normalization_status,
        "normalization_data": report.normalization_data,
    }


class NormalizeRequest(BaseModel):
    target_tickers: Optional[List[str]] = None


@router.post("/{universe_id}/normalize")
def trigger_normalization(
    universe_id: int,
    request: Optional[NormalizeRequest] = None,
    db: Session = Depends(get_db),
):
    """
    Start (or resume) a normalization run that fills all data-quality gaps
    so every ticker in the universe reaches an A grade.

    If a previous run was interrupted (normalization_status='running' or 'error'
    with partial progress), the task resumes from the last checkpoint automatically.
    Returns immediately; poll GET .../quality-report for normalization_status.
    """
    from app.tasks import normalize_universe_quality
    from app.models.universe_quality_report import UniverseQualityReport

    universe = db.query(StockUniverse).filter(StockUniverse.id == universe_id).first()
    if not universe:
        raise HTTPException(status_code=404, detail="Universe not found")

    report = db.query(UniverseQualityReport).filter(
        UniverseQualityReport.universe_id == universe_id
    ).first()

    if not report or not report.report_data:
        raise HTTPException(
            status_code=400,
            detail="No quality analysis found. Run 'Analyse' first.",
        )

    # Determine whether to resume (keep processed_combos checkpoint) or start fresh
    resume = bool(
        report.normalization_status in ("running", "error")
        and report.normalization_data
        and report.normalization_data.get("processed_combos")
    )

    # Mark as pending so the frontend shows a spinner immediately
    report.normalization_status = "pending"
    if not resume:
        report.normalization_data = None
    db.commit()

    target_tickers = request.target_tickers if request else None

    normalize_universe_quality.delay(universe_id, resume=resume, target_tickers=target_tickers)

    return {
        "status": "accepted",
        "resume": resume,
        "message": "Normalization queued." + (" Resuming from checkpoint." if resume else ""),
    }
