"""Unit tests for trading.py Celery task shells."""

from decimal import Decimal
from unittest.mock import MagicMock, patch


class TestExecuteAutoTrade:
    def _run(self, rule=None, event=None):
        import app.tasks.trading as trading_module

        db = MagicMock()
        call_count = [0]

        def _query_side(model):
            q = MagicMock()
            if call_count[0] == 0:
                q.filter.return_value.first.return_value = rule
            else:
                q.filter.return_value.first.return_value = event
            call_count[0] += 1
            return q

        db.query.side_effect = _query_side

        def _retry_reraises(exc, **kw):
            raise exc

        with (
            patch("app.tasks.trading.SessionLocal", return_value=db),
            patch(
                "app.services.auto_trade_service.auto_trade_executor"
            ) as mock_executor,
            patch.object(
                trading_module.execute_auto_trade, "retry", side_effect=_retry_reraises
            ),
        ):
            trading_module.execute_auto_trade.run(rule_id=1, scanner_event_id=2)
            return mock_executor, db

    def test_rule_not_found_returns_without_execute(self):
        mock_executor, _ = self._run(rule=None, event=MagicMock())
        mock_executor.maybe_execute.assert_not_called()

    def test_event_not_found_returns_without_execute(self):
        mock_executor, _ = self._run(rule=MagicMock(), event=None)
        mock_executor.maybe_execute.assert_not_called()

    def test_success_calls_maybe_execute(self):
        rule = MagicMock()
        event = MagicMock()
        event.ticker = "AAPL"
        mock_executor, _ = self._run(rule=rule, event=event)
        mock_executor.maybe_execute.assert_called_once()


class TestSubmitApprovedOrder:
    def _run(self, order=None):
        import app.tasks.trading as trading_module

        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = order

        def _retry_reraises(exc, **kw):
            raise exc

        with (
            patch("app.tasks.trading.SessionLocal", return_value=db),
            patch(
                "app.services.auto_trade_service.auto_trade_executor"
            ) as mock_executor,
            patch.object(
                trading_module.submit_approved_order,
                "retry",
                side_effect=_retry_reraises,
            ),
        ):
            trading_module.submit_approved_order.run(order_id=5)
            return mock_executor, db

    def test_order_not_found_returns_without_submit(self):
        mock_executor, _ = self._run(order=None)
        mock_executor.submit_existing_order.assert_not_called()

    def test_wrong_status_returns_without_submit(self):
        order = MagicMock()
        order.id = 5
        order.status = "open"  # not "pending"
        mock_executor, _ = self._run(order=order)
        mock_executor.submit_existing_order.assert_not_called()

    def test_pending_order_calls_submit(self):
        import app.tasks.trading as trading_module

        order = MagicMock()
        order.id = 5
        order.status = "pending"

        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = order

        def _retry_reraises(exc, **kw):
            raise exc

        with (
            patch("app.tasks.trading.SessionLocal", return_value=db),
            patch(
                "app.services.auto_trade_service.auto_trade_executor"
            ) as mock_executor,
            patch.object(
                trading_module.submit_approved_order,
                "retry",
                side_effect=_retry_reraises,
            ),
        ):
            trading_module.submit_approved_order.run(order_id=5)

        mock_executor.submit_existing_order.assert_called_once_with(order, db)


class TestPollAutoTradeFillsPaperPath:
    def test_no_pending_orders_returns_early(self):
        import app.tasks.trading as trading_module

        db = MagicMock()
        db.query.return_value.filter.return_value.all.return_value = []

        with patch("app.tasks.trading.SessionLocal", return_value=db):
            trading_module.poll_auto_trade_fills.run()

        # No calls to _record_entry_fill or _simulate_paper_exit expected

    def test_submitted_paper_order_calls_record_entry_fill(self):
        import app.tasks.trading as trading_module

        order = MagicMock()
        order.status = "submitted"
        order.is_paper = True
        order.trigger_price = Decimal("100.0")
        order.entry_price_target = None

        db = MagicMock()
        db.query.return_value.filter.return_value.all.return_value = [order]

        with (
            patch("app.tasks.trading.SessionLocal", return_value=db),
            patch("app.tasks.trading._record_entry_fill") as mock_fill,
        ):
            trading_module.poll_auto_trade_fills.run()

        mock_fill.assert_called_once()
        args = mock_fill.call_args[0]
        assert args[0] is order
        assert args[1] == 100.0  # fill_price from trigger_price

    def test_open_paper_order_calls_simulate_paper_exit(self):
        import app.tasks.trading as trading_module

        order = MagicMock()
        order.status = "open"
        order.is_paper = True

        db = MagicMock()
        db.query.return_value.filter.return_value.all.return_value = [order]

        with (
            patch("app.tasks.trading.SessionLocal", return_value=db),
            patch("app.tasks.trading._simulate_paper_exit") as mock_exit,
        ):
            trading_module.poll_auto_trade_fills.run()

        mock_exit.assert_called_once()
