import asyncio
import json
import logging
import threading
from collections import defaultdict
from typing import Any, Dict, List, Optional, Set

import redis.asyncio as aioredis
from polygon import WebSocketClient
from polygon.websocket.models import Feed, WebSocketMessage

from app.core.config import settings

logger = logging.getLogger(__name__)


class StockWebSocketManager:
    """
    Singleton manager for Polygon.io WebSocket connection.
    Proxies updates to Redis Pub/Sub for frontend consumption.
    """

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(StockWebSocketManager, cls).__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self):
        if self._initialized:
            return

        self.api_key = settings.POLYGON_API_KEY
        self.client: Optional[WebSocketClient] = None
        self.active_tickers: Set[str] = set()
        self.redis_client = None
        self._loop = None
        self._initialized = True
        self._connected = False
        # Fan-out registry: channel -> list of asyncio.Queue instances (one per subscriber)
        self._fan_out_subscribers: Dict[str, List[asyncio.Queue]] = defaultdict(list)
        # Background Redis-subscriber tasks: channel -> Task (one per active channel)
        self._fan_out_tasks: Dict[str, asyncio.Task] = {}

    async def _get_redis(self):
        if self.redis_client is None:
            self.redis_client = aioredis.from_url(
                settings.REDIS_URL, decode_responses=True
            )
        return self.redis_client

    def _handle_msg(self, msgs: list[WebSocketMessage]):
        """Callback for Polygon WebSocket messages."""
        if not self._loop:
            return

        for msg in msgs:
            # Handle Aggregate Minute (AM) and Aggregate Second (A)
            if msg.event_type in ["AM", "A"]:
                ticker = msg.symbol
                payload = {
                    "ev": msg.event_type,
                    "sym": msg.symbol,
                    "v": msg.volume,
                    "o": msg.open,
                    "c": msg.close,
                    "h": msg.high,
                    "l": msg.low,
                    "vw": getattr(msg, "vwap", None),
                    "s": msg.start_timestamp,
                    "e": msg.end_timestamp,
                }

                # Determine resolution string
                res = "minute" if msg.event_type == "AM" else "second"

                # Use the loop to call async publish
                asyncio.run_coroutine_threadsafe(
                    self._publish_to_redis(ticker, res, payload), self._loop
                )

    async def _publish_to_redis(
        self, ticker: str, resolution: str, payload: Dict[str, Any]
    ):
        try:
            redis = await self._get_redis()
            channel = f"stock_updates:{ticker}:{resolution}"
            data = json.dumps(payload)
            await redis.publish(channel, data)
        except Exception as e:
            logger.error(f"Error publishing to Redis: {e}")

    def start(self):
        """Start the Polygon WebSocket client in a background thread."""
        if self._connected:
            return

        if not self.api_key:
            logger.warning("POLYGON_API_KEY not set. WebSocket manager will not start.")
            return

        if not settings.LIVE_WEBSOCKET_ENABLED:
            logger.info("Live WebSocket manager disabled by configuration.")
            return

        self._loop = asyncio.get_event_loop()

        def run_client():
            try:
                feed = Feed.Delayed if settings.POLYGON_DELAYED else Feed.RealTime
                logger.info(
                    f"Connecting to Polygon.io WebSocket ({'Delayed' if settings.POLYGON_DELAYED else 'Live'})..."
                )
                self.client = WebSocketClient(
                    api_key=self.api_key,
                    feed=feed,
                    # We'll subscribe dynamically, but start with nothing or a dummy
                    subscriptions=["AM.*"] if self.active_tickers else [],
                )
                self._connected = True
                self.client.run(self._handle_msg)
            except Exception as e:
                logger.error(f"Polygon WebSocket Error: {e}")
                self._connected = False

        thread = threading.Thread(target=run_client, daemon=True)
        thread.start()

    def subscribe(self, ticker: str):
        """Dynamically subscribe to a ticker for both minute and second updates."""
        ticker = ticker.upper()
        if ticker not in self.active_tickers:
            self.active_tickers.add(ticker)
            if self.client and self._connected:
                logger.info(f"Subscribing to live updates for {ticker} (M+S)")
                # Subscribe to both Aggregate Minute and Aggregate Second
                self.client.subscribe(f"AM.{ticker}", f"A.{ticker}")

    def unsubscribe(self, ticker: str):
        """Unsubscribe from a ticker (to be called when no clients are watching)."""
        # Note: We might want a reference counter here if multiple clients watch the same ticker
        # For simplicity, we'll just keep it subscribed for now, or implement a basic TTL
        pass

    # ── Fan-out registry ────────────────────────────────────────────────────

    async def register(self, channel: str) -> asyncio.Queue:
        """Register a new subscriber queue for *channel*.

        Returns a per-subscriber asyncio.Queue(maxsize=100). Starts a Redis
        pubsub subscriber background task for the channel on first registration
        so that messages published by any process (including the live-scanner
        container) are delivered to all in-process queues.  The caller must
        call unregister(channel, queue) when done.
        """
        q: asyncio.Queue = asyncio.Queue(maxsize=100)
        self._fan_out_subscribers[channel].append(q)
        if channel not in self._fan_out_tasks:
            self._fan_out_tasks[channel] = asyncio.create_task(
                self._fan_out(channel), name=f"fan_out:{channel}"
            )
        return q

    def unregister(self, channel: str, queue: asyncio.Queue) -> None:
        """Remove *queue* from the fan-out registry for *channel*.

        Cancels the Redis subscriber background task when the last subscriber leaves.
        """
        try:
            self._fan_out_subscribers[channel].remove(queue)
        except ValueError:
            pass
        if not self._fan_out_subscribers[channel]:
            if channel in self._fan_out_subscribers:
                del self._fan_out_subscribers[channel]
            task = self._fan_out_tasks.pop(channel, None)
            if task and not task.done():
                task.cancel()

    async def _fan_out(self, channel: str) -> None:
        """Background task: subscribe to *channel* on Redis and fan out to in-process queues.

        Runs for the lifetime of any subscriber on the channel. Cancelled by
        unregister() when the last subscriber leaves.
        """
        redis = await self._get_redis()
        pubsub = redis.pubsub()
        await pubsub.subscribe(channel)
        try:
            while True:
                msg = await pubsub.get_message(
                    ignore_subscribe_messages=True, timeout=1.0
                )
                if msg:
                    data = msg["data"]
                    dead = []
                    for q in list(self._fan_out_subscribers.get(channel, [])):
                        try:
                            q.put_nowait(data)
                        except asyncio.QueueFull:
                            logger.warning(
                                f"Fan-out queue full for channel {channel}, dropping message"
                            )
                            dead.append(q)
                    for q in dead:
                        try:
                            self._fan_out_subscribers[channel].remove(q)
                        except ValueError:
                            pass
                await asyncio.sleep(0.01)
        except asyncio.CancelledError:
            pass
        finally:
            await pubsub.unsubscribe(channel)
            await pubsub.aclose()


# Global instance
websocket_manager = StockWebSocketManager()
