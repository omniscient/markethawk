import logging
from datetime import date, timedelta
from typing import Any, Dict, List

from polygon import RESTClient
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.stock_metric import StockMetric
from app.models.ticker_reference import TickerReference

logger = logging.getLogger(__name__)


class DiscoveryService:
    def __init__(self, db: Session):
        self.db = db
        self.client = RESTClient(settings.POLYGON_API_KEY)

    def sync_fundamental_data(
        self, limit: int = None, batch_size: int = 1000, delay_seconds: float = 15.0
    ):
        """
        Triggers the background Celery task chain to sync tickers.
        """
        from app.tasks import sync_tickers_batch

        logger.info(
            f"🚀 Triggering fundamental data sync via Celery task chain (delay={delay_seconds}s)..."
        )
        # Start the chain
        sync_tickers_batch.delay(delay_seconds=delay_seconds)

        return {"status": "started", "message": "Sync started in background task chain"}

    def update_daily_metrics_snapshot(self):
        """
        Updates daily metrics for all stocks using the Grouped Daily API.
        This is efficient (1 call).
        """
        try:
            today = date.today()
            # If market is closed or pre-market, this might return yesterday or nothing.
            # Best to run this after market close or check previous day.
            # For now, let's try to get 'yesterday' to be safe or today.
            # We'll use the most recent trading day logic effectively.

            # Simple approach: Get yesterday's data
            target_date = today - timedelta(days=1)
            # Todo: Handle weekends/holidays logic

            logger.info(f"Fetching grouped daily aggs for {target_date}...")
            aggs = self.client.get_grouped_daily_aggs(target_date)

            if not aggs:
                logger.warning("No data returned for grouped daily aggs.")
                return

            valid_tickers = {t[0] for t in self.db.query(TickerReference.ticker).all()}

            count = 0
            for ag in aggs:
                if ag.ticker not in valid_tickers:
                    continue

                # Update or create metric
                metric = (
                    self.db.query(StockMetric)
                    .filter(
                        StockMetric.ticker == ag.ticker, StockMetric.date == target_date
                    )
                    .first()
                )

                if not metric:
                    metric = StockMetric(ticker=ag.ticker, date=target_date)
                    self.db.add(metric)

                metric.close_price = ag.close
                metric.volume = ag.volume
                metric.high_52w = max(metric.high_52w or 0, ag.high)
                metric.low_52w = (
                    min(metric.low_52w or ag.low, ag.low) if metric.low_52w else ag.low
                )

                # Recalculate SMA/AvgVol if we have previous data
                # This part is tricky without history.
                # For now, we store raw data. SMA calculation requires chain.

                count += 1

            self.db.commit()
            logger.info(f"Updated metrics for {count} stocks.")

        except Exception as e:
            logger.error(f"Error updating daily metrics: {str(e)}")
            self.db.rollback()
            raise

    def sync_ticker_details_crawler(
        self, delay_seconds: float = 15.0, resync: bool = False
    ):
        """
        Triggers the background crawler to fetch detailed info (employees, description, etc.)
        for all tickers one-by-one.

        Args:
            delay_seconds: Time to wait between requests (15.0 for free tier, 0.2 for paid)
            resync: If True, resets the update status for ALL tickers to force a full re-crawl.
        """
        from app.tasks import start_details_crawl

        logger.info(
            f"🚀 Triggering background details crawler with delay={delay_seconds}s (resync={resync})..."
        )
        start_details_crawl.delay(delay_seconds=delay_seconds, resync=resync)

        return {
            "status": "started",
            "message": f"Details crawler started in background (delay={delay_seconds}s)",
        }

    def run_screen(self, criteria: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Executes a screen based on provided criteria.
        Returns list of matching tickers with their fundamental data.
        """
        asset_classes = criteria.get("asset_classes", ["stocks"])
        data_source_stocks = criteria.get("data_source_stocks", "massive")
        data_source_futures = criteria.get("data_source_futures", "ibkr")
        output = []
        has_metric_filters = False

        if "stocks" in asset_classes:
            # Determine if we need to filter by metrics
            # Currently only min_volume is handled in this logic
            has_metric_filters = "min_volume" in criteria and criteria["min_volume"] > 0

            if has_metric_filters:
                # Need metrics -> Inner Join
                # Using inner join because if we filter by volume, we MUST have the volume data
                query = self.db.query(TickerReference, StockMetric).join(
                    StockMetric, TickerReference.ticker == StockMetric.ticker
                )
            else:
                # No metric filters -> Query only Reference for performance
                # No need to join metrics table
                query = self.db.query(TickerReference)

            # Apply Fundamental Filters
            # Only apply filters if value is non-default/truthy
            if "min_market_cap" in criteria and criteria["min_market_cap"] > 0:
                query = query.filter(
                    TickerReference.market_cap >= criteria["min_market_cap"]
                )

            if "max_market_cap" in criteria and criteria["max_market_cap"] > 0:
                query = query.filter(
                    TickerReference.market_cap <= criteria["max_market_cap"]
                )

            if (
                "min_outstanding_shares" in criteria
                and criteria["min_outstanding_shares"] > 0
            ):
                query = query.filter(
                    TickerReference.outstanding_shares
                    >= criteria["min_outstanding_shares"]
                )

            if "sector" in criteria and criteria["sector"]:
                if isinstance(criteria["sector"], list):
                    if len(criteria["sector"]) > 0:
                        query = query.filter(
                            TickerReference.sector.in_(criteria["sector"])
                        )
                elif criteria["sector"]:  # Single value not empty string
                    query = query.filter(TickerReference.sector == criteria["sector"])

            if "primary_exchange" in criteria and criteria["primary_exchange"]:
                if isinstance(criteria["primary_exchange"], list):
                    if len(criteria["primary_exchange"]) > 0:
                        query = query.filter(
                            TickerReference.primary_exchange.in_(
                                criteria["primary_exchange"]
                            )
                        )
                elif criteria["primary_exchange"]:
                    query = query.filter(
                        TickerReference.primary_exchange == criteria["primary_exchange"]
                    )

            if "sic_code" in criteria and criteria["sic_code"]:
                query = query.filter(TickerReference.sic_code == criteria["sic_code"])

            if "description_contains" in criteria and criteria["description_contains"]:
                query = query.filter(
                    TickerReference.description.ilike(
                        f"%{criteria['description_contains']}%"
                    )
                )

            # Range Filters for new numeric fields
            if "min_employees" in criteria and criteria["min_employees"] > 0:
                query = query.filter(
                    TickerReference.total_employees >= criteria["min_employees"]
                )

            if "max_employees" in criteria and criteria["max_employees"] > 0:
                query = query.filter(
                    TickerReference.total_employees <= criteria["max_employees"]
                )

            if (
                "min_share_class_shares" in criteria
                and criteria["min_share_class_shares"] > 0
            ):
                query = query.filter(
                    TickerReference.share_class_shares_outstanding
                    >= criteria["min_share_class_shares"]
                )

            if (
                "max_share_class_shares" in criteria
                and criteria["max_share_class_shares"] > 0
            ):
                query = query.filter(
                    TickerReference.share_class_shares_outstanding
                    <= criteria["max_share_class_shares"]
                )

            if has_metric_filters:
                if "min_volume" in criteria and criteria["min_volume"] > 0:
                    query = query.filter(StockMetric.volume >= criteria["min_volume"])

            # Debug Logging
            if settings.LOG_LEVEL == "DEBUG":
                try:
                    # Compile query with literal binds for readability
                    statement = query.statement.compile(
                        compile_kwargs={"literal_binds": True}
                    )
                    logger.info(f"🔍 Discovery Screen Query: {statement}")
                except Exception as e:
                    logger.error(f"Failed to log debug query: {e}")

            # Execute
            results = query.all()  # No limit as requested by user

            for row in results:
                if has_metric_filters:
                    ref, metric = row
                else:
                    ref = row
                    metric = None

                output.append(
                    {
                        "ticker": ref.ticker,
                        "name": ref.name,
                        "market_cap": ref.market_cap,
                        "close_price": metric.close_price if metric else None,
                        "volume": metric.volume if metric else None,
                        "sector": ref.sector,
                        "primary_exchange": ref.primary_exchange,
                        "employees": ref.total_employees,
                        "sic_code": ref.sic_code,
                        "description": ref.description,
                        "asset_class": "stocks",
                        "data_source": data_source_stocks,
                    }
                )

        if "futures" in asset_classes:
            futures_input = criteria.get("futures_symbols", "")
            if isinstance(futures_input, str):
                futures_symbols = [
                    s.strip().upper() for s in futures_input.split(",") if s.strip()
                ]
            else:
                futures_symbols = [
                    s.strip().upper()
                    for s in futures_input
                    if isinstance(s, str) and s.strip()
                ]

            if futures_symbols:
                from app.models.futures_contract import FuturesContract

                # Find found symbols
                found_futures = (
                    self.db.query(FuturesContract.symbol, FuturesContract.exchange)
                    .filter(FuturesContract.symbol.in_(futures_symbols))
                    .distinct()
                    .all()
                )

                found_symbols = {f.symbol for f in found_futures}

                # Add found ones
                for fut in found_futures:
                    output.append(
                        {
                            "ticker": fut.symbol,
                            "name": f"{fut.symbol} Futures",
                            "market_cap": None,
                            "close_price": None,
                            "volume": None,
                            "sector": "Futures",
                            "primary_exchange": fut.exchange,
                            "employees": None,
                            "sic_code": None,
                            "description": f"Futures contract for {fut.symbol}",
                            "asset_class": "futures",
                            "data_source": data_source_futures,
                        }
                    )

                # Add missing ones as placeholders
                for symbol in futures_symbols:
                    if symbol not in found_symbols:
                        output.append(
                            {
                                "ticker": symbol,
                                "name": f"{symbol} Futures",
                                "market_cap": None,
                                "close_price": None,
                                "volume": None,
                                "sector": "Futures",
                                "primary_exchange": "Unknown",  # Will be resolved on first data sync
                                "employees": None,
                                "sic_code": None,
                                "description": f"Requested Futures contract for {symbol} (Sync pending)",
                                "asset_class": "futures",
                                "data_source": data_source_futures,
                            }
                        )

        return output
