import logging
import httpx
import redis
from datetime import datetime
from sqlalchemy.orm import Session

from app.core.celery_app import celery_app
from app.core.database import SessionLocal
from app.core.config import settings
from app.models.ticker_reference import TickerReference

logger = logging.getLogger(__name__)

@celery_app.task(bind=True, max_retries=3)
def sync_tickers_batch(self, next_url: str = None, delay_seconds: float = 15.0):
    """
    Celery task to sync tickers in batches using strict rate limiting (recursive chaining).
    Each execution processes one page and schedules the next page 15 seconds later.
    """
    db: Session = SessionLocal()
    try:
        # 1. Prepare URL
        if not next_url:
            base_url = "https://api.polygon.io/v3/reference/tickers"
            # Limit 1000 is max per page for Polygon V3
            url = f"{base_url}?market=stocks&active=true&limit=1000"
            logger.info(f"🚀 Starting new Ticker Sync Chain from scratch: {url}")
        else:
            url = next_url
            logger.info(f"🔗 Continuing Ticker Sync Chain: {url}")

        # 2. Make API Request (Strictly ONE call)
        headers = {"Authorization": f"Bearer {settings.POLYGON_API_KEY}"}
        
        with httpx.Client(timeout=30.0) as client:
            response = client.get(url, headers=headers)
            
            # Handle Rate Limits (429) explicitly
            if response.status_code == 429:
                logger.warning("⚠️ Rate limit hit (429). Retrying in 60s...")
                # Retry this same task in 60 seconds
                raise self.retry(countdown=60)
            
            response.raise_for_status()
            data = response.json()

        # 3. Process Results
        results = data.get("results", [])
        count = 0
        
        for t in results:
            try:
                ticker = t.get("ticker")
                if not ticker:
                    continue
                    
                # Upsert Ticker
                stmt = db.query(TickerReference).filter(TickerReference.ticker == ticker).first()
                if not stmt:
                    stmt = TickerReference(ticker=ticker)
                    db.add(stmt)
                
                stmt.name = t.get("name")
                stmt.active = t.get("active")
                stmt.cik = t.get("cik")
                stmt.composite_figi = t.get("composite_figi")
                stmt.market = t.get("market")
                stmt.type = t.get("type")

                # Market Cap not in Polygon v3 list response
                # stmt.market_cap = t.get("market_cap") or 0
                
                # Type is NOT sector (e.g. 'CS' = Common Stock)
                # stmt.sector = t.get("type") # REMOVED: User confirmed this was wrong
                
                stmt.primary_exchange = t.get("primary_exchange")
                stmt.last_updated = datetime.utcnow()
                count += 1
                
            except Exception as e:
                logger.error(f"Error saving ticker {t.get('ticker')}: {e}")
                continue
        
        db.commit()
        logger.info(f"✅ Processed {count} tickers in this batch.")

        # 4. Schedule Next Batch (Recursive Chain)
        next_page = data.get("next_url")
        if next_page:
            logger.info(f"⏭️ Next page found. Scheduling next batch in {delay_seconds} seconds...")
            # Schedule next task 15 seconds from now
            sync_tickers_batch.apply_async(
                args=[next_page], 
                kwargs={"delay_seconds": delay_seconds},
                countdown=delay_seconds
            )
        else:
            logger.info("🎉 Sync Complete! No more pages.")

    except Exception as e:
        logger.error(f"❌ Error in sync_tickers_batch: {str(e)}")
        db.rollback()
        raise e
    finally:
        db.close()


