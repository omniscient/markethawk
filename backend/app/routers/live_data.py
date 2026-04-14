from fastapi import APIRouter, WebSocket, WebSocketDisconnect
import asyncio
import json
import logging
import redis.asyncio as aioredis
from app.core.config import settings
from app.services.websocket_manager import websocket_manager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/live", tags=["live"])

@router.websocket("/ws/{ticker}/{resolution}")
async def stock_live_websocket(websocket: WebSocket, ticker: str, resolution: str):
    """
    WebSocket endpoint for live stock updates with specific resolution (minute/second).
    Subscribes to Redis channel for the given ticker and resolution.
    """
    ticker = ticker.upper()
    resolution = resolution.lower()
    if resolution not in ["minute", "second"]:
        resolution = "minute"
        
    await websocket.accept()
    
    # Ensure backend is connected to Polygon and subscribed to this ticker
    websocket_manager.subscribe(ticker)
    
    # Connect to Redis for this specific client request
    redis_client = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
    pubsub = redis_client.pubsub()
    channel = f"stock_updates:{ticker}:{resolution}"
    await pubsub.subscribe(channel)
    
    logger.info(f"Client connected to {resolution} updates for {ticker}")
    
    try:
        while True:
            # Check for messages from Redis
            message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
            if message:
                await websocket.send_text(message["data"])
            
            # Keep-alive / check if client is still there
            # (get_message timeout handles the yield to event loop)
            await asyncio.sleep(0.01)
            
    except WebSocketDisconnect:
        logger.info(f"Client disconnected from live updates for {ticker}")
    except Exception as e:
        logger.error(f"WebSocket error for {ticker}: {e}")
    finally:
        await pubsub.unsubscribe(channel)
        await redis_client.close()
        # Optionally tell manager to check if anyone else is watching this ticker
        # (simplified: we keep it subscribed in the manager for now)


@router.websocket("/ws/watchlist")
async def watchlist_live_websocket(websocket: WebSocket):
    """
    WebSocket endpoint that streams live tick data and alerts for all
    symbols currently in the active watchlist.

    Publishes two types of messages:
      - tick / minute_bar  (from live_scanner via 'watchlist:live_data' channel)
      - alert              (from live_scanner via 'watchlist:alerts' channel)
    """
    await websocket.accept()

    redis_client = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
    pubsub = redis_client.pubsub()
    await pubsub.subscribe("watchlist:live_data", "watchlist:alerts")

    logger.info("Client connected to watchlist live stream")

    try:
        while True:
            message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
            if message:
                await websocket.send_text(message["data"])
            await asyncio.sleep(0.01)
    except WebSocketDisconnect:
        logger.info("Client disconnected from watchlist live stream")
    except Exception as e:
        logger.error(f"Watchlist WebSocket error: {e}")
    finally:
        await pubsub.unsubscribe("watchlist:live_data", "watchlist:alerts")
        await redis_client.close()
