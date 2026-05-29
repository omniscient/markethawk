from unittest.mock import AsyncMock, MagicMock

import pytest


def _make_ib(connected=True):
    ib = MagicMock()
    ib.isConnected.return_value = connected
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

    adapter = IBKRLiveAdapter(ib)
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

    adapter = IBKRLiveAdapter(ib)
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

    adapter = IBKRLiveAdapter(ib)
    await adapter.subscribe("AAPL", "STK", "SMART", AsyncMock(), AsyncMock())

    ib.reqRealTimeBars.assert_called_once()
    ib.reqMktData.assert_called_once()


@pytest.mark.asyncio
async def test_subscribe_skips_when_not_connected():
    from live_scanner.ibkr_adapter import IBKRLiveAdapter

    ib = _make_ib(connected=False)
    adapter = IBKRLiveAdapter(ib)
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

    adapter = IBKRLiveAdapter(ib)
    await adapter.subscribe("AAPL", "STK", "SMART", AsyncMock(), AsyncMock())
    await adapter.unsubscribe("AAPL")

    ib.cancelRealTimeBars.assert_called_once_with(bar_list)
    ib.cancelMktData.assert_called_once_with(ticker)


@pytest.mark.asyncio
async def test_unsubscribe_unknown_symbol_is_noop():
    from live_scanner.ibkr_adapter import IBKRLiveAdapter

    adapter = IBKRLiveAdapter(_make_ib())
    await adapter.unsubscribe("UNKNOWN")  # must not raise


@pytest.mark.asyncio
async def test_disconnect_calls_ib_disconnect():
    from live_scanner.ibkr_adapter import IBKRLiveAdapter

    ib = _make_ib()
    adapter = IBKRLiveAdapter(ib)
    await adapter.disconnect()
    ib.disconnect.assert_called_once()
