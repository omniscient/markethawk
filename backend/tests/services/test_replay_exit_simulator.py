"""Fixture tests for the pure replay intraday exit simulator."""

from datetime import date, datetime
from decimal import Decimal
from types import SimpleNamespace


def _bar(
    ts: datetime,
    open_: str,
    high: str,
    low: str,
    close: str,
    timespan: str = "minute",
    pre: bool = False,
    post: bool = False,
):
    return SimpleNamespace(
        timestamp=ts,
        open=Decimal(open_),
        high=Decimal(high),
        low=Decimal(low),
        close=Decimal(close),
        timespan=timespan,
        multiplier=1,
        is_pre_market=pre,
        is_after_market=post,
    )


def _signal(previous_close: str = "100"):
    from app.services.replay.protocols import SignalRecord

    return SignalRecord(
        ticker="AAPL",
        signal_date=date(2026, 1, 5),
        indicators={"previous_close": previous_close},
        source_event_id=42,
    )


def _strategy(**overrides):
    from app.services.replay.protocols import StrategyParams

    params = {
        "entry_type": "market",
        "stop_pct": 2.0,
        "risk_reward_ratio": 2.0,
        "limit_offset_pct": 0.0,
        "direction": "long_only",
    }
    params.update(overrides)
    return StrategyParams(**params)


def _entry_bar():
    return _bar(datetime(2026, 1, 5, 9, 30), "100", "101", "99", "100")


def test_long_stop_first_on_minute_bar():
    from app.services.replay.exit_simulator import IntradayExitSimulator

    trade = IntradayExitSimulator().simulate(
        _signal(),
        _strategy(),
        [
            _entry_bar(),
            _bar(datetime(2026, 1, 6, 9, 30), "100", "105", "97", "99"),
        ],
        max_hold_days=5,
    )

    assert trade.entry_price == Decimal("100")
    assert trade.stop_price == Decimal("98.0")
    assert trade.target_price == Decimal("104.00")
    assert trade.exit_reason == "stop"
    assert trade.exit_price == Decimal("98.0")
    assert trade.result_r == -1.0
    assert trade.return_pct == -2.0
    assert trade.mfe_pct == 5.0
    assert trade.mae_pct == 3.0
    assert trade.bars_held == 1
    assert trade.fill_source == "intraday"


def test_long_target_first_on_minute_bar():
    from app.services.replay.exit_simulator import IntradayExitSimulator

    trade = IntradayExitSimulator().simulate(
        _signal(),
        _strategy(),
        [
            _entry_bar(),
            _bar(datetime(2026, 1, 6, 9, 30), "100", "104.50", "99", "104"),
        ],
        max_hold_days=5,
    )

    assert trade.exit_reason == "target"
    assert trade.exit_price == Decimal("104.00")
    assert trade.result_r == 2.0
    assert trade.return_pct == 4.0
    assert trade.mfe_pct == 4.5
    assert trade.mae_pct == 1.0


def test_time_exit_uses_first_bar_on_or_after_cutoff():
    from app.services.replay.exit_simulator import IntradayExitSimulator

    trade = IntradayExitSimulator().simulate(
        _signal(),
        _strategy(),
        [
            _entry_bar(),
            _bar(datetime(2026, 1, 6, 9, 30), "100", "101", "99", "100"),
            _bar(datetime(2026, 1, 7, 9, 30), "101", "102", "100", "101"),
        ],
        max_hold_days=2,
    )

    assert trade.exit_reason == "time_exit"
    assert trade.exit_date == date(2026, 1, 7)
    assert trade.exit_price == Decimal("101")
    assert trade.bars_held == 1
    assert trade.result_r == 0.5


def test_limit_entry_no_fill_returns_eod_no_fill():
    from app.services.replay.exit_simulator import IntradayExitSimulator

    trade = IntradayExitSimulator().simulate(
        _signal(previous_close="100"),
        _strategy(entry_type="limit", limit_offset_pct=-2.0),
        [
            _bar(datetime(2026, 1, 5, 9, 30), "100", "101", "99", "100"),
            _bar(datetime(2026, 1, 5, 9, 31), "100", "101", "98.50", "100"),
        ],
        max_hold_days=5,
    )

    assert trade.exit_reason == "eod-no-fill"
    assert trade.entry_price is None
    assert trade.result_r is None


def test_daily_fallback_stop_first_when_daily_bar_spans_stop_and_target():
    from app.services.replay.exit_simulator import IntradayExitSimulator

    trade = IntradayExitSimulator().simulate(
        _signal(),
        _strategy(),
        [
            _entry_bar(),
            _bar(
                datetime(2026, 1, 6),
                "100",
                "106",
                "96",
                "101",
                timespan="day",
            ),
        ],
        max_hold_days=5,
    )

    assert trade.exit_reason == "stop"
    assert trade.exit_price == Decimal("98.0")
    assert trade.fill_source == "daily-fallback"
    assert trade.bars_held == 1


def test_short_only_inverts_target_and_return_math():
    from app.services.replay.exit_simulator import IntradayExitSimulator

    trade = IntradayExitSimulator().simulate(
        _signal(),
        _strategy(direction="short_only"),
        [
            _entry_bar(),
            _bar(datetime(2026, 1, 6, 9, 30), "100", "101", "95", "96"),
        ],
        max_hold_days=5,
    )

    assert trade.stop_price == Decimal("102.0")
    assert trade.target_price == Decimal("96.00")
    assert trade.exit_reason == "target"
    assert trade.exit_price == Decimal("96.00")
    assert trade.result_r == 2.0
    assert trade.return_pct == 4.0
    assert trade.mfe_pct == 5.0
    assert trade.mae_pct == 1.0
