"""
News API router for managing preferences.
"""

import asyncio
from typing import List

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.rate_limits import limiter
from app.models.news_article import NewsArticle
from app.models.news_preference import NewsPreference
from app.schemas.news_preference import (
    NewsArticleResponse,
    NewsPreferenceResponse,
    NewsPreferenceUpdate,
)

router = APIRouter(prefix="/api/v1/news", tags=["news"])


@router.get("/preferences", response_model=NewsPreferenceResponse)
async def get_news_preferences(db: Session = Depends(get_db)):
    """Get the current news filtering preferences."""
    loop = asyncio.get_running_loop()

    def _get():
        pref = db.query(NewsPreference).first()
        if not pref:
            # Create a default if none exists
            pref = NewsPreference(tracked_tickers=[], tracked_universes=[])
            db.add(pref)
            db.commit()
            db.refresh(pref)
        return pref

    return await loop.run_in_executor(None, _get)


@router.put("/preferences", response_model=NewsPreferenceResponse)
async def update_news_preferences(
    prefs_in: NewsPreferenceUpdate, db: Session = Depends(get_db)
):
    """Update news filtering preferences."""
    loop = asyncio.get_running_loop()

    def _update():
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

    return await loop.run_in_executor(None, _update)


@router.get("/recent", response_model=List[NewsArticleResponse])
async def get_recent_news(ticker: str = None, db: Session = Depends(get_db)):
    """Get the latest 100 news articles, optionally filtered by ticker."""
    loop = asyncio.get_running_loop()

    def _query():
        query = db.query(NewsArticle)
        if ticker:
            # Extremely robust filtering for both JSON and JSONB type across different databases
            # Using string search on the JSON representation is the most universal fallback
            from sqlalchemy import String, cast

            query = query.filter(
                cast(NewsArticle.tickers, String).contains(f'"{ticker.upper()}"')
            )
        return query.order_by(NewsArticle.published_utc.desc()).limit(100).all()

    return await loop.run_in_executor(None, _query)


@router.post("/refresh")
async def trigger_news_refresh():
    """Manually trigger a news refresh (bypasses weekday/time schedule)."""
    loop = asyncio.get_running_loop()

    def _trigger():
        from app.tasks import poll_massive_news

        result = poll_massive_news.apply_async(kwargs={"force": True})
        return {"status": "ok", "task_id": str(result.id)}

    return await loop.run_in_executor(None, _trigger)


@router.websocket("/ws")
@limiter.exempt
async def news_websocket(websocket: WebSocket):
    await websocket.accept()
    # Connect to redis using async redis client
    redis_client = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
    pubsub = redis_client.pubsub()
    await pubsub.subscribe("news_updates")

    try:
        while True:
            message = await pubsub.get_message(
                ignore_subscribe_messages=True, timeout=1.0
            )
            if message:
                await websocket.send_text(message["data"])
            await asyncio.sleep(0.1)  # prevent busy looping
    except WebSocketDisconnect:
        pass
    except Exception as e:
        print(f"WS Exception: {e}")
    finally:
        await pubsub.unsubscribe("news_updates")
        await redis_client.close()
