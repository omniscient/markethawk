import asyncio
import json
import logging
import time as _time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import httpx
import redis
from sqlalchemy.orm import Session

from app.core.celery_app import celery_app
from app.core.config import settings
from app.core.database import SessionLocal
from app.core.metrics import celery_task_duration_seconds, celery_tasks_total
from app.models.monitored_stock import MonitoredStock
from app.models.news_article import NewsArticle
from app.models.news_preference import NewsPreference
from app.models.stock_aggregate import StockAggregate
from app.models.stock_split import StockSplit
from app.models.ticker_reference import TickerReference
from app.services.stock_data import StockDataService

logger = logging.getLogger(__name__)


@celery_app.task(bind=True, max_retries=3, name="app.tasks.sync_tickers_batch")
def sync_tickers_batch(self, next_url: str = None, delay_seconds: float = 15.0):
    """
    Celery task to sync tickers in batches using strict rate limiting (recursive chaining).
    Each execution processes one page and schedules the next page 15 seconds later.
    """
    _task_name = "sync_tickers_batch"
    _start = _time.monotonic()
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
                stmt = (
                    db.query(TickerReference)
                    .filter(TickerReference.ticker == ticker)
                    .first()
                )
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
            logger.info(
                f"⏭️ Next page found. Scheduling next batch in {delay_seconds} seconds..."
            )
            # Schedule next task 15 seconds from now
            sync_tickers_batch.apply_async(
                args=[next_page],
                kwargs={"delay_seconds": delay_seconds},
                countdown=delay_seconds,
            )
        else:
            logger.info("🎉 Sync Complete! No more pages.")
        celery_tasks_total.labels(task_name=_task_name, status="success").inc()

    except Exception as e:
        logger.error(f"❌ Error in sync_tickers_batch: {str(e)}")
        celery_tasks_total.labels(task_name=_task_name, status="failure").inc()
        db.rollback()
        raise e
    finally:
        celery_task_duration_seconds.labels(task_name=_task_name).observe(
            _time.monotonic() - _start
        )
        db.close()


@celery_app.task(bind=True, max_retries=3, name="app.tasks.sync_ticker_details")
def sync_ticker_details(self, ticker: str, delay_seconds: float = 15.0):
    """
    Slow crawler task to fetch details for ONE ticker.
    Reschedules itself for the NEXT ticker after `delay_seconds`.
    """
    db: Session = SessionLocal()
    try:
        logger.info(
            f"🔍 Fetching details for ticker: {ticker} (Delay: {delay_seconds}s)"
        )

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
                stmt = (
                    db.query(TickerReference)
                    .filter(TickerReference.ticker == ticker)
                    .first()
                )
                if stmt:
                    stmt.description = results.get("description")
                    stmt.market_cap = results.get("market_cap")
                    stmt.primary_exchange = results.get("primary_exchange")
                    stmt.list_date = results.get("list_date")
                    stmt.total_employees = results.get("total_employees")
                    stmt.share_class_shares_outstanding = results.get(
                        "share_class_shares_outstanding"
                    )
                    stmt.weighted_shares_outstanding = results.get(
                        "weighted_shares_outstanding"
                    )
                    stmt.sic_code = results.get("sic_code")
                    stmt.sic_description = results.get("sic_description")
                    # Map SIC description to Industry as a fallback/primary
                    stmt.industry = results.get("sic_description")
                    # Clear out the incorrect 'CS' sector values if present
                    if stmt.sector == "CS":
                        stmt.sector = None

                    stmt.homepage_url = results.get("homepage_url")
                    stmt.last_details_update = datetime.now(timezone.utc).replace(
                        tzinfo=None
                    )

                    db.commit()
                    logger.info(f"✅ Updated details for {ticker}")

        # 3. Schedule Next Ticker (Recursive Chain)
        # Find next ticker that hasn't been updated recently (or at all)
        next_ticker = (
            db.query(TickerReference.ticker)
            .filter(
                (TickerReference.last_details_update == None)
                | (
                    TickerReference.last_details_update
                    < datetime.now(timezone.utc).date()
                )
            )
            .order_by(TickerReference.last_updated.desc())  # Prioritize recently active
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

            logger.info(
                f"⏭️ Scheduling details sync for {next_ticker.ticker} in {delay_seconds} seconds..."
            )
            sync_ticker_details.apply_async(
                args=[next_ticker.ticker],
                kwargs={"delay_seconds": delay_seconds},
                countdown=delay_seconds,
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


@celery_app.task(bind=True, name="app.tasks.start_details_crawl")
def start_details_crawl(self, delay_seconds: float = 15.0, resync: bool = False):
    """
    Kicks off the details crawler if it's not running.
    """
    db: Session = SessionLocal()
    try:
        if resync:
            logger.info(
                "♻️ Force Resync requested. Resetting crawl status for all tickers..."
            )
            db.query(TickerReference).update(
                {TickerReference.last_details_update: None}
            )
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
                (TickerReference.last_details_update == None)
                | (
                    TickerReference.last_details_update
                    < datetime.now(timezone.utc).date()
                )
            )
            .order_by(TickerReference.last_updated.desc())
            .first()
        )

        if next_ticker:
            logger.info(
                f"🚀 Starting Details Crawler with {next_ticker.ticker} (Delay: {delay_seconds}s)"
            )
            sync_ticker_details.delay(
                ticker=next_ticker.ticker, delay_seconds=delay_seconds
            )
        else:
            logger.info("No tickers need detail updates.")

    finally:
        db.close()


