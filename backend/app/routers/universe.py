"""
Universe router - CRUD operations for stock universes.
"""

import logging
from datetime import datetime
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models import StockUniverse, MonitoredStock
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
    db: Session = Depends(get_db),
):
    """Trigger background sync of fundamental data from Polygon."""
    service = DiscoveryService(db)
    background_tasks.add_task(service.sync_fundamental_data)
    return {"status": "accepted", "message": "Fundamental sync started in background"}

@router.post("/sync/details")
async def sync_ticker_details(
    background_tasks: BackgroundTasks,
    delay: float = 15.0, # Default to 15s (Free Tier)
    db: Session = Depends(get_db),
):
    """
    Trigger background sync of ticker details (Description, etc).
    delay: Seconds to wait between requests (15.0=Free, 0.2=Paid)
    """
    service = DiscoveryService(db)
    background_tasks.add_task(service.sync_ticker_details_crawler, delay)
    return {"status": "accepted", "message": f"Ticker details sync started in background (delay={delay}s)"}



@router.post("/sync/stop")
async def stop_sync(
    db: Session = Depends(get_db),
):
    """
    Stops any running sync process by purging the Celery queue.
    This breaks the recursive chain.
    """
    from app.core.celery_app import celery_app
    
    # Purge all pending tasks
    purged_count = celery_app.control.purge()
    
    return {
        "status": "stopped", 
        "message": f"Sync process stopped. {purged_count} pending tasks removed."
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
