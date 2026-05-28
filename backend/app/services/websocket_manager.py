import asyncio
import json
import logging
import threading
from typing import Any, Dict, Optional, Set

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
            # Channel format supports specific resolution subscriptions
            channel = f"stock_updates:{ticker}:{resolution}"
            await redis.publish(channel, json.dumps(payload))
        except Exception as e:
            logger.error(f"Error publishing to Redis: {e}")

    def start(self):
        """Start the Polygon WebSocket client in a background thread."""
        if self._connected:
            return

        if not self.api_key:
            logger.warning("POLYGON_API_KEY not set. WebSocket manager will not start.")
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


# Global instance
websocket_manager = StockWebSocketManager()
