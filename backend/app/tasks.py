import logging
import httpx
import redis
import asyncio
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from sqlalchemy.orm import Session

from app.core.celery_app import celery_app
from app.core.database import SessionLocal
from app.core.config import settings
from app.models.ticker_reference import TickerReference
from app.models.stock_aggregate import StockAggregate
from app.services.stock_data import StockDataService
from app.models.news_preference import NewsPreference
from app.models.news_article import NewsArticle
from app.models.monitored_stock import MonitoredStock
from app.models.stock_split import StockSplit
import json

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
                stmt.last_updated = datetime.now(timezone.utc).replace(tzinfo=None)
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
                    stmt.last_details_update = datetime.now(timezone.utc).replace(tzinfo=None)
                    
                    db.commit()
                    logger.info(f"✅ Updated details for {ticker}")

        # 3. Schedule Next Ticker (Recursive Chain)
        # Find next ticker that hasn't been updated recently (or at all)
        next_ticker = (
            db.query(TickerReference.ticker)
            .filter(
                (TickerReference.last_details_update == None) | 
                (TickerReference.last_details_update < datetime.now(timezone.utc).date())
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
                (TickerReference.last_details_update < datetime.now(timezone.utc).date())
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

@celery_app.task(bind=True, max_retries=3)
def sync_stock_aggregates(
    self, 
    ticker: str, 
    from_date: str, 
    to_date: str, 
    multiplier: int = 1, 
    timespan: str = "minute",
    adjusted: bool = True,
    sort: str = "asc",
    limit: int = 50000
):
    """
    Fetch and store aggregates for a specific ticker and date range.
    """
    db: Session = SessionLocal()
    try:
        logger.info(
            f"📊 Syncing aggregates for {ticker} {timespan}×{multiplier} "
            f"({from_date} to {to_date})"
        )

        # 1. Fetch data (paginate so >50k bars over a long range aren't truncated)
        aggs = StockDataService.get_aggregates(
            ticker=ticker,
            multiplier=multiplier,
            timespan=timespan,
            from_date=from_date,
            to_date=to_date,
            adjusted=adjusted,
            sort=sort,
            limit=limit,
            paginate=True,
        )

        if not aggs:
            logger.info(
                f"📭 Polygon returned no bars for {ticker} "
                f"{timespan}×{multiplier} ({from_date} to {to_date})"
            )
            return

        # 2. Delete existing data for the SAME timespan/multiplier and date range to
        #    avoid duplicates. Filtering by timespan/multiplier is critical: a day-bar
        #    sync must not wipe minute-bar rows in the same date range, and vice versa.
        start_dt = datetime.strptime(from_date, "%Y-%m-%d")
        end_dt = datetime.strptime(to_date, "%Y-%m-%d") + timedelta(days=1)

        db.query(StockAggregate).filter(
            StockAggregate.ticker == ticker,
            StockAggregate.timespan == timespan,
            StockAggregate.multiplier == multiplier,
            StockAggregate.timestamp >= start_dt,
            StockAggregate.timestamp < end_dt
        ).delete(synchronize_session=False)
        
        # 3. Insert new data
        from app.utils.session import classify_session
        new_records = []
        for agg in aggs:
            ts_utc = agg['timestamp']
            is_pre_market, is_after_market = classify_session(ts_utc)
            
            record = StockAggregate(
                ticker=ticker,
                timestamp=ts_utc.replace(tzinfo=None), # Store naive UTC in DB
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
            
        db.bulk_save_objects(new_records)
        db.commit()
        logger.info(f"✅ Saved {len(new_records)} aggregates for {ticker}")

    except Exception as e:
        logger.error(f"❌ Error syncing aggregates for {ticker}: {e}")
        db.rollback()
        raise self.retry(exc=e, countdown=60)
    finally:
        db.close()

@celery_app.task(bind=True, max_retries=3)
def poll_massive_news(self, limit: int = 50, force: bool = False):
    """
    Celery task to poll Polygon.io News API based on NewsPreference settings.
    Dispatches events via Redis PubSub for real-time frontend updates.

    Schedule window: Monday 2 AM ET through Friday 8 PM ET.
    Pass force=True to bypass the schedule check (manual refresh).
    """
    # ── Trading-hours guard ──────────────────────────────────────────
    if not force:
        et = ZoneInfo("America/New_York")
        now_et = datetime.now(et)
        weekday = now_et.weekday()  # 0=Mon … 6=Sun

        # Completely skip Saturday (5) and Sunday (6)
        if weekday >= 5:
            return

        # Monday (0): only allow from 2 AM onward
        if weekday == 0 and now_et.hour < 2:
            return

        # Friday (4): only allow until 8 PM (hour < 20 means before 8 PM,
        # hour == 20 and minute > 0 would be past 8 PM)
        if weekday == 4 and now_et.hour >= 20:
            return

    # ── Main logic ───────────────────────────────────────────────────
    db: Session = SessionLocal()
    try:
        pref = db.query(NewsPreference).first()
        if not pref:
            logger.info("No NewsPreference found. Skipping poll.")
            return

        now = datetime.now(timezone.utc).replace(tzinfo=None)
        if not force and pref.last_polled_at:
            delta_minutes = (now - pref.last_polled_at).total_seconds() / 60.0
            if delta_minutes < pref.refresh_interval_minutes:
                # Not enough time has passed
                return
        
        # Build list of tickers
        tickers_to_poll = set()
        if pref.tracked_tickers:
            tickers_to_poll.update(pref.tracked_tickers)
        
        if pref.tracked_universes:
            db_tickers = db.query(MonitoredStock.ticker).filter(
                MonitoredStock.universe_id.in_(pref.tracked_universes)
            ).all()
            for (t,) in db_tickers:
                tickers_to_poll.add(t)

        r = redis.from_url(settings.REDIS_URL, decode_responses=True)

        def fetch_category(query_params: dict):
            url = "https://api.polygon.io/v2/reference/news"
            headers = {"Authorization": f"Bearer {settings.POLYGON_API_KEY}"}
            
            # Ensure we don't fetch archaic news
            seven_days_ago = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=7)
            query_params["published_utc.gte"] = seven_days_ago.strftime("%Y-%m-%d")

            with httpx.Client(timeout=30.0) as client:
                response = client.get(url, headers=headers, params=query_params)
                if response.status_code == 429:
                     logger.warning("Rate limit hit polling news.")
                     return
                response.raise_for_status()
                data = response.json()
            
            results = data.get("results", [])
            new_articles = 0
            for item in reversed(results): # Process oldest to newest
                article_url = item.get("article_url")
                if db.query(NewsArticle).filter(NewsArticle.article_url == article_url).first():
                     continue 
                     
                pub_utc = item.get("published_utc")
                dt = datetime.strptime(pub_utc.replace("Z", "+0000"), "%Y-%m-%dT%H:%M:%S%z") if pub_utc else datetime.now(timezone.utc)
                dt = dt.replace(tzinfo=None)

                if dt < seven_days_ago:
                    continue

                article = NewsArticle(
                    title=item.get("title", ""),
                    author=item.get("author"),
                    published_utc=dt,
                    article_url=article_url,
                    image_url=item.get("image_url"),
                    description=item.get("description"),
                    provider=item.get("publisher", {}).get("name"),
                    tickers=item.get("tickers", [])
                )
                db.add(article)
                db.commit()
                db.refresh(article)
                new_articles += 1

                msg = {
                    "id": article.id,
                    "title": article.title,
                    "author": article.author,
                    "published_utc": dt.isoformat(),
                    "article_url": article.article_url,
                    "image_url": article.image_url,
                    "description": article.description,
                    "provider": article.provider,
                    "tickers": article.tickers
                }
                r.publish("news_updates", json.dumps(msg))
            if new_articles > 0:
                logger.info(f"Polled news params={query_params}. Found {new_articles} new articles.")

        if tickers_to_poll:
            for t in tickers_to_poll:
                fetch_category({"ticker": t, "limit": 5, "order": "desc"})
                
        # Update last_polled_at
        pref.last_polled_at = now
        db.commit()
        
    except Exception as e:
        logger.error(f"Error polling news: {e}")
        db.rollback()
    finally:
        db.close()


@celery_app.task(bind=True, max_retries=3)
def sync_futures_aggregates(
    self,
    symbol: str,
    exchange: str,
    timespan: str = "day",
    multiplier: int = 1,
    force: bool = False,
    from_date: str = None,
    to_date: str = None,
):
    """
    Download historical futures data from IBKR for one root symbol.
    When from_date/to_date are provided only contracts overlapping that range
    are downloaded, keeping the job fast for short backfills.
    """
    from app.services.futures_data import FuturesDataService

    db: Session = SessionLocal()
    # Always create a fresh event loop for each Celery task.
    # ForkPoolWorker reuses the same process for many tasks; reusing the
    # inherited or previous loop can leave ib_insync in a broken state.
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        logger.info(
            f"📊 Starting futures aggregate sync for {symbol} ({exchange})"
            + (f" [{from_date} → {to_date}]" if from_date else "")
        )

        result = loop.run_until_complete(
            FuturesDataService.download_full_history(
                db=db,
                symbol=symbol,
                exchange=exchange,
                timespan=timespan,
                multiplier=multiplier,
                force_refresh=force,
                from_date=from_date,
                to_date=to_date,
            )
        )
        logger.info(f"✅ Futures sync complete for {symbol}: {result}")

    except Exception as e:
        logger.error(f"❌ Error syncing futures aggregates for {symbol}: {e}")
        db.rollback()
        raise self.retry(exc=e, countdown=60)
    finally:
        # Release the IBKR clientId so the next task in this worker process
        # can connect without hitting error 326 "clientId already in use".
        from app.providers import DataProviderFactory
        ibkr = DataProviderFactory.get_or_none("ibkr")
        if ibkr:
            ibkr.disconnect()
        loop.close()
        db.close()


@celery_app.task(bind=True, max_retries=0)
def analyze_universe_quality(self, universe_id: int):
    """
    Run a full data-quality analysis for a universe and persist the result.
    """
    from app.models.universe_quality_report import UniverseQualityReport
    from app.services.data_quality import DataQualityService

    db: Session = SessionLocal()
    try:
        logger.info(f"🔍 Starting quality analysis for universe {universe_id}")

        # Mark as running
        report = db.query(UniverseQualityReport).filter(
            UniverseQualityReport.universe_id == universe_id
        ).first()
        if not report:
            report = UniverseQualityReport(universe_id=universe_id)
            db.add(report)
        report.status = "running"
        report.started_at = datetime.now(timezone.utc).replace(tzinfo=None)
        report.error_message = None
        db.commit()

        result = DataQualityService.analyze_universe(db, universe_id)

        report.status = "complete"
        report.overall_grade = result["overall_grade"]
        report.overall_score = result["overall_score"]
        report.ticker_count = result["ticker_count"]
        report.generated_at = datetime.now(timezone.utc).replace(tzinfo=None)
        report.report_data = result
        db.commit()

        logger.info(
            f"✅ Quality analysis complete for universe {universe_id}: "
            f"grade={result['overall_grade']} score={result['overall_score']}"
        )

    except Exception as e:
        logger.error(f"❌ Quality analysis failed for universe {universe_id}: {e}")
        try:
            report = db.query(UniverseQualityReport).filter(
                UniverseQualityReport.universe_id == universe_id
            ).first()
            if report:
                report.status = "error"
                report.error_message = str(e)
                db.commit()
        except Exception:
            pass
        db.rollback()
        raise
    finally:
        db.close()


@celery_app.task(bind=True, max_retries=0)
def normalize_universe_quality(self, universe_id: int, resume: bool = False, target_tickers: list = None):
    """
    Fix all data-quality issues for a universe so every ticker reaches an A grade.

    Fixes applied per ticker×timespan combo:
      1. Dedup duplicate timestamps
      2. Fill gaps detected by the quality analyser
      3. Back-fill stale tails to today

    The task is resumable: pass resume=True to continue from a previous
    interrupted run.  Progress is checkpointed after every combo.

    After all fixes are applied the quality analyser is re-run automatically
    so the report reflects the improvements.
    """
    from app.models.universe_quality_report import UniverseQualityReport
    from app.services.normalization import NormalizationService

    db: Session = SessionLocal()
    try:
        logger.info(f"🔧 Starting normalization for universe {universe_id} (resume={resume})")

        report = db.query(UniverseQualityReport).filter(
            UniverseQualityReport.universe_id == universe_id
        ).first()

        if not report or not report.report_data:
            logger.error(f"No quality report found for universe {universe_id}. Run analysis first.")
            raise RuntimeError("Quality analysis must be run before normalization.")

        # Load checkpoint for resume, or start fresh
        checkpoint = {}
        if resume and report.normalization_data:
            checkpoint = dict(report.normalization_data)
            logger.info(
                f"Resuming from checkpoint: "
                f"{len(checkpoint.get('processed_combos', []))} combos already done"
            )

        # Mark as running
        report.normalization_status = "running"
        report.normalization_data = {**checkpoint, "status": "running"}
        db.commit()

        quality_report = dict(report.report_data)

        final_data = NormalizationService.run(
            db=db,
            universe_id=universe_id,
            quality_report=quality_report,
            normalization_data=checkpoint,
            target_tickers=target_tickers,
        )

        # Save final state
        report = db.query(UniverseQualityReport).filter(
            UniverseQualityReport.universe_id == universe_id
        ).first()
        report.normalization_status = "complete"
        report.normalization_data = final_data
        db.commit()

        logger.info(
            f"✅ Normalization complete for universe {universe_id}: "
            f"{final_data.get('fixes_applied')}"
        )

        # Automatically re-run quality analysis so the modal shows updated grades
        analyze_universe_quality.delay(universe_id)

    except Exception as e:
        logger.error(f"❌ Normalization failed for universe {universe_id}: {e}")
        try:
            report = db.query(UniverseQualityReport).filter(
                UniverseQualityReport.universe_id == universe_id
            ).first()
            if report:
                report.normalization_status = "error"
                existing = dict(report.normalization_data) if report.normalization_data else {}
                existing["error"] = str(e)
                report.normalization_data = existing
                db.commit()
        except Exception:
            pass
        db.rollback()
        raise
    finally:
        db.close()


@celery_app.task(bind=True, max_retries=3)
def sync_stock_splits(self):
    """
    Celery task to fetch recent stock splits from Polygon.io.
    Fetches splits executed in the last 180 days.
    """
    db: Session = SessionLocal()
    try:
        six_months_ago = (datetime.now(timezone.utc) - timedelta(days=180)).strftime("%Y-%m-%d")
        url = "https://api.polygon.io/v3/reference/splits"
        headers = {"Authorization": f"Bearer {settings.POLYGON_API_KEY}"}
        params = {
            "execution_date.gte": six_months_ago,
            "limit": 1000,
            "sort": "execution_date",
            "order": "desc"
        }

        with httpx.Client(timeout=30.0) as client:
            response = client.get(url, headers=headers, params=params)
            if response.status_code == 429:
                logger.warning("Rate limit hit syncing splits.")
                raise self.retry(countdown=60)
            response.raise_for_status()
            data = response.json()
            
        results = data.get("results", [])
        count = 0
        
        for item in results:
            ticker = item.get("ticker")
            execution_date_str = item.get("execution_date")
            split_from = item.get("split_from")
            split_to = item.get("split_to")
            
            if not all([ticker, execution_date_str, split_from, split_to]):
                continue
                
            execution_date = datetime.strptime(execution_date_str, "%Y-%m-%d").date()
            
            # Check if exists
            existing = db.query(StockSplit).filter(
                StockSplit.ticker == ticker,
                StockSplit.execution_date == execution_date
            ).first()
            
            if not existing:
                split = StockSplit(
                    ticker=ticker,
                    execution_date=execution_date,
                    split_from=split_from,
                    split_to=split_to,
                    source="polygon",
                )
                db.add(split)
                count += 1

        db.commit()
        if count > 0:
            logger.info(f"✅ Synced {count} new stock splits.")

        from app.services.split_adjustment import SplitAdjustmentService
        adj_results = SplitAdjustmentService.apply_all_pending(db)
        applied = [r for r in adj_results if not r.get("skipped")]
        if applied:
            logger.info(f"✅ Applied split adjustments for {len(applied)} splits.")
            
    except Exception as e:
        logger.error(f"Error syncing stock splits: {e}")
        db.rollback()
        raise self.retry(exc=e, countdown=60)
    finally:
        db.close()


@celery_app.task(bind=True, max_retries=2)
def evaluate_scanner_alerts(self, scanner_event_id: int):
    """
    Evaluate all active alert rules against a newly-saved ScannerEvent.
    Dispatches notifications via all configured channels for any matching rules.
    For rules with auto_trade=True, queues execute_auto_trade as a follow-up task.
    Called automatically when a new ScannerEvent is created.
    """
    from app.models.scanner_event import ScannerEvent
    from app.services.alert_service import AlertRuleService, NotificationDispatcher

    db: Session = SessionLocal()
    try:
        event = db.query(ScannerEvent).filter(ScannerEvent.id == scanner_event_id).first()
        if not event:
            logger.warning(f"evaluate_scanner_alerts: ScannerEvent id={scanner_event_id} not found.")
            return

        matching_rules = AlertRuleService.get_matching_rules(event, db)
        if not matching_rules:
            return

        logger.info(
            f"🔔 {len(matching_rules)} alert rule(s) matched "
            f"event={scanner_event_id} ticker={event.ticker} type={event.scanner_type}"
        )

        for rule in matching_rules:
            # Notification dispatch
            try:
                NotificationDispatcher.dispatch(rule, event, db)
            except Exception as exc:
                logger.error(f"❌ Dispatch failed for rule {rule.id}: {exc}")

            # Auto-trade: queue a separate task so notification failures
            # never block order placement, and vice versa.
            if rule.auto_trade and rule.trading_strategy_id:
                execute_auto_trade.delay(
                    rule_id=rule.id,
                    scanner_event_id=scanner_event_id,
                )
                logger.info(
                    f"🤖 Auto-trade queued for rule={rule.id} "
                    f"strategy={rule.trading_strategy_id} ticker={event.ticker}"
                )

    except Exception as e:
        logger.error(f"❌ evaluate_scanner_alerts failed for event {scanner_event_id}: {e}")
        db.rollback()
        raise self.retry(exc=e, countdown=30)
    finally:
        db.close()


@celery_app.task(bind=True, max_retries=1)
def execute_auto_trade(self, rule_id: int, scanner_event_id: int):
    """
    Execute an automated trade for a matched alert rule.

    Runs AutoTradeExecutor.maybe_execute() which handles all guards,
    position sizing, and IBKR bracket-order placement.

    max_retries=1: a single retry on transient failure (e.g. DB lock).
    On IBKR errors the executor sets status='error' and does NOT retry —
    better to miss a trade than to double-enter.
    """
    from app.models.alert_rule import AlertRule
    from app.models.scanner_event import ScannerEvent
    from app.services.auto_trade_service import auto_trade_executor

    db: Session = SessionLocal()
    try:
        rule = db.query(AlertRule).filter(AlertRule.id == rule_id).first()
        event = db.query(ScannerEvent).filter(ScannerEvent.id == scanner_event_id).first()

        if not rule:
            logger.warning(f"execute_auto_trade: AlertRule id={rule_id} not found.")
            return
        if not event:
            logger.warning(f"execute_auto_trade: ScannerEvent id={scanner_event_id} not found.")
            return

        order = auto_trade_executor.maybe_execute(rule, event, db)
        if order:
            logger.info(
                f"✅ execute_auto_trade: order id={order.id} status={order.status} "
                f"ticker={event.ticker}"
            )
        else:
            logger.debug(
                f"execute_auto_trade: no order created for rule={rule_id} "
                f"event={scanner_event_id}"
            )

    except Exception as exc:
        logger.error(f"❌ execute_auto_trade failed rule={rule_id} event={scanner_event_id}: {exc}")
        db.rollback()
        raise self.retry(exc=exc, countdown=15)
    finally:
        db.close()


@celery_app.task(bind=True, max_retries=1)
def submit_approved_order(self, order_id: int):
    """
    Submit a manually-approved AutoTradeOrder to IBKR.

    Called by the approve_order endpoint instead of re-queuing execute_auto_trade
    (which would hit the idempotency guard and silently skip the order).
    Reads all sizing values from the stored order — no recalculation.
    """
    from app.models.auto_trade_order import AutoTradeOrder
    from app.services.auto_trade_service import auto_trade_executor

    db: Session = SessionLocal()
    try:
        order = db.query(AutoTradeOrder).filter(AutoTradeOrder.id == order_id).first()
        if not order:
            logger.warning(f"submit_approved_order: order {order_id} not found")
            return
        if order.status != "pending":
            logger.warning(
                f"submit_approved_order: order {order_id} has status='{order.status}', "
                f"expected 'pending' — skipping to avoid double-submit"
            )
            return

        auto_trade_executor.submit_existing_order(order, db)
        logger.info(
            f"✅ submit_approved_order: order {order_id} submitted, status={order.status}"
        )
    except Exception as exc:
        logger.error(f"❌ submit_approved_order failed order={order_id}: {exc}")
        db.rollback()
        raise self.retry(exc=exc, countdown=15)
    finally:
        db.close()


@celery_app.task(bind=True, max_retries=0)
def poll_auto_trade_fills(self):
    """
    Poll IBKR for fill updates on submitted/open AutoTradeOrders.

    Runs every minute via Celery Beat during market hours.
    For each open order:
      - "submitted" + entry filled → status=open, create Trade record
      - "open" + exit order filled → status=closed, update Trade record
      - Order disappeared from IBKR open list → status=rejected

    Paper-mode orders simulate an instant fill at trigger_price.
    """
    from app.models.auto_trade_order import AutoTradeOrder
    from app.models.trade import Trade, TradeExecution

    db: Session = SessionLocal()
    try:
        pending_orders = (
            db.query(AutoTradeOrder)
            .filter(AutoTradeOrder.status.in_(["submitted", "open"]))
            .all()
        )
        if not pending_orders:
            return

        logger.info(f"poll_auto_trade_fills: checking {len(pending_orders)} open order(s)")

        # ── Paper mode: simulate fill at trigger price ───────────────────
        paper_orders = [o for o in pending_orders if o.is_paper]
        live_orders  = [o for o in pending_orders if not o.is_paper]

        now = datetime.now(timezone.utc).replace(tzinfo=None)

        for order in paper_orders:
            if order.status == "submitted":
                fill_price = float(order.trigger_price or order.entry_price_target or 0)
                _record_entry_fill(order, fill_price, now, db)
            elif order.status == "open":
                _simulate_paper_exit(order, db, now)

        # ── Live mode: query IBKR ────────────────────────────────────────
        if live_orders:
            _poll_live_orders(live_orders, db, now)

    except Exception as exc:
        logger.error(f"❌ poll_auto_trade_fills error: {exc}")
        db.rollback()
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Fill helpers (called by poll_auto_trade_fills)
# ---------------------------------------------------------------------------

def _check_entry_slippage(
    order: "AutoTradeOrder",
    fill_price: float,
    now: "datetime",
    db: "Session",
) -> None:
    """
    Enforce max_slippage_pct: reject the order if fill deviated too far from
    entry_price_target; otherwise delegate to _record_entry_fill.

    Slippage is computed as abs deviation regardless of side, because any
    large deviation from the intended entry invalidates the trade's risk model.
    """
    strategy = order.trading_strategy
    target = order.entry_price_target

    if strategy is not None and target is not None:
        target_f = float(target)
        if target_f > 0:
            slippage_pct = abs(fill_price - target_f) / target_f * 100
            max_slip = float(strategy.max_slippage_pct)
            if slippage_pct > max_slip:
                order.status = "rejected"
                order.rejection_reason = (
                    f"Slippage {slippage_pct:.3f}% exceeded limit {max_slip}% "
                    f"(fill={fill_price}, target={target_f})"
                )
                db.commit()
                logger.warning(
                    f"_check_entry_slippage: order {order.id} rejected — {order.rejection_reason}"
                )
                return

    _record_entry_fill(order, fill_price, now, db)


def _record_entry_fill(
    order: "AutoTradeOrder",
    fill_price: float,
    now: "datetime",
    db: "Session",
) -> None:
    """Mark an order as open (entry filled) and create the journal Trade record."""
    from app.models.trade import Trade, TradeExecution

    order.fill_price = fill_price
    order.filled_at = now
    order.status = "open"

    # Create journal Trade
    exec_side = "buy" if order.side == "long" else "sshort"
    trade = Trade(
        symbol=order.symbol,
        status="open",
        side=order.side,
        open_date=now,
        quantity=order.quantity,
        avg_entry_price=fill_price,
        notes=f"Auto-trade order id={order.id} strategy={order.trading_strategy_id}",
    )
    db.add(trade)
    db.flush()  # get trade.id

    execution = TradeExecution(
        trade_id=trade.id,
        timestamp=now,
        side=exec_side,
        price=fill_price,
        quantity=order.quantity,
        external_id=f"auto_trade_order_{order.id}",
    )
    db.add(execution)
    order.trade_id = trade.id
    db.commit()
    logger.info(
        f"poll_auto_trade_fills: entry fill recorded — "
        f"order={order.id} trade={trade.id} price={fill_price}"
    )


def _record_exit_fill(
    order: "AutoTradeOrder",
    exit_price: float,
    exit_reason: str,
    now: "datetime",
    db: "Session",
) -> None:
    """Mark an order closed and update the journal Trade."""
    from app.models.trade import Trade, TradeExecution

    order.exit_price = exit_price
    order.exited_at = now
    order.exit_reason = exit_reason
    order.status = "closed"

    if order.trade_id:
        trade = db.query(Trade).filter(Trade.id == order.trade_id).first()
        if trade:
            exec_side = "sell" if order.side == "long" else "scover"
            execution = TradeExecution(
                trade_id=trade.id,
                timestamp=now,
                side=exec_side,
                price=exit_price,
                quantity=order.quantity,
                external_id=f"auto_trade_exit_{order.id}",
            )
            db.add(execution)

            trade.status = "closed"
            trade.close_date = now
            trade.avg_exit_price = exit_price

            # Compute P&L
            if trade.avg_entry_price and trade.quantity:
                entry = float(trade.avg_entry_price)
                qty = float(trade.quantity)
                if order.side == "long":
                    pnl = (exit_price - entry) * qty
                else:
                    pnl = (entry - exit_price) * qty
                trade.gross_pnl = round(pnl, 2)
                trade.net_pnl = round(pnl - float(trade.commissions or 0), 2)
                if entry > 0:
                    trade.return_pct = round(
                        (exit_price - entry) / entry * 100 * (1 if order.side == "long" else -1),
                        2,
                    )

    db.commit()
    logger.info(
        f"poll_auto_trade_fills: exit fill recorded — "
        f"order={order.id} price={exit_price} reason={exit_reason}"
    )


def _poll_live_orders(
    orders: list,
    db: "Session",
    now: "datetime",
) -> None:
    """
    Query IBKR for status of live AutoTradeOrders and process any fills.
    Batches all orders into a single IBKR connection to minimise clientId churn.
    """
    from app.providers.ibkr_orders import IBKROrderManager

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        manager = IBKROrderManager()
        open_orders = loop.run_until_complete(manager.get_open_orders())
        open_ids = {o.order_id for o in open_orders}

        for order in orders:
            try:
                parent_id = int(order.broker_order_id) if order.broker_order_id else None
                stop_id   = int(order.broker_stop_id)   if order.broker_stop_id   else None
                target_id = int(order.broker_target_id) if order.broker_target_id else None

                if order.status == "submitted":
                    # Check if entry order is filled (no longer in open orders)
                    if parent_id and parent_id not in open_ids:
                        # Fetch fill price from completed orders
                        status = loop.run_until_complete(
                            manager.get_order_status(parent_id)
                        )
                        if status and status.get("filled", 0) > 0:
                            fill_price = float(status["avg_fill_price"])
                            _check_entry_slippage(order, fill_price, now, db)
                        elif status is None:
                            # Order vanished — likely rejected
                            order.status = "rejected"
                            order.rejection_reason = "Order not found in IBKR after submission"
                            db.commit()

                elif order.status == "open":
                    # Check if stop or target child is filled
                    for child_id, reason in (
                        (stop_id, "stop"),
                        (target_id, "target"),
                    ):
                        if child_id and child_id not in open_ids:
                            status = loop.run_until_complete(
                                manager.get_order_status(child_id)
                            )
                            if status and status.get("filled", 0) > 0:
                                exit_price = float(status["avg_fill_price"])
                                _record_exit_fill(order, exit_price, reason, now, db)
                                break

            except Exception as exc:
                logger.error(
                    f"poll_auto_trade_fills: error processing order {order.id}: {exc}"
                )

    except Exception as exc:
        logger.error(f"_poll_live_orders: IBKR connection error: {exc}")
    finally:
        loop.close()


def _simulate_paper_exit(
    order: "AutoTradeOrder",
    db: "Session",
    now: "datetime",
) -> None:
    from app.providers import DataProviderFactory

    provider = DataProviderFactory.get_or_none("massive")
    if not provider:
        return

    price = provider.get_snapshot_price(order.symbol)
    if price is None:
        return

    stop   = float(order.calculated_stop)
    target = float(order.calculated_target)

    if order.side == "long":
        if price >= target:
            _record_exit_fill(order, price, "target", now, db)
        elif price <= stop:
            _record_exit_fill(order, price, "stop", now, db)
    else:  # short
        if price <= target:
            _record_exit_fill(order, price, "target", now, db)
        elif price >= stop:
            _record_exit_fill(order, price, "stop", now, db)


# ---------------------------------------------------------------------------
# Date-range scan task
# ---------------------------------------------------------------------------

@celery_app.task
def run_range_scan(
    ticker: str,
    scanner_types: list,
    start_date_str: str,
    end_date_str: str,
    fetch_missing_data: bool,
):
    """Background task: run selected scanners over a date range for one ticker."""
    import asyncio
    from datetime import date, timedelta
    from app.services.scanner import ScannerService
    from app.services.liquidity_hunt import run_liquidity_hunt_scan_for_date as _lh_scan

    task_id = run_range_scan.request.id
    r = redis.Redis.from_url(settings.REDIS_URL, decode_responses=True)
    channel = f"scan_task:{task_id}"

    from datetime import datetime as _dt
    r.set(
        f"scan:{ticker}:range",
        json.dumps({"task_ids": [task_id], "started_at": _dt.utcnow().isoformat()}),
        ex=14400,
    )

    start = date.fromisoformat(start_date_str)
    end = date.fromisoformat(end_date_str)

    trading_days = [
        start + timedelta(days=i)
        for i in range((end - start).days + 1)
        if (start + timedelta(days=i)).weekday() < 5
    ]

    total = len(trading_days) * len(scanner_types)
    events_detected = 0
    done = 0

    db: Session = SessionLocal()
    try:
        if fetch_missing_data:
            # Daily bars: need 90-day lookback before start for rolling metrics
            daily_period_days = (date.today() - (start - timedelta(days=90))).days
            StockDataService.refresh_stock_data(
                db, ticker, timespan='day', period=f"{daily_period_days}d"
            )
            # Minute bars: cover just the requested range
            minute_period_days = (date.today() - start).days + 5
            StockDataService.refresh_stock_data(
                db, ticker, timespan='minute', period=f"{minute_period_days}d"
            )

        scanner_map = {
            "pre_market_volume_spike": ScannerService.run_pre_market_scan_for_date,
            "liquidity_hunt": _lh_scan,
            "liquidity_hunt_pre": _lh_scan,
            "liquidity_hunt_post": _lh_scan,
            "oversold_bounce": ScannerService.run_oversold_bounce_scan_for_date,
        }

        async def _scan_day(day):
            results = []
            for st in scanner_types:
                fn = scanner_map.get(st)
                if fn:
                    results.extend(await fn(ticker, day, db))
            return results

        for day in trading_days:
            day_results = asyncio.run(_scan_day(day))
            events_detected += len(day_results)
            done += len(scanner_types)
            r.publish(channel, json.dumps({
                "status": "progress",
                "day": day.isoformat(),
                "done": done,
                "total": total,
            }))

        r.publish(channel, json.dumps({
            "status": "completed",
            "events_detected": events_detected,
        }))
        logger.info(f"run_range_scan {task_id}: completed, {events_detected} events")

    except Exception as e:
        logger.error(f"run_range_scan {task_id} failed: {e}")
        r.publish(channel, json.dumps({
            "status": "failed",
            "error": str(e),
        }))
    finally:
        r.delete(f"scan:{ticker}:range")
        db.close()


@celery_app.task(bind=True, max_retries=1)
def run_liquidity_hunt_scheduled(self):
    """
    Nightly 02:00 UTC task: run liquidity_hunt_pre and liquidity_hunt_post
    for today's date over all active ScannerConfig universes of type 'liquidity_hunt'.
    """
    from app.utils.session import get_market_today
    from app.services.liquidity_hunt import run_liquidity_hunt_scan
    from app.models.scanner_config import ScannerConfig

    db: Session = SessionLocal()
    try:
        event_date = get_market_today()
        configs = (
            db.query(ScannerConfig)
            .filter(
                ScannerConfig.scanner_type == "liquidity_hunt",
                ScannerConfig.is_active.is_(True),
            )
            .all()
        )

        for cfg in configs:
            universe_id = cfg.parameters.get("universe_id")
            if not universe_id:
                logger.warning("liquidity_hunt ScannerConfig %s has no universe_id", cfg.id)
                continue

            tickers = [
                ms.ticker
                for ms in db.query(MonitoredStock).filter(
                    MonitoredStock.universe_id == universe_id,
                    MonitoredStock.is_active.is_(True),
                ).all()
            ]
            if not tickers:
                continue

            results = asyncio.run(
                run_liquidity_hunt_scan(tickers, db, start_date=event_date, end_date=event_date)
            )
            logger.info(
                "liquidity_hunt scheduled scan for universe %s on %s: %d events",
                universe_id, event_date, len(results),
            )
    except Exception as exc:
        logger.exception("run_liquidity_hunt_scheduled failed: %s", exc)
        raise self.retry(exc=exc)
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Async universe scan — drives a (universe, scanner_type) over a date range
# and publishes per-day progress to Redis.
# ---------------------------------------------------------------------------

@celery_app.task(bind=True, max_retries=0)
def run_universe_scan(
    self,
    scan_id: str,
    scanner_type: str,
    universe_id: int,
    start_date_iso: str,
    end_date_iso: str,
):
    """Run a scanner across (universe, [start_date..end_date]) with progress reporting.

    Per-day granularity: invokes the relevant scanner once per trading day with
    every ticker in the universe. After each day we update the Redis state key
    (so /runs/{id}/status reflects current progress) and publish a message on
    the pub/sub channel (so the WS reattach path receives it). The state key is
    deleted in ``finally``; the system tasks aggregator at /api/system/ws/tasks
    discovers active scans by scanning ``universe:*:scan:*``.
    """
    from datetime import date as _date, timedelta as _td
    from app.models.scanner_run import ScannerRun
    import app.services.pre_market_scan  # noqa: F401 — triggers self-registration
    import app.services.oversold_bounce_scan  # noqa: F401
    import app.services.liquidity_hunt  # noqa: F401
    import app.services.scan_orchestrator as _orchestrator

    task_id = self.request.id
    r = redis.Redis.from_url(settings.REDIS_URL, decode_responses=True)
    channel = f"scan_task:{task_id}"
    state_key = f"universe:{universe_id}:scan:{scanner_type}"
    cancel_key = f"scan_cancel:{scan_id}"

    def _cancelled() -> bool:
        return r.exists(cancel_key) > 0

    def _publish(payload: dict) -> None:
        try:
            r.publish(channel, json.dumps(payload, default=str))
        except Exception:
            logger.exception("scan_task publish failed")

    db: Session = SessionLocal()
    started_at = datetime.now(timezone.utc).replace(tzinfo=None)
    try:
        run = db.query(ScannerRun).filter(ScannerRun.uuid == scan_id).first()
        if run is None:
            logger.error("run_universe_scan: ScannerRun %s not found", scan_id)
            return

        tickers = [
            ms.ticker
            for ms in db.query(MonitoredStock).filter(
                MonitoredStock.universe_id == universe_id,
                MonitoredStock.is_active.is_(True),
            ).all()
        ]
        if not tickers:
            run.status = "failed"
            run.error_message = "Universe has no active tickers"
            db.commit()
            _publish({"type": "failed", "error": run.error_message})
            return

        start = _date.fromisoformat(start_date_iso)
        end = _date.fromisoformat(end_date_iso)
        trading_days = [
            start + _td(days=i)
            for i in range((end - start).days + 1)
            if (start + _td(days=i)).weekday() < 5
        ]

        run.status = "running"
        run.stocks_scanned = len(tickers)
        run.scan_start_date = start
        run.scan_end_date = end
        db.commit()

        cum = {
            "evaluated": 0, "no_data": 0, "no_prior_close": 0, "no_baseline": 0,
            "errors": 0, "fired_pre": 0, "fired_post": 0,
        }
        events_total = 0

        def _write_state(progress_extra: dict | None = None):
            r.set(state_key, json.dumps({
                "task_ids": [task_id],
                "scan_id": scan_id,
                "scanner_type": scanner_type,
                "universe_id": universe_id,
                "start_date": start.isoformat(),
                "end_date": end.isoformat(),
                "started_at": started_at.replace(tzinfo=timezone.utc).isoformat(),
                "tickers": len(tickers),
                "total_days": len(trading_days),
                "events_detected": events_total,
                **cum,
                **(progress_extra or {}),
            }), ex=14400)

        _write_state({"day_index": 0})
        _publish({
            "type": "started",
            "scan_id": scan_id,
            "task_id": task_id,
            "total_days": len(trading_days),
            "total_tickers": len(tickers),
            "estimated_pairs": len(tickers) * len(trading_days),
            "scanner_type": scanner_type,
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
        })

        for i, day in enumerate(trading_days, start=1):
            if _cancelled():
                run.status = "cancelled"
                run.events_detected = events_total
                run.execution_time_ms = int(
                    (datetime.now(timezone.utc).replace(tzinfo=None) - started_at).total_seconds() * 1000
                )
                db.commit()
                _publish({
                    "type": "cancelled",
                    "evaluated_so_far": cum["evaluated"],
                    "events_detected_so_far": events_total,
                })
                return

            _publish({
                "type": "day_started",
                "date": day.isoformat(),
                "day_index": i,
                "total_days": len(trading_days),
            })

            try:
                day_events = asyncio.run(
                    _orchestrator.run(scanner_type, tickers, db=db, event_date=day)
                )
            except Exception as e:
                cum["errors"] += 1
                logger.exception("run_universe_scan: day %s failed", day)
                _publish({"type": "day_error", "date": day.isoformat(), "error": str(e)})
                continue

            events_total += len(day_events)

            run.events_detected = events_total
            db.commit()

            _write_state({"day_index": i})
            _publish({
                "type": "day_completed",
                "date": day.isoformat(),
                "day_index": i,
                "total_days": len(trading_days),
                "events": len(day_events),
                "events_detected": events_total,
                **cum,
            })

        run.status = "completed"
        run.events_detected = events_total
        run.execution_time_ms = int(
            (datetime.now(timezone.utc).replace(tzinfo=None) - started_at).total_seconds() * 1000
        )
        db.commit()
        _publish({
            "type": "completed",
            "events_detected": events_total,
            "diagnostics": {
                "tickers": len(tickers),
                "days": len(trading_days),
                "start_date": start.isoformat(),
                "end_date": end.isoformat(),
                **cum,
            },
            "execution_time_ms": run.execution_time_ms,
        })
        logger.info(
            "run_universe_scan %s completed: type=%s universe=%s days=%d events=%d",
            scan_id, scanner_type, universe_id, len(trading_days), events_total,
        )

    except Exception as exc:
        logger.exception("run_universe_scan %s failed", scan_id)
        try:
            run = db.query(ScannerRun).filter(ScannerRun.uuid == scan_id).first()
            if run is not None:
                run.status = "failed"
                run.error_message = str(exc)
                run.execution_time_ms = int(
                    (datetime.now(timezone.utc).replace(tzinfo=None) - started_at).total_seconds() * 1000
                )
                db.commit()
        except Exception:
            db.rollback()
        _publish({"type": "failed", "error": str(exc)})
    finally:
        try:
            r.delete(state_key)
            r.delete(cancel_key)
        except Exception:
            pass
        db.close()


@celery_app.task(bind=True, max_retries=1, name='app.tasks.analyze_signal_features')
def analyze_signal_features(self, scanner_type: str | None = None, k: int = 6):
    import pandas as pd
    from app.models.scanner_event import ScannerEvent
    from app.models.signal_analysis_run import SignalAnalysisRun
    from app.models.signal_cluster import SignalCluster
    from app.models.scanner_outcome_summary import ScannerOutcomeSummary
    from app.models.scanner_outcome_snapshot import ScannerOutcomeSnapshot
    from app.services.statistical_discovery import StatisticalDiscoveryService

    db: Session = SessionLocal()
    try:
        run = SignalAnalysisRun(
            status="running",
            scanner_type=scanner_type,
            celery_task_id=self.request.id,
        )
        db.add(run)
        db.commit()
        db.refresh(run)

        query = (
            db.query(
                ScannerEvent.id.label("event_id"),
                ScannerEvent.scanner_type,
                ScannerEvent.indicators,
                ScannerOutcomeSnapshot.interval_key,
                ScannerOutcomeSnapshot.pct_change,
            )
            .join(
                ScannerOutcomeSummary,
                ScannerOutcomeSummary.scanner_event_id == ScannerEvent.id,
            )
            .join(
                ScannerOutcomeSnapshot,
                ScannerOutcomeSnapshot.scanner_event_id == ScannerEvent.id,
            )
            .filter(
                ScannerOutcomeSummary.is_complete.is_(True),
                ScannerOutcomeSnapshot.status == "captured",
            )
        )
        if scanner_type:
            query = query.filter(ScannerEvent.scanner_type == scanner_type)

        rows = query.all()

        unique_event_ids = {r.event_id for r in rows}
        if len(unique_event_ids) < 500:
            run.status = "failed"
            run.error_message = f"Insufficient data (n={len(unique_event_ids)} events, min=500)"
            db.commit()
            logger.info("analyze_signal_features: insufficient data (%d events)", len(unique_event_ids))
            return

        flat_rows = []
        for r in rows:
            indicators = r.indicators or {}
            row = {
                "event_id": r.event_id,
                "interval_key": r.interval_key,
                "pct_change": float(r.pct_change) if r.pct_change is not None else None,
            }
            for k_feat, v in indicators.items():
                try:
                    row[k_feat] = float(v)
                except (TypeError, ValueError):
                    row[k_feat] = None
            flat_rows.append(row)

        raw_df = pd.DataFrame(flat_rows)
        svc = StatisticalDiscoveryService()
        df = svc.build_feature_matrix(raw_df)

        correlation_matrix = svc.compute_correlations(df)
        run.correlation_matrix = correlation_matrix

        feature_weights = svc.compute_shap_weights(df)
        run.feature_weights = feature_weights

        cluster_labels, centroids = svc.run_kmeans(df, k=k)
        conditional_stats = svc.compute_conditional_stats(df, cluster_labels)

        feature_cols = [
            c for c in df.columns
            if c not in {"event_id", "interval_key", "pct_change"}
        ]
        global_mean = {feat: float(df[feat].mean()) for feat in feature_cols}

        cluster_id_map: dict[int, int] = {}
        for cluster_idx, centroid in enumerate(centroids):
            label = svc.generate_label(centroid, global_mean)
            event_count = sum(1 for v in cluster_labels.values() if v == cluster_idx)
            cluster = SignalCluster(
                analysis_run_id=run.id,
                cluster_index=cluster_idx,
                label=label,
                centroid=centroid,
                return_profile=conditional_stats.get(cluster_idx, {}),
                event_count=event_count,
            )
            db.add(cluster)
            db.flush()
            cluster_id_map[cluster_idx] = cluster.id

        for event_id, cluster_idx in cluster_labels.items():
            db.query(ScannerEvent).filter(ScannerEvent.id == event_id).update(
                {"signal_cluster_id": cluster_id_map[cluster_idx]},
                synchronize_session=False,
            )

        run.status = "completed"
        run.event_count = len(unique_event_ids)
        run.completed_at = datetime.now(timezone.utc).replace(tzinfo=None)
        db.commit()
        logger.info("analyze_signal_features: completed (events=%d)", len(unique_event_ids))

    except Exception as exc:
        logger.exception("analyze_signal_features failed: %s", exc)
        try:
            run.status = "failed"
            run.error_message = str(exc)
            db.commit()
        except Exception:
            pass
        raise
    finally:
        db.close()
