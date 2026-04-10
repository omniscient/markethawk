"""
Stocks router - historical data endpoints.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
import pandas as pd
from datetime import datetime, timezone

from app.core.database import get_db
from app.services import StockDataService
from typing import Optional, Union
from fastapi.responses import ORJSONResponse
import orjson

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
    format: str = "row",  # "row" (default) or "columnar"
    db: Session = Depends(get_db),
):
    """Get historical stock data from DB."""
    ticker = ticker.upper()
    try:
        is_futures = _is_futures_ticker(db, ticker)

        if is_futures:
            data = await StockDataService.get_futures_historical_from_db(
                db, ticker, period, timespan, multiplier
            )
        else:
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

        # Guardrail: Limit extremely large requests that could crash the browser
        MAX_DATAPOINTS = 500000 
        if len(data) > MAX_DATAPOINTS:
             data = data.tail(MAX_DATAPOINTS)

        # Add indicators only for intraday views with a manageable row count.
        INDICATOR_ROW_LIMIT = 3000
        if timespan in ["minute", "hour"] and len(data) <= INDICATOR_ROW_LIMIT:
            from app.services.chart_indicators import ChartIndicatorsService
            data = ChartIndicatorsService.add_indicators(data, is_intraday=True)

        # Vectorized serialization — avoid per-row Python loops over large DataFrames.
        data = data.reset_index()
        date_col = "Date" if "Date" in data.columns else "timestamp"

        # Normalize timestamp column to UTC ISO-8601 strings in one pass
        ts = pd.to_datetime(data[date_col], utc=True)
        data["Date"] = ts.dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        if date_col != "Date":
            data = data.drop(columns=[date_col])

        # marker_type: keep None where blank/NaN
        if "marker_type" in data.columns:
            data["marker_type"] = data["marker_type"].where(
                data["marker_type"].notna() & (data["marker_type"] != ""), other=None
            )

        # Broad numeric coercion: identify and convert columns that might contain Decimal objects
        # orjson is strict and fails on decimal.Decimal (common with PostgreSQL NUMERIC types).
        exclude_cols = ["Date", "marker_type", "contract_month"]
        for col in data.columns:
            if col not in exclude_cols:
                # Convert to numeric, leaving strings/complex types alone if they fail conversion
                try:
                    data[col] = pd.to_numeric(data[col], errors="coerce")
                except Exception:
                    pass

        # PERFORMANCE OPTIMIZATION: 
        # If columnar format requested or dataset is massive, pivot to columnar JSON.
        # This reduces payload size by ~60% for large time series.
        if format == "columnar" or len(data) > 50000:
            # { "Date": [...], "Open": [...], ... }
            columnar_data = data.to_dict(orient="list")
            return ORJSONResponse({
                "ticker": ticker,
                "period": period,
                "timespan": timespan,
                "multiplier": multiplier,
                "data_points": len(data),
                "format": "columnar",
                "data": columnar_data,
            })

        # Default row-oriented JSON: List[Dict]
        # orjson is significantly faster than standard json for large lists of dicts
        records = data.to_dict(orient="records")
        return ORJSONResponse({
            "ticker": ticker,
            "period": period,
            "timespan": timespan,
            "multiplier": multiplier,
            "data_points": len(records),
            "format": "row",
            "data": records,
        })

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
    import json
    import redis as redis_lib
    from app.core.config import settings

    ticker = ticker.upper()

    # Cache in Redis for 60s — avoids 3 consecutive Polygon calls on every page visit.
    _redis = None
    cache_key = f"stock_detail:{ticker}"
    try:
        _redis = redis_lib.from_url(settings.REDIS_URL)
        cached = _redis.get(cache_key)
        if cached:
            return json.loads(cached)
    except Exception:
        pass  # Redis unavailable — fall through to live fetch

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

            result = {
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
            try:
                if _redis:
                    _redis.setex(cache_key, 60, json.dumps(result))
            except Exception:
                pass
            return result

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

        result = {
            "ticker": ticker,
            "info": info,
            "pre_market": pre_market,
            "latest_price": latest_price,
            "last_updated": datetime.now(timezone.utc).isoformat()
        }
        try:
            if _redis:
                _redis.setex(cache_key, 60, json.dumps(result))
        except Exception:
            pass
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching stock details: {str(e)}")

@router.post("/{ticker}/sync-missing")
async def sync_missing_stock_aggregates(
    ticker: str,
    db: Session = Depends(get_db),
):
    """
    For a specific ticker, identify all (timespan, multiplier) combos already 
    in the database and queue a sync from the last stored bar up to today.
    Uses the same pattern as Universe sync-missing, but for one instrument.
    """
    import json
    import redis as redis_lib
    from datetime import timedelta
    from sqlalchemy import func
    from app.tasks import sync_stock_aggregates, sync_futures_aggregates
    from app.models.stock_aggregate import StockAggregate
    from app.models.futures_aggregate import FuturesAggregate
    from app.models import MonitoredStock
    from app.core.config import settings
    from app.services.futures_data import SYMBOL_EXCHANGE_MAP

    ticker = ticker.upper()
    is_futures = _is_futures_ticker(db, ticker)
    
    now_utc = datetime.utcnow()
    today = now_utc.strftime("%Y-%m-%d")
    
    task_ids: list = []
    summary: list = []

    if is_futures:
        # 1. Handle Futures
        combos = (
            db.query(
                FuturesAggregate.timespan,
                FuturesAggregate.multiplier,
                func.max(FuturesAggregate.timestamp).label("max_ts"),
            )
            .filter(FuturesAggregate.symbol == ticker)
            .group_by(FuturesAggregate.timespan, FuturesAggregate.multiplier)
            .all()
        )
        
        if not combos:
            return {"status": "skipped", "message": "No existing aggregate data found for this futures symbol."}

        # Find exchange for futures instrument
        stock = db.query(MonitoredStock).filter(
            MonitoredStock.ticker == ticker, 
            MonitoredStock.asset_class == "futures",
            MonitoredStock.is_active == True
        ).first()
        metadata = (stock.stock_metadata or {}) if stock else {}
        exchange = metadata.get("primary_exchange")
        if not exchange or exchange == "Unknown":
            exchange = SYMBOL_EXCHANGE_MAP.get(ticker)
            
        if not exchange:
            raise HTTPException(status_code=400, detail=f"Cannot determine exchange for futures symbol '{ticker}'")

        for combo in combos:
            from_dt = (combo.max_ts + timedelta(seconds=1)) if combo.max_ts else (now_utc - timedelta(days=7))
            if from_dt > now_utc:
                summary.append(f"{combo.timespan}×{combo.multiplier}: up to date")
                continue
            
            from_date = from_dt.strftime("%Y-%m-%d")
            r = sync_futures_aggregates.delay(
                symbol=ticker,
                exchange=exchange,
                timespan=combo.timespan,
                multiplier=combo.multiplier,
                from_date=from_date,
                to_date=today,
            )
            task_ids.append(r.id)
            summary.append(f"{combo.timespan}×{combo.multiplier}: from {from_date}")
            
    else:
        # 2. Handle Stocks
        combos = (
            db.query(
                StockAggregate.timespan,
                StockAggregate.multiplier,
                func.max(StockAggregate.timestamp).label("max_ts"),
            )
            .filter(StockAggregate.ticker == ticker)
            .group_by(StockAggregate.timespan, StockAggregate.multiplier)
            .all()
        )
        
        if not combos:
            return {"status": "skipped", "message": "No existing aggregate data found for this stock."}

        for combo in combos:
            from_dt = (combo.max_ts + timedelta(seconds=1)) if combo.max_ts else (now_utc - timedelta(days=7))
            if from_dt > now_utc:
                summary.append(f"{combo.timespan}×{combo.multiplier}: up to date")
                continue
                
            from_date = from_dt.strftime("%Y-%m-%d")
            r = sync_stock_aggregates.delay(
                ticker=ticker,
                from_date=from_date,
                to_date=today,
                multiplier=combo.multiplier,
                timespan=combo.timespan,
            )
            task_ids.append(r.id)
            summary.append(f"{combo.timespan}×{combo.multiplier}: from {from_date}")

    if not task_ids:
         return {"status": "skipped", "message": "All timespans are already up to date.", "summary": summary}
         
    # Store in Redis for sync-status polling (compatible with SystemActivityMonitor)
    try:
        r = redis_lib.from_url(settings.REDIS_URL)
        r.setex(
            f"ticker:{ticker}:sync",
            14400,
            json.dumps({"task_ids": task_ids, "total": len(task_ids), "started_at": datetime.utcnow().isoformat()}),
        )
    except Exception as e:
        # Log but don't fail the request 
        print(f"REDIS ERROR: {e}")

    return {"status": "accepted", "queued": len(task_ids), "summary": summary}