@celery_app.task(bind=True, max_retries=3)
def sync_ticker_details(self, ticker: str, delay_seconds: float = 15.0):
    """
    Slow crawler task to fetch details for ONE ticker.
    Reschedules itself for the NEXT ticker after `delay_seconds`.
    """
    db: Session = SessionLocal()
    try:
        logger.info(f"🔍 Fetching details for ticker: {ticker} (Delay: {delay_seconds}s)")
        
        # 1. Fetch Data
        url = f"https://api.polygon.io/v3/reference/tickers/{ticker}"
        headers = {"Authorization": f"Bearer {settings.POLYGON_API_KEY}"}
        
        with httpx.Client(timeout=30.0) as client:
            response = client.get(url, headers=headers)
            
            if response.status_code == 429:
                logger.warning(f"⚠️ Rate limit hit for {ticker}. Retrying in 60s...")
                raise self.retry(countdown=60)
                
            if response.status_code == 404:
                logger.warning(f"Ticker {ticker} not found on Polygon. Skipping.")
                # Don't fail, just move to next
            else:
                response.raise_for_status()
                data = response.json()
                results = data.get("results", {})
                
                # 2. Update DB
                stmt = db.query(TickerReference).filter(TickerReference.ticker == ticker).first()
                if stmt:
                    stmt.description = results.get("description")
                    stmt.market_cap = results.get("market_cap")
                    stmt.primary_exchange = results.get("primary_exchange")
                    stmt.list_date = results.get("list_date")
                    stmt.total_employees = results.get("total_employees")
                    stmt.share_class_shares_outstanding = results.get("share_class_shares_outstanding")
                    stmt.weighted_shares_outstanding = results.get("weighted_shares_outstanding")
                    stmt.sic_code = results.get("sic_code")
                    stmt.sic_description = results.get("sic_description")
                    # Map SIC description to Industry as a fallback/primary
                    stmt.industry = results.get("sic_description")
                    # Clear out the incorrect 'CS' sector values if present
                    if stmt.sector == 'CS':
                        stmt.sector = None
                        
                    stmt.homepage_url = results.get("homepage_url")
                    stmt.last_details_update = datetime.utcnow()
                    
                    db.commit()
                    logger.info(f"✅ Updated details for {ticker}")

        # 3. Schedule Next Ticker (Recursive Chain)
        # Find next ticker that hasn't been updated recently (or at all)
        next_ticker = (
            db.query(TickerReference.ticker)
            .filter(
                (TickerReference.last_details_update == None) | 
                (TickerReference.last_details_update < datetime.utcnow().date())
            )
            .order_by(TickerReference.last_updated.desc()) # Prioritize recently active
            .first()
        )
        
        if next_ticker:
            # 4. Check for Stop Flag Check
            try:
                r = redis.from_url(settings.REDIS_URL)
                if r.exists("CRAWLER_STOP_FLAG"):
                    logger.warning("🛑 Stop Flag detected. Halting crawler.")
                    return
            except Exception as e:
                logger.error(f"Redis check failed: {e}")

            logger.info(f"⏭️ Scheduling details sync for {next_ticker.ticker} in {delay_seconds} seconds...")
            sync_ticker_details.apply_async(
                args=[next_ticker.ticker], 
                kwargs={"delay_seconds": delay_seconds},
                countdown=delay_seconds
            )
        else:
            logger.info("🎉 All tickers updated! Crawler sleeping.")

    except Exception as e:
        logger.error(f"❌ Error syncing details for {ticker}: {e}")
        db.rollback()
        # Even if error, try to schedule next so chain doesn't die?
        # Maybe better to let retry handle it.
        raise self.retry(exc=e, countdown=60)
    finally:
        db.close()

@celery_app.task(bind=True)
def start_details_crawl(self, delay_seconds: float = 15.0, resync: bool = False):
    """
    Kicks off the details crawler if it's not running.
    """
    db: Session = SessionLocal()
    try:
        if resync:
            logger.info("♻️ Force Resync requested. Resetting crawl status for all tickers...")
            db.query(TickerReference).update({TickerReference.last_details_update: None})
            db.commit()
        
        # Clear Stop Flag to allow restart
        try:
             r = redis.from_url(settings.REDIS_URL)
             r.delete("CRAWLER_STOP_FLAG")
        except Exception:
             pass
        
        # Find first candidate (Priority: Never updated > Updated long ago)
        next_ticker = (
            db.query(TickerReference.ticker)
            .filter(
                (TickerReference.last_details_update == None) | 
                (TickerReference.last_details_update < datetime.utcnow().date())
            )
            .order_by(TickerReference.last_updated.desc())
            .first()
        )
        
        if next_ticker:
            logger.info(f"🚀 Starting Details Crawler with {next_ticker.ticker} (Delay: {delay_seconds}s)")
            sync_ticker_details.delay(ticker=next_ticker.ticker, delay_seconds=delay_seconds)
        else:
            logger.info("No tickers need detail updates.")
            
    finally:
        db.close()
