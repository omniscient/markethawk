"""
News API router for managing preferences.
"""

from typing import List

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.news_article import NewsArticle
from app.models.news_preference import NewsPreference
from app.schemas.news_preference import (
    NewsArticleResponse,
    NewsPreferenceResponse,
    NewsPreferenceUpdate,
)

router = APIRouter(prefix="/api/v1/news", tags=["news"])


@router.get("/preferences", response_model=NewsPreferenceResponse)
def get_news_preferences(db: Session = Depends(get_db)):
    """Get the current news filtering preferences."""
    pref = db.query(NewsPreference).first()
    if not pref:
        # Create a default if none exists
        pref = NewsPreference(tracked_tickers=[], tracked_universes=[])
        db.add(pref)
        db.commit()
        db.refresh(pref)
    return pref


@router.put("/preferences", response_model=NewsPreferenceResponse)
def update_news_preferences(
    prefs_in: NewsPreferenceUpdate, db: Session = Depends(get_db)
):
    """Update news filtering preferences."""
    pref = db.query(NewsPreference).first()
    if not pref:
        pref = NewsPreference(**prefs_in.model_dump())
        db.add(pref)
    else:
        for key, value in prefs_in.model_dump().items():
            setattr(pref, key, value)

    db.commit()
    db.refresh(pref)
    return pref


@router.get("/recent", response_model=List[NewsArticleResponse])
def get_recent_news(ticker: str = None, db: Session = Depends(get_db)):
    """Get the latest 100 news articles, optionally filtered by ticker."""
    query = db.query(NewsArticle)

    if ticker:
        # Extremely robust filtering for both JSON and JSONB type across different databases
        # Using string search on the JSON representation is the most universal fallback
        from sqlalchemy import String, cast

        query = query.filter(
            cast(NewsArticle.tickers, String).contains(f'"{ticker.upper()}"')
        )

    articles = query.order_by(NewsArticle.published_utc.desc()).limit(100).all()

    return articles


import asyncio  # noqa: E402
import logging  # noqa: E402
import time  # noqa: E402

import redis.asyncio as aioredis  # noqa: E402
from fastapi import Depends, WebSocket, WebSocketDisconnect  # noqa: E402

from app.core.auth import verify_ws_origin, ws_get_current_user  # noqa: E402
from app.core.config import settings  # noqa: E402
from app.core.rate_limits import limiter  # noqa: E402
from app.core.ws_limits import ws_connection_slot  # noqa: E402
from app.models.user import User  # noqa: E402

_news_logger = logging.getLogger(__name__)


@router.post("/refresh")
def trigger_news_refresh():
    """Manually trigger a news refresh (bypasses weekday/time schedule)."""
    from app.tasks import poll_massive_news

    result = poll_massive_news.apply_async(kwargs={"force": True})
    return {"status": "ok", "task_id": str(result.id)}


@router.websocket("/ws")
@limiter.exempt
async def news_websocket(
    websocket: WebSocket,
    _user: User = Depends(ws_get_current_user),
    _origin: None = Depends(verify_ws_origin),
):
    async with ws_connection_slot(str(_user.id)):
        await websocket.accept()
        redis_client = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
        pubsub = redis_client.pubsub()
        await pubsub.subscribe("news_updates")

        deadline = time.monotonic() + settings.WS_MAX_LIFETIME_SECONDS
        idle_timeout = settings.WS_IDLE_TIMEOUT_SECONDS
        last_message_at = time.monotonic()

        try:
            while True:
                now = time.monotonic()
                if now >= deadline:
                    await websocket.close(1001)
                    break
                if now - last_message_at >= idle_timeout:
                    await websocket.close(1000)
                    break
                message = await pubsub.get_message(
                    ignore_subscribe_messages=True, timeout=1.0
                )
                if message:
                    last_message_at = time.monotonic()
                    await websocket.send_text(message["data"])
                await asyncio.sleep(0.1)
        except WebSocketDisconnect:
            pass
        except Exception as e:
            _news_logger.error(f"News WS error: {e}")
        finally:
            await pubsub.unsubscribe("news_updates")
            await redis_client.aclose()
