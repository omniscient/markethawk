"""
Tweets router — WebSocket feed + REST endpoint for TweetSignal data.

WebSocket: /api/tweets/feed  — streams all new tweet signals from Redis pub/sub
REST:      GET /api/tweets/recent  — returns recent tweet signals from DB
"""

import asyncio
import logging
from typing import Optional

import redis.asyncio as aioredis
from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import SessionLocal
from app.core.rate_limits import limiter
from app.models.monitored_account import MonitoredAccount
from app.models.tweet_signal import TweetSignal

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/tweets", tags=["tweets"])


@router.websocket("/feed")
@limiter.exempt
async def tweet_feed_websocket(websocket: WebSocket):
    """WebSocket: streams real-time tweet signals from Redis channel tweet_signals:all."""
    await websocket.accept()

    redis_client = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
    pubsub = redis_client.pubsub()
    await pubsub.subscribe("tweet_signals:all")

    try:
        while True:
            message = await pubsub.get_message(
                ignore_subscribe_messages=True, timeout=1.0
            )
            if message:
                await websocket.send_text(message["data"])
            await asyncio.sleep(0.01)
    except WebSocketDisconnect:
        logger.info("Client disconnected from tweet feed")
    finally:
        await pubsub.unsubscribe("tweet_signals:all")
        await redis_client.aclose()


@router.get("/recent")
async def get_recent_tweets(
    limit: int = Query(50, ge=1, le=200),
    classification: Optional[str] = Query(None),
    promoted_only: bool = Query(False),
):
    """Return recent tweet signals from DB, newest first."""
    db: Session = SessionLocal()
    try:
        q = db.query(TweetSignal).join(MonitoredAccount)
        if classification:
            q = q.filter(TweetSignal.classification == classification.upper())
        if promoted_only:
            q = q.filter(TweetSignal.promoted == True)
        signals = q.order_by(TweetSignal.posted_at.desc()).limit(limit).all()

        return [
            {
                "id": s.id,
                "tweet_id": s.tweet_id,
                "tweet_url": s.tweet_url,
                "handle": s.account.handle if s.account else None,
                "display_name": s.account.display_name if s.account else None,
                "full_text": s.full_text,
                "classification": s.classification,
                "confidence": s.confidence,
                "tickers": s.tickers,
                "price_levels": s.price_levels,
                "direction": s.direction,
                "promoted": s.promoted,
                "scanner_event_id": s.scanner_event_id,
                "posted_at": s.posted_at.isoformat() if s.posted_at else None,
                "scraped_at": s.scraped_at.isoformat() if s.scraped_at else None,
            }
            for s in signals
        ]
    finally:
        db.close()
