"""
Unit tests for backtest_service._simulate_trade and related helpers.

Tests cover:
- Stop precedence: stop is hit before target, stop wins
- Target precedence: target is hit before stop, target wins
- Conservative intrabar rule: if bar spans both stop and target, stop wins
- Time-stop: position closed after max_hold_sessions
- Delisting/data-end exit: bars run out while position is open
- No entry bar: no bars after signal
- Limit order no-fill: limit entry where open > (entry - offset), no fill
- _compute_stats: win_rate, profit_factor, expectancy_r, max_drawdown_r
"""

from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _bar(open_: float, high: float, low: float, close: float, ts: date | None = None):
    b = MagicMock()
    b.open = open_
    b.high = high
    b.low = low
    b.close = close
    if ts is None:
        ts = date(2026, 1, 2)
    dt = MagicMock()
    dt.year = ts.year
    dt.month = ts.month
    dt.day = ts.day
    b.timestamp = dt
    return b


def _market_entry(**kwargs):
    defaults = dict(entry_type="market", limit_offset_pct=0.0)
    defaults.update(kwargs)
    return defaults


def _run(entry_bar, subsequent_bars, stop_pct=2.0, risk_reward_ratio=2.0, **kwargs):
    from app.services.backtest_service import _simulate_trade

    return _simulate_trade(
        entry_bar=entry_bar,
        subsequent_bars=subsequent_bars,
        stop_pct=stop_pct,
        risk_reward_ratio=risk_reward_ratio,
        entry_type=kwargs.get("entry_type", "market"),
        limit_offset_pct=kwargs.get("limit_offset_pct", 0.0),
        max_hold_sessions=kwargs.get("max_hold_sessions", 10),
    )


# ---------------------------------------------------------------------------
# Stop precedence
# ---------------------------------------------------------------------------


def test_stop_hit_before_target():
    """Bar where only the low touches the stop (high < target): stop exit."""
    # Entry at open=100; stop=2% below=98; target=4% above=104
    entry = _bar(open_=100, high=100, low=100, close=100)
    # Day 2: open 99, low touches stop at 97 (< 98), high = 101 (< 104)
    bar2 = _bar(open_=99, high=101, low=97, close=98)
    entry_price, exit_price, exit_reason, hold, stop_p, target_p = _run(entry, [bar2])

    assert exit_reason == "stop"
    assert exit_price == Decimal("98.0")  # stop price
    assert hold == 1


def test_target_hit_before_stop():
    """Bar where only the high hits the target (low > stop): target exit."""
    entry = _bar(open_=100, high=100, low=100, close=100)
    # Day 2: low=101 (> 98), high=105 (>= 104)
    bar2 = _bar(open_=101, high=105, low=101, close=104)
    entry_price, exit_price, exit_reason, hold, stop_p, target_p = _run(entry, [bar2])

    assert exit_reason == "target"
    assert exit_price == Decimal("104.0")  # target price at 2:1 RR, stop=2%
    assert hold == 1


# ---------------------------------------------------------------------------
# Conservative intrabar rule
# ---------------------------------------------------------------------------


def test_intrabar_both_sides_hit_stop_wins():
    """
    If a bar's low <= stop AND high >= target simultaneously, count the stop.
    This is the conservative intrabar rule required by the spec.
    """
    entry = _bar(open_=100, high=100, low=100, close=100)
    # Bar spans from 96 (below stop=98) to 106 (above target=104)
    both_hit = _bar(open_=100, high=106, low=96, close=100)
    entry_price, exit_price, exit_reason, hold, stop_p, target_p = _run(
        entry, [both_hit]
    )

    assert exit_reason == "stop", f"Expected stop, got {exit_reason}"
    assert exit_price == stop_p
    assert hold == 1


def test_intrabar_only_high_hits():
    """High >= target but low > stop → target exit (no intrabar rule triggered)."""
    entry = _bar(open_=100, high=100, low=100, close=100)
    bar = _bar(open_=100, high=105, low=99, close=104)  # low=99 > stop=98
    _, _, exit_reason, _, _, _ = _run(entry, [bar])
    assert exit_reason == "target"


def test_intrabar_only_low_hits():
    """Low <= stop but high < target → stop exit."""
    entry = _bar(open_=100, high=100, low=100, close=100)
    bar = _bar(open_=99, high=103, low=97, close=99)  # high=103 < target=104
    _, _, exit_reason, _, _, _ = _run(entry, [bar])
    assert exit_reason == "stop"


# ---------------------------------------------------------------------------
# Time-stop
# ---------------------------------------------------------------------------


def test_time_stop_exits_at_next_open():
    """Position held for max_hold_sessions without hitting stop/target → time_stop at NEXT session open."""
    entry = _bar(open_=100, high=100, low=100, close=100)
    # 3 neutral bars + 4th bar providing the time-stop exit open
    bars = [
        _bar(open_=100, high=102, low=99, close=101),
        _bar(open_=101, high=103, low=100, close=102),
        _bar(open_=102, high=103, low=100, close=101),  # hold=3 triggers time_stop
        _bar(open_=103, high=104, low=102, close=103),  # exit at open=103
    ]
    entry_price, exit_price, exit_reason, hold, _, _ = _run(
        entry, bars, max_hold_sessions=3
    )
    assert exit_reason == "time_stop"
    assert exit_price == Decimal("103")  # next session open, NOT last bar close
    assert hold == 3


