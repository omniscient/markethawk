import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.websocket_manager import StockWebSocketManager


def test_start_skips_polygon_client_when_live_websocket_disabled():
    StockWebSocketManager._instance = None
    manager = StockWebSocketManager()
    manager.api_key = "demo_no_live_key"

    with (
        patch("app.services.websocket_manager.settings.LIVE_WEBSOCKET_ENABLED", False),
        patch("app.services.websocket_manager.WebSocketClient") as client_cls,
        patch(
            "app.services.websocket_manager.asyncio.get_event_loop",
            return_value=MagicMock(),
        ),
    ):
        manager.start()

    client_cls.assert_not_called()
    assert manager._connected is False


def _make_pubsub_mock(messages):
    """Build a mock aioredis PubSub that yields messages from the list then returns None."""
    mock_pubsub = MagicMock()  # pubsub itself is sync-returned from redis.pubsub()
    iter_msgs = iter(messages)

    async def get_message(*args, **kwargs):
        try:
            return next(iter_msgs)
        except StopIteration:
            await asyncio.sleep(0.01)
            return None

    mock_pubsub.subscribe = AsyncMock()
    mock_pubsub.unsubscribe = AsyncMock()
    mock_pubsub.aclose = AsyncMock()
    mock_pubsub.get_message = get_message
    return mock_pubsub


def _make_redis_mock(pubsub):
    """Build a mock aioredis client whose pubsub() (sync) returns pubsub."""
    mock_redis = MagicMock()
    mock_redis.pubsub.return_value = pubsub
    return mock_redis


@pytest.mark.asyncio
async def test_register_creates_redis_subscriber_background_task():
    """register() must be async and create a Redis pubsub subscriber task per channel.

    Without this, only messages published via _publish_to_redis (in-process) reach queues.
    The live-scanner container publishes directly to Redis from a separate process, so
    the fan-out must subscribe to Redis to receive those messages (spec req #7).
    """
    StockWebSocketManager._instance = None
    manager = StockWebSocketManager()

    channel = "watchlist:alerts"
    mock_pubsub = _make_pubsub_mock([])
    mock_redis = _make_redis_mock(mock_pubsub)

    with patch.object(manager, "_get_redis", new=AsyncMock(return_value=mock_redis)):
        queue = await manager.register(channel)

    assert hasattr(manager, "_fan_out_tasks"), "manager must have _fan_out_tasks dict"
    assert channel in manager._fan_out_tasks, f"no fan-out task for channel {channel!r}"
    assert isinstance(manager._fan_out_tasks[channel], asyncio.Task)
    assert not manager._fan_out_tasks[channel].done(), (
        "fan-out task must still be running"
    )

    manager._fan_out_tasks[channel].cancel()
    try:
        await manager._fan_out_tasks[channel]
    except (asyncio.CancelledError, Exception):
        pass

    StockWebSocketManager._instance = None


@pytest.mark.asyncio
async def test_fan_out_delivers_cross_process_redis_message():
    """Messages published to Redis by any process must reach in-process subscriber queues.

    This covers the live-scanner container which publishes stock_updates:* and
    watchlist:live_data / watchlist:alerts directly to Redis without going through
    _publish_to_redis (spec req #7).
    """
    StockWebSocketManager._instance = None
    manager = StockWebSocketManager()

    channel = "watchlist:alerts"
    test_message = '{"type": "alert", "symbol": "AAPL"}'

    mock_pubsub = _make_pubsub_mock([{"data": test_message}])
    mock_redis = _make_redis_mock(mock_pubsub)

    with patch.object(manager, "_get_redis", new=AsyncMock(return_value=mock_redis)):
        queue = await manager.register(channel)
        await asyncio.sleep(0.1)

    assert not queue.empty(), (
        "Queue must receive the message from the Redis subscriber task"
    )
    received = queue.get_nowait()
    assert received == test_message

    manager._fan_out_tasks[channel].cancel()
    try:
        await manager._fan_out_tasks[channel]
    except (asyncio.CancelledError, Exception):
        pass

    StockWebSocketManager._instance = None
