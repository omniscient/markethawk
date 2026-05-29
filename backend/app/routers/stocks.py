"""
Stocks router - historical data endpoints.
"""

from datetime import datetime, timezone
from typing import Optional

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import ORJSONResponse
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.exceptions import DataFetchError
from app.services import StockDataService
from app.utils.session import get_market_today

router = APIRouter(prefix="/api/stocks", tags=["stocks"])


@router.get("/historical/{ticker}")
def get_historical_data(
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
        data = StockDataService.get_historical_enriched(
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

        # Vectorized serialization — avoid per-row Python loops over large DataFrames.
        data = data.reset_index()
        date_col = "Date" if "Date" in data.columns else "timestamp"

        # COMPACT FORMAT OPTIMIZATION:
        # 1. Convert Timestamps to Unix Epoch (seconds)
        data["t"] = pd.to_datetime(data[date_col], utc=True).astype("int64") // 10**9

        # 2. Map other columns to short keys
        mapping = {
            "Open": "o",
            "High": "h",
            "Low": "l",
            "Close": "c",
            "Volume": "v",
            "vwap": "w",
            "transactions": "n",
            "vwap_intraday": "wi",
            "marker_type": "mt",
            "contract_month": "cm",
        }

        compact_data = {}
        compact_data["t"] = data["t"].tolist()

        for col, short in mapping.items():
            if col in data.columns:
                if col == "marker_type":
                    data[col] = data[col].where(
                        data[col].notna() & (data[col] != ""), other=None
                    )
                compact_data[short] = data[col].tolist()

        # PERFORMANCE OPTIMIZATION:
        # Always return columnar format for this endpoint as it's significantly more efficient.
        return ORJSONResponse(
            {
                "ticker": ticker,
                "period": period,
                "timespan": timespan,
                "multiplier": multiplier,
                "data_points": len(data),
                "format": "columnar_compact",
                "data": compact_data,
            }
        )

    except HTTPException:
        raise
    except Exception as e:
        import traceback

        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Error fetching data: {str(e)}")


@router.post("/refresh/{ticker}")
def refresh_stock_data(
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
        if StockDataService.is_futures_ticker(db, ticker):
            return {
                "status": "skipped",
                "message": "Futures data is synced via IBKR, not Polygon.",
            }
        result = StockDataService.refresh_stock_data(
            db, ticker, timespan, multiplier, full_history, period
        )
        return result
    except DataFetchError as e:
        status = 503 if e.is_retryable else 422
        raise HTTPException(status_code=status, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error refreshing data: {str(e)}")


@router.get("/details/{ticker}")
def get_stock_detail_consolidated(
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
        if StockDataService.is_futures_ticker(db, ticker):
            # Return cached info from MonitoredStock — no Polygon calls for futures

            from app.models import MonitoredStock
            from app.models.futures_aggregate import FuturesAggregate

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
        info = StockDataService.get_stock_info(ticker)

        # 2. Pre-market / Extended Hours data
        pre_market = StockDataService.get_pre_market_data(ticker)

        # 3. Latest aggregates for summary (e.g. today's close if available)
        # Fetching last 1 day minute data to get a accurate "current" or "close" price
        today = get_market_today().strftime("%Y-%m-%d")
        minute_aggs = StockDataService.get_aggregates(
            ticker, 1, "minute", today, today, limit=1
        )

        latest_price = None
        if minute_aggs:
            latest_price = minute_aggs[-1]["close"]

        from app.models.stock_split import StockSplit

        recent_splits_query = (
            db.query(StockSplit)
            .filter(StockSplit.ticker == ticker)
            .order_by(StockSplit.execution_date.desc())
            .limit(5)
            .all()
        )
        recent_splits = [
            {
                "execution_date": s.execution_date.isoformat(),
                "split_from": float(s.split_from),
                "split_to": float(s.split_to),
                "adjusted": s.adjustments_applied_at is not None,
            }
            for s in recent_splits_query
        ]
        split_adjustment_pending = any(
            s.adjustments_applied_at is None for s in recent_splits_query
        )

        result = {
            "ticker": ticker,
            "info": info,
            "pre_market": pre_market,
            "latest_price": latest_price,
            "last_updated": datetime.now(timezone.utc).isoformat(),
            "recent_splits": recent_splits,
            "split_adjustment_pending": split_adjustment_pending,
        }
        try:
            if _redis:
                _redis.setex(cache_key, 60, json.dumps(result))
        except Exception:
            pass
        return result
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Error fetching stock details: {str(e)}"
        )


@router.post("/{ticker}/sync-missing")
def sync_missing_stock_aggregates(
    ticker: str,
    db: Session = Depends(get_db),
):
    """
    For a specific ticker, identify all (timespan, multiplier) combos already
    in the database and queue a sync from the last stored bar up to today.
    Uses the same pattern as Universe sync-missing, but for one instrument.
    """
    import json
    from datetime import timedelta

    import redis as redis_lib
    from sqlalchemy import func

    from app.core.config import settings
    from app.models import MonitoredStock
    from app.models.futures_aggregate import FuturesAggregate
    from app.models.stock_aggregate import StockAggregate
    from app.services.futures_data import SYMBOL_EXCHANGE_MAP
    from app.tasks import sync_futures_aggregates, sync_stock_aggregates

    ticker = ticker.upper()
    is_futures = StockDataService.is_futures_ticker(db, ticker)

    now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
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
            # Default to standard sync for new futures
            from collections import namedtuple

            Combo = namedtuple("Combo", ["timespan", "multiplier", "max_ts"])
            combos = [Combo("minute", 1, None), Combo("day", 1, None)]
            summary.append(
                "Initial sync: no existing data found, defaulting to standard sets."
            )

        # Find exchange for futures instrument
        stock = (
            db.query(MonitoredStock)
            .filter(
                MonitoredStock.ticker == ticker,
                MonitoredStock.asset_class == "futures",
                MonitoredStock.is_active == True,
            )
            .first()
        )
        metadata = (stock.stock_metadata or {}) if stock else {}
        exchange = metadata.get("primary_exchange")
        if not exchange or exchange == "Unknown":
            exchange = SYMBOL_EXCHANGE_MAP.get(ticker)

        if not exchange:
            raise HTTPException(
                status_code=400,
                detail=f"Cannot determine exchange for futures symbol '{ticker}'",
            )

        for combo in combos:
            from_dt = (
                (combo.max_ts + timedelta(seconds=1))
                if combo.max_ts
                else (now_utc - timedelta(days=30))
            )
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
            # Default to standard sync for new stocks
            from collections import namedtuple

            Combo = namedtuple("Combo", ["timespan", "multiplier", "max_ts"])
            combos = [Combo("minute", 1, None), Combo("day", 1, None)]
            summary.append(
                "Initial sync: no existing data found, defaulting to standard sets."
            )

        for combo in combos:
            from_dt = (
                (combo.max_ts + timedelta(seconds=1))
                if combo.max_ts
                else (now_utc - timedelta(days=30))
            )
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
        return {
            "status": "skipped",
            "message": "All timespans are already up to date.",
            "summary": summary,
        }

    # Store in Redis for sync-status polling (compatible with SystemActivityMonitor)
    try:
        r = redis_lib.from_url(settings.REDIS_URL)
        r.setex(
            f"ticker:{ticker}:sync",
            14400,
            json.dumps(
                {
                    "task_ids": task_ids,
                    "total": len(task_ids),
                    "started_at": datetime.now(timezone.utc).isoformat(),
                }
            ),
        )
    except Exception as e:
        # Log but don't fail the request
        print(f"REDIS ERROR: {e}")

    return {"status": "accepted", "queued": len(task_ids), "summary": summary}
