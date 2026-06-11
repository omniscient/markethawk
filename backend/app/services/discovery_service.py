import logging
from datetime import date, timedelta
from typing import Any, Callable, Dict, List

from polygon import RESTClient
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.stock_metric import StockMetric
from app.models.ticker_reference import TickerReference

logger = logging.getLogger(__name__)

ScreenerFn = Callable[[Session, Dict[str, Any]], List[Dict[str, Any]]]

_SCREENER_REGISTRY: Dict[str, ScreenerFn] = {}


def register_screener(asset_class: str, fn: ScreenerFn) -> None:
    _SCREENER_REGISTRY[asset_class] = fn


def _apply_shared_filters(
    results: List[Dict[str, Any]], criteria: Dict[str, Any]
) -> List[Dict[str, Any]]:
    # Seam for future cross-asset filters; currently a no-op.
    return results


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

        # Lazy-import to trigger self-registration of screener adapters.
        import app.services.futures_screener  # noqa: F401
        import app.services.stock_screener  # noqa: F401

        output = []
        for asset_class in asset_classes:
            screener_fn = _SCREENER_REGISTRY.get(asset_class)
            if screener_fn is None:
                logger.warning(
                    f"No screener registered for asset_class={asset_class!r}"
                )
                continue
            output.extend(screener_fn(self.db, criteria))

        return _apply_shared_filters(output, criteria)
