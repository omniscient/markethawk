"""Integration tests for replay API endpoints."""

from datetime import date
from decimal import Decimal
from itertools import count
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.main import app

client = TestClient(app)
_name_counter = count(1)


def _strategy_and_universe(db: Session):
    from app.models.stock_universe import StockUniverse
    from app.models.trading_strategy import TradingStrategy

    universe = StockUniverse(
        name=f"Replay API Universe {next(_name_counter)}",
        description="Fixture universe",
        criteria={},
        is_active=True,
    )
    strategy = TradingStrategy(
        name=f"Replay API Strategy {next(_name_counter)}",
        direction="long_only",
        entry_type="market",
        stop_pct=Decimal("2"),
        risk_reward_ratio=Decimal("2"),
        limit_offset_pct=Decimal("0"),
        max_slippage_pct=Decimal("0.5"),
        allowed_sessions=["regular"],
    )
    db.add(universe)
    db.add(strategy)
    db.flush()
    return strategy, universe


def _run(db: Session, status: str = "completed", data_hash: str = "abc"):
    from app.models.replay_run import ReplayRun

    strategy, universe = _strategy_and_universe(db)
    run = ReplayRun(
        scanner_type="pre_market_volume_spike",
        scanner_config_snapshot={"scanner_type": "pre_market_volume_spike"},
        trading_strategy_id=strategy.id,
        strategy_snapshot={"direction": "long_only"},
        universe_id=universe.id,
        universe_snapshot={"tickers": ["AAPL"]},
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 31),
        max_hold_days=10,
        exit_fidelity="intraday",
        benchmark_symbol="SPY",
        status=status,
        data_hash=data_hash,
        total_trades=1,
        hit_rate=1.0,
        expectancy_r=2.0,
        metrics={
            "equity_curve": [{"date": "2026-01-02", "cumulative_r": 2.0}],
            "calendar_decay": [],
            "holding_period_decay": [],
            "regime_breakdown": [],
        },
    )
    db.add(run)
    db.flush()
    return run


def test_create_replay_run_enqueues_task(db: Session):
    strategy, universe = _strategy_and_universe(db)

    with patch("app.routers.replay.run_signal_replay.delay") as delay:
        delay.return_value.id = "task-1"
        response = client.post(
            "/api/v1/replay/runs",
            json={
                "scanner_type": "pre_market_volume_spike",
                "trading_strategy_id": strategy.id,
                "universe_id": universe.id,
                "start_date": "2026-01-01",
                "end_date": "2026-01-31",
                "max_hold_days": 10,
                "exit_fidelity": "intraday",
                "benchmark_symbol": "SPY",
            },
        )

    assert response.status_code == 202
    data = response.json()
    assert data["status"] == "queued"
    assert data["celery_task_id"] == "task-1"
    delay.assert_called_once()


def test_list_and_get_replay_run(db: Session):
    run = _run(db)

    list_response = client.get("/api/v1/replay/runs?status=completed")
    assert list_response.status_code == 200
    assert list_response.json()[0]["uuid"] == str(run.uuid)

    get_response = client.get(f"/api/v1/replay/runs/{run.uuid}")
    assert get_response.status_code == 200
    assert get_response.json()["metrics"]["equity_curve"][0]["cumulative_r"] == 2.0


def test_replay_trades_endpoint_returns_paginated_ledger(db: Session):
    from app.models.replay_trade import ReplayTrade

    run = _run(db)
    db.add(
        ReplayTrade(
            replay_run_id=run.id,
            ticker="AAPL",
            signal_date=date(2026, 1, 2),
            return_r=Decimal("2"),
            return_pct=Decimal("4"),
            mfe_pct=Decimal("5"),
            mae_pct=Decimal("1"),
            bars_held=3,
            exit_reason="target",
        )
    )
    db.flush()

    response = client.get(f"/api/v1/replay/runs/{run.uuid}/trades")

    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1
    assert data["trades"][0]["ticker"] == "AAPL"


def test_replay_analytics_returns_empty_for_running_and_metrics_for_completed(db: Session):
    running = _run(db, status="running")
    completed = _run(db, status="completed")

    running_response = client.get(f"/api/v1/replay/runs/{running.uuid}/analytics")
    assert running_response.status_code == 200
    assert running_response.json()["equity_curve"] == []

    completed_response = client.get(f"/api/v1/replay/runs/{completed.uuid}/analytics")
    assert completed_response.status_code == 200
    assert completed_response.json()["equity_curve"][0]["cumulative_r"] == 2.0


def test_replay_compare_validates_count_and_flags_hash_mismatch(db: Session):
    first = _run(db, data_hash="aaa")
    second = _run(db, data_hash="bbb")

    invalid = client.get(f"/api/v1/replay/runs/compare?ids={first.uuid}")
    assert invalid.status_code == 422

    response = client.get(f"/api/v1/replay/runs/compare?ids={first.uuid},{second.uuid}")
    assert response.status_code == 200
    data = response.json()
    assert data["all_hashes_match"] is False
    assert data["comparisons"][0]["data_hash_match"] is False


def test_replay_get_unknown_or_malformed_uuid(db: Session):
    assert client.get("/api/v1/replay/runs/not-a-uuid").status_code == 422
    assert (
        client.get("/api/v1/replay/runs/00000000-0000-0000-0000-000000000001").status_code
        == 404
    )
