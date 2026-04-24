# backend/tests/tasks/test_paper_exit.py
from unittest.mock import MagicMock, patch
from app.providers.massive import MassiveDataProvider


def _make_provider(client=None):
    """Return a MassiveDataProvider with a mocked internal client."""
    p = MassiveDataProvider.__new__(MassiveDataProvider)
    p._client = client
    return p


def _make_snapshot(last_trade_price=None, day_close=None):
    snap = MagicMock()
    if last_trade_price is not None:
        snap.last_trade = MagicMock()
        snap.last_trade.price = last_trade_price
    else:
        snap.last_trade = None
    if day_close is not None:
        snap.day = MagicMock()
        snap.day.close = day_close
    else:
        snap.day = None
    return snap


class TestGetSnapshotPrice:
    def test_returns_last_trade_price(self):
        client = MagicMock()
        client.get_snapshot_ticker.return_value = _make_snapshot(last_trade_price=123.45)
        p = _make_provider(client)
        assert p.get_snapshot_price("AAPL") == 123.45

    def test_falls_back_to_day_close_when_no_last_trade(self):
        client = MagicMock()
        client.get_snapshot_ticker.return_value = _make_snapshot(day_close=99.0)
        p = _make_provider(client)
        assert p.get_snapshot_price("AAPL") == 99.0

    def test_returns_none_when_no_price_available(self):
        client = MagicMock()
        client.get_snapshot_ticker.return_value = _make_snapshot()
        p = _make_provider(client)
        assert p.get_snapshot_price("AAPL") is None

    def test_returns_none_when_client_not_initialized(self):
        p = _make_provider(client=None)
        assert p.get_snapshot_price("AAPL") is None

    def test_returns_none_on_exception(self):
        client = MagicMock()
        client.get_snapshot_ticker.side_effect = Exception("network error")
        p = _make_provider(client)
        assert p.get_snapshot_price("AAPL") is None

    def test_delegates_to_get_snapshot_ticker_correctly(self):
        client = MagicMock()
        client.get_snapshot_ticker.return_value = _make_snapshot(last_trade_price=50.0)
        p = _make_provider(client)
        p.get_snapshot_price("TSLA")
        client.get_snapshot_ticker.assert_called_once_with("stocks", "TSLA")