@celery_app.task(bind=True, max_retries=3, name="app.tasks.sync_stock_aggregates")
def sync_stock_aggregates(
    self,
    ticker: str,
    from_date: str,
    to_date: str,
    multiplier: int = 1,
    timespan: str = "minute",
    adjusted: bool = True,
    sort: str = "asc",
    limit: int = 50000,
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
            StockAggregate.timestamp < end_dt,
        ).delete(synchronize_session=False)

        # 3. Insert new data
        from app.utils.session import classify_session

        new_records = []
        for agg in aggs:
            ts_utc = agg["timestamp"]
            is_pre_market, is_after_market = classify_session(ts_utc)

            record = StockAggregate(
                ticker=ticker,
                timestamp=ts_utc.replace(tzinfo=None),  # Store naive UTC in DB
                multiplier=multiplier,
                timespan=timespan,
                open=agg["open"],
                high=agg["high"],
                low=agg["low"],
                close=agg["close"],
                volume=agg["volume"],
                vwap=agg["vwap"],
                transactions=agg["transactions"],
                is_pre_market=is_pre_market,
                is_after_market=is_after_market,
                provider="polygon",
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


@celery_app.task(bind=True, max_retries=3, name="app.tasks.poll_massive_news")
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
            db_tickers = (
                db.query(MonitoredStock.ticker)
                .filter(MonitoredStock.universe_id.in_(pref.tracked_universes))
                .all()
            )
            for (t,) in db_tickers:
                tickers_to_poll.add(t)

        r = redis.from_url(settings.REDIS_URL, decode_responses=True)

        def fetch_category(query_params: dict):
            url = "https://api.polygon.io/v2/reference/news"
            headers = {"Authorization": f"Bearer {settings.POLYGON_API_KEY}"}

            # Ensure we don't fetch archaic news
            seven_days_ago = datetime.now(timezone.utc).replace(
                tzinfo=None
            ) - timedelta(days=7)
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
            for item in reversed(results):  # Process oldest to newest
                article_url = item.get("article_url")
                if (
                    db.query(NewsArticle)
                    .filter(NewsArticle.article_url == article_url)
                    .first()
                ):
                    continue

                pub_utc = item.get("published_utc")
                dt = (
                    datetime.strptime(
                        pub_utc.replace("Z", "+0000"), "%Y-%m-%dT%H:%M:%S%z"
                    )
                    if pub_utc
                    else datetime.now(timezone.utc)
                )
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
                    tickers=item.get("tickers", []),
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
                    "tickers": article.tickers,
                }
                r.publish("news_updates", json.dumps(msg))
            if new_articles > 0:
                logger.info(
                    f"Polled news params={query_params}. Found {new_articles} new articles."
                )

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


@celery_app.task(bind=True, max_retries=3, name="app.tasks.sync_futures_aggregates")
def sync_futures_aggregates(  # pragma: no cover
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
            FuturesDataService._download_full_history(
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


@celery_app.task(bind=True, max_retries=3, name="app.tasks.sync_stock_splits")
def sync_stock_splits(self):
    """
    Celery task to fetch recent stock splits from Polygon.io.
    Fetches splits executed in the last 180 days.
    """
    db: Session = SessionLocal()
    try:
        six_months_ago = (datetime.now(timezone.utc) - timedelta(days=180)).strftime(
            "%Y-%m-%d"
        )
        url = "https://api.polygon.io/v3/reference/splits"
        headers = {"Authorization": f"Bearer {settings.POLYGON_API_KEY}"}
        params = {
            "execution_date.gte": six_months_ago,
            "limit": 1000,
            "sort": "execution_date",
            "order": "desc",
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
            existing = (
                db.query(StockSplit)
                .filter(
                    StockSplit.ticker == ticker,
                    StockSplit.execution_date == execution_date,
                )
                .first()
            )

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


@celery_app.task(bind=True, max_retries=2, name="app.tasks.trigger_tweet_monitor")
def trigger_tweet_monitor(self):
    """HTTP trigger for the tweet-monitor microservice (POST /poll)."""
    try:
        with httpx.Client(timeout=30.0) as client:
            response = client.post("http://tweet-monitor:8000/poll")
            response.raise_for_status()
            return response.json()
    except Exception as exc:
        logger.warning(f"Tweet monitor poll failed: {exc}")
        raise self.retry(exc=exc, countdown=10)