def test_stop_beats_time_stop_on_same_bar():
    """Stop is hit on the last session bar — stop wins over time_stop."""
    entry = _bar(open_=100, high=100, low=100, close=100)
    bars = [
        _bar(open_=100, high=102, low=99, close=101),
        _bar(open_=101, high=102, low=97, close=98),  # stop hit (low=97 < stop=98)
    ]
    _, _, exit_reason, hold, _, _ = _run(entry, bars, max_hold_sessions=2)
    assert exit_reason == "stop"
    assert hold == 2


# ---------------------------------------------------------------------------
# Delisting / data end
# ---------------------------------------------------------------------------


def test_delisting_exit_at_last_close():
    """Bars end while position open → exit at last close, reason=delisted_or_data_end."""
    entry = _bar(open_=100, high=100, low=100, close=100)
    bars = [
        _bar(open_=100, high=102, low=99, close=101),
        _bar(open_=101, high=103, low=100, close=102),
        # No more bars — delisted
    ]
    entry_price, exit_price, exit_reason, hold, _, _ = _run(
        entry, bars, max_hold_sessions=10
    )
    assert exit_reason == "delisted_or_data_end"
    assert exit_price == Decimal("102")
    assert hold == 2


def test_delisting_with_single_subsequent_bar():
    """Only one bar follows signal and position not resolved → delisted exit."""
    entry = _bar(open_=100, high=100, low=100, close=100)
    bars = [_bar(open_=100, high=102, low=99, close=101)]
    entry_price, exit_price, exit_reason, hold, _, _ = _run(
        entry, bars, max_hold_sessions=10
    )
    assert exit_reason == "delisted_or_data_end"
    assert exit_price == Decimal("101")


def test_no_subsequent_bars_is_delisted():
    """Entry bar exists but no subsequent bars → delisted immediately."""
    entry = _bar(open_=100, high=100, low=100, close=100)
    entry_price, exit_price, exit_reason, hold, _, _ = _run(entry, [])
    assert exit_reason == "delisted_or_data_end"
    assert hold == 0


# ---------------------------------------------------------------------------
# No entry bar
# ---------------------------------------------------------------------------


def test_limit_entry_no_fill_when_gap_down():
    """
    Limit entry: limit_price = previous_close * (1 + offset/100).
    If open > limit_price, no fill (no_entry_bar).
    """
    from app.services.backtest_service import _simulate_trade

    # signal_previous_close=100, limit_offset_pct=-2%: limit_price = 100 * 0.98 = 98
    # open = 100 > limit_price = 98 → no fill
    entry = _bar(open_=100, high=102, low=99, close=101)
    result = _simulate_trade(
        entry_bar=entry,
        subsequent_bars=[_bar(open_=100, high=104, low=97, close=101)],
        stop_pct=2.0,
        risk_reward_ratio=2.0,
        entry_type="limit",
        limit_offset_pct=-2.0,
        max_hold_sessions=10,
        signal_previous_close=100.0,
    )
    entry_price, exit_price, exit_reason, hold, _, _ = result
    assert exit_reason == "no_entry_bar"
    assert entry_price is None


def test_limit_entry_no_previous_close_is_no_entry():
    """
    Limit entry with signal_previous_close=None → no_entry_bar (treat as missing data).
    Must NOT silently fall back to open-based limit which would always fill on positive offset.
    """
    from app.services.backtest_service import _simulate_trade

    entry = _bar(open_=100, high=102, low=99, close=101)
    result = _simulate_trade(
        entry_bar=entry,
        subsequent_bars=[_bar(open_=100, high=104, low=97, close=101)],
        stop_pct=2.0,
        risk_reward_ratio=2.0,
        entry_type="limit",
        limit_offset_pct=2.0,
        max_hold_sessions=10,
        signal_previous_close=None,
    )
    entry_price, exit_price, exit_reason, hold, _, _ = result
    assert exit_reason == "no_entry_bar"
    assert entry_price is None


# ---------------------------------------------------------------------------
# Stop / target level computation
# ---------------------------------------------------------------------------


def test_stop_and_target_levels():
    """Verify stop/target prices are computed correctly for 2% stop, 2:1 RR."""
    entry = _bar(open_=100, high=100, low=100, close=100)
    bars = [_bar(open_=100, high=102, low=99, close=101)] * 5
    entry_price, exit_price, exit_reason, hold, stop_price, target_price = _run(
        entry, bars, max_hold_sessions=5
    )
    assert stop_price == Decimal("98.0")
    assert target_price == Decimal("104.0")


