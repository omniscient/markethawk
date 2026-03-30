"""
Stocks router - historical data endpoints.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
import pandas as pd
from datetime import datetime, timezone

from app.core.database import get_db
from app.services import StockDataService
from typing import Optional

router = APIRouter(prefix="/api/stocks", tags=["stocks"])


@router.get("/historical/{ticker}")
async def get_historical_data(
    ticker: str,
    period: str = "30d",
    timespan: str = "day",
    multiplier: int = 1,
    db: Session = Depends(get_db),
):
    """Get historical stock data from DB, fallback to Polygon."""
    ticker = ticker.upper()
    try:
        # 1. Try to fetch from DB first
        data = await StockDataService.get_historical_from_db(
            db, ticker, period, timespan, multiplier
        )

        # 2. If NO data in DB at all, we might want to trigger a sync or fetch once from Polygon
        # But the user wants a specific 'refresh' call, so let's just return what we have
        # Or if it's empty, we can do a one-time fetch.
        if data.empty:
            # Fallback to direct Polygon fetch for the requested period only (non-persistent)
            # or we could trigger the massive refresh here.
            # User said: "pokes the database to know the last computed day... and just refresh"
            # So I'll implement the refresh logic and use it.
            await StockDataService.refresh_stock_data(db, ticker, timespan, multiplier)
            data = await StockDataService.get_historical_from_db(
                db, ticker, period, timespan, multiplier
            )

        if data.empty:
            raise HTTPException(status_code=404, detail="No data found for ticker")

        # Convert to JSON-serializable format
        data_dict = data.reset_index().to_dict("records")
        for record in data_dict:
            # Handle both Date and timestamp columns
            date_col = "Date" if "Date" in record else "timestamp"
            if date_col in record and record[date_col]:
                if isinstance(record[date_col], str):
                    if not record[date_col].endswith('Z') and 'T' in record[date_col]:
                        record["Date"] = record[date_col] + 'Z'
                    else:
                        record["Date"] = record[date_col]
                else:
                    # Convert to ISO format with Z
                    record["Date"] = record[date_col].isoformat()
                    if not record["Date"].endswith('Z') and '+' not in record["Date"]:
                        record["Date"] += 'Z'
            
            for key in ["Open", "High", "Low", "Close", "Volume", "open", "high", "low", "close", "volume"]:
                if key in record:
                    record[key] = float(record[key]) if pd.notna(record[key]) else None

        return {
            "ticker": ticker,
            "period": period,
            "timespan": timespan,
            "multiplier": multiplier,
            "data_points": len(data_dict),
            "data": data_dict,
        }

    except HTTPException:
        raise
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Error fetching data: {str(e)}")


@router.post("/refresh/{ticker}")
async def refresh_stock_data(
    ticker: str,
    timespan: str = "day",
    multiplier: int = 1,
    full_history: bool = False,
    period: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """Trigger a refresh of stock data from Polygon to DB."""
    try:
        ticker = ticker.upper()
        # If period is provided, the service could potentially use it, 
        # but for now StockDataService.refresh_stock_data will handle it via its internal target_start logic
        # if period indicates we need more than it thinks.
        result = await StockDataService.refresh_stock_data(
            db, ticker, timespan, multiplier, full_history, period
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error refreshing data: {str(e)}")



@router.get("/details/{ticker}")
async def get_stock_detail_consolidated(
    ticker: str,
    db: Session = Depends(get_db),
):
    """Get consolidated stock detail for the frontend detail page."""
    ticker = ticker.upper()
    try:
        # 1. Fundamental Info
        info = await StockDataService.get_stock_info(ticker)
        
        # 2. Pre-market / Extended Hours data
        pre_market = await StockDataService.get_pre_market_data(ticker)
        
        # 3. Latest aggregates for summary (e.g. today's close if available)
        # Fetching last 1 day minute data to get a accurate "current" or "close" price
        today = datetime.now().strftime("%Y-%m-%d")
        minute_aggs = await StockDataService.get_aggregates(
            ticker, 1, "minute", today, today, limit=1
        )
        
        latest_price = None
        if minute_aggs:
            latest_price = minute_aggs[-1]["close"]

        return {
            "ticker": ticker,
            "info": info,
            "pre_market": pre_market,
            "latest_price": latest_price,
            "last_updated": datetime.now(timezone.utc).isoformat()
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching stock details: {str(e)}")
