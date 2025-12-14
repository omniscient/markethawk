import logging
import time
from datetime import datetime, date, timedelta
from typing import List, Optional, Dict, Any
from sqlalchemy.orm import Session
from sqlalchemy import func, desc

from polygon import RESTClient
from polygon.exceptions import BadResponse
from app.models.ticker_reference import TickerReference
from app.models.stock_metric import StockMetric
from app.core.config import settings

logger = logging.getLogger(__name__)

class DiscoveryService:
    def __init__(self, db: Session):
        self.db = db
        self.client = RESTClient(settings.POLYGON_API_KEY)

    def sync_fundamental_data(self, limit: int = None, batch_size: int = 1000):
        """
        Triggers the background Celery task chain to sync tickers.
        """
        from app.tasks import sync_tickers_batch
        
        logger.info("🚀 Triggering fundamental data sync via Celery task chain...")
        # Start the chain
        sync_tickers_batch.delay()
        
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

            count = 0
            for ag in aggs:
                # Update or create metric
                metric = self.db.query(StockMetric).filter(
                    StockMetric.ticker == ag.ticker,
                    StockMetric.date == target_date
                ).first()
                
                if not metric:
                    metric = StockMetric(
                        ticker=ag.ticker,
                        date=target_date
                    )
                    self.db.add(metric)
                
                metric.close_price = ag.close
                metric.volume = ag.volume
                metric.high_52w = max(metric.high_52w or 0, ag.high)
                metric.low_52w = min(metric.low_52w or ag.low, ag.low) if metric.low_52w else ag.low
                
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

    def sync_ticker_details_crawler(self):
        """
        Triggers the background crawler to fetch detailed info (employees, description, etc.)
        for all tickers one-by-one.
        """
        from app.tasks import start_details_crawl
        
        logger.info("🚀 Triggering background details crawler...")
        start_details_crawl.delay()
        
        return {"status": "started", "message": "Details crawler started in background"}

    def run_screen(self, criteria: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Executes a screen based on provided criteria.
        Returns list of matching tickers with their fundamental data.
        """
        # Start query joining Reference and Metric
        # Note: In production we need to ensure we join the *latest* metric.
        # Here we assume the metrics table is clean or we filter by date.
        query = self.db.query(TickerReference, StockMetric).join(
            StockMetric, TickerReference.ticker == StockMetric.ticker
        )
        
        # Apply Fundamental Filters
        if "min_market_cap" in criteria:
            query = query.filter(TickerReference.market_cap >= criteria["min_market_cap"])
            
        if "min_outstanding_shares" in criteria:
            query = query.filter(TickerReference.outstanding_shares >= criteria["min_outstanding_shares"])
            
        if "sector" in criteria and criteria["sector"]:
            query = query.filter(TickerReference.sector == criteria["sector"])

        # Apply Technical Filters
        if "price_above_sma50" in criteria and criteria["price_above_sma50"]:
            query = query.filter(StockMetric.close_price > StockMetric.sma_50)
            
        if "price_below_sma50" in criteria and criteria["price_below_sma50"]:
             query = query.filter(StockMetric.close_price < StockMetric.sma_50)
             
        if "min_volume" in criteria:
            query = query.filter(StockMetric.volume >= criteria["min_volume"])

        # Execute
        results = query.limit(100).all() # Safety limit
        
        # Format output
        output = []
        for ref, metric in results:
            output.append({
                "ticker": ref.ticker,
                "name": ref.name,
                "market_cap": ref.market_cap,
                "close_price": metric.close_price,
                "volume": metric.volume,
                "sector": ref.sector
            })
            
        return output

