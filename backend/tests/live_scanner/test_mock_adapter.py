import asyncio
from unittest.mock import patch

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


# ── New chaos-test methods ─────────────────────────────────────────────────


def test_mock_adapter_is_connected_starts_true():
    assert MockLiveAdapter().is_connected() is True


def test_mock_adapter_wire_disconnect_queue_stores_state():
    adapter = MockLiveAdapter()
    queue = asyncio.Queue()
    loop = asyncio.new_event_loop()
    try:
        adapter.wire_disconnect_queue(queue, "disconnect", loop)
        assert adapter._queue is queue
        assert adapter._disconnect_tag == "disconnect"
        assert adapter._loop is loop
    finally:
        loop.close()


@pytest.mark.asyncio
async def test_simulate_disconnect_sets_not_connected():
    adapter = MockLiveAdapter()
    queue = asyncio.Queue()
    loop = asyncio.get_event_loop()
    adapter.wire_disconnect_queue(queue, "disconnect", loop)
    adapter.simulate_disconnect()
    assert adapter.is_connected() is False


@pytest.mark.asyncio
async def test_simulate_disconnect_puts_tag_on_queue():
    adapter = MockLiveAdapter()
    queue = asyncio.Queue()
    loop = asyncio.get_event_loop()
    adapter.wire_disconnect_queue(queue, "disconnect", loop)

    adapter.simulate_disconnect()
    await asyncio.sleep(0)  # let call_soon_threadsafe flush

    assert not queue.empty()
    tag, a, b = queue.get_nowait()
    assert tag == "disconnect"
    assert a is None and b is None


@pytest.mark.asyncio
async def test_mock_adapter_reconnect_returns_true():
    adapter = MockLiveAdapter()
    result = await adapter.reconnect()
    assert result is True
    assert adapter.is_connected() is True


def test_force_disconnect_delegates_to_simulate_disconnect():
    adapter = MockLiveAdapter()
    with patch.object(adapter, "simulate_disconnect") as mock_sim:
        adapter.force_disconnect()
    mock_sim.assert_called_once()


@pytest.mark.asyncio
async def test_subscribe_sets_connected_true_after_simulate_disconnect():
    adapter = MockLiveAdapter()
    queue = asyncio.Queue()
    loop = asyncio.get_event_loop()
    adapter.wire_disconnect_queue(queue, "disconnect", loop)
    adapter.simulate_disconnect()
    assert not adapter.is_connected()
    await adapter.subscribe(
        "SPY", "STK", "SMART", on_bar=lambda s, b: None, on_quote=lambda s, q: None
    )
    assert adapter.is_connected()
