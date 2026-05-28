import asyncio
import json
import logging
import time as _time
from datetime import datetime, timezone

import redis
from sqlalchemy.orm import Session

from app.core.celery_app import celery_app
from app.core.config import settings
from app.core.database import SessionLocal
from app.core.metrics import celery_task_duration_seconds, celery_tasks_total
from app.models.monitored_stock import MonitoredStock

logger = logging.getLogger(__name__)


@celery_app.task(bind=True, max_retries=2, name="app.tasks.evaluate_scanner_alerts")
def evaluate_scanner_alerts(self, scanner_event_id: int):
    """
    Evaluate all active alert rules against a newly-saved ScannerEvent.
    Dispatches notifications via all configured channels for any matching rules.
    For rules with auto_trade=True, queues execute_auto_trade as a follow-up task.
    Called automatically when a new ScannerEvent is created.
    """
    from app.models.scanner_event import ScannerEvent
    from app.services.alert_service import AlertRuleService, NotificationDispatcher

    _task_name = "evaluate_scanner_alerts"
    _start = _time.monotonic()
    db: Session = SessionLocal()
    try:
        event = (
            db.query(ScannerEvent).filter(ScannerEvent.id == scanner_event_id).first()
        )
        if not event:
            logger.warning(
                f"evaluate_scanner_alerts: ScannerEvent id={scanner_event_id} not found."
            )
            return

        matching_rules = AlertRuleService.get_matching_rules(event, db)
        if not matching_rules:
            return

        logger.info(
            f"🔔 {len(matching_rules)} alert rule(s) matched "
            f"event={scanner_event_id} ticker={event.ticker} type={event.scanner_type}"
        )

        for rule in matching_rules:
            # Notification dispatch
            try:
                NotificationDispatcher.dispatch(rule, event, db)
            except Exception as exc:
                logger.error(f"❌ Dispatch failed for rule {rule.id}: {exc}")

            # Auto-trade: queue a separate task so notification failures
            # never block order placement, and vice versa.
            if rule.auto_trade and rule.trading_strategy_id:
                from app.tasks.trading import execute_auto_trade

                execute_auto_trade.delay(
                    rule_id=rule.id,
                    scanner_event_id=scanner_event_id,
                )
                logger.info(
                    f"🤖 Auto-trade queued for rule={rule.id} "
                    f"strategy={rule.trading_strategy_id} ticker={event.ticker}"
                )

        celery_tasks_total.labels(task_name=_task_name, status="success").inc()
    except Exception as e:
        celery_tasks_total.labels(task_name=_task_name, status="failure").inc()
        logger.error(
            f"❌ evaluate_scanner_alerts failed for event {scanner_event_id}: {e}"
        )
        db.rollback()
        raise self.retry(exc=e, countdown=30)
    finally:
        celery_task_duration_seconds.labels(task_name=_task_name).observe(
            _time.monotonic() - _start
        )
        db.close()


