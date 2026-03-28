"""
Stock Data Service - Polygon.io integration for stock data.
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, Any, Optional

import pandas as pd
from polygon import RESTClient

import pandas as pd
from polygon import RESTClient
from sqlalchemy.orm import Session
from sqlalchemy import func, desc

from app.core.config import settings
from app.models.stock_aggregate import StockAggregate


# Initialize Polygon client
polygon_client: Optional[RESTClient] = (
    RESTClient(settings.POLYGON_API_KEY) if settings.POLYGON_API_KEY else None
)


class StockDataService:
    """Service for fetching stock data from Polygon.io."""

    @staticmethod
    async def get_historical_data(ticker: str, period: str = "30d") -> pd.DataFrame:
        """Get historical stock data from Polygon.io."""
        try:
            if not polygon_client:
                logging.error("Polygon client not initialized - check POLYGON_API_KEY")
                return pd.DataFrame()

            # Convert period to days
            days = int(period.replace("d", "")) if "d" in period else 30
            end_date = datetime.now()
            start_date = end_date - timedelta(days=days)

            # Fetch daily aggregates from Polygon
            aggs = polygon_client.get_aggs(
                ticker=ticker.upper(),
                multiplier=1,
                timespan="day",
                from_=start_date.strftime("%Y-%m-%d"),
                to=end_date.strftime("%Y-%m-%d"),
                limit=50000,
            )

            if not aggs:
                return pd.DataFrame()

            # Convert to DataFrame
            data = []
            for agg in aggs:
                data.append(
                    {
                        "Date": datetime.fromtimestamp(agg.timestamp / 1000),
                        "Open": agg.open,
                        "High": agg.high,
                        "Low": agg.low,
                        "Close": agg.close,
                        "Volume": agg.volume,
                    }
                )

            df = pd.DataFrame(data)
            df.set_index("Date", inplace=True)
            return df

        except Exception as e:
            logging.error(f"Error fetching data for {ticker}: {e}")
            return pd.DataFrame()

    @staticmethod
    async def get_pre_market_data(ticker: str) -> Dict[str, Any]:
        """Get pre-market data from Polygon.io."""
        try:
            if not polygon_client:
                logging.error("Polygon client not initialized - check POLYGON_API_KEY")
                return {}

            today = datetime.now()

            # Fetch minute-level data for extended hours
            aggs = polygon_client.get_aggs(
                ticker=ticker.upper(),
                multiplier=1,
                timespan="minute",
                from_=today.strftime("%Y-%m-%d"),
                to=today.strftime("%Y-%m-%d"),
                limit=50000,
            )

            if not aggs:
                return {}

            # Filter for extended hours (Pre-market: 4:00 AM - 9:30 AM AND After-market: 4:00 PM - 8:00 PM ET)
            extended_data = []
            for agg in aggs:
                agg_time = datetime.fromtimestamp(agg.timestamp / 1000)
                hour = agg_time.hour
                minute = agg_time.minute

                # Pre-market: 4:00 AM to 9:30 AM
                is_pre = (hour >= 4 and hour < 9) or (hour == 9 and minute < 30)
                # After-market: 4:00 PM to 8:00 PM
                is_after = (hour >= 16 and hour < 20)
                
                if is_pre or is_after:
                    extended_data.append(agg)

            if not extended_data:
                return {}

            return {
                "pre_market_volume": sum(agg.volume for agg in extended_data),
                "pre_market_high": max(agg.high for agg in extended_data),
                "pre_market_low": min(agg.low for agg in extended_data),
                "pre_market_open": extended_data[0].open if extended_data else None,
                "pre_market_close": extended_data[-1].close if extended_data else None,
            }

        except Exception as e:
            logging.error(f"Error fetching pre-market data for {ticker}: {e}")
            return {}

    @staticmethod
    async def get_stock_info(ticker: str) -> Dict[str, Any]:
        """Get stock details from Polygon.io."""
        try:
            if not polygon_client:
                logging.error("Polygon client not initialized - check POLYGON_API_KEY")
                return {}

            details = polygon_client.get_ticker_details(ticker.upper())

            if not details:
                return {}

            return {
                "longName": details.name,
                "shortName": details.name,
                "sector": getattr(details, "sic_description", "") or "",
                "industry": getattr(details, "sic_description", "") or "",
                "marketCap": getattr(details, "market_cap", None),
                "currentPrice": None,  # Will be fetched from latest quote if needed
            }

        except Exception as e:
            logging.error(f"Error fetching stock info for {ticker}: {e}")
            return {}

    @staticmethod
    async def get_historical_from_db(
        db: Session,
        ticker: str,
        period: str = "30d",
        timespan: str = "day",
        multiplier: int = 1
    ) -> pd.DataFrame:
        """Fetch historical data from the local database."""
        try:
            # Calculate start date based on period
            days = 30
            if period.endswith("d"):
                days = int(period[:-1])
            elif period.endswith("y"):
                days = int(period[:-1]) * 365
            elif period.endswith("w"):
                days = int(period[:-1]) * 7
            elif period.isdigit():
                days = int(period)
            
            start_date = datetime.now() - timedelta(days=days)
            
            # Query DB
            query = db.query(StockAggregate).filter(
                StockAggregate.ticker == ticker,
                StockAggregate.timespan == timespan,
                StockAggregate.multiplier == multiplier,
                StockAggregate.timestamp >= start_date
            ).order_by(StockAggregate.timestamp.asc())
            
            results = query.all()
            
            if not results:
                return pd.DataFrame()
            
            # Convert to DataFrame
            data = []
            for r in results:
                data.append({
                    "Date": r.timestamp,
                    "Open": float(r.open),
                    "High": float(r.high),
                    "Low": float(r.low),
                    "Close": float(r.close),
                    "Volume": int(r.volume),
                    "vwap": float(r.vwap) if r.vwap else None,
                    "transactions": r.transactions
                })
            
            df = pd.DataFrame(data)
            df.set_index("Date", inplace=True)
            return df
            
        except Exception as e:
            logging.error(f"Error fetching historical data from DB for {ticker}: {e}")
            return pd.DataFrame()

    @staticmethod
    async def refresh_stock_data(
        db: Session,
        ticker: str,
        timespan: str = "day",
        multiplier: int = 1,
        full_history: bool = False
    ) -> Dict[str, Any]:
        """
        Refresh stock data from Polygon to DB incrementally.
        Pokes the DB to find the last available date and fetches the delta.
        """
        try:
            if not polygon_client:
                return {"status": "error", "message": "Polygon client not initialized"}

            ticker = ticker.upper()
            
            # 1. Determine from_date
            last_entry = db.query(func.max(StockAggregate.timestamp)).filter(
                StockAggregate.ticker == ticker,
                StockAggregate.timespan == timespan,
                StockAggregate.multiplier == multiplier
            ).scalar()
            
            now = datetime.now()
            
            if last_entry and not full_history:
                # Start from one unit after the last entry
                # For daily, +1 day. For minute, +1 minute.
                if timespan == "day":
                    from_date_dt = last_entry + timedelta(days=1)
                elif timespan == "minute":
                    from_date_dt = last_entry + timedelta(minutes=1)
                else:
                    from_date_dt = last_entry + timedelta(seconds=1)
            else:
                # Full history requested or no entries
                if timespan == "day":
                    # Go back 2 years for daily full history
                    from_date_dt = now - timedelta(days=365 * 2)
                else:
                    # Generic fallback (e.g. 7 days for minute data)
                    from_date_dt = now - timedelta(days=7)
            
            from_date = from_date_dt.strftime("%Y-%m-%d")
            to_date = now.strftime("%Y-%m-%d")
            
            if from_date_dt.date() > now.date() and timespan == "day":
                return {"status": "success", "message": "Already up to date", "added": 0}

            # 2. Fetch from Polygon
            logging.info(f"🔄 Refreshing {ticker} {timespan} data from {from_date} to {to_date}")
            
            # This is essentially what sync_stock_aggregates task does
            # We call the service method directly here for synchronous response
            aggs = await StockDataService.get_aggregates(
                ticker=ticker,
                multiplier=multiplier,
                timespan=timespan,
                from_date=from_date,
                to_date=to_date,
                limit=50000
            )
            
            if not aggs:
                return {"status": "success", "message": "No new data found", "added": 0}
            
            # 3. Store in DB
            new_records = []
            for agg in aggs:
                ts = agg['timestamp']
                
                # Check for duplicates if we didn't start strictly after
                # (Polygon API from_date is inclusive)
                if last_entry and ts <= last_entry:
                    continue
                
                # Extended hours logic (copied from tasks.py)
                hour = ts.hour
                minute = ts.minute
                is_pre_market = (hour >= 4 and hour < 9) or (hour == 9 and minute < 30)
                is_after_market = (hour >= 16 and hour < 20)
                
                record = StockAggregate(
                    ticker=ticker,
                    timestamp=ts,
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
                    is_after_market=is_after_market
                )
                new_records.append(record)
            
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
    async def get_aggregates(
        ticker: str,
        multiplier: int,
        timespan: str,
        from_date: str,
        to_date: str,
        adjusted: bool = True,
        sort: str = "asc",
        limit: int = 50000
    ) -> list[Dict[str, Any]]:
        """Fetch aggregates from Polygon.io."""
        try:
            if not polygon_client:
                logging.error("Polygon client not initialized")
                return []

            aggs = polygon_client.get_aggs(
                ticker=ticker.upper(),
                multiplier=multiplier,
                timespan=timespan,
                from_=from_date,
                to=to_date,
                adjusted=adjusted,
                sort=sort,
                limit=limit,
            )

            if not aggs:
                return []

            return [
                {
                    "timestamp": datetime.fromtimestamp(agg.timestamp / 1000),
                    "open": agg.open,
                    "high": agg.high,
                    "low": agg.low,
                    "close": agg.close,
                    "volume": agg.volume,
                    "vwap": getattr(agg, "vwap", None),
                    "transactions": getattr(agg, "transactions", None)
                }
                for agg in aggs
            ]

        except Exception as e:
            logging.error(f"Error fetching aggregates for {ticker}: {e}")
            return []
