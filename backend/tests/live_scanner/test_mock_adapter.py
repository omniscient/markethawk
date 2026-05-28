import pytest
from live_scanner.mock_adapter import MockLiveAdapter
from live_scanner.provider import LiveDataProvider


def test_mock_satisfies_protocol():
    adapter = MockLiveAdapter()
    assert isinstance(adapter, LiveDataProvider)


@pytest.mark.asyncio
async def test_fetch_seed_data_returns_fixed_values():
    adapter = MockLiveAdapter()
    prior_close, avg_vol = await adapter.fetch_seed_data("AAPL", "STK", "SMART")
    assert prior_close == 100.0
    assert avg_vol == 500_000.0


@pytest.mark.asyncio
async def test_subscribe_accepts_without_error():
    adapter = MockLiveAdapter()

    async def noop_bar(sym, bar):
        pass

    async def noop_quote(sym, quote):
        pass

    await adapter.subscribe(
        "AAPL", "STK", "SMART", on_bar=noop_bar, on_quote=noop_quote
    )
    assert "AAPL" in adapter.subscribed


@pytest.mark.asyncio
async def test_unsubscribe_removes_symbol():
    adapter = MockLiveAdapter()

    async def noop_bar(sym, bar):
        pass

    async def noop_quote(sym, quote):
        pass

    await adapter.subscribe(
        "AAPL", "STK", "SMART", on_bar=noop_bar, on_quote=noop_quote
    )
    await adapter.unsubscribe("AAPL")
    assert "AAPL" not in adapter.subscribed


@pytest.mark.asyncio
async def test_disconnect_clears_subscriptions():
    adapter = MockLiveAdapter()

    async def noop_bar(sym, bar):
        pass

    async def noop_quote(sym, quote):
        pass

    await adapter.subscribe(
        "AAPL", "STK", "SMART", on_bar=noop_bar, on_quote=noop_quote
    )
    await adapter.disconnect()
    assert len(adapter.subscribed) == 0