@celery_app.task(name="app.tasks.run_range_scan")
def run_range_scan(
    ticker: str,
    scanner_types: list,
    start_date_str: str,
    end_date_str: str,
    fetch_missing_data: bool,
):
    """Background task: run selected scanners over a date range for one ticker."""
    import asyncio
    from datetime import date, timedelta

    from app.exceptions import DataFetchError, ProviderError
    from app.services.liquidity_hunt import run_liquidity_hunt_scan_for_date as _lh_scan
    from app.services.scanner import ScannerService
    from app.services.stock_data import StockDataService

    _task_name = "run_range_scan"
    _start = _time.monotonic()
    task_id = run_range_scan.request.id
    r = redis.Redis.from_url(settings.REDIS_URL, decode_responses=True)
    channel = f"scan_task:{task_id}"

    from datetime import datetime as _dt

    r.set(
        f"scan:{ticker}:range",
        json.dumps({"task_ids": [task_id], "started_at": _dt.utcnow().isoformat()}),
        ex=14400,
    )

    start = date.fromisoformat(start_date_str)
    end = date.fromisoformat(end_date_str)

    trading_days = [
        start + timedelta(days=i)
        for i in range((end - start).days + 1)
        if (start + timedelta(days=i)).weekday() < 5
    ]

    total = len(trading_days) * len(scanner_types)
    events_detected = 0
    done = 0

    db: Session = SessionLocal()
    try:
        if fetch_missing_data:
            # Daily bars: need 90-day lookback before start for rolling metrics
            daily_period_days = (date.today() - (start - timedelta(days=90))).days
            try:
                StockDataService.refresh_stock_data(
                    db, ticker, timespan="day", period=f"{daily_period_days}d"
                )
            except (DataFetchError, ProviderError) as exc:
                logger.warning(
                    "refresh_stock_data (day) failed for %s: %s", ticker, exc
                )
            # Minute bars: cover just the requested range
            minute_period_days = (date.today() - start).days + 5
            try:
                StockDataService.refresh_stock_data(
                    db, ticker, timespan="minute", period=f"{minute_period_days}d"
                )
            except (DataFetchError, ProviderError) as exc:
                logger.warning(
                    "refresh_stock_data (minute) failed for %s: %s", ticker, exc
                )

        scanner_map = {
            "pre_market_volume_spike": ScannerService.run_pre_market_scan_for_date,
            "liquidity_hunt": _lh_scan,
            "liquidity_hunt_pre": _lh_scan,
            "liquidity_hunt_post": _lh_scan,
            "oversold_bounce": ScannerService.run_oversold_bounce_scan_for_date,
        }

        async def _scan_day(day):
            results = []
            for st in scanner_types:
                fn = scanner_map.get(st)
                if fn:
                    results.extend(await fn(ticker, day, db))
            return results

        for day in trading_days:
            day_results = asyncio.run(_scan_day(day))
            events_detected += len(day_results)
            done += len(scanner_types)
            r.publish(
                channel,
                json.dumps(
                    {
                        "status": "progress",
                        "day": day.isoformat(),
                        "done": done,
                        "total": total,
                    }
                ),
            )

        r.publish(
            channel,
            json.dumps(
                {
                    "status": "completed",
                    "events_detected": events_detected,
                }
            ),
        )
        logger.info(f"run_range_scan {task_id}: completed, {events_detected} events")
        celery_tasks_total.labels(task_name=_task_name, status="success").inc()

    except Exception as e:
        celery_tasks_total.labels(task_name=_task_name, status="failure").inc()
        logger.error(f"run_range_scan {task_id} failed: {e}")
        r.publish(
            channel,
            json.dumps(
                {
                    "status": "failed",
                    "error": str(e),
                }
            ),
        )
    finally:
        celery_task_duration_seconds.labels(task_name=_task_name).observe(
            _time.monotonic() - _start
        )
        r.delete(f"scan:{ticker}:range")
        db.close()


@celery_app.task(
    bind=True, max_retries=1, name="app.tasks.run_liquidity_hunt_scheduled"
)
def run_liquidity_hunt_scheduled(self):
    """
    Nightly 02:00 UTC task: run liquidity_hunt_pre and liquidity_hunt_post
    for today's date over all active ScannerConfig universes of type 'liquidity_hunt'.
    """
    from app.models.scanner_config import ScannerConfig
    from app.services.liquidity_hunt import run_liquidity_hunt_scan
    from app.utils.session import get_market_today

    _task_name = "run_liquidity_hunt_scheduled"
    _start = _time.monotonic()
    db: Session = SessionLocal()
    try:
        event_date = get_market_today()
        configs = (
            db.query(ScannerConfig)
            .filter(
                ScannerConfig.scanner_type == "liquidity_hunt",
                ScannerConfig.is_active.is_(True),
            )
            .all()
        )

        for cfg in configs:
            universe_id = cfg.parameters.get("universe_id")
            if not universe_id:
                logger.warning(
                    "liquidity_hunt ScannerConfig %s has no universe_id", cfg.id
                )
                continue

            tickers = [
                ms.ticker
                for ms in db.query(MonitoredStock)
                .filter(
                    MonitoredStock.universe_id == universe_id,
                    MonitoredStock.is_active.is_(True),
                )
                .all()
            ]
            if not tickers:
                continue

            results = asyncio.run(
                run_liquidity_hunt_scan(
                    tickers, db, start_date=event_date, end_date=event_date
                )
            )
            logger.info(
                "liquidity_hunt scheduled scan for universe %s on %s: %d events",
                universe_id,
                event_date,
                len(results),
            )
        celery_tasks_total.labels(task_name=_task_name, status="success").inc()
    except Exception as exc:
        celery_tasks_total.labels(task_name=_task_name, status="failure").inc()
        logger.exception("run_liquidity_hunt_scheduled failed: %s", exc)
        raise self.retry(exc=exc)
    finally:
        celery_task_duration_seconds.labels(task_name=_task_name).observe(
            _time.monotonic() - _start
        )
        db.close()


