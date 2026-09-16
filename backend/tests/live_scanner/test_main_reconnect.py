"""Tests for main.py reconnect flow and liveness watchdog."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_process_loop_publishes_feed_loss_on_tag_disconnect():
    """TAG_DISCONNECT on the queue triggers publish_feed_loss."""
    from live_scanner.main import TAG_DISCONNECT, _process_loop

    queue = asyncio.Queue()
    aggregators = {}
    publisher = MagicMock()
    publisher.publish_feed_loss = AsyncMock()
    publisher.publish_feed_recovered = AsyncMock()
    adapter = MagicMock()
    adapter.reconnect = AsyncMock(return_value=False)
    adapter.wire_disconnect_queue = MagicMock()
    subscribed_items: dict = {}
    last_bar_ts: list = [None]

    queue.put_nowait((TAG_DISCONNECT, None, None))

    task = asyncio.create_task(
        _process_loop(
            queue, aggregators, publisher, adapter, subscribed_items, last_bar_ts
        )
    )
    await asyncio.sleep(0.1)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    publisher.publish_feed_loss.assert_awaited_once()


@pytest.mark.asyncio
async def test_process_loop_publishes_feed_recovered_on_tag_connect_recovered():
    """TAG_CONNECT_RECOVERED triggers publish_feed_recovered."""
    from live_scanner.main import TAG_CONNECT_RECOVERED, _process_loop

    queue = asyncio.Queue()
    aggregators = {}
    publisher = MagicMock()
    publisher.publish_feed_recovered = AsyncMock()
    publisher.publish_feed_loss = AsyncMock()
    adapter = MagicMock()
    adapter.reconnect = AsyncMock(return_value=True)
    adapter.wire_disconnect_queue = MagicMock()
    subscribed_items: dict = {}
    last_bar_ts: list = [None]

    queue.put_nowait((TAG_CONNECT_RECOVERED, None, None))

    task = asyncio.create_task(
        _process_loop(
            queue, aggregators, publisher, adapter, subscribed_items, last_bar_ts
        )
    )
    await asyncio.sleep(0.1)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    publisher.publish_feed_recovered.assert_awaited_once()


@pytest.mark.asyncio
async def test_process_loop_resubscribes_on_tag_connect_recovered():
    """TAG_CONNECT_RECOVERED resubscribes all subscribed_items."""
    from live_scanner.main import TAG_CONNECT_RECOVERED, _process_loop

    queue = asyncio.Queue()
    aggregators = {}
    publisher = MagicMock()
    publisher.publish_feed_recovered = AsyncMock()
    publisher.publish_feed_loss = AsyncMock()
    adapter = MagicMock()
    adapter.reconnect = AsyncMock(return_value=True)
    adapter.wire_disconnect_queue = MagicMock()
    subscribed_items = {
        "SPY": {"symbol": "SPY", "security_type": "STK", "exchange": "SMART"}
    }
    last_bar_ts: list = [None]

    with patch("live_scanner.main._subscribe", AsyncMock()) as mock_subscribe:
        queue.put_nowait((TAG_CONNECT_RECOVERED, None, None))

        task = asyncio.create_task(
            _process_loop(
                queue, aggregators, publisher, adapter, subscribed_items, last_bar_ts
            )
        )
        await asyncio.sleep(0.1)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    mock_subscribe.assert_awaited_once()


@pytest.mark.asyncio
async def test_process_loop_updates_last_bar_ts_on_tag_bar():
    """TAG_BAR messages update last_bar_ts[0] for the watchdog."""
    from live_scanner.main import TAG_BAR, _process_loop

    queue = asyncio.Queue()
    bar = MagicMock()
    bar.time = MagicMock()
    bar.open_ = 100.0
    bar.high = 101.0
    bar.low = 99.0
    bar.close = 100.5
    bar.volume = 1000
    bar.wap = 100.2

    mock_aggregator = MagicMock()
    mock_aggregator.update = MagicMock(return_value=None)
    aggregators = {"SPY": mock_aggregator}

    publisher = MagicMock()
    publisher.publish_tick = AsyncMock()
    publisher.publish_feed_loss = AsyncMock()
    publisher.publish_feed_recovered = AsyncMock()

    adapter = MagicMock()
    adapter.reconnect = AsyncMock(return_value=False)
    subscribed_items: dict = {}
    last_bar_ts: list = [None]

    queue.put_nowait((TAG_BAR, "SPY", bar))

    task = asyncio.create_task(
        _process_loop(
            queue, aggregators, publisher, adapter, subscribed_items, last_bar_ts
        )
    )
    await asyncio.sleep(0.1)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    assert last_bar_ts[0] is not None
    assert isinstance(last_bar_ts[0], float)


@pytest.mark.asyncio
async def test_run_uses_mock_adapter_when_live_scanner_mock_true():
    """When settings.LIVE_SCANNER_MOCK=True, run() uses MockLiveAdapter, not create_adapter."""
    from live_scanner.main import run

    mock_settings = MagicMock()
    mock_settings.LIVE_SCANNER_MOCK = True
    mock_settings.REDIS_URL = "redis://localhost"
    mock_settings.IBKR_HOST = "localhost"
    mock_settings.IBKR_PORT = 4004
    mock_settings.LOG_LEVEL = "INFO"

    with patch("live_scanner.main.settings", mock_settings):
        with patch("live_scanner.main.create_adapter", AsyncMock()) as mock_create:
            with patch("live_scanner.main.LivePublisher") as mock_pub_cls:
                mock_pub = AsyncMock()
                mock_pub.connect = AsyncMock()
                mock_pub.close = AsyncMock()
                mock_pub_cls.return_value = mock_pub

                # MockLiveAdapter is a lazy import inside run(), so patch at its source module
                with patch(
                    "live_scanner.mock_adapter.MockLiveAdapter"
                ) as mock_mock_cls:
                    mock_mock = MagicMock()
                    mock_mock.wire_disconnect_queue = MagicMock()
                    mock_mock.disconnect = AsyncMock()
                    mock_mock_cls.return_value = mock_mock

                    task = asyncio.create_task(run())
                    await asyncio.sleep(0.05)
                    task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass

    mock_create.assert_not_called()
