# backend/tests/tasks/test_paper_exit.py
from decimal import Decimal
from unittest.mock import ANY, MagicMock, patch

import app.tasks.trading as tasks_module
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
        client.get_snapshot_ticker.return_value = _make_snapshot(
            last_trade_price=123.45
        )
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


def _make_order(
    status="open",
    side="long",
    calculated_stop=95.0,
    calculated_target=110.0,
    fill_price=100.0,
    symbol="AAPL",
):
    order = MagicMock()
    order.id = 1
    order.status = status
    order.side = side
    order.symbol = symbol
    order.calculated_stop = Decimal(str(calculated_stop))
    order.calculated_target = Decimal(str(calculated_target))
    order.fill_price = Decimal(str(fill_price))
    return order


class TestSimulatePaperExit:
    def _run(self, order, snapshot_price):
        db = MagicMock()
        now = MagicMock()
        mock_provider = MagicMock()
        mock_provider.get_snapshot_price.return_value = snapshot_price

        with (
            patch("app.providers.DataProviderFactory") as mock_factory,
            patch("app.tasks.trading._record_exit_fill") as mock_exit,
        ):
            mock_factory.get_or_none.return_value = mock_provider
            tasks_module._simulate_paper_exit(order, db, now)
            return mock_exit

    def test_long_target_hit_closes_as_target(self):
        order = _make_order(side="long", calculated_target=110.0, calculated_stop=95.0)
        mock_exit = self._run(order, snapshot_price=111.0)
        mock_exit.assert_called_once_with(order, ANY, "target", ANY, ANY)

    def test_long_stop_hit_closes_as_stop(self):
        order = _make_order(side="long", calculated_target=110.0, calculated_stop=95.0)
        mock_exit = self._run(order, snapshot_price=94.0)
        mock_exit.assert_called_once_with(order, ANY, "stop", ANY, ANY)

    def test_long_price_between_levels_no_exit(self):
        order = _make_order(side="long", calculated_target=110.0, calculated_stop=95.0)
        mock_exit = self._run(order, snapshot_price=102.0)
        mock_exit.assert_not_called()

    def test_short_price_between_levels_no_exit(self):
        order = _make_order(side="short", calculated_target=90.0, calculated_stop=105.0)
        mock_exit = self._run(order, snapshot_price=97.0)
        mock_exit.assert_not_called()

    def test_short_target_hit_closes_as_target(self):
        order = _make_order(side="short", calculated_target=90.0, calculated_stop=105.0)
        mock_exit = self._run(order, snapshot_price=89.0)
        mock_exit.assert_called_once_with(order, ANY, "target", ANY, ANY)

    def test_short_stop_hit_closes_as_stop(self):
        order = _make_order(side="short", calculated_target=90.0, calculated_stop=105.0)
        mock_exit = self._run(order, snapshot_price=106.0)
        mock_exit.assert_called_once_with(order, ANY, "stop", ANY, ANY)

    def test_no_price_available_skips_silently(self):
        order = _make_order()
        mock_exit = self._run(order, snapshot_price=None)
        mock_exit.assert_not_called()

    def test_no_provider_skips_silently(self):
        order = _make_order()
        db = MagicMock()
        now = MagicMock()
        with (
            patch("app.providers.DataProviderFactory") as mock_factory,
            patch("app.tasks.trading._record_exit_fill") as mock_exit,
        ):
            mock_factory.get_or_none.return_value = None
            tasks_module._simulate_paper_exit(order, db, now)
            mock_exit.assert_not_called()

    def test_exit_price_equals_snapshot_price(self):
        order = _make_order(side="long", calculated_target=110.0, calculated_stop=95.0)
        mock_exit = self._run(order, snapshot_price=115.0)
        mock_exit.assert_called_once_with(order, 115.0, ANY, ANY, ANY)
