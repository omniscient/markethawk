"""
Tweet-monitor FastAPI application.

Endpoints:
  POST /poll              — Triggered by Celery beat every 45s
  GET  /health            — Browser + DB + Redis liveness
  GET  /status            — Operational metrics
  GET  /accounts          — List monitored accounts
  POST /accounts          — Create/update a monitored account
  POST /poll/{account_id} — Manual single-account trigger (debugging)
"""
import asyncio
import logging
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any

import redis as redis_lib
from fastapi import FastAPI, HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.browser import browser_manager
from app.classifier import TweetClassifier
from app.config import settings
from app.extractor import PriceLevelExtractor, TickerExtractor
from app.health import check_health
from app.models import MonitoredAccount, TweetSignal
from app.pipeline import SignalPipeline
from app.schemas import (
    AccountCreate, AccountStatus, HealthResponse, PollSummary, StatusResponse,
)
from app.scraper import XProfileScraper

logging.basicConfig(level=settings.log_level.upper())
logger = logging.getLogger(__name__)

_engine = create_engine(settings.database_url, pool_pre_ping=True)
_SessionLocal = sessionmaker(bind=_engine, autoflush=False, autocommit=False)
_redis = redis_lib.from_url(settings.redis_url, decode_responses=True)

_classifier = TweetClassifier()
_ticker_extractor = TickerExtractor()
_price_extractor = PriceLevelExtractor()
_pipeline = SignalPipeline()
_scraper = XProfileScraper()


@asynccontextmanager
async def lifespan(app: FastAPI):
    await browser_manager.start()
    logger.info("Tweet-monitor started")
    yield
    await browser_manager.stop()
    logger.info("Tweet-monitor stopped")


app = FastAPI(title="Tweet Monitor", lifespan=lifespan)


@app.post("/poll", response_model=PollSummary)
async def poll_all():
    """Scrape all enabled accounts and process new tweets."""
    start = time.perf_counter()
    with _SessionLocal() as db:
        accounts = db.query(MonitoredAccount).filter(MonitoredAccount.enabled == True).all()

    summary = PollSummary(
        accounts_polled=0, tweets_found=0, tweets_new=0, tweets_promoted=0, duration_ms=0
    )
    errors: list[str] = []

    for account in accounts:
        try:
            promoted = await _poll_account(account, summary)
            summary.accounts_polled += 1
            summary.tweets_promoted += promoted
        except Exception as exc:
            msg = f"@{account.handle}: {exc}"
            logger.error(msg)
            errors.append(msg)

    summary.duration_ms = round((time.perf_counter() - start) * 1000, 1)
    summary.errors = errors
    return summary


@app.post("/poll/{account_id}", response_model=PollSummary)
async def poll_one(account_id: int):
    """Manually trigger a poll for a single account."""
    with _SessionLocal() as db:
        account = db.query(MonitoredAccount).filter(MonitoredAccount.id == account_id).first()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    start = time.perf_counter()
    summary = PollSummary(
        accounts_polled=1, tweets_found=0, tweets_new=0, tweets_promoted=0, duration_ms=0
    )
    promoted = await _poll_account(account, summary)
    summary.tweets_promoted = promoted
    summary.duration_ms = round((time.perf_counter() - start) * 1000, 1)
    return summary


async def _poll_account(account: MonitoredAccount, summary: PollSummary) -> int:
    """Scrape one account and process new tweets. Returns number promoted."""
    redis_key = f"tweet_monitor:last_seen:{account.id}"
    last_id: str | None = _redis.get(redis_key) or account.last_tweet_id

    tweets = await _scraper.scrape(account.handle, since_tweet_id=last_id)
    summary.tweets_found += len(tweets)

    promoted = 0
    newest_id: str | None = last_id

    for raw in tweets:
        raw["handle"] = account.handle
        tickers = _ticker_extractor.extract(raw["text"])
        price_levels = _price_extractor.extract(raw["text"], tickers)

        # Parse posted_at for classifier
        try:
            posted_at = datetime.fromisoformat(raw["posted_at"].replace("Z", "+00:00"))
        except Exception:
            posted_at = datetime.now(timezone.utc)

        result = _classifier.classify(
            text=raw["text"],
            posted_at=posted_at,
            is_retweet=raw.get("is_retweet", False),
            is_reply=raw.get("is_reply", False),
            tickers=tickers,
            price_levels=price_levels,
            account_config=account.classification_config or {},
        )

        signal = _pipeline.process(
            account=account,
            raw=raw,
            classification=result.classification,
            confidence=result.confidence,
            tickers=result.tickers,
            price_levels=result.price_levels,
            direction=result.direction,
        )
        if signal:
            summary.tweets_new += 1
            if signal.promoted:
                promoted += 1
            if newest_id is None or int(raw["tweet_id"]) > int(newest_id):
                newest_id = raw["tweet_id"]

    # Update last_seen in Redis + DB
    if newest_id and newest_id != last_id:
        _redis.set(redis_key, newest_id)
        with _SessionLocal() as db:
            acc = db.query(MonitoredAccount).filter(MonitoredAccount.id == account.id).first()
            if acc:
                acc.last_tweet_id = newest_id
                acc.last_poll_at = datetime.now(timezone.utc).replace(tzinfo=None)
                db.commit()

    return promoted


@app.get("/health", response_model=HealthResponse)
async def health():
    result = await check_health()
    if not result["healthy"]:
        from fastapi.responses import JSONResponse
        return JSONResponse(status_code=503, content=result)
    return result


@app.get("/status", response_model=StatusResponse)
async def status():
    health_data = await check_health()
    with _SessionLocal() as db:
        accounts = db.query(MonitoredAccount).all()
    return StatusResponse(
        accounts=[
            AccountStatus(
                id=a.id,
                handle=a.handle,
                display_name=a.display_name,
                platform=a.platform,
                enabled=a.enabled,
                last_poll_at=a.last_poll_at,
                last_tweet_id=a.last_tweet_id,
                poll_interval_seconds=a.poll_interval_seconds,
            )
            for a in accounts
        ],
        health=HealthResponse(**health_data),
    )


@app.get("/accounts", response_model=list[AccountStatus])
async def list_accounts():
    with _SessionLocal() as db:
        accounts = db.query(MonitoredAccount).all()
    return [
        AccountStatus(
            id=a.id,
            handle=a.handle,
            display_name=a.display_name,
            platform=a.platform,
            enabled=a.enabled,
            last_poll_at=a.last_poll_at,
            last_tweet_id=a.last_tweet_id,
            poll_interval_seconds=a.poll_interval_seconds,
        )
        for a in accounts
    ]


@app.post("/accounts", response_model=AccountStatus, status_code=201)
async def create_account(body: AccountCreate):
    with _SessionLocal() as db:
        existing = db.query(MonitoredAccount).filter(
            MonitoredAccount.handle == body.handle,
            MonitoredAccount.platform == body.platform,
        ).first()
        if existing:
            for k, v in body.model_dump().items():
                setattr(existing, k, v)
            db.commit()
            db.refresh(existing)
            a = existing
        else:
            a = MonitoredAccount(**body.model_dump())
            db.add(a)
            db.commit()
            db.refresh(a)
    return AccountStatus(
        id=a.id,
        handle=a.handle,
        display_name=a.display_name,
        platform=a.platform,
        enabled=a.enabled,
        last_poll_at=a.last_poll_at,
        last_tweet_id=a.last_tweet_id,
        poll_interval_seconds=a.poll_interval_seconds,
    )
