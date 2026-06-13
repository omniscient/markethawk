"""
Backtest Celery task.

No retry (max_retries=0): backtests are deterministic — a retry on the same
inputs produces the same result, so there's no point retrying transient failures.
Use the GET /api/v1/backtest/runs/{uuid} poll endpoint to check status.
"""

import logging
import time as _time
from datetime import date

from app.core.celery_app import celery_app
from app.core.database import SessionLocal
from app.core.metrics import celery_task_duration_seconds, celery_tasks_total
from app.utils.time import utc_now

logger = logging.getLogger(__name__)


def _run_backtest_logic(
    run_id: int,
    scanner_type: str,
    strategy_id: int,
    universe_id: int,
    start_date: date,
    end_date: date,
    max_hold_sessions: int,
    db,
):
    """Thin shim so tests can call service directly without importing Celery."""
    from app.services.backtest_service import run_backtest_logic

    return run_backtest_logic(
        run_id=run_id,
        scanner_type=scanner_type,
        strategy_id=strategy_id,
        universe_id=universe_id,
        start_date=start_date,
        end_date=end_date,
        max_hold_sessions=max_hold_sessions,
        db=db,
    )


@celery_app.task(
    bind=True,
    max_retries=0,
    name="app.tasks.run_backtest",
)
def run_backtest(
    self,
    run_id: int,
    scanner_type: str,
    strategy_id: int,
    universe_id: int,
    start_date_iso: str,
    end_date_iso: str,
    max_hold_sessions: int = 10,
):
    """
    Execute a backtest run asynchronously.

    Updates BacktestRun status: queued → running → completed | failed.
    On completion, writes summary stats + per-trade rows to DB.
    """
    from datetime import date as _date

    from app.models.backtest_run import BacktestRun
    from app.models.backtest_trade import BacktestTrade

    _task_name = "run_backtest"
    _start = _time.monotonic()
    db = SessionLocal()

    try:
        run = db.query(BacktestRun).filter(BacktestRun.id == run_id).first()
        if not run:
            logger.error(f"run_backtest: BacktestRun id={run_id} not found")
            return

        run.status = "running"
        db.commit()

        start_date = _date.fromisoformat(start_date_iso)
        end_date = _date.fromisoformat(end_date_iso)

        result = _run_backtest_logic(
            run_id=run_id,
            scanner_type=scanner_type,
            strategy_id=strategy_id,
            universe_id=universe_id,
            start_date=start_date,
            end_date=end_date,
            max_hold_sessions=max_hold_sessions,
            db=db,
        )

        # Persist summary stats back to the run record
        run.total_signals = result.total_signals
        run.total_trades = result.total_trades
        run.wins = result.wins
        run.losses = result.losses
        run.win_rate = result.win_rate
        run.profit_factor = result.profit_factor
        run.expectancy_r = result.expectancy_r
        run.max_drawdown_r = result.max_drawdown_r
        run.avg_hold_sessions = result.avg_hold_sessions
        run.median_hold_sessions = result.median_hold_sessions
        run.signals_skipped_no_data = result.signals_skipped_no_data
        run.trades_exited_on_data_end = result.trades_exited_on_data_end
        run.universe_as_of = result.universe_as_of
        run.bars_source = result.bars_source
        run.status = "completed"
        run.completed_at = utc_now()
        db.flush()

        # Persist per-trade rows
        for t in result.trades:
            bt = BacktestTrade(
                run_id=run_id,
                ticker=t.ticker,
                signal_date=t.signal_date,
                source_event_id=t.source_event_id,
                signal_indicators=t.signal_indicators,
                entry_date=t.entry_date,
                entry_price=t.entry_price,
                exit_date=t.exit_date,
                exit_price=t.exit_price,
                exit_reason=t.exit_reason,
                hold_sessions=t.hold_sessions,
                result_r=t.result_r,
                stop_price=t.stop_price,
                target_price=t.target_price,
            )
            db.add(bt)

        db.commit()

        elapsed_ms = int((_time.monotonic() - _start) * 1000)
        logger.info(
            f"✅ run_backtest: run_id={run_id} completed in {elapsed_ms}ms "
            f"signals={result.total_signals} trades={result.total_trades}"
        )

        celery_tasks_total.labels(task_name=_task_name, status="success").inc()
        celery_task_duration_seconds.labels(task_name=_task_name).observe(
            _time.monotonic() - _start
        )

    except Exception as exc:
        logger.exception(f"❌ run_backtest: run_id={run_id} failed: {exc}")
        try:
            run = db.query(BacktestRun).filter(BacktestRun.id == run_id).first()
            if run:
                run.status = "failed"
                run.error_message = str(exc)[:2000]
                db.commit()
        except Exception:
            pass

        celery_tasks_total.labels(task_name=_task_name, status="failure").inc()
        celery_task_duration_seconds.labels(task_name=_task_name).observe(
            _time.monotonic() - _start
        )
        raise

    finally:
        db.close()
