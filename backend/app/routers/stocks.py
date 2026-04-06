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


def _is_futures_ticker(db: Session, ticker: str) -> bool:
    """Return True if this ticker is tracked as a futures asset class."""
    from app.models import MonitoredStock
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
        is_futures = _is_futures_ticker(db, ticker)

        if is_futures:
            # Futures bars live in FuturesAggregate — skip Polygon refresh
            data = await StockDataService.get_futures_historical_from_db(
                db, ticker, period, timespan, multiplier
            )
        else:
            # 1. Always trigger an incremental refresh to ensure data is up to date
            await StockDataService.refresh_stock_data(db, ticker, timespan, multiplier, period=period)

            # 2. Fetch from DB (it will now have the latest sync)
            data = await StockDataService.get_historical_from_db(
                db, ticker, period, timespan, multiplier
            )

        if data.empty:
            return {
                "ticker": ticker,
                "period": period,
                "timespan": timespan,
                "multiplier": multiplier,
                "data_points": 0,
                "data": [],
            }

        # 3. Add indicators if intraday
        if timespan in ["minute", "hour"]:
            from app.services.chart_indicators import ChartIndicatorsService
            data = ChartIndicatorsService.add_indicators(data, is_intraday=True)

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
                    # Only append Z if it's naive (no offset '+', '-', or 'Z' suffix after time 'T')
                    time_part = record["Date"].split('T')[1] if 'T' in record["Date"] else ""
                    if time_part and not any(c in time_part for c in ['Z', '+', '-']):
                        record["Date"] += 'Z'
            
            for key in ["Open", "High", "Low", "Close", "Volume", "open", "high", "low", "close", "volume", "vwap_intraday"]:
                if key in record:
                    record[key] = float(record[key]) if pd.notna(record[key]) else None
            
            # handle marker_type None substitution handled above but check pd.isna
            if "marker_type" in record and pd.isna(record["marker_type"]):
                record["marker_type"] = None

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
        if _is_futures_ticker(db, ticker):
            return {"status": "skipped", "message": "Futures data is synced via IBKR, not Polygon."}
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
        if _is_futures_ticker(db, ticker):
            # Return cached info from MonitoredStock — no Polygon calls for futures
            from app.models import MonitoredStock
            from app.models.futures_aggregate import FuturesAggregate
            from sqlalchemy import func

            stock = (
                db.query(MonitoredStock)
                .filter(
                    MonitoredStock.ticker == ticker,
                    MonitoredStock.asset_class == "futures",
                    MonitoredStock.is_active == True,
                )
                .first()
            )

            latest_close = (
                db.query(FuturesAggregate.close)
                .filter(FuturesAggregate.symbol == ticker)
                .order_by(FuturesAggregate.timestamp.desc())
                .limit(1)
                .scalar()
            )

            return {
                "ticker": ticker,
                "info": {
                    "longName": (stock.company_name if stock else None) or ticker,
                    "shortName": ticker,
                    "sector": (stock.sector if stock else None) or "Futures",
                    "industry": "Futures",
                    "marketCap": None,
                },
                "pre_market": {
                    "pre_market_volume": 0,
                    "pre_market_high": None,
                    "pre_market_low": None,
                    "pre_market_open": None,
                    "pre_market_close": None,
                },
                "latest_price": float(latest_close) if latest_close else None,
                "last_updated": datetime.now(timezone.utc).isoformat(),
            }

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
