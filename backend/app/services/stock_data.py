"""
Stock Data Service - Polygon.io integration for stock data.
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, Any, Optional

import pandas as pd
from polygon import RESTClient

from app.core.config import settings


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
