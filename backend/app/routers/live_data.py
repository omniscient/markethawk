import asyncio
import json
import logging
import time

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect

from app.core.auth import verify_ws_origin, ws_get_current_user
from app.core.config import settings
from app.core.metrics import active_websocket_connections
from app.core.rate_limits import limiter
from app.core.ws_limits import ws_connection_slot
from app.models.user import User
from app.services.websocket_manager import websocket_manager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/live", tags=["live"])


@router.websocket("/ws/{ticker}/{resolution}")
@limiter.exempt
async def stock_live_websocket(
    websocket: WebSocket,
    ticker: str,
    resolution: str,
    _user: User = Depends(ws_get_current_user),
    _origin: None = Depends(verify_ws_origin),
):
    """Live stock updates for a specific ticker and resolution via shared fan-out."""
    ticker = ticker.upper()
    resolution = resolution.lower()
    if resolution not in ["minute", "second"]:
        resolution = "minute"

    channel = f"stock_updates:{ticker}:{resolution}"

    async with ws_connection_slot(str(_user.id)):
        await websocket.accept()
        active_websocket_connections.inc()
        websocket_manager.subscribe(ticker)
        queue = await websocket_manager.register(channel)

        logger.info(f"Client connected to {resolution} updates for {ticker}")

        deadline = time.monotonic() + settings.WS_MAX_LIFETIME_SECONDS
        idle_timeout = settings.WS_IDLE_TIMEOUT_SECONDS

        try:
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    await websocket.close(1001)
                    break
                wait = min(idle_timeout, remaining)
                try:
                    message = await asyncio.wait_for(queue.get(), timeout=wait)
                    await websocket.send_text(message)
                except asyncio.TimeoutError:
                    if time.monotonic() >= deadline:
                        await websocket.close(1001)
                    else:
                        # Idle timeout exceeded
                        await websocket.close(1000)
                    break
        except WebSocketDisconnect:
            logger.info(f"Client disconnected from live updates for {ticker}")
        except Exception as e:
            logger.error(f"WebSocket error for {ticker}: {e}")
        finally:
            active_websocket_connections.dec()
            websocket_manager.unregister(channel, queue)


@router.websocket("/ws/watchlist")
@limiter.exempt
async def watchlist_live_websocket(
    websocket: WebSocket,
    _user: User = Depends(ws_get_current_user),
    _origin: None = Depends(verify_ws_origin),
):
    """Live tick data and alerts for all watchlist symbols via shared fan-out."""
    async with ws_connection_slot(str(_user.id)):
        await websocket.accept()
        active_websocket_connections.inc()

        # Register on both watchlist channels
        live_queue = await websocket_manager.register("watchlist:live_data")
        alert_queue = await websocket_manager.register("watchlist:alerts")

        logger.info("Client connected to watchlist live stream")

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

                sent = False
                try:
                    message = live_queue.get_nowait()
                    await websocket.send_text(message)
                    last_message_at = time.monotonic()
                    sent = True
                except asyncio.QueueEmpty:
                    pass
                try:
                    message = alert_queue.get_nowait()
                    await websocket.send_text(message)
                    last_message_at = time.monotonic()
                    sent = True
                except asyncio.QueueEmpty:
                    pass
                if not sent:
                    await asyncio.sleep(0.05)
        except WebSocketDisconnect:
            logger.info("Client disconnected from watchlist live stream")
        except Exception as e:
            logger.error(f"Watchlist WebSocket error: {e}")
        finally:
            active_websocket_connections.dec()
            websocket_manager.unregister("watchlist:live_data", live_queue)
            websocket_manager.unregister("watchlist:alerts", alert_queue)


@router.websocket("/ws/scan-task/{task_id}")
@limiter.exempt
async def scan_task_websocket(
    websocket: WebSocket,
    task_id: str,
    _user: User = Depends(ws_get_current_user),
    _origin: None = Depends(verify_ws_origin),
):
    """Stream Celery task progress for a range scan."""
    async with ws_connection_slot(str(_user.id)):
        await websocket.accept()
        active_websocket_connections.inc()

        redis_client = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
        pubsub = redis_client.pubsub()
        channel = f"scan_task:{task_id}"
        await pubsub.subscribe(channel)

        logger.info(f"Client connected to scan task: {task_id}")

        deadline = time.monotonic() + settings.WS_MAX_LIFETIME_SECONDS
        idle_timeout = settings.WS_SCAN_TASK_IDLE_TIMEOUT_SECONDS
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
                    try:
                        parsed = json.loads(message["data"])
                        if parsed.get("status") in ("completed", "failed"):
                            break
                    except Exception:
                        pass
                await asyncio.sleep(0.01)
        except WebSocketDisconnect:
            logger.info(f"Client disconnected from scan task: {task_id}")
        except Exception as e:
            logger.error(f"Scan task WebSocket error for {task_id}: {e}")
        finally:
            active_websocket_connections.dec()
            await pubsub.unsubscribe(channel)
            await redis_client.aclose()
