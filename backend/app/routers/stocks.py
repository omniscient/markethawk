"""
Stocks router - historical data endpoints.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
import pandas as pd
from datetime import datetime

from app.core.database import get_db
from app.services import StockDataService

router = APIRouter(prefix="/api/stocks", tags=["stocks"])


@router.get("/historical/{ticker}")
async def get_historical_data(
    ticker: str,
    period: str = "30d",
    db: Session = Depends(get_db),
):
    """Get historical stock data."""
    try:
        data = await StockDataService.get_historical_data(ticker.upper(), period)

        if data.empty:
            raise HTTPException(status_code=404, detail="No data found for ticker")

        # Convert to JSON-serializable format
        data_dict = data.reset_index().to_dict("records")
        for record in data_dict:
            record["Date"] = record["Date"].strftime("%Y-%m-%d")
            for key in ["Open", "High", "Low", "Close", "Volume"]:
                if key in record:
                    record[key] = float(record[key]) if pd.notna(record[key]) else None

        return {
            "ticker": ticker.upper(),
            "period": period,
            "data_points": len(data_dict),
            "data": data_dict,
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching data: {str(e)}")


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
            "last_updated": datetime.now().isoformat()
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching stock details: {str(e)}")
