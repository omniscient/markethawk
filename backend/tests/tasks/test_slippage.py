# backend/tests/tasks/test_slippage.py
from decimal import Decimal
from unittest.mock import ANY, MagicMock, patch
import app.tasks.trading as tasks_module


def _make_order(entry_price_target=100.0, max_slippage_pct=0.5):
    order = MagicMock()
    order.id = 42
    order.symbol = "AAPL"
    order.side = "long"
    order.entry_price_target = Decimal(str(entry_price_target))
    order.status = "submitted"

    strategy = MagicMock()
    strategy.max_slippage_pct = Decimal(str(max_slippage_pct))
    order.trading_strategy = strategy

    return order


class TestCheckEntrySlippage:
    def _run(self, order, fill_price, mock_record=None):
        db = MagicMock()
        now = MagicMock()
        with patch("app.tasks.trading._record_entry_fill") as mock_fill:
            tasks_module._check_entry_slippage(order, fill_price, now, db)
            return mock_fill, db, now

    def test_fill_within_tolerance_records_entry(self):
        order = _make_order(entry_price_target=100.0, max_slippage_pct=0.5)
        # 100.3 → 0.3% slippage < 0.5% limit
        mock_fill, db, now = self._run(order, 100.3)
        mock_fill.assert_called_once_with(order, 100.3, now, db)

    def test_fill_exceeds_tolerance_rejects_order(self):
        order = _make_order(entry_price_target=100.0, max_slippage_pct=0.5)
        # 101.0 → 1.0% slippage > 0.5% limit
        mock_fill, db, _ = self._run(order, 101.0)
        mock_fill.assert_not_called()
        assert order.status == "rejected"
        db.commit.assert_called_once()

    def test_fill_at_exact_tolerance_is_accepted(self):
        order = _make_order(entry_price_target=100.0, max_slippage_pct=0.5)
        # 100.5 → exactly 0.5% — on the boundary, accept
        mock_fill, _, _ = self._run(order, 100.5)
        mock_fill.assert_called_once()

    def test_rejection_reason_mentions_slippage(self):
        order = _make_order(entry_price_target=100.0, max_slippage_pct=0.5)
        self._run(order, 102.0)
        assert order.rejection_reason is not None
        assert "slippage" in order.rejection_reason.lower()

    def test_no_strategy_bypasses_check(self):
        order = _make_order()
        order.trading_strategy = None
        mock_fill, _, now = self._run(order, 110.0)
        mock_fill.assert_called_once_with(order, 110.0, now, ANY)

    def test_no_entry_price_target_bypasses_check(self):
        order = _make_order()
        order.entry_price_target = None
        mock_fill, _, now = self._run(order, 100.0)
        mock_fill.assert_called_once_with(order, 100.0, now, ANY)

    def test_short_side_negative_slippage_is_caught(self):
        # Short: fill below target is favorable; fill above target is slippage
        order = _make_order(entry_price_target=100.0, max_slippage_pct=0.5)
        order.side = "short"
        # Fill at 99.0 → short side fills lower, abs slippage 1.0% > 0.5%
        mock_fill, db, _ = self._run(order, 99.0)
        mock_fill.assert_not_called()
        assert order.status == "rejected"


