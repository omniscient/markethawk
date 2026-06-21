import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _make_ib(connected=True):
    ib = MagicMock()
    ib.isConnected.return_value = connected
    ib.disconnectedEvent = MagicMock()
    ib.disconnectedEvent.__iadd__ = MagicMock(return_value=None)
    return ib


@pytest.mark.asyncio
async def test_fetch_seed_data_returns_prior_close_and_avg_volume():
    from live_scanner.ibkr_adapter import IBKRLiveAdapter

    ib = _make_ib()
    bar1 = MagicMock()
    bar1.close = 150.0
    bar1.volume = 1_000_000
    bar2 = MagicMock()
    bar2.close = 152.0
    bar2.volume = 1_200_000
    qualified = MagicMock()
    ib.qualifyContractsAsync = AsyncMock(return_value=[qualified])
    ib.reqHistoricalDataAsync = AsyncMock(return_value=[bar1, bar2])

    adapter = IBKRLiveAdapter(ib, "localhost", 4004, 5)
    prior_close, avg_vol = await adapter.fetch_seed_data("AAPL", "STK", "SMART")

    assert prior_close == 152.0
    assert avg_vol == pytest.approx(1_100_000.0)


@pytest.mark.asyncio
async def test_fetch_seed_data_returns_zeros_on_empty_bars():
    from live_scanner.ibkr_adapter import IBKRLiveAdapter

    ib = _make_ib()
    qualified = MagicMock()
    ib.qualifyContractsAsync = AsyncMock(return_value=[qualified])
    ib.reqHistoricalDataAsync = AsyncMock(return_value=[])

    adapter = IBKRLiveAdapter(ib, "localhost", 4004, 5)
    prior_close, avg_vol = await adapter.fetch_seed_data("AAPL", "STK", "SMART")

    assert prior_close == 0.0 and avg_vol == 0.0


@pytest.mark.asyncio
async def test_subscribe_calls_reqRealTimeBars_and_reqMktData():
    from live_scanner.ibkr_adapter import IBKRLiveAdapter

    ib = _make_ib()
    qualified = MagicMock()
    ib.qualifyContractsAsync = AsyncMock(return_value=[qualified])
    ib.reqHistoricalDataAsync = AsyncMock(return_value=[])

    bar_list = MagicMock()
    bar_list.updateEvent = MagicMock()
    ticker = MagicMock()
    ticker.updateEvent = MagicMock()
    ib.reqRealTimeBars.return_value = bar_list
    ib.reqMktData.return_value = ticker

    adapter = IBKRLiveAdapter(ib, "localhost", 4004, 5)
    await adapter.subscribe("AAPL", "STK", "SMART", AsyncMock(), AsyncMock())

    ib.reqRealTimeBars.assert_called_once()
    ib.reqMktData.assert_called_once()


@pytest.mark.asyncio
async def test_subscribe_skips_when_not_connected():
    from live_scanner.ibkr_adapter import IBKRLiveAdapter

    ib = _make_ib(connected=False)
    adapter = IBKRLiveAdapter(ib, "localhost", 4004, 5)
    await adapter.subscribe("AAPL", "STK", "SMART", AsyncMock(), AsyncMock())
    ib.reqRealTimeBars.assert_not_called()


@pytest.mark.asyncio
async def test_unsubscribe_cancels_both_subscriptions():
    from live_scanner.ibkr_adapter import IBKRLiveAdapter

    ib = _make_ib()
    qualified = MagicMock()
    ib.qualifyContractsAsync = AsyncMock(return_value=[qualified])
    ib.reqHistoricalDataAsync = AsyncMock(return_value=[])
    bar_list = MagicMock()
    bar_list.updateEvent = MagicMock()
    ticker = MagicMock()
    ticker.updateEvent = MagicMock()
    ib.reqRealTimeBars.return_value = bar_list
    ib.reqMktData.return_value = ticker

    adapter = IBKRLiveAdapter(ib, "localhost", 4004, 5)
    await adapter.subscribe("AAPL", "STK", "SMART", AsyncMock(), AsyncMock())
    await adapter.unsubscribe("AAPL")

    ib.cancelRealTimeBars.assert_called_once_with(bar_list)
    ib.cancelMktData.assert_called_once_with(ticker)


@pytest.mark.asyncio
async def test_unsubscribe_unknown_symbol_is_noop():
    from live_scanner.ibkr_adapter import IBKRLiveAdapter

    adapter = IBKRLiveAdapter(_make_ib(), "localhost", 4004, 5)
    await adapter.unsubscribe("UNKNOWN")  # must not raise


@pytest.mark.asyncio
async def test_disconnect_calls_ib_disconnect():
    from live_scanner.ibkr_adapter import IBKRLiveAdapter

    ib = _make_ib()
    adapter = IBKRLiveAdapter(ib, "localhost", 4004, 5)
    await adapter.disconnect()
    ib.disconnect.assert_called_once()


# ── New reconnect tests ────────────────────────────────────────────────────


def test_ibkr_adapter_stores_connection_params():
    from live_scanner.ibkr_adapter import IBKRLiveAdapter

    ib = _make_ib()
    adapter = IBKRLiveAdapter(ib, "myhost", 4004, 5)
    assert adapter._host == "myhost"
    assert adapter._port == 4004
    assert adapter._client_id == 5


def test_wire_disconnect_queue_registers_event_handler():
    from live_scanner.ibkr_adapter import IBKRLiveAdapter

    ib = _make_ib()
    handlers = []

    def fake_iadd(h):
        handlers.append(h)
        return ib.disconnectedEvent

    ib.disconnectedEvent.__iadd__ = MagicMock(side_effect=fake_iadd)

    adapter = IBKRLiveAdapter(ib, "localhost", 4004, 5)
    queue = asyncio.Queue()
    loop = asyncio.new_event_loop()
    try:
        adapter.wire_disconnect_queue(queue, "disconnect", loop)
    finally:
        loop.close()

    assert len(handlers) == 1


def test_is_connected_delegates_to_ib():
    from live_scanner.ibkr_adapter import IBKRLiveAdapter

    ib = _make_ib(connected=True)
    assert IBKRLiveAdapter(ib, "localhost", 4004, 5).is_connected() is True

    ib2 = _make_ib(connected=False)
    assert IBKRLiveAdapter(ib2, "localhost", 4004, 5).is_connected() is False


def test_force_disconnect_calls_ib_disconnect():
    from live_scanner.ibkr_adapter import IBKRLiveAdapter

    ib = _make_ib()
    IBKRLiveAdapter(ib, "localhost", 4004, 5).force_disconnect()
    ib.disconnect.assert_called_once()


@pytest.mark.asyncio
async def test_reconnect_delegates_to_connect_ib_and_returns_true():
    from live_scanner.ibkr_adapter import IBKRLiveAdapter

    ib = _make_ib(connected=True)
    adapter = IBKRLiveAdapter(ib, "localhost", 4004, 5)

    with patch(
        "live_scanner.ibkr_adapter._connect_ib", AsyncMock(return_value=True)
    ) as mock_conn:
        result = await adapter.reconnect()

    mock_conn.assert_awaited_once_with(ib, "localhost", 4004, 5)
    assert result is True


@pytest.mark.asyncio
async def test_reconnect_returns_false_on_exhausted_retries():
    from live_scanner.ibkr_adapter import IBKRLiveAdapter

    ib = _make_ib(connected=False)
    adapter = IBKRLiveAdapter(ib, "localhost", 4004, 5)

    with patch("live_scanner.ibkr_adapter._connect_ib", AsyncMock(return_value=False)):
        result = await adapter.reconnect()

    assert result is False
