"""Tests for replay metrics computation."""

from datetime import date
from decimal import Decimal


def _run(db):
    from app.models.replay_run import ReplayRun
    from app.models.stock_universe import StockUniverse

    universe = StockUniverse(
        name="Replay Metrics Universe",
        description="Fixture universe",
        criteria={},
        is_active=True,
    )
    db.add(universe)
    db.flush()

    run = ReplayRun(
        scanner_type="pre_market_volume_spike",
        scanner_config_snapshot={"scanner_type": "pre_market_volume_spike"},
        universe_id=universe.id,
        universe_snapshot={"tickers": ["AAPL", "MSFT"]},
        start_date=date(2026, 1, 1),
        end_date=date(2026, 4, 30),
        max_hold_days=5,
        exit_fidelity="intraday",
        benchmark_symbol="SPY",
    )
    db.add(run)
    db.flush()
    return run


def _trade(db, run_id: int, ticker: str, signal_date: date, result_r: str, bars: int, trend: str, vol: str):
    from app.models.replay_trade import ReplayTrade

    trade = ReplayTrade(
        replay_run_id=run_id,
        ticker=ticker,
        signal_date=signal_date,
        entry_date=signal_date,
        entry_price=Decimal("100"),
        exit_date=signal_date,
        exit_price=Decimal("100"),
        exit_reason="target" if Decimal(result_r) > 0 else "stop",
        return_pct=Decimal("1"),
        return_r=Decimal(result_r),
        mfe_pct=Decimal("4"),
        mae_pct=Decimal("2"),
        bars_held=bars,
        regime_trend=trend,
        regime_vol=vol,
        fill_source="intraday",
    )
    db.add(trade)
    db.flush()
    return trade


def test_metrics_computer_builds_headline_decay_regime_and_equity(db):
    from app.services.replay.metrics import MetricsComputer

    run = _run(db)
    _trade(db, run.id, "AAPL", date(2026, 1, 5), "2.0", 2, "bull", "calm")
    _trade(db, run.id, "MSFT", date(2026, 1, 6), "-1.0", 4, "bull", "calm")
    _trade(db, run.id, "AAPL", date(2026, 2, 5), "0.0", 1, "bear", "normal")
    _trade(db, run.id, "MSFT", date(2026, 4, 6), "1.0", 5, "bear", "normal")
    _trade(db, run.id, "AAPL", date(2026, 4, 7), "-1.0", 3, "bear", "turbulent")

    result = MetricsComputer(db).compute(run.id)

    assert result.total_trades == 5
    assert result.hit_rate == 0.4
    assert result.expectancy_r == 0.2
    assert result.profit_factor == 1.5
    assert result.max_drawdown_r == 1.0
    assert result.avg_bars_held == 3.0
    assert result.median_bars_held == 3.0
    assert result.avg_mfe_pct == 4.0
    assert result.avg_mae_pct == 2.0
    assert result.mfe_mae_ratio == 2.0
    assert result.equity_curve[-1] == {"date": "2026-04-07", "cumulative_r": 1.0}
    assert {row["period"] for row in result.calendar_decay} == {"2026-Q1", "2026-Q2"}
    assert result.holding_period_decay[0]["day"] == 1
    assert result.holding_period_decay[0]["avg_return_r"] == 0.2
    assert any(
        row["trend"] == "bull" and row["vol"] == "calm" and row["n"] == 2
        for row in result.regime_breakdown
    )
