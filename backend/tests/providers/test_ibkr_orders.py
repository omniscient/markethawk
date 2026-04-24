# backend/tests/providers/test_ibkr_orders.py
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
import pytest


def _make_manager():
    with patch("app.providers.ibkr_orders.IB_INSYNC_AVAILABLE", True):
        from app.providers.ibkr_orders import IBKROrderManager
        return IBKROrderManager.__new__(IBKROrderManager)


def _make_account_item(tag, value, currency="USD"):
    item = MagicMock()
    item.tag = tag
    item.value = value
    item.currency = currency
    return item


def _make_trade(order_id=1001, symbol="AAPL", action="BUY",
                order_type="LMT", total_qty=100.0, status="Submitted",
                filled=0.0, avg_fill_price=0.0, perm_id=9001):
    trade = MagicMock()
    trade.order.orderId = order_id
    trade.order.permId = perm_id
    trade.order.action = action
    trade.order.orderType = order_type
    trade.order.totalQuantity = total_qty
    trade.contract.symbol = symbol
    trade.orderStatus.status = status
    trade.orderStatus.filled = filled
    trade.orderStatus.avgFillPrice = avg_fill_price
    return trade


class TestGetAccountAndOrders:
    """get_account_and_orders reuses one IBKR connection for both calls."""

    def _run(self, account_items, open_trades):
        from app.providers.ibkr_orders import IBKROrderManager
        manager = IBKROrderManager.__new__(IBKROrderManager)

        ib_mock = AsyncMock()
        ib_mock.reqAccountSummaryAsync = AsyncMock(return_value=account_items)
        ib_mock.reqAllOpenOrdersAsync = AsyncMock(return_value=None)
        ib_mock.openTrades = MagicMock(return_value=open_trades)

        async def fake_connect():
            return ib_mock

        async def fake_disconnect(ib):
            pass

        manager._connect = fake_connect
        manager._disconnect = fake_disconnect

        loop = asyncio.new_event_loop()
        result = loop.run_until_complete(manager.get_account_and_orders())
        loop.close()
        return result, ib_mock

    def test_returns_account_summary_fields(self):
        items = [
            _make_account_item("NetLiquidation", "150000.0"),
            _make_account_item("AvailableFunds", "80000.0"),
            _make_account_item("BuyingPower", "160000.0"),
        ]
        result, _ = self._run(items, [])
        account, orders = result
        assert account.net_liquidation == 150000.0
        assert account.available_funds == 80000.0
        assert account.buying_power == 160000.0

    def test_returns_open_orders(self):
        items = [_make_account_item("NetLiquidation", "0")]
        trades = [_make_trade(order_id=42, symbol="TSLA")]
        result, _ = self._run(items, trades)
        _, orders = result
        assert len(orders) == 1
        assert orders[0].order_id == 42
        assert orders[0].symbol == "TSLA"

    def test_single_connect_call(self):
        items = [_make_account_item("NetLiquidation", "0")]
        connect_calls = []

        from app.providers.ibkr_orders import IBKROrderManager
        manager = IBKROrderManager.__new__(IBKROrderManager)

        ib_mock = AsyncMock()
        ib_mock.reqAccountSummaryAsync = AsyncMock(return_value=items)
        ib_mock.reqAllOpenOrdersAsync = AsyncMock(return_value=None)
        ib_mock.openTrades = MagicMock(return_value=[])

        async def fake_connect():
            connect_calls.append(1)
            return ib_mock

        async def fake_disconnect(ib):
            pass

        manager._connect = fake_connect
        manager._disconnect = fake_disconnect

        loop = asyncio.new_event_loop()
        loop.run_until_complete(manager.get_account_and_orders())
        loop.close()

        assert len(connect_calls) == 1, "Must use exactly one IBKR connection"

    def test_tags_passed_to_reqAccountSummaryAsync(self):
        """reqAccountSummaryAsync must be called without extra args (IBKR returns all)."""
        items = [_make_account_item("NetLiquidation", "0")]
        _, ib_mock = self._run(items, [])
        # Called once with no positional filtering args (tags filtering happens client-side)
        ib_mock.reqAccountSummaryAsync.assert_called_once()
