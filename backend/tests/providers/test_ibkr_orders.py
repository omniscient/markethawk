# backend/tests/providers/test_ibkr_orders.py
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Patch target for the Redis kill-switch check in ibkr_orders.
KS_REDIS_PATCH = "app.providers.ibkr_orders.redis.from_url"


def _ks_redis_no_ks():
    """Mock Redis client that returns None for trading:kill_switch (not engaged)."""
    client = MagicMock()
    client.get = MagicMock(return_value=None)
    return client


def _ks_redis_engaged_val(val="1"):
    """Mock Redis client that returns *val* for trading:kill_switch (engaged)."""
    client = MagicMock()
    client.get = MagicMock(return_value=val)
    return client


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


def _make_trade(
    order_id=1001,
    symbol="AAPL",
    action="BUY",
    order_type="LMT",
    total_qty=100.0,
    status="Submitted",
    filled=0.0,
    avg_fill_price=0.0,
    perm_id=9001,
):
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


class TestPlaceBracketOrderGuards:
    """Non-bypassable guards at the top of place_bracket_order (R1 / R2)."""

    def _make_manager(self):
        with patch("app.providers.ibkr_orders.IB_INSYNC_AVAILABLE", True):
            from app.providers.ibkr_orders import IBKROrderManager

            return IBKROrderManager.__new__(IBKROrderManager)

    def _armed_settings(self):
        """Settings mock: LIVE_TRADING_ARMED=True, conservative caps."""
        s = MagicMock()
        s.LIVE_TRADING_ARMED = True
        s.TRADING_KILL_SWITCH = False
        s.MAX_ORDER_NOTIONAL = 10_000.0
        s.MAX_ORDER_QTY = 200
        s.IBKR_HOST = "127.0.0.1"
        s.IBKR_PORT = 7496
        s.IBKR_TRADING_CLIENT_ID = 11
        return s

    def _run(
        self,
        manager,
        quantity=10,
        entry_price=100.0,
        stop_price=95.0,
        target_price=110.0,
    ):
        import asyncio as _asyncio

        loop = _asyncio.new_event_loop()
        try:
            return loop.run_until_complete(
                manager.place_bracket_order(
                    symbol="AAPL",
                    side="long",
                    quantity=quantity,
                    entry_price=entry_price,
                    stop_price=stop_price,
                    target_price=target_price,
                )
            )
        finally:
            loop.close()

    def _attach_ib_mock(self, manager):
        """Wire a disconnected IB mock so _connect never touches the network."""
        ib_mock = MagicMock()
        ib_mock.placeOrder = MagicMock()

        async def fake_connect():
            return ib_mock

        async def fake_disconnect(ib):
            pass

        manager._connect = fake_connect
        manager._disconnect = fake_disconnect
        return ib_mock

    def test_place_bracket_order_kill_switch(self):
        """TRADING_KILL_SWITCH=true must raise PermissionError; placeOrder not called.

        Env deny-list fires before the Redis check so no Redis mock needed here.
        """
        import os as _os

        manager = self._make_manager()
        ib_mock = self._attach_ib_mock(manager)

        with patch.dict(_os.environ, {"TRADING_KILL_SWITCH": "true"}):
            with pytest.raises(PermissionError, match="kill switch"):
                self._run(manager)

        ib_mock.placeOrder.assert_not_called()

    def test_place_bracket_order_not_armed(self):
        """LIVE_TRADING_ARMED=False (test default via conftest.py) must raise PermissionError.

        Redis is mocked to not engage the kill switch so the LIVE_TRADING_ARMED guard fires.
        """
        import os as _os

        manager = self._make_manager()
        ib_mock = self._attach_ib_mock(manager)

        # conftest.py sets LIVE_TRADING_ARMED=false; disable env kill switch, mock Redis ok
        with (
            patch.dict(_os.environ, {"TRADING_KILL_SWITCH": ""}),
            patch(KS_REDIS_PATCH, return_value=_ks_redis_no_ks()),
        ):
            with pytest.raises(PermissionError, match="LIVE_TRADING_ARMED"):
                self._run(manager)

        ib_mock.placeOrder.assert_not_called()

    def test_place_bracket_order_notional_cap(self):
        """qty=100 * max-price=200.0 → notional=20_000 > 10_000 cap → ValueError."""
        import os as _os

        manager = self._make_manager()
        ib_mock = self._attach_ib_mock(manager)

        with (
            patch("app.providers.ibkr_orders.settings", self._armed_settings()),
            patch.dict(_os.environ, {"TRADING_KILL_SWITCH": ""}),
            patch(KS_REDIS_PATCH, return_value=_ks_redis_no_ks()),
        ):
            with pytest.raises(ValueError, match="notional cap"):
                self._run(manager, quantity=100, entry_price=200.0)

        ib_mock.placeOrder.assert_not_called()

    def test_place_bracket_order_qty_cap(self):
        """qty=300 > 200 cap → ValueError for quantity cap.

        Prices are chosen so that qty * max(entry, target, stop) stays under the
        notional cap (300 * 12.0 = 3600 < 10000), ensuring ONLY the qty guard fires.
        """
        import os as _os

        manager = self._make_manager()
        ib_mock = self._attach_ib_mock(manager)

        with (
            patch("app.providers.ibkr_orders.settings", self._armed_settings()),
            patch.dict(_os.environ, {"TRADING_KILL_SWITCH": ""}),
            patch(KS_REDIS_PATCH, return_value=_ks_redis_no_ks()),
        ):
            with pytest.raises(ValueError, match="quantity cap"):
                import asyncio as _asyncio

                loop = _asyncio.new_event_loop()
                try:
                    loop.run_until_complete(
                        manager.place_bracket_order(
                            symbol="AAPL",
                            side="long",
                            quantity=300,
                            entry_price=10.0,
                            stop_price=9.0,  # max(10, 9, 12) = 12; 300*12 = 3600 < 10000
                            target_price=12.0,
                        )
                    )
                finally:
                    loop.close()

        ib_mock.placeOrder.assert_not_called()

    # ── New kill-switch tests ─────────────────────────────────────────────────

    def test_kill_switch_redis_flag_halts(self):
        """Redis trading:kill_switch='1' → PermissionError; placeOrder not called."""
        import os as _os

        manager = self._make_manager()
        ib_mock = self._attach_ib_mock(manager)

        with (
            patch.dict(_os.environ, {"TRADING_KILL_SWITCH": ""}),
            patch(KS_REDIS_PATCH, return_value=_ks_redis_engaged_val("1")),
        ):
            with pytest.raises(PermissionError, match="kill switch"):
                self._run(manager)

        ib_mock.placeOrder.assert_not_called()

    def test_kill_switch_redis_flag_truthy_string_halts(self):
        """Redis trading:kill_switch='true' → PermissionError."""
        import os as _os

        manager = self._make_manager()
        ib_mock = self._attach_ib_mock(manager)

        with (
            patch.dict(_os.environ, {"TRADING_KILL_SWITCH": ""}),
            patch(KS_REDIS_PATCH, return_value=_ks_redis_engaged_val("true")),
        ):
            with pytest.raises(PermissionError, match="kill switch"):
                self._run(manager)

        ib_mock.placeOrder.assert_not_called()

    def test_kill_switch_redis_absent_proceeds_past_ks(self):
        """Redis returns None (key absent) → kill switch not engaged; reaches LIVE_TRADING_ARMED check."""
        import os as _os

        manager = self._make_manager()
        ib_mock = self._attach_ib_mock(manager)

        # Redis ok but LIVE_TRADING_ARMED=false (conftest default) → PermissionError about ARMED, not kill switch
        with (
            patch.dict(_os.environ, {"TRADING_KILL_SWITCH": ""}),
            patch(KS_REDIS_PATCH, return_value=_ks_redis_no_ks()),
        ):
            with pytest.raises(PermissionError) as exc_info:
                self._run(manager)

        # Must NOT be a kill-switch error — confirms the kill switch guard passed
        assert "kill switch" not in str(exc_info.value).lower()
        ib_mock.placeOrder.assert_not_called()

    def test_kill_switch_redis_unreachable_fails_closed(self):
        """Redis raises ConnectionError → fail-closed: PermissionError raised, placeOrder not called."""
        import os as _os

        manager = self._make_manager()
        ib_mock = self._attach_ib_mock(manager)

        def _raise_connection_error(*args, **kwargs):
            raise ConnectionError("Redis connection refused")

        with (
            patch.dict(_os.environ, {"TRADING_KILL_SWITCH": ""}),
            patch(KS_REDIS_PATCH, side_effect=_raise_connection_error),
        ):
            with pytest.raises(PermissionError, match="kill switch"):
                self._run(manager)

        ib_mock.placeOrder.assert_not_called()

    def test_kill_switch_env_deny_list_on_halts(self):
        """TRADING_KILL_SWITCH='on' is not in allow-list → PermissionError (no Redis call needed)."""
        import os as _os

        manager = self._make_manager()
        ib_mock = self._attach_ib_mock(manager)

        with patch.dict(_os.environ, {"TRADING_KILL_SWITCH": "on"}):
            with pytest.raises(PermissionError, match="kill switch"):
                self._run(manager)

        ib_mock.placeOrder.assert_not_called()

    def test_kill_switch_env_deny_list_stop_halts(self):
        """TRADING_KILL_SWITCH='stop' is not in allow-list → PermissionError."""
        import os as _os

        manager = self._make_manager()
        ib_mock = self._attach_ib_mock(manager)

        with patch.dict(_os.environ, {"TRADING_KILL_SWITCH": "stop"}):
            with pytest.raises(PermissionError, match="kill switch"):
                self._run(manager)

        ib_mock.placeOrder.assert_not_called()

    def test_kill_switch_env_deny_list_space_true_halts(self):
        """TRADING_KILL_SWITCH=' true ' (with spaces) → stripped 'true' not in allow-list → PermissionError."""
        import os as _os

        manager = self._make_manager()
        ib_mock = self._attach_ib_mock(manager)

        with patch.dict(_os.environ, {"TRADING_KILL_SWITCH": " true "}):
            with pytest.raises(PermissionError, match="kill switch"):
                self._run(manager)

        ib_mock.placeOrder.assert_not_called()

    def test_kill_switch_env_allow_list_false_passes(self):
        """TRADING_KILL_SWITCH='false' is in allow-list → env not engaged; reaches LIVE_TRADING_ARMED."""
        import os as _os

        manager = self._make_manager()
        ib_mock = self._attach_ib_mock(manager)

        with (
            patch.dict(_os.environ, {"TRADING_KILL_SWITCH": "false"}),
            patch(KS_REDIS_PATCH, return_value=_ks_redis_no_ks()),
        ):
            with pytest.raises(PermissionError) as exc_info:
                self._run(manager)

        assert "kill switch" not in str(exc_info.value).lower()
        ib_mock.placeOrder.assert_not_called()

    def test_kill_switch_env_allow_list_zero_passes(self):
        """TRADING_KILL_SWITCH='0' is in allow-list → env not engaged; reaches LIVE_TRADING_ARMED."""
        import os as _os

        manager = self._make_manager()
        ib_mock = self._attach_ib_mock(manager)

        with (
            patch.dict(_os.environ, {"TRADING_KILL_SWITCH": "0"}),
            patch(KS_REDIS_PATCH, return_value=_ks_redis_no_ks()),
        ):
            with pytest.raises(PermissionError) as exc_info:
                self._run(manager)

        assert "kill switch" not in str(exc_info.value).lower()
        ib_mock.placeOrder.assert_not_called()

    # ── Notional cap / bounds guard new tests ─────────────────────────────────

    def test_notional_cap_short_market_order_uses_max_price(self):
        """SHORT market order: entry=None, target=80.0, stop=110.0.

        Old code: notional = qty * target = 90 * 80 = 7_200 (under 10_000 cap → passes).
        New code: price_basis = max(None-excluded, 80.0, 110.0) = 110.0.
                  notional = 90 * 110 = 9_900 (under cap → still passes).

        Use qty=100, stop=105 so new code rejects (100*105=10_500 > 10_000).
        """
        import os as _os

        manager = self._make_manager()
        ib_mock = self._attach_ib_mock(manager)

        armed = self._armed_settings()

        with (
            patch("app.providers.ibkr_orders.settings", armed),
            patch.dict(_os.environ, {"TRADING_KILL_SWITCH": ""}),
            patch(KS_REDIS_PATCH, return_value=_ks_redis_no_ks()),
        ):
            # qty=100, entry=None (market), target=80.0, stop=105.0
            # old notional = 100 * 80 = 8_000 (would PASS old cap)
            # new notional = 100 * max(80.0, 105.0) = 100 * 105 = 10_500 (EXCEEDS new cap)
            with pytest.raises(ValueError, match="notional cap"):
                import asyncio as _asyncio

                loop = _asyncio.new_event_loop()
                try:
                    loop.run_until_complete(
                        manager.place_bracket_order(
                            symbol="TSLA",
                            side="short",
                            quantity=100,
                            entry_price=None,  # market order
                            stop_price=105.0,
                            target_price=80.0,
                        )
                    )
                finally:
                    loop.close()

        ib_mock.placeOrder.assert_not_called()

    def test_quantity_zero_raises(self):
        """quantity=0 must raise ValueError."""
        import os as _os

        manager = self._make_manager()
        ib_mock = self._attach_ib_mock(manager)

        armed = self._armed_settings()

        with (
            patch("app.providers.ibkr_orders.settings", armed),
            patch.dict(_os.environ, {"TRADING_KILL_SWITCH": ""}),
            patch(KS_REDIS_PATCH, return_value=_ks_redis_no_ks()),
        ):
            with pytest.raises(ValueError, match="quantity must be positive"):
                self._run(manager, quantity=0, entry_price=100.0)

        ib_mock.placeOrder.assert_not_called()

    def test_quantity_negative_raises(self):
        """quantity=-1 must raise ValueError."""
        import os as _os

        manager = self._make_manager()
        ib_mock = self._attach_ib_mock(manager)

        armed = self._armed_settings()

        with (
            patch("app.providers.ibkr_orders.settings", armed),
            patch.dict(_os.environ, {"TRADING_KILL_SWITCH": ""}),
            patch(KS_REDIS_PATCH, return_value=_ks_redis_no_ks()),
        ):
            with pytest.raises(ValueError, match="quantity must be positive"):
                self._run(manager, quantity=-1, entry_price=100.0)

        ib_mock.placeOrder.assert_not_called()

    def test_effective_price_zero_raises(self):
        """entry=None, target=0.0, stop=0.0 → price_basis=0 → ValueError."""
        import os as _os

        manager = self._make_manager()
        ib_mock = self._attach_ib_mock(manager)

        armed = self._armed_settings()

        with (
            patch("app.providers.ibkr_orders.settings", armed),
            patch.dict(_os.environ, {"TRADING_KILL_SWITCH": ""}),
            patch(KS_REDIS_PATCH, return_value=_ks_redis_no_ks()),
        ):
            with pytest.raises(ValueError, match="price basis must be positive"):
                import asyncio as _asyncio

                loop = _asyncio.new_event_loop()
                try:
                    loop.run_until_complete(
                        manager.place_bracket_order(
                            symbol="AAPL",
                            side="long",
                            quantity=10,
                            entry_price=None,
                            stop_price=0.0,
                            target_price=0.0,
                        )
                    )
                finally:
                    loop.close()

        ib_mock.placeOrder.assert_not_called()
