import asyncio
import json
import logging
import time as _time
from datetime import date, datetime
from types import SimpleNamespace

import redis
from sqlalchemy.orm import Session

from app.core.celery_app import celery_app
from app.core.config import settings
from app.core.database import SessionLocal
from app.core.metrics import celery_task_duration_seconds, celery_tasks_total
from app.models.monitored_stock import MonitoredStock
from app.services.quality_gate import quality_gate_service
from app.utils.time import ensure_utc, utc_now

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Testable logic helpers — no Redis/Celery/OTel imports required
# ---------------------------------------------------------------------------


def _evaluate_scanner_alerts_logic(scanner_event_id: int, db: Session) -> None:
    """Testable core of evaluate_scanner_alerts. No OTel/Celery context needed."""
    from app.models.scanner_event import ScannerEvent
    from app.services.alert_service import AlertRuleService, NotificationDispatcher

    event = db.query(ScannerEvent).filter(ScannerEvent.id == scanner_event_id).first()
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
        try:
            NotificationDispatcher.dispatch(rule, event, db)
        except Exception as exc:
            logger.error(f"❌ Dispatch failed for rule {rule.id}: {exc}")

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


def _run_range_scan_logic(
    ticker: str,
    scanner_types: list,
    start: date,
    end: date,
    fetch_missing_data: bool,
    db: Session,
    publish,
) -> int:
    """Testable core of run_range_scan. Returns events_detected count."""
    from datetime import timedelta

    from app.exceptions import DataFetchError, ProviderError
    from app.services.liquidity_hunt import run_liquidity_hunt_scan_for_date as _lh_scan
    from app.services.pocket_pivot import run_pocket_pivot_scan_for_date as _pp_scan
    from app.services.scanner import ScannerService
    from app.services.stock_data import StockDataService
    from app.services.trend_pullback_scan import (
        run_trend_pullback_scan_for_date as _tpb_scan,
    )

    trading_days = [
        start + timedelta(days=i)
        for i in range((end - start).days + 1)
        if (start + timedelta(days=i)).weekday() < 5
    ]
    total = len(trading_days) * len(scanner_types)
    events_detected = 0
    done = 0

    if fetch_missing_data:
        daily_period_days = (date.today() - (start - timedelta(days=90))).days
        try:
            StockDataService.refresh_stock_data(
                db, ticker, timespan="day", period=f"{daily_period_days}d"
            )
        except (DataFetchError, ProviderError) as exc:
            logger.warning("refresh_stock_data (day) failed for %s: %s", ticker, exc)
        minute_period_days = (date.today() - start).days + 5
        try:
            StockDataService.refresh_stock_data(
                db, ticker, timespan="minute", period=f"{minute_period_days}d"
            )
        except (DataFetchError, ProviderError) as exc:
            logger.warning("refresh_stock_data (minute) failed for %s: %s", ticker, exc)

    scanner_map = {
        "pre_market_volume_spike": ScannerService.run_pre_market_scan_for_date,
        "liquidity_hunt": _lh_scan,
        "liquidity_hunt_pre": _lh_scan,
        "liquidity_hunt_post": _lh_scan,
        "oversold_bounce": ScannerService.run_oversold_bounce_scan_for_date,
        "pocket_pivot": _pp_scan,
        "trend_pullback": _tpb_scan,
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
        publish(
            {
                "status": "progress",
                "day": day.isoformat(),
                "done": done,
                "total": total,
            }
        )

    publish({"status": "completed", "events_detected": events_detected})
    return events_detected


def _compute_data_degraded(universe_id: int, db: Session) -> bool:
    """
    Return True if the universe data is degraded at scan start time.

    Reads the latest UniverseQualityReport; if missing or generated >staleness_hours ago,
    treats as degraded. Otherwise counts stale/gapped tickers from report_data.tickers
    and returns True if affected_pct > quality_alert_pct.
    Non-blocking: any failure defaults to True (degraded) rather than aborting scan.
    """
    from app.models.system_config import SystemConfig
    from app.models.universe_quality_report import UniverseQualityReport

    try:
        keys = [
            "quality_staleness_hours",
            "quality_gap_min_weekdays",
            "quality_alert_pct",
        ]
        cfg_rows = db.query(SystemConfig).filter(SystemConfig.key.in_(keys)).all()
        cfg = {r.key: r.value for r in cfg_rows}

        def _int(key, default):
            try:
                return int(cfg.get(key, default))
            except (ValueError, TypeError):
                return default

        staleness_hours = _int("quality_staleness_hours", 48)
        alert_pct = _int("quality_alert_pct", 20)

        report = (
            db.query(UniverseQualityReport)
            .filter(UniverseQualityReport.universe_id == universe_id)
            .first()
        )
        if not report or not report.generated_at:
            return True

        now_utc = utc_now()
        report_age_hours = (now_utc - report.generated_at).total_seconds() / 3600
        if report_age_hours > staleness_hours:
            return True

        if not report.report_data:
            return True

        ticker_entries = report.report_data.get("tickers", [])
        if not ticker_entries:
            return True

        # Count stale/gapped unique tickers from the per-ticker report entries.
        # Each entry has: ticker, last_bar (ISO str or datetime), gap_count (int).
        # A ticker is stale if last_bar is None or older than staleness_hours.
        # A ticker is gapped if gap_count > 0 (gaps already filtered by _detect_gaps weekday check).
        ticker_flags: dict = {}
        for entry in ticker_entries:
            sym = entry.get("ticker")
            if not sym:
                continue
            if sym not in ticker_flags:
                ticker_flags[sym] = {"stale": False, "gapped": False}

            last_bar = entry.get("last_bar")
            if last_bar is None:
                ticker_flags[sym]["stale"] = True
            elif not ticker_flags[sym]["stale"]:
                if isinstance(last_bar, str):
                    try:
                        last_bar_dt = datetime.fromisoformat(
                            last_bar.replace("Z", "+00:00")
                        ).replace(tzinfo=None)
                    except Exception:
                        ticker_flags[sym]["stale"] = True
                        continue
                else:
                    last_bar_dt = last_bar
                if (now_utc - last_bar_dt).total_seconds() / 3600 > staleness_hours:
                    ticker_flags[sym]["stale"] = True

            if entry.get("gap_count", 0) > 0:
                ticker_flags[sym]["gapped"] = True

        total = len(ticker_flags)
        if total == 0:
            return True

        stale_count = sum(1 for v in ticker_flags.values() if v["stale"])
        gapped_count = sum(1 for v in ticker_flags.values() if v["gapped"])
        affected_pct = max(stale_count, gapped_count) / total * 100

        return affected_pct > alert_pct

    except Exception as exc:
        logger.warning("_compute_data_degraded: error reading quality report: %s", exc)
        return True


def _start_scheduled_scanner_run(
    db: Session,
    scanner_type: str,
    universe_id: int,
    event_date: date,
    stocks_scanned: int,
):
    from app.models.scanner_run import ScannerRun

    run = ScannerRun(
        scanner_type=scanner_type,
        universe_id=universe_id,
        status="running",
        stocks_scanned=stocks_scanned,
        scan_start_date=event_date,
        scan_end_date=event_date,
    )
    db.add(run)
    db.commit()
    return run


def _finish_scheduled_scanner_run(
    db: Session,
    run,
    started_at: float,
    events_detected: int,
) -> None:
    run.status = "completed"
    run.events_detected = events_detected
    run.execution_time_ms = int((_time.monotonic() - started_at) * 1000)
    db.commit()


def _fail_scheduled_scanner_run(db: Session, run, started_at: float, exc: Exception):
    try:
        db.rollback()
    except Exception:
        pass
    run.status = "failed"
    run.error_message = str(exc)
    run.execution_time_ms = int((_time.monotonic() - started_at) * 1000)
    db.commit()


def _run_universe_scan_logic(
    scan_id: str,
    scanner_type: str,
    universe_id: int,
    start: date,
    end: date,
    db: Session,
    publish,
    is_cancelled,
    task_id: str,
    write_state=None,
) -> None:
    """Testable core of run_universe_scan. No Redis/Celery/OTel imports needed."""
    from datetime import timedelta as _td

    import app.services.liquidity_hunt  # noqa: F401
    import app.services.oversold_bounce_scan  # noqa: F401
    import app.services.pocket_pivot  # noqa: F401
    import app.services.pre_market_scan  # noqa: F401 — triggers self-registration
    import app.services.scan_orchestrator as _orchestrator
    import app.services.trend_pullback_scan  # noqa: F401
    from app.models.scanner_run import ScannerRun

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
        publish({"type": "failed", "error": run.error_message})
        return

    trading_days = [
        start + _td(days=i)
        for i in range((end - start).days + 1)
        if (start + _td(days=i)).weekday() < 5
    ]

    run.status = "running"
    run.stocks_scanned = len(tickers)
    run.scan_start_date = start
    run.scan_end_date = end
    run.data_degraded = _compute_data_degraded(universe_id, db)

    gate_metadata = None
    try:
        _gate_req = SimpleNamespace(
            policy="advisory",
            universe_id=universe_id,
            scanner_type=scanner_type,
            ticker=None,
            requirements=None,
        )
        _assessment = quality_gate_service.assess(db, _gate_req)
        run.quality_gate = json.loads(json.dumps(_assessment.model_dump(), default=str))
        gate_metadata = {
            "tier": _assessment.verdict.value,
            "warnings": [
                {"code": w.code.value, "severity": w.severity, "message": w.message}
                for w in _assessment.warnings
            ],
            "schema_version": _assessment.schema_version,
        }
        if _assessment.verdict.value != "trusted":
            logger.warning(
                "run_universe_scan %s: quality gate verdict=%s for universe=%s scanner=%s",
                scan_id,
                _assessment.verdict.value,
                universe_id,
                scanner_type,
            )
    except Exception as _gate_exc:
        logger.exception(
            "run_universe_scan %s: quality gate assessment failed (degrading gracefully): %s",
            scan_id,
            _gate_exc,
        )

    db.commit()

    started_at = utc_now()

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

    def _state_payload(day_index: int) -> dict:
        return {
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "started_at": ensure_utc(started_at).isoformat(),
            "tickers": len(tickers),
            "total_days": len(trading_days),
            "events_detected": events_total,
            "day_index": day_index,
            **cum,
        }

    if write_state:
        write_state(_state_payload(0))
    publish(
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
        if is_cancelled():
            run.status = "cancelled"
            run.events_detected = events_total
            run.execution_time_ms = int((utc_now() - started_at).total_seconds() * 1000)
            db.commit()
            publish(
                {
                    "type": "cancelled",
                    "evaluated_so_far": cum["evaluated"],
                    "events_detected_so_far": events_total,
                }
            )
            return

        publish(
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
                    scanner_type,
                    tickers,
                    db=db,
                    event_date=day,
                    scanner_run=run,
                    gate_metadata=gate_metadata,
                )
            )
        except Exception as e:
            cum["errors"] += 1
            logger.exception("run_universe_scan: day %s failed", day)
            publish({"type": "day_error", "date": day.isoformat(), "error": str(e)})
            continue

        events_total += len(day_events)
        run.events_detected = events_total
        db.commit()

        if write_state:
            write_state(_state_payload(i))
        publish(
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
    run.execution_time_ms = int((utc_now() - started_at).total_seconds() * 1000)
    db.commit()
    publish(
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


@celery_app.task(bind=True, max_retries=2, name="app.tasks.evaluate_scanner_alerts")
def evaluate_scanner_alerts(self, scanner_event_id: int):
    """
    Evaluate all active alert rules against a newly-saved ScannerEvent.
    Dispatches notifications via all configured channels for any matching rules.
    For rules with auto_trade=True, queues execute_auto_trade as a follow-up task.
    Called automatically when a new ScannerEvent is created.
    """
    from opentelemetry import trace as _otel_trace

    _tracer = _otel_trace.get_tracer(__name__)
    _task_name = "evaluate_scanner_alerts"
    _start = _time.monotonic()
    db: Session = SessionLocal()
    try:
        with _tracer.start_as_current_span("alerts.evaluate") as _span:
            _span.set_attribute("event_id", scanner_event_id)
            _evaluate_scanner_alerts_logic(scanner_event_id, db)
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
    _task_name = "run_range_scan"
    _start = _time.monotonic()
    task_id = run_range_scan.request.id
    r = redis.Redis.from_url(settings.REDIS_URL, decode_responses=True)
    channel = f"scan_task:{task_id}"

    r.set(
        f"scan:{ticker}:range",
        json.dumps(
            {"task_ids": [task_id], "started_at": utc_now().isoformat()}
        ),
        ex=14400,
    )

    db: Session = SessionLocal()
    try:
        events_detected = _run_range_scan_logic(
            ticker=ticker,
            scanner_types=scanner_types,
            start=date.fromisoformat(start_date_str),
            end=date.fromisoformat(end_date_str),
            fetch_missing_data=fetch_missing_data,
            db=db,
            publish=lambda p: r.publish(channel, json.dumps(p)),
        )
        logger.info(f"run_range_scan {task_id}: completed, {events_detected} events")
        celery_tasks_total.labels(task_name=_task_name, status="success").inc()

    except Exception as e:
        celery_tasks_total.labels(task_name=_task_name, status="failure").inc()
        logger.error(f"run_range_scan {task_id} failed: {e}")
        r.publish(
            channel,
            json.dumps({"status": "failed", "error": str(e)}),
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

        if not configs:
            logger.error(
                "run_liquidity_hunt_scheduled: no active liquidity_hunt ScannerConfig "
                "rows found — add a row to scanner_configs with scanner_type='liquidity_hunt', "
                "is_active=true, and a valid universe_id FK."
            )
            raise RuntimeError("no active liquidity_hunt scanner configs")

        for cfg in configs:
            if cfg.universe_id is None:
                logger.error(
                    "run_liquidity_hunt_scheduled: ScannerConfig id=%s has universe_id=NULL "
                    "— this is a data integrity violation; run the migration "
                    "c7d8e9f0a1b2_add_universe_id_to_scanner_configs to backfill.",
                    cfg.id,
                )
                raise RuntimeError(f"ScannerConfig id={cfg.id} has universe_id=NULL")

            tickers = [
                ms.ticker
                for ms in db.query(MonitoredStock)
                .filter(
                    MonitoredStock.universe_id == cfg.universe_id,
                    MonitoredStock.is_active.is_(True),
                )
                .all()
            ]
            if not tickers:
                logger.warning(
                    "run_liquidity_hunt_scheduled: universe_id=%s has no active tickers, "
                    "skipping ScannerConfig id=%s",
                    cfg.universe_id,
                    cfg.id,
                )
                run_started = _time.monotonic()
                scanner_run = _start_scheduled_scanner_run(
                    db, "liquidity_hunt", cfg.universe_id, event_date, 0
                )
                _finish_scheduled_scanner_run(db, scanner_run, run_started, 0)
                continue

            run_started = _time.monotonic()
            scanner_run = _start_scheduled_scanner_run(
                db, "liquidity_hunt", cfg.universe_id, event_date, len(tickers)
            )
            try:
                results = asyncio.run(
                    run_liquidity_hunt_scan(
                        tickers, db, start_date=event_date, end_date=event_date
                    )
                )
                _finish_scheduled_scanner_run(
                    db, scanner_run, run_started, len(results)
                )
            except Exception as exc:
                _fail_scheduled_scanner_run(db, scanner_run, run_started, exc)
                raise
            logger.info(
                "liquidity_hunt scheduled scan for universe %s on %s: %d events",
                cfg.universe_id,
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
    from opentelemetry import context as _otel_context
    from opentelemetry import trace as _otel_trace

    _tracer = _otel_trace.get_tracer(__name__)
    _root_span = _tracer.start_span("scanner.universe_scan")
    _root_token = _otel_context.attach(_otel_trace.set_span_in_context(_root_span))
    _root_span.set_attribute("scan_id", scan_id)
    _root_span.set_attribute("universe_id", universe_id)
    _root_span.set_attribute("scanner_type", scanner_type)

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

    def _write_state(progress_extra: dict | None = None) -> None:
        r.set(
            state_key,
            json.dumps(
                {
                    "task_ids": [task_id],
                    "scan_id": scan_id,
                    "scanner_type": scanner_type,
                    "universe_id": universe_id,
                    **(progress_extra or {}),
                }
            ),
            ex=14400,
        )

    db: Session = SessionLocal()
    try:
        _run_universe_scan_logic(
            scan_id=scan_id,
            scanner_type=scanner_type,
            universe_id=universe_id,
            start=date.fromisoformat(start_date_iso),
            end=date.fromisoformat(end_date_iso),
            db=db,
            publish=_publish,
            is_cancelled=_cancelled,
            task_id=task_id,
            write_state=_write_state,
        )
        celery_tasks_total.labels(task_name=_task_name, status="success").inc()
    except Exception as exc:
        celery_tasks_total.labels(task_name=_task_name, status="failure").inc()
        logger.exception("run_universe_scan %s failed", scan_id)
        try:
            from app.models.scanner_run import ScannerRun as _ScannerRun

            _run = db.query(_ScannerRun).filter(_ScannerRun.uuid == scan_id).first()
            if _run is not None:
                _run.status = "failed"
                _run.error_message = str(exc)
                _run.execution_time_ms = int((_time.monotonic() - _perf_start) * 1000)
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
        _root_span.end()
        _otel_context.detach(_root_token)


@celery_app.task(bind=True, max_retries=1, name="app.tasks.run_pocket_pivot_scheduled")
def run_pocket_pivot_scheduled(self):
    """
    Nightly 02:00 UTC task: run pocket_pivot for today's date over all active
    ScannerConfig universes of type 'pocket_pivot'.
    """
    from app.models.scanner_config import ScannerConfig
    from app.services.pocket_pivot import run_pocket_pivot_scan
    from app.utils.session import get_market_today

    _task_name = "run_pocket_pivot_scheduled"
    _start = _time.monotonic()
    db: Session = SessionLocal()
    try:
        event_date = get_market_today()
        configs = (
            db.query(ScannerConfig)
            .filter(
                ScannerConfig.scanner_type == "pocket_pivot",
                ScannerConfig.is_active.is_(True),
            )
            .all()
        )

        if not configs:
            logger.error(
                "run_pocket_pivot_scheduled: no active pocket_pivot ScannerConfig "
                "rows found — add a row to scanner_configs with scanner_type='pocket_pivot', "
                "is_active=true, and a valid universe_id FK."
            )
            raise RuntimeError("no active pocket_pivot scanner configs")

        for cfg in configs:
            if cfg.universe_id is None:
                logger.error(
                    "run_pocket_pivot_scheduled: ScannerConfig id=%s has universe_id=NULL "
                    "— this is a data integrity violation; run the migration "
                    "c7d8e9f0a1b2_add_universe_id_to_scanner_configs to backfill.",
                    cfg.id,
                )
                raise RuntimeError(f"ScannerConfig id={cfg.id} has universe_id=NULL")

            tickers = [
                ms.ticker
                for ms in db.query(MonitoredStock)
                .filter(
                    MonitoredStock.universe_id == cfg.universe_id,
                    MonitoredStock.is_active.is_(True),
                )
                .all()
            ]
            if not tickers:
                logger.warning(
                    "run_pocket_pivot_scheduled: universe_id=%s has no active tickers, "
                    "skipping ScannerConfig id=%s",
                    cfg.universe_id,
                    cfg.id,
                )
                run_started = _time.monotonic()
                scanner_run = _start_scheduled_scanner_run(
                    db, "pocket_pivot", cfg.universe_id, event_date, 0
                )
                _finish_scheduled_scanner_run(db, scanner_run, run_started, 0)
                continue

            run_started = _time.monotonic()
            scanner_run = _start_scheduled_scanner_run(
                db, "pocket_pivot", cfg.universe_id, event_date, len(tickers)
            )
            try:
                results = asyncio.run(
                    run_pocket_pivot_scan(
                        tickers, db, start_date=event_date, end_date=event_date
                    )
                )
                _finish_scheduled_scanner_run(
                    db, scanner_run, run_started, len(results)
                )
            except Exception as exc:
                _fail_scheduled_scanner_run(db, scanner_run, run_started, exc)
                raise
            logger.info(
                "pocket_pivot scheduled scan for universe %s on %s: %d events",
                cfg.universe_id,
                event_date,
                len(results),
            )
        celery_tasks_total.labels(task_name=_task_name, status="success").inc()
    except Exception as exc:
        celery_tasks_total.labels(task_name=_task_name, status="failure").inc()
        logger.exception("run_pocket_pivot_scheduled failed: %s", exc)
        raise self.retry(exc=exc)
    finally:
        celery_task_duration_seconds.labels(task_name=_task_name).observe(
            _time.monotonic() - _start
        )
        db.close()


@celery_app.task(
    bind=True, max_retries=1, name="app.tasks.run_trend_pullback_scheduled"
)
def run_trend_pullback_scheduled(self):
    """
    Nightly 02:00 UTC task: run trend_pullback for today's date over all active
    ScannerConfig universes of type 'trend_pullback'.
    """
    from app.models.scanner_config import ScannerConfig
    from app.services.trend_pullback_scan import run_trend_pullback_scan
    from app.utils.session import get_market_today

    _task_name = "run_trend_pullback_scheduled"
    _start = _time.monotonic()
    db: Session = SessionLocal()
    try:
        event_date = get_market_today()
        configs = (
            db.query(ScannerConfig)
            .filter(
                ScannerConfig.scanner_type == "trend_pullback",
                ScannerConfig.is_active.is_(True),
            )
            .all()
        )

        if not configs:
            logger.error(
                "run_trend_pullback_scheduled: no active trend_pullback ScannerConfig "
                "rows found — add a row to scanner_configs with scanner_type='trend_pullback', "
                "is_active=true, and a valid universe_id FK."
            )
            raise RuntimeError("no active trend_pullback scanner configs")

        for cfg in configs:
            if cfg.universe_id is None:
                logger.error(
                    "run_trend_pullback_scheduled: ScannerConfig id=%s has universe_id=NULL "
                    "— this is a data integrity violation; run the migration "
                    "c7d8e9f0a1b2_add_universe_id_to_scanner_configs to backfill.",
                    cfg.id,
                )
                raise RuntimeError(f"ScannerConfig id={cfg.id} has universe_id=NULL")

            tickers = [
                ms.ticker
                for ms in db.query(MonitoredStock)
                .filter(
                    MonitoredStock.universe_id == cfg.universe_id,
                    MonitoredStock.is_active.is_(True),
                )
                .all()
            ]
            if not tickers:
                logger.warning(
                    "run_trend_pullback_scheduled: universe_id=%s has no active tickers, "
                    "skipping ScannerConfig id=%s",
                    cfg.universe_id,
                    cfg.id,
                )
                run_started = _time.monotonic()
                scanner_run = _start_scheduled_scanner_run(
                    db, "trend_pullback", cfg.universe_id, event_date, 0
                )
                _finish_scheduled_scanner_run(db, scanner_run, run_started, 0)
                continue

            run_started = _time.monotonic()
            scanner_run = _start_scheduled_scanner_run(
                db, "trend_pullback", cfg.universe_id, event_date, len(tickers)
            )
            try:
                results = asyncio.run(
                    run_trend_pullback_scan(
                        tickers, db, start_date=event_date, end_date=event_date
                    )
                )
                _finish_scheduled_scanner_run(
                    db, scanner_run, run_started, len(results)
                )
            except Exception as exc:
                _fail_scheduled_scanner_run(db, scanner_run, run_started, exc)
                raise
            logger.info(
                "trend_pullback scheduled scan for universe %s on %s: %d events",
                cfg.universe_id,
                event_date,
                len(results),
            )
        celery_tasks_total.labels(task_name=_task_name, status="success").inc()
    except Exception as exc:
        celery_tasks_total.labels(task_name=_task_name, status="failure").inc()
        logger.exception("run_trend_pullback_scheduled failed: %s", exc)
        raise self.retry(exc=exc)
    finally:
        celery_task_duration_seconds.labels(task_name=_task_name).observe(
            _time.monotonic() - _start
        )
        db.close()


# ---------------------------------------------------------------------------
# Nightly replay-diff task — 04:00 UTC weekdays
# ---------------------------------------------------------------------------


def _run_replay_diff_logic(db: Session, scan_date: date) -> None:
    """Testable core of run_replay_diff_nightly. No Celery/OTel context needed."""
    import app.services.liquidity_hunt  # noqa: F401
    import app.services.oversold_bounce_scan  # noqa: F401
    import app.services.pocket_pivot  # noqa: F401
    import app.services.pre_market_scan  # noqa: F401
    import app.services.scan_orchestrator as _orchestrator
    import app.services.trend_pullback_scan  # noqa: F401
    from app.models.scanner_config import ScannerConfig
    from app.services.replay_diff_service import run_replay_diff_for_scanner

    all_descriptors = _orchestrator.get_all()
    eligible = [d for d in all_descriptors if d.supports_date_range]

    if not eligible:
        logger.warning("run_replay_diff_nightly: no eligible scanner descriptors found")
        return

    for descriptor in eligible:
        scanner_type = descriptor.key
        configs = (
            db.query(ScannerConfig)
            .filter(
                ScannerConfig.scanner_type == scanner_type,
                ScannerConfig.is_active.is_(True),
            )
            .all()
        )
        if not configs:
            logger.info(
                "replay_diff: no active ScannerConfig for scanner_type=%s, skipping",
                scanner_type,
            )
            continue

        # Collect tickers from all active universes for this scanner type
        tickers_seen: set = set()
        for cfg in configs:
            if cfg.universe_id is None:
                continue
            rows = (
                db.query(MonitoredStock)
                .filter(
                    MonitoredStock.universe_id == cfg.universe_id,
                    MonitoredStock.is_active.is_(True),
                )
                .all()
            )
            tickers_seen.update(ms.ticker for ms in rows)

        tickers = sorted(tickers_seen)
        try:
            run_replay_diff_for_scanner(scanner_type, scan_date, tickers, db)
        except Exception as exc:
            logger.exception(
                "replay_diff: run_replay_diff_for_scanner failed scanner=%s date=%s: %s",
                scanner_type,
                scan_date,
                exc,
            )


@celery_app.task(bind=True, max_retries=1, name="app.tasks.run_replay_diff_nightly")
def run_replay_diff_nightly(self):
    """04:00 UTC weekdays: re-run yesterday's scans and diff vs live signals."""
    from datetime import timedelta

    _task_name = "run_replay_diff_nightly"
    _start = _time.monotonic()
    db: Session = SessionLocal()
    try:
        yesterday = date.today() - timedelta(days=1)
        _run_replay_diff_logic(db, yesterday)
        celery_tasks_total.labels(task_name=_task_name, status="success").inc()
    except Exception as exc:
        celery_tasks_total.labels(task_name=_task_name, status="failure").inc()
        logger.exception("run_replay_diff_nightly failed: %s", exc)
        raise self.retry(exc=exc)
    finally:
        celery_task_duration_seconds.labels(task_name=_task_name).observe(
            _time.monotonic() - _start
        )
        db.close()


# ---------------------------------------------------------------------------
# Startup validation — wired to worker_ready signal in celery_app.py
# ---------------------------------------------------------------------------

_BEAT_SCHEDULED_SCANNER_TYPES = ["liquidity_hunt", "pocket_pivot", "trend_pullback"]


def validate_scheduled_scanner_configs() -> None:
    """Check that every beat-scheduled scanner type has at least one active
    ScannerConfig with a non-null universe_id. Logs errors but never raises —
    a crash here would kill the entire worker process rather than surfacing a
    clear, actionable message.

    Called once at Celery worker/beat startup via the worker_ready signal.
    """
    from app.models.scanner_config import ScannerConfig

    try:
        db = SessionLocal()
    except Exception as exc:
        logger.error(
            "validate_scheduled_scanner_configs: could not open DB session — %s. "
            "Beat tasks may still fail at runtime.",
            exc,
        )
        return

    try:
        for scanner_type in _BEAT_SCHEDULED_SCANNER_TYPES:
            configs = (
                db.query(ScannerConfig)
                .filter(
                    ScannerConfig.scanner_type == scanner_type,
                    ScannerConfig.is_active.is_(True),
                )
                .all()
            )

            if not configs:
                logger.error(
                    "STARTUP VALIDATION FAILED: no active ScannerConfig rows for "
                    "scanner_type='%s'. The '%s' beat task will fail at 02:00 UTC. "
                    "Add a row to scanner_configs with scanner_type='%s', is_active=true, "
                    "and a valid universe_id FK referencing stock_universes(id).",
                    scanner_type,
                    scanner_type,
                    scanner_type,
                )
                continue

            for cfg in configs:
                if cfg.universe_id is None:
                    logger.error(
                        "STARTUP VALIDATION FAILED: ScannerConfig id=%s "
                        "(scanner_type='%s') has universe_id=NULL. "
                        "Run migration c7d8e9f0a1b2_add_universe_id_to_scanner_configs "
                        "to backfill existing rows.",
                        cfg.id,
                        scanner_type,
                    )

    except Exception as exc:
        logger.error(
            "validate_scheduled_scanner_configs: unexpected error during startup "
            "validation — %s. Beat tasks may still fail at runtime.",
            exc,
        )
    finally:
        db.close()
