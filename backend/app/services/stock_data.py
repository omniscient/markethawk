"""
Stock Data Service - provider-agnostic stock data layer.

All external data access is routed through DataProviderFactory so the
underlying vendor (Polygon, IBKR, etc.) can be swapped without touching
this file or any router that depends on it.
"""

import logging
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from typing import Dict, Any, Optional

import pandas as pd
from sqlalchemy.orm import Session
from sqlalchemy import func, desc

from app.models.stock_aggregate import StockAggregate
from app.models.futures_aggregate import FuturesAggregate
from app.models.monitored_stock import MonitoredStock
from app.services.chart_indicators import ChartIndicatorsService
from app.providers import DataProviderFactory


class StockDataService:
    """Service for fetching stock data from Polygon.io."""

    @staticmethod
    def get_historical_data(ticker: str, period: str = "30d") -> pd.DataFrame:
        """Get historical stock data via the Massive (Polygon) provider."""
        try:
            massive = DataProviderFactory.get("massive")
            if not massive.is_available():
                logging.error("Massive provider not available - check POLYGON_API_KEY")
                return pd.DataFrame()

            # Convert period to days
            days = int(period.replace("d", "")) if "d" in period else 30
            end_date = datetime.now(timezone.utc)
            start_date = end_date - timedelta(days=days)

            aggs = massive.get_bars(
                symbol=ticker.upper(),
                timespan="day",
                multiplier=1,
                from_date=start_date.strftime("%Y-%m-%d"),
                to_date=end_date.strftime("%Y-%m-%d"),
                limit=50000,
            )

            if not aggs:
                return pd.DataFrame()

            # Convert to DataFrame
            data = [
                {
                    "Date": row["timestamp"],
                    "Open": row["open"],
                    "High": row["high"],
                    "Low": row["low"],
                    "Close": row["close"],
                    "Volume": row["volume"],
                }
                for row in aggs
            ]

            df = pd.DataFrame(data)
            df.set_index("Date", inplace=True)
            return df

        except Exception as e:
            logging.error(f"Error fetching data for {ticker}: {e}")
            return pd.DataFrame()

    @staticmethod
    def get_pre_market_data(ticker: str) -> Dict[str, Any]:
        """Get pre-market/extended-hours data via the Massive (Polygon) provider."""
        try:
            massive = DataProviderFactory.get("massive")
            if not massive.is_available():
                logging.error("Massive provider not available - check POLYGON_API_KEY")
                return {}

            # Compute today in US/Eastern so the date boundary is always
            # correct regardless of where the server is running (H3 fix).
            _ET = ZoneInfo("America/New_York")
            today_et = datetime.now(_ET)

            # Fetch minute-level data for extended hours
            aggs = massive.get_bars(
                symbol=ticker.upper(),
                timespan="minute",
                multiplier=1,
                from_date=today_et.strftime("%Y-%m-%d"),
                to_date=today_et.strftime("%Y-%m-%d"),
                limit=50000,
            )

            if not aggs:
                return {}

            # Filter for extended hours
            from app.utils.session import classify_session
            extended_data = []
            for row in aggs:
                is_pre, is_after = classify_session(row["timestamp"])
                if is_pre or is_after:
                    extended_data.append(row)

            if not extended_data:
                return {}

            return {
                "pre_market_volume": sum(r["volume"] for r in extended_data),
                "pre_market_high": max(r["high"] for r in extended_data),
                "pre_market_low": min(r["low"] for r in extended_data),
                "pre_market_open": extended_data[0]["open"] if extended_data else None,
                "pre_market_close": extended_data[-1]["close"] if extended_data else None,
            }

        except Exception as e:
            logging.error(f"Error fetching pre-market data for {ticker}: {e}")
            return {}

    @staticmethod
    def get_stock_info(ticker: str) -> Dict[str, Any]:
        """Get stock details from the Massive (Polygon) provider."""
        try:
            massive = DataProviderFactory.get("massive")
            if not massive.is_available():
                logging.error("Massive provider not available - check POLYGON_API_KEY")
                return {}

            details = massive.get_ticker_details(ticker.upper())
            if not details:
                return {}

            return {
                "longName": details.get("name"),
                "shortName": details.get("name"),
                "sector": details.get("sector", ""),
                "industry": details.get("industry", ""),
                "marketCap": details.get("market_cap"),
                "currentPrice": None,  # Will be fetched from latest quote if needed
            }

        except Exception as e:
            logging.error(f"Error fetching stock info for {ticker}: {e}")
            return {}

    @staticmethod
    def get_historical_from_db(
        db: Session,
        ticker: str,
        period: str = "30d",
        timespan: str = "day",
        multiplier: int = 1
    ) -> pd.DataFrame:
        """Fetch historical data from the local database."""
        try:
            if period == "all":
                # For "all", we don't apply a start_date filter.
                # The 1990 date is used as a fallback "earliest" date to keep the query structure simple,
                # or we can dynamically build the query. Using an ancient date is safe.
                start_date = datetime(1990, 1, 1)
            else:
                days = 30
                if period.endswith("d"):
                    days = int(period[:-1])
                elif period.endswith("y"):
                    days = int(period[:-1]) * 365
                elif period.endswith("w"):
                    days = int(period[:-1]) * 7
                elif period.isdigit():
                    days = int(period)
                start_date = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=days)

            # Use raw SQL to return lightweight tuples instead of full ORM objects.
            # For large datasets (e.g. 30D of 1M bars) this is 3-5x faster than .all().
            from sqlalchemy import text
            rows = db.execute(
                text("""
                    SELECT timestamp, open, high, low, close, volume, vwap, transactions
                    FROM stock_aggregates
                    WHERE ticker = :ticker
                      AND timespan = :timespan
                      AND multiplier = :multiplier
                      AND timestamp >= :start_date
                    ORDER BY timestamp ASC
                """),
                {"ticker": ticker, "timespan": timespan,
                 "multiplier": multiplier, "start_date": start_date},
            ).fetchall()

            if not rows:
                return pd.DataFrame()

            df = pd.DataFrame(rows, columns=["Date", "Open", "High", "Low", "Close", "Volume", "vwap", "transactions"])
            df.set_index("Date", inplace=True)
            return df

        except Exception as e:
            logging.error(f"Error fetching historical data from DB for {ticker}: {e}")
            return pd.DataFrame()

    @staticmethod
    def get_futures_historical_from_db(
        db: Session,
        symbol: str,
        period: str = "30d",
        timespan: str = "minute",
        multiplier: int = 1,
    ) -> pd.DataFrame:
        """
        Fetch futures bars for the chart using the rollover-based continuous series.

        Delegates to FuturesDataService.get_continuous_series so that only the
        front-month contract is returned for each timestamp — prevents double
        data lines when the next contract has been downloaded ahead of its roll.
        """
        try:
            from app.services.futures_data import FuturesDataService

            if period == "all":
                from_date = "1990-01-01"
            else:
                days = 30
                if period.endswith("d"):
                    days = int(period[:-1])
                elif period.endswith("y"):
                    days = int(period[:-1]) * 365
                elif period.endswith("w"):
                    days = int(period[:-1]) * 7
                elif period.isdigit():
                    days = int(period)
                from_date = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")

            df = FuturesDataService.get_continuous_series(
                symbol=symbol,
                timespan=timespan,
                multiplier=multiplier,
                from_date=from_date,
            )

            if df.empty:
                return pd.DataFrame()

            # Rename columns to match the format expected by the chart endpoint
            df = df.rename(columns={
                "timestamp": "Date",
                "open": "Open",
                "high": "High",
                "low": "Low",
                "close": "Close",
                "volume": "Volume",
                "vwap": "vwap",
            })
            df.set_index("Date", inplace=True)
            return df

        except Exception as e:
            logging.error(f"Error fetching futures historical data for {symbol}: {e}")
            return pd.DataFrame()

    @staticmethod
    def refresh_stock_data(
        db: Session,
        ticker: str,
        timespan: str = "day",
        multiplier: int = 1,
        full_history: bool = False,
        period: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Refresh stock data from Polygon to DB incrementally.
        Pokes the DB to find the last available date and fetches the delta.
        """
        try:
            massive = DataProviderFactory.get("massive")
            if not massive.is_available():
                return {"status": "error", "message": "Massive (Polygon) provider not available"}

            ticker = ticker.upper()
            
            # 1. Determine from_date and target range
            db_range = db.query(
                func.max(StockAggregate.timestamp),
                func.min(StockAggregate.timestamp)
            ).filter(
                StockAggregate.ticker == ticker,
                StockAggregate.timespan == timespan,
                StockAggregate.multiplier == multiplier
            ).first()
            
            last_entry = db_range[0] if db_range else None
            first_entry = db_range[1] if db_range else None
            
            # Use UTC-aware 'now' but strip tzinfo to match naive DB models if necessary
            now = datetime.now(timezone.utc).replace(tzinfo=None)
            
            # Determine target start date for full history/first fetch
            if period:
                days = 30
                if period.endswith("d"):
                    days = int(period[:-1])
                elif period.endswith("y"):
                    days = int(period[:-1]) * 365
                elif period.endswith("w"):
                    days = int(period[:-1]) * 7
                elif period.isdigit():
                    days = int(period)
                target_start = now - timedelta(days=days)
            elif timespan == "day" or timespan == "hour":
                target_start = now - timedelta(days=365 * 2)
            elif timespan == "minute":
                target_start = now - timedelta(days=30)
            else:
                target_start = now - timedelta(days=7)

            if full_history or not last_entry:
                from_date_dt = target_start
            elif first_entry and first_entry > target_start:
                # We have some data, but not enough history. 
                # Fetch from target start to now (incremental check will handle duplicates)
                from_date_dt = target_start
            else:
                # Normal incremental update from last entry
                if timespan == "day":
                    from_date_dt = last_entry + timedelta(days=1)
                elif timespan == "minute":
                    from_date_dt = last_entry + timedelta(minutes=1)
                else:
                    from_date_dt = last_entry + timedelta(seconds=1)
            
            from_date = from_date_dt.strftime("%Y-%m-%d")
            to_date = now.strftime("%Y-%m-%d")
            
            if from_date_dt.date() > now.date() and timespan == "day":
                return {"status": "success", "message": "Already up to date", "added": 0}

            # 2. Fetch from Polygon
            logging.info(f"🔄 Refreshing {ticker} {timespan} data from {from_date} to {to_date}")
            
            # This is essentially what sync_stock_aggregates task does
            # We call the service method directly here for synchronous response
            aggs = StockDataService.get_aggregates(
                ticker=ticker,
                multiplier=multiplier,
                timespan=timespan,
                from_date=from_date,
                to_date=to_date,
                limit=50000,
                paginate=True,
            )
            
            if not aggs:
                return {"status": "success", "message": "No new data found", "added": 0}
            
            # 3. Store in DB
            new_records = []
            
            # Fetch existing timestamps in this range for deduplication
            # Making them naive for comparison
            existing_ts = set(
                r[0] for r in db.query(StockAggregate.timestamp).filter(
                    StockAggregate.ticker == ticker,
                    StockAggregate.timespan == timespan,
                    StockAggregate.multiplier == multiplier,
                    StockAggregate.timestamp >= from_date_dt
                ).all()
            )

            from app.utils.session import classify_session
            for agg in aggs:
                ts_utc = agg['timestamp']
                ts_naive = ts_utc.replace(tzinfo=None)  # Store naive UTC in DB

                if ts_naive in existing_ts:
                    continue

                is_pre_market, is_after_market = classify_session(ts_utc)
                
                record = StockAggregate(
                    ticker=ticker,
                    timestamp=ts_naive,
                    multiplier=multiplier,
                    timespan=timespan,
                    open=agg['open'],
                    high=agg['high'],
                    low=agg['low'],
                    close=agg['close'],
                    volume=agg['volume'],
                    vwap=agg['vwap'],
                    transactions=agg['transactions'],
                    is_pre_market=is_pre_market,
                    is_after_market=is_after_market,
                    provider='polygon',
                )
                new_records.append(record)
                existing_ts.add(ts_naive) # Prevent duplicates within the same batch
            
            if new_records:
                db.bulk_save_objects(new_records)
                db.commit()
                logging.info(f"✅ Saved {len(new_records)} new aggregates for {ticker}")
            
            return {
                "status": "success",
                "message": f"Refreshed {len(new_records)} records",
                "added": len(new_records),
                "from_date": from_date,
                "to_date": to_date
            }


        except Exception as e:
            logging.error(f"Error refreshing data for {ticker}: {e}")
            db.rollback()
            return {"status": "error", "message": str(e)}

    @staticmethod
    def get_aggregates(
        ticker: str,
        multiplier: int,
        timespan: str,
        from_date: str,
        to_date: str,
        adjusted: bool = True,
        sort: str = "asc",
        limit: int = 50000,
        provider: str = "massive",
        paginate: bool = False,
    ) -> list[Dict[str, Any]]:
        """
        Fetch OHLCV bars via the configured data provider.

        Defaults to the 'massive' (Polygon) provider for backwards compat.
        Pass provider='ibkr' to route through Interactive Brokers instead.
        Pass paginate=True to follow Polygon page boundaries automatically.
        """
        try:
            p = DataProviderFactory.get(provider)
            if not p.is_available():
                logging.error(f"Provider '{provider}' is not available.")
                return []

            return p.get_bars(
                symbol=ticker.upper(),
                timespan=timespan,
                multiplier=multiplier,
                from_date=from_date,
                to_date=to_date,
                adjusted=adjusted,
                sort=sort,
                limit=limit,
                paginate=paginate,
            )

        except Exception as e:
            logging.exception(
                f"❌ Provider fetch FAILED for {ticker} {timespan}×{multiplier} "
                f"({from_date} → {to_date}) via {provider}: {e}"
            )
            return []

    @staticmethod
    def get_pre_market_movers(
        db: Optional[Session] = None,
        min_volume: int = 10000,
        limit: int = 100
    ) -> list[Dict[str, Any]]:
        """
        Fetch pre-market movers for all US stocks using Polygon Snapshot API.
        Filter by volume and return top movers by absolute percentage change.
        """
        try:
            massive = DataProviderFactory.get("massive")
            if not massive.is_available():
                logging.error("Massive (Polygon) provider not available")
                return []

            snapshots = massive.get_snapshots()

            if not snapshots:
                logging.warning("No snapshots returned from Polygon")
                return []

            movers = []
            for s in snapshots:
                if s["volume"] < min_volume:
                    continue

                movers.append({
                    "ticker": s["ticker"],
                    "name": None,
                    "price": s["price"],
                    "change_percent": s["change_pct"],
                    "change_value": s["change_value"],
                    "volume": s["volume"],
                    "prev_close": s["prev_close"],
                })

            # Sort by absolute change percent descending
            movers.sort(key=lambda x: abs(x["change_percent"]), reverse=True)
            top_movers = movers[:limit]

            # Enrich with DB data if available
            if db and top_movers:
                from app.models.ticker_reference import TickerReference
                ticker_list = [m["ticker"] for m in top_movers]
                refs = db.query(TickerReference).filter(TickerReference.ticker.in_(ticker_list)).all()
                ref_map = {r.ticker: r for r in refs}
                
                for m in top_movers:
                    ref = ref_map.get(m["ticker"])
                    if ref:
                        m["name"] = ref.name
                        m["sector"] = ref.sector
                        m["market_cap"] = ref.market_cap

            return top_movers

        except Exception as e:
            logging.error(f"Error fetching pre-market movers: {e}")
            return []

    @staticmethod
    def is_futures_ticker(db: Session, ticker: str) -> bool:
        """Return True if ticker is tracked as futures asset class."""
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

    @staticmethod
    def get_historical_enriched(
        db: Session,
        ticker: str,
        period: str,
        timespan: str,
        multiplier: int,
    ) -> pd.DataFrame:
        """Fetch, coerce, and optionally enrich with indicators.

        - Dispatches to get_historical_from_db or get_futures_historical_from_db
        - Applies pd.to_numeric() coercion (Decimal → float, required by orjson + indicators)
        - Applies MAX_DATAPOINTS guardrail
        - Applies INDICATOR_ROW_LIMIT guard and calls ChartIndicatorsService.add_indicators()
        - Returns empty DataFrame on no data
        Router remains responsible for compact serialization.
        """
        is_futures = StockDataService.is_futures_ticker(db, ticker)
        if is_futures:
            data = StockDataService.get_futures_historical_from_db(
                db, ticker, period, timespan, multiplier
            )
        else:
            data = StockDataService.get_historical_from_db(
                db, ticker, period, timespan, multiplier
            )

        if data.empty:
            return data

        exclude_cols = ["Date", "marker_type", "contract_month"]
        for col in data.columns:
            if col not in exclude_cols:
                data[col] = pd.to_numeric(data[col], errors="coerce")

        MAX_DATAPOINTS = 500000
        if len(data) > MAX_DATAPOINTS:
            data = data.tail(MAX_DATAPOINTS)

        INDICATOR_ROW_LIMIT = 3000
        if timespan in ["minute", "hour"] and len(data) <= INDICATOR_ROW_LIMIT:
            data = ChartIndicatorsService.add_indicators(data, is_intraday=True)

        return data
