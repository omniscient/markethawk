"""Celery task for canonical signal replay runs."""

from __future__ import annotations

import logging
import time as _time
from datetime import datetime, time, timedelta
from decimal import Decimal

from app.core.celery_app import celery_app
from app.core.database import SessionLocal
from app.core.metrics import celery_task_duration_seconds, celery_tasks_total
from app.utils.time import utc_now

logger = logging.getLogger(__name__)


DEFAULT_STRATEGY = {
    "direction": "long_only",
    "entry_type": "market",
    "limit_offset_pct": "0",
    "stop_pct": "2",
    "risk_reward_ratio": "2",
}


def _decimal(value) -> Decimal:
    return value if isinstance(value, Decimal) else Decimal(str(value))


def _strategy_params(snapshot: dict | None):
    from app.services.replay.protocols import StrategyParams

    data = {**DEFAULT_STRATEGY, **(snapshot or {})}
    return StrategyParams(
        direction=data.get("direction") or "long_only",
        entry_type=data.get("entry_type") or "market",
        limit_offset_pct=float(_decimal(data.get("limit_offset_pct", 0))),
        stop_pct=float(_decimal(data.get("stop_pct", 2))),
        risk_reward_ratio=float(_decimal(data.get("risk_reward_ratio", 2))),
    )


def _bar_window(signal_date, max_hold_days: int):
    start = datetime.combine(signal_date, time.min)
    end = datetime.combine(signal_date + timedelta(days=max_hold_days + 1), time.min)
    return start, end


def _load_bars(db, ticker: str, signal_date, max_hold_days: int) -> list:
    from app.models.stock_aggregate import StockAggregate

    start, end = _bar_window(signal_date, max_hold_days)
    return (
        db.query(StockAggregate)
        .filter(
            StockAggregate.ticker == ticker,
            StockAggregate.timestamp >= start,
            StockAggregate.timestamp < end,
            StockAggregate.multiplier == 1,
            StockAggregate.timespan.in_(["minute", "day"]),
        )
        .order_by(StockAggregate.timestamp.asc(), StockAggregate.timespan.desc())
        .all()
    )


def _signal_record(event):
    from app.services.replay.protocols import SignalRecord

    indicators = dict(event.indicators or {})
    if event.previous_close is not None:
        indicators.setdefault("previous_close", str(event.previous_close))
    return SignalRecord(
        ticker=event.ticker,
        signal_date=event.event_date,
        indicators=indicators,
        source_event_id=event.id,
    )


def _persist_trade(db, run, simulated, direction: str, regime) -> bool:
    from app.models.replay_trade import ReplayTrade

    db.add(
        ReplayTrade(
            replay_run_id=run.id,
            scanner_event_id=simulated.source_event_id,
            ticker=simulated.ticker,
            signal_date=simulated.signal_date,
            entry_date=simulated.entry_date,
            entry_price=simulated.entry_price,
            direction="short" if direction == "short_only" else "long",
            stop_price=simulated.stop_price,
            target_price=simulated.target_price,
            exit_date=simulated.exit_date,
            exit_price=simulated.exit_price,
            exit_reason=simulated.exit_reason,
            return_pct=simulated.return_pct,
            return_r=simulated.result_r,
            mfe_pct=simulated.mfe_pct,
            mae_pct=simulated.mae_pct,
            bars_held=simulated.bars_held,
            regime_trend=regime.trend,
            regime_vol=regime.vol,
            fill_source=simulated.fill_source,
        )
    )
    return simulated.entry_price is None


def _execute_replay_run(run, db) -> None:
    """Load canonical signals, simulate exits, persist trades, and cache metrics."""

    from app.models.replay_trade import ReplayTrade
    from app.services.replay.classifier import RegimeClassifier, get_benchmark_regime
    from app.services.replay.exit_simulator import IntradayExitSimulator
    from app.services.replay.manifest import compute_data_hash
    from app.services.replay.metrics import MetricsComputer
    from app.services.replay.signal_source import SignalSource

    tickers = sorted((run.universe_snapshot or {}).get("tickers") or [])
    hash_end = run.end_date + timedelta(days=run.max_hold_days)
    run.data_hash = compute_data_hash(db, tickers, run.start_date, hash_end)

    db.query(ReplayTrade).filter(ReplayTrade.replay_run_id == run.id).delete()

    loaded = SignalSource(db).load_existing(
        scanner_type=run.scanner_type,
        tickers=tickers,
        start_date=run.start_date,
        end_date=run.end_date,
    )
    run.signal_source = loaded.signal_source

    strategy = _strategy_params(run.strategy_snapshot)
    simulator = IntradayExitSimulator()
    classifier = RegimeClassifier(run.benchmark_symbol or "SPY")
    classifier.classify(run.start_date, hash_end, db)

    skipped = 0
    for event in loaded.signals:
        bars = _load_bars(db, event.ticker, event.event_date, run.max_hold_days)
        simulated = simulator.simulate(
            signal=_signal_record(event),
            strategy=strategy,
            bars=bars,
            max_hold_days=run.max_hold_days,
        )
        regime = get_benchmark_regime(classifier, event.event_date)
        if _persist_trade(db, run, simulated, strategy.direction, regime):
            skipped += 1

    run.skipped_count = skipped
    db.flush()

    result = MetricsComputer(db).compute(run.id)
    run.total_trades = result.total_trades
    run.hit_rate = result.hit_rate
    run.expectancy_r = result.expectancy_r
    run.profit_factor = result.profit_factor
    run.max_drawdown_r = result.max_drawdown_r
    run.avg_bars_held = result.avg_bars_held
    run.median_bars_held = result.median_bars_held
    run.avg_mfe_pct = result.avg_mfe_pct
    run.avg_mae_pct = result.avg_mae_pct
    run.mfe_mae_ratio = result.mfe_mae_ratio
    run.metrics = result.as_metrics_json()


@celery_app.task(bind=True, max_retries=0, name="app.tasks.run_signal_replay")
def run_signal_replay(self, run_id: int):
    from app.models.replay_run import ReplayRun

    task_name = "run_signal_replay"
    start = _time.monotonic()
    db = SessionLocal()
    try:
        run = db.query(ReplayRun).filter(ReplayRun.id == run_id).first()
        if not run:
            logger.error("run_signal_replay: ReplayRun id=%s not found", run_id)
            return

        run.status = "running"
        db.commit()

        _execute_replay_run(run, db)

        run.status = "completed"
        run.completed_at = utc_now()
        db.commit()
        celery_tasks_total.labels(task_name=task_name, status="success").inc()
        celery_task_duration_seconds.labels(task_name=task_name).observe(
            _time.monotonic() - start
        )
    except Exception as exc:
        logger.exception("run_signal_replay: run_id=%s failed: %s", run_id, exc)
        try:
            run = db.query(ReplayRun).filter(ReplayRun.id == run_id).first()
            if run:
                run.status = "failed"
                run.error_message = str(exc)[:2000]
                db.commit()
        finally:
            celery_tasks_total.labels(task_name=task_name, status="failure").inc()
            celery_task_duration_seconds.labels(task_name=task_name).observe(
                _time.monotonic() - start
            )
        raise
    finally:
        db.close()