# ---------------------------------------------------------------------------
# _compute_stats
# ---------------------------------------------------------------------------


def test_compute_stats_basic():
    """Basic stats for 2 wins and 1 loss."""
    from app.services.backtest_service import SimulatedTrade, _compute_stats

    def _trade(r):
        t = SimulatedTrade(
            ticker="X",
            signal_date=date(2026, 1, 1),
            source_event_id=None,
            signal_indicators={},
        )
        t.result_r = r
        t.hold_sessions = 3
        return t

    trades = [_trade(2.0), _trade(2.0), _trade(-1.0)]
    stats = _compute_stats(trades)

    assert stats["wins"] == 2
    assert stats["losses"] == 1
    assert abs(stats["win_rate"] - 2 / 3) < 1e-6
    # gross_profit=4.0, gross_loss=1.0 → profit_factor=4.0
    assert abs(stats["profit_factor"] - 4.0) < 1e-6
    # expectancy = (2+2-1)/3 = 1.0
    assert abs(stats["expectancy_r"] - 1.0) < 1e-6


def test_compute_stats_no_trades():
    from app.services.backtest_service import _compute_stats

    assert _compute_stats([]) == {}


def test_compute_stats_all_losses():
    from app.services.backtest_service import SimulatedTrade, _compute_stats

    def _trade(r):
        t = SimulatedTrade(
            ticker="X",
            signal_date=date(2026, 1, 1),
            source_event_id=None,
            signal_indicators={},
        )
        t.result_r = r
        t.hold_sessions = 1
        return t

    trades = [_trade(-1.0), _trade(-1.0)]
    stats = _compute_stats(trades)
    assert stats["wins"] == 0
    assert stats["losses"] == 2
    assert stats["win_rate"] == 0.0
    assert stats["profit_factor"] == 0.0  # gross_profit=0, gross_loss>0 → 0/loss = 0


def test_compute_stats_max_drawdown():
    """Drawdown should track the worst peak-to-trough in R."""
    from app.services.backtest_service import SimulatedTrade, _compute_stats

    def _trade(r):
        t = SimulatedTrade(
            ticker="X",
            signal_date=date(2026, 1, 1),
            source_event_id=None,
            signal_indicators={},
        )
        t.result_r = r
        t.hold_sessions = 1
        return t

    # Cumulative: +2, +4, +1, +3 — peak=4 at idx1, trough=1 at idx2 → dd=3
    trades = [_trade(2.0), _trade(2.0), _trade(-3.0), _trade(2.0)]
    stats = _compute_stats(trades)
    assert abs(stats["max_drawdown_r"] - 3.0) < 1e-6


def test_compute_stats_all_wins_profit_factor():
    """All-wins run: no losses → profit_factor=inf (undefined/infinite, not None)."""
    import math

    from app.services.backtest_service import SimulatedTrade, _compute_stats

    def _trade(r):
        t = SimulatedTrade(
            ticker="X",
            signal_date=date(2026, 1, 1),
            source_event_id=None,
            signal_indicators={},
        )
        t.result_r = r
        t.hold_sessions = 1
        return t

    trades = [_trade(2.0), _trade(1.5)]
    stats = _compute_stats(trades)
    assert stats["wins"] == 2
    assert stats["losses"] == 0
    assert math.isinf(stats["profit_factor"])


def test_compute_stats_breakeven_not_a_loss():
    """Break-even trades (result_r == 0) must not be counted as losses."""
    from app.services.backtest_service import SimulatedTrade, _compute_stats

    def _trade(r):
        t = SimulatedTrade(
            ticker="X",
            signal_date=date(2026, 1, 1),
            source_event_id=None,
            signal_indicators={},
        )
        t.result_r = r
        t.hold_sessions = 1
        return t

    trades = [_trade(2.0), _trade(0.0), _trade(-1.0)]
    stats = _compute_stats(trades)
    assert stats["wins"] == 1
    assert stats["losses"] == 1  # break-even is NOT a loss


# ---------------------------------------------------------------------------
# run_backtest_logic validation
# ---------------------------------------------------------------------------


def test_run_backtest_logic_raises_on_zero_stop_pct():
    """run_backtest_logic raises ValueError when strategy.stop_pct == 0 (silent zeroing of result_r)."""
    from decimal import Decimal as D

    from app.services.backtest_service import run_backtest_logic

    mock_strategy = MagicMock()
    mock_strategy.stop_pct = D("0")
    mock_strategy.risk_reward_ratio = D("2")
    mock_strategy.entry_type = "market"
    mock_strategy.limit_offset_pct = None

    mock_db = MagicMock()
    mock_db.query.return_value.filter.return_value.first.return_value = mock_strategy

    with pytest.raises(ValueError, match="stop_pct"):
        run_backtest_logic(
            run_id=1,
            scanner_type="pre_market_volume_spike",
            strategy_id=1,
            universe_id=1,
            start_date=date(2026, 1, 1),
            end_date=date(2026, 1, 31),
            max_hold_sessions=10,
            db=mock_db,
        )
