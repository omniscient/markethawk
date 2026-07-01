"""Tests for replay Celery task status transitions."""

from unittest.mock import MagicMock, patch


def _db_with_run(run):
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = run
    return db


def test_run_signal_replay_marks_completed_on_success():
    import app.tasks.replay as replay_module

    run = MagicMock()
    run.id = 1
    db = _db_with_run(run)

    with (
        patch("app.tasks.replay.SessionLocal", return_value=db),
        patch("app.tasks.replay._execute_replay_run") as execute,
    ):
        replay_module.run_signal_replay.run(run_id=1)

    execute.assert_called_once_with(run, db)
    assert run.status == "completed"
    assert run.completed_at is not None
    db.commit.assert_called()
    db.close.assert_called_once()


def test_run_signal_replay_records_failure_message():
    import app.tasks.replay as replay_module

    run = MagicMock()
    run.id = 1
    db = _db_with_run(run)

    with (
        patch("app.tasks.replay.SessionLocal", return_value=db),
        patch("app.tasks.replay._execute_replay_run", side_effect=RuntimeError("bad replay")),
    ):
        try:
            replay_module.run_signal_replay.run(run_id=1)
        except RuntimeError:
            pass

    assert run.status == "failed"
    assert run.error_message == "bad replay"
    db.commit.assert_called()
    db.close.assert_called_once()


def test_execute_replay_run_persists_trades_and_metrics(db):
    from datetime import date, datetime
    from decimal import Decimal

    from app.models.replay_run import ReplayRun
    from app.models.replay_trade import ReplayTrade
    from app.models.scanner_event import ScannerEvent
    from app.models.stock_aggregate import StockAggregate
    from app.models.stock_universe import StockUniverse
    from app.tasks.replay import _execute_replay_run

    universe = StockUniverse(
        name="Replay Task Universe",
        description="Task fixture",
        criteria={},
        is_active=True,
    )
    db.add(universe)
    db.flush()

    run = ReplayRun(
        scanner_type="pre_market_volume_spike",
        scanner_config_snapshot={"scanner_type": "pre_market_volume_spike"},
        strategy_snapshot={
            "direction": "long_only",
            "entry_type": "market",
            "stop_pct": "2",
            "risk_reward_ratio": "2",
            "limit_offset_pct": "0",
        },
        universe_id=universe.id,
        universe_snapshot={"tickers": ["AAPL"]},
        start_date=date(2026, 1, 2),
        end_date=date(2026, 1, 2),
        max_hold_days=3,
        exit_fidelity="intraday",
        benchmark_symbol="SPY",
        status="running",
    )
    db.add(run)
    db.flush()

    db.add(
        ScannerEvent(
            ticker="AAPL",
            event_date=date(2026, 1, 2),
            scanner_type="pre_market_volume_spike",
            previous_close=Decimal("99"),
            indicators={},
            criteria_met={},
            metadata_={},
        )
    )
    db.add_all(
        [
            StockAggregate(
                ticker="AAPL",
                timestamp=datetime(2026, 1, 2, 9, 30),
                multiplier=1,
                timespan="minute",
                open=Decimal("100"),
                high=Decimal("101"),
                low=Decimal("99"),
                close=Decimal("100"),
                volume=1000,
            ),
            StockAggregate(
                ticker="AAPL",
                timestamp=datetime(2026, 1, 3, 9, 30),
                multiplier=1,
                timespan="minute",
                open=Decimal("101"),
                high=Decimal("105"),
                low=Decimal("100"),
                close=Decimal("104"),
                volume=1000,
            ),
        ]
    )
    db.flush()

    _execute_replay_run(run, db)

    trade = db.query(ReplayTrade).filter(ReplayTrade.replay_run_id == run.id).one()
    assert trade.ticker == "AAPL"
    assert trade.exit_reason == "target"
    assert float(trade.return_r) == 2.0
    assert run.data_hash
    assert run.total_trades == 1
    assert run.hit_rate == 1.0
    assert run.signal_source == "db"
