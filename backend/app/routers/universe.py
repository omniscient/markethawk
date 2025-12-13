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


@router.post("/{universe_id}/refresh")
async def refresh_universe_stocks(
    universe_id: int,
    db: Session = Depends(get_db),
):
    """
    Refresh stocks in a universe based on criteria.
    Scans common stocks and adds those matching the universe criteria.
    """
    universe = db.query(StockUniverse).filter(StockUniverse.id == universe_id).first()
    if not universe:
        raise HTTPException(status_code=404, detail="Universe not found")

    # Clear existing stocks for this universe
    db.query(MonitoredStock).filter(MonitoredStock.universe_id == universe_id).delete()

    added_count = 0
    scanned_count = 0
    criteria = universe.criteria or {}

    # Get filter criteria
    min_market_cap = criteria.get("min_market_cap")
    max_market_cap = criteria.get("max_market_cap")
    target_sector = criteria.get("sector")
    min_price = criteria.get("min_price")
    max_price = criteria.get("max_price")

    for ticker in COMMON_STOCKS:
        scanned_count += 1
        try:
            # Fetch stock info from Polygon.io
            info = await StockDataService.get_stock_info(ticker)

            # Apply filters based on criteria
            should_add = True

            market_cap = info.get("marketCap")
            current_price = info.get("currentPrice")
            sector = info.get("sector")

            if min_market_cap and market_cap and market_cap < min_market_cap:
                should_add = False
            if max_market_cap and market_cap and market_cap > max_market_cap:
                should_add = False
            if target_sector and sector and target_sector.lower() not in sector.lower():
                should_add = False
            if min_price and current_price and current_price < min_price:
                should_add = False
            if max_price and current_price and current_price > max_price:
                should_add = False

            if should_add:
                monitored_stock = MonitoredStock(
                    ticker=ticker,
                    universe_id=universe_id,
                    added_date=datetime.now().date(),
                    is_active=True,
                    company_name=info.get("longName") or info.get("shortName") or ticker,
                    sector=sector,
                    industry=info.get("industry"),
                    market_cap=market_cap,
                    stock_metadata={
                        "source": "auto_refresh",
                        "current_price": current_price,
                    },
                )
                db.add(monitored_stock)
                added_count += 1

        except Exception as e:
            logging.warning(f"Error processing {ticker}: {e}")
            continue

    db.commit()

    return {
        "status": "completed",
        "scanned": scanned_count,
        "added": added_count,
        "message": f"Successfully refreshed universe. Added {added_count} stocks.",
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