# ---------------------------------------------------------------------------
# Async universe scan — drives a (universe, scanner_type) over a date range
# and publishes per-day progress to Redis.
# ---------------------------------------------------------------------------


@celery_app.task(bind=True, max_retries=0, name="app.tasks.run_universe_scan")
def run_universe_scan(
    self,
    scan_id: str,
    scanner_type: str,
    universe_id: int,
    start_date_iso: str,
    end_date_iso: str,
):
    """Run a scanner across (universe, [start_date..end_date]) with progress reporting.

    Per-day granularity: invokes the relevant scanner once per trading day with
    every ticker in the universe. After each day we update the Redis state key
    (so /runs/{id}/status reflects current progress) and publish a message on
    the pub/sub channel (so the WS reattach path receives it). The state key is
    deleted in ``finally``; the system tasks aggregator at /api/system/ws/tasks
    discovers active scans by scanning ``universe:*:scan:*``.
    """
    from datetime import date as _date
    from datetime import timedelta as _td

    import app.services.liquidity_hunt  # noqa: F401
    import app.services.oversold_bounce_scan  # noqa: F401
    import app.services.pre_market_scan  # noqa: F401 — triggers self-registration
    import app.services.scan_orchestrator as _orchestrator
    from app.models.scanner_run import ScannerRun

    _task_name = "run_universe_scan"
    _perf_start = _time.monotonic()
    task_id = self.request.id
    r = redis.Redis.from_url(settings.REDIS_URL, decode_responses=True)
    channel = f"scan_task:{task_id}"
    state_key = f"universe:{universe_id}:scan:{scanner_type}"
    cancel_key = f"scan_cancel:{scan_id}"

    def _cancelled() -> bool:
        return r.exists(cancel_key) > 0

    def _publish(payload: dict) -> None:
        try:
            r.publish(channel, json.dumps(payload, default=str))
        except Exception:
            logger.exception("scan_task publish failed")

    db: Session = SessionLocal()
    started_at = datetime.now(timezone.utc).replace(tzinfo=None)
    try:
        run = db.query(ScannerRun).filter(ScannerRun.uuid == scan_id).first()
        if run is None:
            logger.error("run_universe_scan: ScannerRun %s not found", scan_id)
            return

        tickers = [
            ms.ticker
            for ms in db.query(MonitoredStock)
            .filter(
                MonitoredStock.universe_id == universe_id,
                MonitoredStock.is_active.is_(True),
            )
            .all()
        ]
        if not tickers:
            run.status = "failed"
            run.error_message = "Universe has no active tickers"
            db.commit()
            _publish({"type": "failed", "error": run.error_message})
            return

        start = _date.fromisoformat(start_date_iso)
        end = _date.fromisoformat(end_date_iso)
        trading_days = [
            start + _td(days=i)
            for i in range((end - start).days + 1)
            if (start + _td(days=i)).weekday() < 5
        ]

        run.status = "running"
        run.stocks_scanned = len(tickers)
        run.scan_start_date = start
        run.scan_end_date = end
        db.commit()

        cum = {
            "evaluated": 0,
            "no_data": 0,
            "no_prior_close": 0,
            "no_baseline": 0,
            "errors": 0,
            "fired_pre": 0,
            "fired_post": 0,
        }
        events_total = 0

        def _write_state(progress_extra: dict | None = None):
            r.set(
                state_key,
                json.dumps(
                    {
                        "task_ids": [task_id],
                        "scan_id": scan_id,
                        "scanner_type": scanner_type,
                        "universe_id": universe_id,
                        "start_date": start.isoformat(),
                        "end_date": end.isoformat(),
                        "started_at": started_at.replace(
                            tzinfo=timezone.utc
                        ).isoformat(),
                        "tickers": len(tickers),
                        "total_days": len(trading_days),
                        "events_detected": events_total,
                        **cum,
                        **(progress_extra or {}),
                    }
                ),
                ex=14400,
            )

        _write_state({"day_index": 0})
        _publish(
            {
                "type": "started",
                "scan_id": scan_id,
                "task_id": task_id,
                "total_days": len(trading_days),
                "total_tickers": len(tickers),
                "estimated_pairs": len(tickers) * len(trading_days),
                "scanner_type": scanner_type,
                "start_date": start.isoformat(),
                "end_date": end.isoformat(),
            }
        )

        for i, day in enumerate(trading_days, start=1):
            if _cancelled():
                run.status = "cancelled"
                run.events_detected = events_total
                run.execution_time_ms = int(
                    (
                        datetime.now(timezone.utc).replace(tzinfo=None) - started_at
                    ).total_seconds()
                    * 1000
                )
                db.commit()
                _publish(
                    {
                        "type": "cancelled",
                        "evaluated_so_far": cum["evaluated"],
                        "events_detected_so_far": events_total,
                    }
                )
                return

            _publish(
                {
                    "type": "day_started",
                    "date": day.isoformat(),
                    "day_index": i,
                    "total_days": len(trading_days),
                }
            )

            try:
                day_events = asyncio.run(
                    _orchestrator.run(
                        scanner_type, tickers, db=db, event_date=day, scanner_run=run
                    )
                )
            except Exception as e:
                cum["errors"] += 1
                logger.exception("run_universe_scan: day %s failed", day)
                _publish(
                    {"type": "day_error", "date": day.isoformat(), "error": str(e)}
                )
                continue

            events_total += len(day_events)

            run.events_detected = events_total
            db.commit()

            _write_state({"day_index": i})
            _publish(
                {
                    "type": "day_completed",
                    "date": day.isoformat(),
                    "day_index": i,
                    "total_days": len(trading_days),
                    "events": len(day_events),
                    "events_detected": events_total,
                    **cum,
                }
            )

        run.status = "completed"
        run.events_detected = events_total
        run.execution_time_ms = int(
            (
                datetime.now(timezone.utc).replace(tzinfo=None) - started_at
            ).total_seconds()
            * 1000
        )
        db.commit()
        _publish(
            {
                "type": "completed",
                "events_detected": events_total,
                "diagnostics": {
                    "tickers": len(tickers),
                    "days": len(trading_days),
                    "start_date": start.isoformat(),
                    "end_date": end.isoformat(),
                    **cum,
                },
                "execution_time_ms": run.execution_time_ms,
            }
        )
        logger.info(
            "run_universe_scan %s completed: type=%s universe=%s days=%d events=%d",
            scan_id,
            scanner_type,
            universe_id,
            len(trading_days),
            events_total,
        )
        celery_tasks_total.labels(task_name=_task_name, status="success").inc()

    except Exception as exc:
        celery_tasks_total.labels(task_name=_task_name, status="failure").inc()
        logger.exception("run_universe_scan %s failed", scan_id)
        try:
            run = db.query(ScannerRun).filter(ScannerRun.uuid == scan_id).first()
            if run is not None:
                run.status = "failed"
                run.error_message = str(exc)
                run.execution_time_ms = int(
                    (
                        datetime.now(timezone.utc).replace(tzinfo=None) - started_at
                    ).total_seconds()
                    * 1000
                )
                db.commit()
        except Exception:
            db.rollback()
        _publish({"type": "failed", "error": str(exc)})
    finally:
        celery_task_duration_seconds.labels(task_name=_task_name).observe(
            _time.monotonic() - _perf_start
        )
        try:
            r.delete(state_key)
            r.delete(cancel_key)
        except Exception:
            pass
        db.close()
