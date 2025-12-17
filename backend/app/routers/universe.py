"""
Universe router - CRUD operations for stock universes.
"""

import logging
from datetime import datetime
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models import StockUniverse, MonitoredStock, StockUniverseTicker
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
    """List all stock universes."""
    universes = db.query(StockUniverse).filter(StockUniverse.is_active == True).all()
    return universes


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
async def refresh_universe_stocks(
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
            created_at=datetime.utcnow()
        )
        db.add(stock_ticker)

        added_count += 1
        
    db.commit()

    return {
        "status": "completed",
        "scanned": "ALL",  # We scanned the whole DB effectively
        "added": added_count,
        "message": f"Successfully refreshed universe. Added {added_count} stocks from Discovery Engine.",
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
    db: Session = Depends(get_db),
):
    """
    Trigger backfill of aggregates for all stocks in the universe.
    """
    # 1. Get stocks in universe
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
         
    # 2. Schedule tasks
    from app.tasks import sync_stock_aggregates
    
    count = 0
    for stock in stocks:
        sync_stock_aggregates.delay(
            ticker=stock.ticker,
            from_date=from_date,
            to_date=to_date,
            multiplier=multiplier,
            timespan=timespan
        )
        count += 1
        
    return {
        "status": "accepted", 
        "message": f"Scheduled aggregate sync for {count} stocks ({from_date} to {to_date})."
    }
