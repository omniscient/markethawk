"""
News API router for managing preferences.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from datetime import datetime

from app.core.database import get_db
from app.models.news_preference import NewsPreference
from app.models.news_article import NewsArticle
from app.schemas.news_preference import NewsPreferenceResponse, NewsPreferenceUpdate, NewsArticleResponse
from typing import List
from datetime import timedelta

router = APIRouter(prefix="/api/news", tags=["news"])


@router.get("/preferences", response_model=NewsPreferenceResponse)
def get_news_preferences(db: Session = Depends(get_db)):
    """Get the current news filtering preferences."""
    pref = db.query(NewsPreference).first()
    if not pref:
        # Create a default if none exists
        pref = NewsPreference(
            tracked_tickers=[],
            tracked_universes=[]
        )
        db.add(pref)
        db.commit()
        db.refresh(pref)
    return pref


@router.put("/preferences", response_model=NewsPreferenceResponse)
def update_news_preferences(
    prefs_in: NewsPreferenceUpdate,
    db: Session = Depends(get_db)
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
def get_recent_news(db: Session = Depends(get_db)):
    """Get the latest 100 news articles."""
    # We no longer enforce a strict 60-minute cutoff because if market news is slow, 
    # it results in a completely blank dashboard. The DB already drops news older than 7 days.
    articles = db.query(NewsArticle).order_by(NewsArticle.published_utc.desc()).limit(100).all()
    return articles

from fastapi import WebSocket, WebSocketDisconnect
import asyncio
import redis.asyncio as aioredis
from app.core.config import settings
import json
@router.post("/refresh")
def trigger_news_refresh():
    """Manually trigger a news refresh (bypasses weekday/time schedule)."""
    from app.tasks import poll_massive_news
    result = poll_massive_news.apply_async(kwargs={"force": True})
    return {"status": "ok", "task_id": str(result.id)}

@router.websocket("/ws")
async def news_websocket(websocket: WebSocket):
    await websocket.accept()
    # Connect to redis using async redis client
    redis_client = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
    pubsub = redis_client.pubsub()
    await pubsub.subscribe("news_updates")
    
    try:
        while True:
            message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
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
