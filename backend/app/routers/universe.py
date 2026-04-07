"""
Universe router - CRUD operations for stock universes.
"""

import logging
from datetime import datetime, timedelta
from typing import List

from fastapi import APIRouter, Depends, HTTPException
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

# Common stocks for scanning (Mock "All Stocks" source)
# In production, this would be replaced by a real market screener API
COMMON_STOCKS = [
    "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "TSLA", "META", "BRK-B", "TSM", "UNH",
    "JNJ", "JPM", "V", "PG", "MA", "HD", "CVX", "MRK", "ABBV", "PEP",
    "KO", "LLY", "BAC", "COST", "AVGO", "TMO", "DIS", "WMT", "CSCO", "ACN",
]


@router.post("/create", response_model=StockUniverseResponse)
async def create_stock_universe(
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
async def update_stock_universe(
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
async def delete_stock_universe(
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


@router.get("/list", response_model=List[StockUniverseResponse])
async def list_stock_universes(
    db: Session = Depends(get_db),
):
    from sqlalchemy import func
    from app.models.futures_aggregate import FuturesAggregate

    """List all stock universes."""
    universes = db.query(StockUniverse).filter(StockUniverse.is_active == True).all()

    # Enrich with stats
    # Optimization: Could use a single complex query, but loop is clearer for now given <50 universes

    results = []
    for universe in universes:
        # 1. Ticker Count
        ticker_count = (
            db.query(func.count(StockUniverseTicker.id))
            .filter(StockUniverseTicker.universe_id == universe.id)
            .scalar()
        )

        # 2. Aggregate Stats — split by asset class so futures bars (FuturesAggregate)
        #    and stock bars (StockAggregate) are both counted.
        futures_tickers = [
            row.ticker
            for row in db.query(StockUniverseTicker.ticker)
            .filter(
                StockUniverseTicker.universe_id == universe.id,
                StockUniverseTicker.asset_class == "futures",
            )
            .all()
        ]
        stock_tickers = [
            row.ticker
            for row in db.query(StockUniverseTicker.ticker)
            .filter(
                StockUniverseTicker.universe_id == universe.id,
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

        # 3. Available timespans — distinct (timespan, multiplier) pairs across both tables
        timespans_set = set()
        if stock_tickers:
            for row in db.query(StockAggregate.timespan, StockAggregate.multiplier).filter(
                StockAggregate.ticker.in_(stock_tickers)
            ).distinct().all():
                label = f"{row.multiplier}{row.timespan}" if row.multiplier > 1 else row.timespan
                timespans_set.add(label)
        if futures_tickers:
            for row in db.query(FuturesAggregate.timespan, FuturesAggregate.multiplier).filter(
                FuturesAggregate.symbol.in_(futures_tickers)
            ).distinct().all():
                label = f"{row.multiplier}{row.timespan}" if row.multiplier > 1 else row.timespan
                timespans_set.add(label)

        # Convert to Pydantic model with extra fields
        universe_data = StockUniverseResponse.from_orm(universe)
        universe_data.ticker_count = ticker_count or 0
        universe_data.aggregate_count = count_aggs or 0
        universe_data.min_aggregate_date = min_date
        universe_data.max_aggregate_date = max_date
        universe_data.available_timespans = sorted(timespans_set)

        results.append(universe_data)

    return results


from fastapi import BackgroundTasks
from app.services.discovery_service import DiscoveryService

@router.post("/sync/fundamentals")
async def sync_fundamental_data(
    background_tasks: BackgroundTasks,
    delay: float = 15.0, # Default to 15s (Free Tier)
    db: Session = Depends(get_db),
):
    """Trigger background sync of fundamental data from Polygon."""
    service = DiscoveryService(db)
    background_tasks.add_task(service.sync_fundamental_data, delay_seconds=delay)
    return {"status": "accepted", "message": f"Fundamental sync started in background (delay={delay}s)"}

@router.post("/sync/details")
async def sync_ticker_details(
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
async def stop_sync(
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
async def sync_daily_metrics(
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """Trigger background update of daily technical metrics."""
    service = DiscoveryService(db)
    background_tasks.add_task(service.update_daily_metrics_snapshot)
    return {"status": "accepted", "message": "Daily metrics update started in background"}


@router.post("/{universe_id}/refresh")
async def refresh_universe(
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
            added_date=datetime.now().date(),
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
            created_at=datetime.utcnow()
        )
        db.add(stock_ticker)

        added_count += 1
        
    db.commit()

    return {
        "status": "completed",
        "scanned": "ALL",  # We scanned the whole DB effectively
        "added": added_count,
        "message": f"Successfully refreshed universe. Added {added_count} assets from Discovery Engine.",
    }


@router.post("/{universe_id}/sync-missing")
async def sync_missing_aggregates(
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

    now_utc = datetime.utcnow()
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
            json.dumps({"task_ids": task_ids, "total": len(task_ids), "started_at": datetime.utcnow().isoformat()}),
        )
    except Exception as e:
        logger.warning(f"Could not store sync-missing status in Redis: {e}")

    return {"status": "accepted", "queued": len(task_ids), "summary": summary}


@router.get("/{universe_id}/sync-status")
async def get_universe_sync_status(universe_id: int):
    """
    Return the current sync progress for a universe.
    Reads task IDs stored by sync-aggregates and checks Celery task states.
    """
    import json
    import redis as redis_lib
    from celery.result import AsyncResult
    from app.core.celery_app import celery_app
    from app.core.config import settings

    r = redis_lib.from_url(settings.REDIS_URL)
    raw = r.get(f"universe:{universe_id}:sync")
    if not raw:
        return {"is_syncing": False, "pending": 0, "success": 0, "failed": 0, "total": 0}

    data = json.loads(raw)
    task_ids = data.get("task_ids", [])

    states = [AsyncResult(tid, app=celery_app).state for tid in task_ids]
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
        "started_at": data.get("started_at"),
        "timespan": data.get("timespan"),
        "from_date": data.get("from_date"),
        "to_date": data.get("to_date"),
    }


@router.get("/{universe_id}/stocks", response_model=List[MonitoredStockResponse])
async def get_universe_stocks(
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
async def sync_universe_aggregates(
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
                "started_at": datetime.utcnow().isoformat(),
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
