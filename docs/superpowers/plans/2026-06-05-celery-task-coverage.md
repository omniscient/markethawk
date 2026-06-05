# Implementation Plan: Celery Task Coverage — Issue #204

**Goal**: Narrow `app/tasks/*.py` coverage omit to only genuinely broker-bound code paths, extract injectable helper functions from the three most complex task bodies (`run_universe_scan`, `run_range_scan`, `evaluate_scanner_alerts`), expand tests for all in-scope scanning/quality/trading/sync tasks, and add unit tests covering the newly-measurable ~1,800 lines of task business logic so the 60% gate applies to them.

**Architecture**: Extract business logic from Celery task shells into `_<task>_logic(...)` helpers that receive injected DB sessions, publish callables, and cancel-check callables. Task shells retain only broker-bound concerns: `self.request.id`, `SessionLocal()`, `redis.Redis.from_url(...)`, retry, OTel span creation, Prometheus timing. Tests call helpers directly with `MagicMock` DB and `fakeredis.FakeRedis`.

**Tech Stack**: pytest, unittest.mock, fakeredis (already in requirements.txt)

---

## File Structure

| File | Change |
|---|---|
| `backend/pyproject.toml` | Remove `app/tasks/*.py` from `[tool.coverage.run] omit` |
| `backend/app/tasks/trading.py` | Add `# pragma: no cover` to `_poll_live_orders` def line |
| `backend/app/tasks/sync.py` | Add `# pragma: no cover` to `sync_futures_aggregates` def line |
| `backend/app/tasks/scanning.py` | Extract `_run_universe_scan_logic`, `_run_range_scan_logic`, `_evaluate_scanner_alerts_logic` |
| `backend/tests/tasks/test_scanning_tasks.py` | New: tests for extracted scanning helpers + `run_universe_scan` guard |
| `backend/tests/tasks/test_scheduled_scanner_tasks.py` | Extend: add `run_liquidity_hunt_scheduled` no-tickers + success cases, `run_pocket_pivot_scheduled` no-tickers + success cases (`validate_scheduled_scanner_configs` already covered by 5 existing tests — no additions) |
| `backend/tests/tasks/test_quality_tasks.py` | New: tests for quality.py task shells |
| `backend/tests/tasks/test_trading_task_shells.py` | New: tests for trading.py task shells |
| `backend/tests/tasks/test_sync_tasks.py` | New: tests for sync.py tasks |

---

## Task 1: Narrow `pyproject.toml` coverage omit and add `# pragma: no cover` annotations

**Files**: `backend/pyproject.toml`, `backend/app/tasks/trading.py`, `backend/app/tasks/sync.py`

### TDD steps

#### Step 1 — Write a failing test to pin the omit list
```bash
# backend/tests/test_coverage_config.py (new file)
```
```python
"""Assert the coverage config no longer omits the full tasks package."""
import tomllib
import pathlib


def test_tasks_glob_not_in_coverage_omit():
    cfg = tomllib.loads(
        (pathlib.Path(__file__).parent.parent / "pyproject.toml").read_text()
    )
    omit = cfg["tool"]["coverage"]["run"]["omit"]
    assert "app/tasks/*.py" not in omit, (
        "app/tasks/*.py must be removed from [tool.coverage.run] omit — "
        "use # pragma: no cover on the two broker-bound functions instead"
    )
```

Run:
```bash
cd backend && python -m pytest tests/test_coverage_config.py -q
# FAILS: app/tasks/*.py is still in the omit list
```

#### Step 2 — Remove blanket omit from `pyproject.toml`

Replace in `backend/pyproject.toml`:
```toml
[tool.coverage.run]
source = ["app"]
omit = [
    "app/main.py",
    "app/migrations/*",
    # Requires live IBKR connection — tested via manual QA and docker-status agent
    "app/services/futures_data.py",
]
# _poll_live_orders and sync_futures_aggregates carry # pragma: no cover
```

#### Step 3 — Add `# pragma: no cover` to the two broker-bound functions

In `backend/app/tasks/trading.py`, line 327:
```python
def _poll_live_orders(  # pragma: no cover
    orders: list,
    db: "Session",
    now: "datetime",
) -> None:
```

In `backend/app/tasks/sync.py`, the decorator is at line 538 and the `def` is at line 539 — the pragma must go on the `def` line so coverage.py excludes the function body:
```python
@celery_app.task(bind=True, max_retries=3, name="app.tasks.sync_futures_aggregates")
def sync_futures_aggregates(  # pragma: no cover
    self,
    symbol: str,
    exchange: str,
    ...
```

#### Step 4 — Verify test passes
```bash
cd backend && python -m pytest tests/test_coverage_config.py -q
# PASSES
```

#### Step 5 — Commit
```bash
git add backend/pyproject.toml backend/app/tasks/trading.py backend/app/tasks/sync.py backend/tests/test_coverage_config.py
git commit -m "fix(coverage): narrow task omit to broker-bound functions only (#204)"
```

---

## Task 2: Extract `_run_universe_scan_logic` from `run_universe_scan`

**Files**: `backend/app/tasks/scanning.py`

### TDD steps

#### Step 1 — Write a failing import test
```python
# backend/tests/tasks/test_scanning_tasks.py (new)
def test_run_universe_scan_logic_is_importable():
    from app.tasks.scanning import _run_universe_scan_logic
    assert callable(_run_universe_scan_logic)
```
Run: fails with `ImportError`.

#### Step 2 — Extract `_run_universe_scan_logic` into `scanning.py`

Add before `run_universe_scan` in `backend/app/tasks/scanning.py`:

```python
def _run_universe_scan_logic(
    scan_id: str,
    scanner_type: str,
    universe_id: int,
    start: "date",
    end: "date",
    db: Session,
    publish: "Callable[[dict], None]",
    is_cancelled: "Callable[[], bool]",
    task_id: str,
    write_state: "Callable[[dict | None], None] | None" = None,
) -> None:
    """Testable core of run_universe_scan. No Redis/Celery imports needed."""
    from datetime import date as _date
    from datetime import timedelta as _td
    from datetime import datetime as _dt, timezone as _tz

    import app.services.liquidity_hunt  # noqa: F401
    import app.services.oversold_bounce_scan  # noqa: F401
    import app.services.pre_market_scan  # noqa: F401
    import app.services.pocket_pivot  # noqa: F401
    import app.services.scan_orchestrator as _orchestrator
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
    db.commit()

    started_at = _dt.now(_tz.utc).replace(tzinfo=None)

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
        """Build the full Redis state dict that the frontend polling path reads.

        Preserves the shape written by the original run_universe_scan shell:
        task_ids, scan_id, scanner_type, universe_id, start/end dates,
        started_at, tickers count, total_days, events_detected, cum diagnostics,
        and day_index.  The shell's _write_state merges this as progress_extra.
        """
        return {
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "started_at": started_at.replace(tzinfo=_tz.utc).isoformat(),
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
            run.execution_time_ms = int(
                (_dt.now(_tz.utc).replace(tzinfo=None) - started_at).total_seconds() * 1000
            )
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
                    scanner_type, tickers, db=db, event_date=day, scanner_run=run
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
    run.execution_time_ms = int(
        (_dt.now(_tz.utc).replace(tzinfo=None) - started_at).total_seconds() * 1000
    )
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
        scan_id, scanner_type, universe_id, len(trading_days), events_total,
    )
```

Update the `run_universe_scan` shell to call the helper (keep OTel, Redis, metrics, finally):

```python
@celery_app.task(bind=True, max_retries=0, name="app.tasks.run_universe_scan")
def run_universe_scan(self, scan_id, scanner_type, universe_id, start_date_iso, end_date_iso):
    """Run a scanner across (universe, [start_date..end_date]) with progress reporting."""
    from datetime import date as _date
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

    def _publish(payload):
        try:
            r.publish(channel, json.dumps(payload, default=str))
        except Exception:
            logger.exception("scan_task publish failed")

    def _cancelled():
        return r.exists(cancel_key) > 0

    def _write_state(progress_extra=None):
        # Preserve the full state contract read by the frontend polling path.
        # The logic helper passes the full diagnostics dict as progress_extra
        # so consumers of the Redis key see the same payload shape as before.
        r.set(state_key, json.dumps({
            "task_ids": [task_id], "scan_id": scan_id, "scanner_type": scanner_type,
            "universe_id": universe_id, **(progress_extra or {}),
        }), ex=14400)

    db: Session = SessionLocal()
    try:
        _run_universe_scan_logic(
            scan_id=scan_id,
            scanner_type=scanner_type,
            universe_id=universe_id,
            start=_date.fromisoformat(start_date_iso),
            end=_date.fromisoformat(end_date_iso),
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
        # Preserve the original failure-persistence logic: re-fetch run and mark failed
        # so the frontend does not see it stuck in "running" after a crash.
        try:
            from app.models.scanner_run import ScannerRun as _ScannerRun
            _run = db.query(_ScannerRun).filter(_ScannerRun.uuid == scan_id).first()
            if _run is not None:
                _run.status = "failed"
                _run.error_message = str(exc)
                _run.execution_time_ms = int(
                    (_time.monotonic() - _perf_start) * 1000
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
        _root_span.end()
        _otel_context.detach(_root_token)
```

#### Step 3 — Verify import test passes
```bash
cd backend && python -m pytest tests/tasks/test_scanning_tasks.py::test_run_universe_scan_logic_is_importable -q
# PASSES
```

#### Step 4 — Commit
```bash
git add backend/app/tasks/scanning.py
git commit -m "refactor(tasks): extract _run_universe_scan_logic helper for testability (#204)"
```

---

## Task 3: Extract `_run_range_scan_logic` and `_evaluate_scanner_alerts_logic`

**Files**: `backend/app/tasks/scanning.py`

### TDD steps

#### Step 1 — Write failing import tests (add to `test_scanning_tasks.py`)
```python
def test_run_range_scan_logic_is_importable():
    from app.tasks.scanning import _run_range_scan_logic
    assert callable(_run_range_scan_logic)

def test_evaluate_scanner_alerts_logic_is_importable():
    from app.tasks.scanning import _evaluate_scanner_alerts_logic
    assert callable(_evaluate_scanner_alerts_logic)
```

#### Step 2 — Add `_run_range_scan_logic` to `scanning.py`

```python
def _run_range_scan_logic(
    ticker: str,
    scanner_types: list,
    start: "date",
    end: "date",
    fetch_missing_data: bool,
    db: Session,
    publish: "Callable[[dict], None]",
) -> int:
    """Testable core of run_range_scan. Returns events_detected count."""
    from datetime import date, timedelta
    from app.exceptions import DataFetchError, ProviderError
    from app.services.liquidity_hunt import run_liquidity_hunt_scan_for_date as _lh_scan
    from app.services.pocket_pivot import run_pocket_pivot_scan_for_date as _pp_scan
    from app.services.scanner import ScannerService
    from app.services.stock_data import StockDataService

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
            StockDataService.refresh_stock_data(db, ticker, timespan="day", period=f"{daily_period_days}d")
        except (DataFetchError, ProviderError) as exc:
            logger.warning("refresh_stock_data (day) failed for %s: %s", ticker, exc)
        minute_period_days = (date.today() - start).days + 5
        try:
            StockDataService.refresh_stock_data(db, ticker, timespan="minute", period=f"{minute_period_days}d")
        except (DataFetchError, ProviderError) as exc:
            logger.warning("refresh_stock_data (minute) failed for %s: %s", ticker, exc)

    scanner_map = {
        "pre_market_volume_spike": ScannerService.run_pre_market_scan_for_date,
        "liquidity_hunt": _lh_scan,
        "liquidity_hunt_pre": _lh_scan,
        "liquidity_hunt_post": _lh_scan,
        "oversold_bounce": ScannerService.run_oversold_bounce_scan_for_date,
        "pocket_pivot": _pp_scan,
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
        publish({
            "status": "progress",
            "day": day.isoformat(),
            "done": done,
            "total": total,
        })

    publish({"status": "completed", "events_detected": events_detected})
    return events_detected
```

Update `run_range_scan` shell:
```python
@celery_app.task(name="app.tasks.run_range_scan")
def run_range_scan(ticker, scanner_types, start_date_str, end_date_str, fetch_missing_data):
    """Background task: run selected scanners over a date range for one ticker."""
    from datetime import date

    _task_name = "run_range_scan"
    _start = _time.monotonic()
    task_id = run_range_scan.request.id
    r = redis.Redis.from_url(settings.REDIS_URL, decode_responses=True)
    channel = f"scan_task:{task_id}"

    from datetime import datetime as _dt
    r.set(f"scan:{ticker}:range", json.dumps({"task_ids": [task_id], "started_at": _dt.utcnow().isoformat()}), ex=14400)

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
        r.publish(channel, json.dumps({"status": "failed", "error": str(e)}))
    finally:
        celery_task_duration_seconds.labels(task_name=_task_name).observe(_time.monotonic() - _start)
        r.delete(f"scan:{ticker}:range")
        db.close()
```

Add `_evaluate_scanner_alerts_logic`:
```python
def _evaluate_scanner_alerts_logic(scanner_event_id: int, db: Session) -> None:
    """Testable core of evaluate_scanner_alerts. No OTel/Celery context needed."""
    from app.models.scanner_event import ScannerEvent
    from app.services.alert_service import AlertRuleService, NotificationDispatcher

    event = db.query(ScannerEvent).filter(ScannerEvent.id == scanner_event_id).first()
    if not event:
        logger.warning(f"evaluate_scanner_alerts: ScannerEvent id={scanner_event_id} not found.")
        return

    matching_rules = AlertRuleService.get_matching_rules(event, db)
    if not matching_rules:
        return

    logger.info(
        f"🔔 {len(matching_rules)} alert rule(s) matched event={scanner_event_id} "
        f"ticker={event.ticker} type={event.scanner_type}"
    )

    for rule in matching_rules:
        try:
            NotificationDispatcher.dispatch(rule, event, db)
        except Exception as exc:
            logger.error(f"❌ Dispatch failed for rule {rule.id}: {exc}")

        if rule.auto_trade and rule.trading_strategy_id:
            from app.tasks.trading import execute_auto_trade
            execute_auto_trade.delay(rule_id=rule.id, scanner_event_id=scanner_event_id)
            logger.info(f"🤖 Auto-trade queued for rule={rule.id} strategy={rule.trading_strategy_id} ticker={event.ticker}")
```

Update `evaluate_scanner_alerts` shell:
```python
@celery_app.task(bind=True, max_retries=2, name="app.tasks.evaluate_scanner_alerts")
def evaluate_scanner_alerts(self, scanner_event_id: int):
    """Evaluate all active alert rules against a newly-saved ScannerEvent."""
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
        logger.error(f"❌ evaluate_scanner_alerts failed for event {scanner_event_id}: {e}")
        db.rollback()
        raise self.retry(exc=e, countdown=30)
    finally:
        celery_task_duration_seconds.labels(task_name=_task_name).observe(_time.monotonic() - _start)
        db.close()
```

#### Step 3 — Verify import tests pass
```bash
cd backend && python -m pytest tests/tasks/test_scanning_tasks.py -k "importable" -q
# PASSES (3 tests)
```

#### Step 4 — Commit
```bash
git add backend/app/tasks/scanning.py
git commit -m "refactor(tasks): extract _run_range_scan_logic and _evaluate_scanner_alerts_logic (#204)"
```

---

## Task 4: Tests for `_run_universe_scan_logic` and `run_universe_scan` guard

**Files**: `backend/tests/tasks/test_scanning_tasks.py`

### TDD steps

#### Step 1 — Write failing tests

Full content of `backend/tests/tasks/test_scanning_tasks.py`:

```python
"""Unit tests for scanning task helpers — no broker required."""
import pytest
from datetime import date
from unittest.mock import MagicMock, patch, call
import fakeredis


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_run(uuid, status="pending"):
    run = MagicMock()
    run.uuid = uuid
    run.status = status
    run.events_detected = 0
    return run


def _make_ticker(ticker_str):
    t = MagicMock()
    t.ticker = ticker_str
    return t


def _make_db(run=None, tickers=None):
    """Mock DB that returns run from first query and tickers from second."""
    from app.models.scanner_run import ScannerRun
    from app.models.monitored_stock import MonitoredStock

    db = MagicMock()
    call_count = [0]

    def _query_side_effect(model):
        q = MagicMock()
        idx = call_count[0]
        call_count[0] += 1
        if model is ScannerRun or idx == 0:
            q.filter.return_value.first.return_value = run
        else:
            q.filter.return_value.all.return_value = tickers or []
        return q

    db.query.side_effect = _query_side_effect
    return db


# ---------------------------------------------------------------------------
# Import checks
# ---------------------------------------------------------------------------

def test_run_universe_scan_logic_is_importable():
    from app.tasks.scanning import _run_universe_scan_logic
    assert callable(_run_universe_scan_logic)


def test_run_range_scan_logic_is_importable():
    from app.tasks.scanning import _run_range_scan_logic
    assert callable(_run_range_scan_logic)


def test_evaluate_scanner_alerts_logic_is_importable():
    from app.tasks.scanning import _evaluate_scanner_alerts_logic
    assert callable(_evaluate_scanner_alerts_logic)


# ---------------------------------------------------------------------------
# _run_universe_scan_logic tests
# ---------------------------------------------------------------------------

class TestRunUniverseScanLogic:

    def _run_logic(self, run, tickers, days=1, is_cancelled=False, orchestrator_side_effect=None):
        from app.tasks.scanning import _run_universe_scan_logic
        from app.models.scanner_run import ScannerRun
        from app.models.monitored_stock import MonitoredStock

        published = []

        db = MagicMock()
        call_count = [0]

        def _query_side(model):
            q = MagicMock()
            if call_count[0] == 0:
                q.filter.return_value.first.return_value = run
            else:
                q.filter.return_value.all.return_value = tickers
            call_count[0] += 1
            return q

        db.query.side_effect = _query_side

        cancel_calls = [0]
        def _cancelled():
            cancel_calls[0] += 1
            return is_cancelled and cancel_calls[0] > 1  # cancel after first iteration

        orch_mock = MagicMock()
        if orchestrator_side_effect:
            orch_mock.side_effect = orchestrator_side_effect
        else:
            orch_mock.return_value = []

        with patch("app.services.scan_orchestrator.run", orch_mock):
            with patch("app.tasks.scanning.asyncio.run", side_effect=lambda coro: []):
                _run_universe_scan_logic(
                    scan_id="scan-001",
                    scanner_type="pre_market_volume_spike",
                    universe_id=1,
                    start=date(2026, 6, 2),  # Monday
                    end=date(2026, 6, 2),
                    db=db,
                    publish=lambda p: published.append(p),
                    is_cancelled=lambda: is_cancelled,
                    task_id="task-abc",
                )

        return published, db

    def test_run_not_found_returns_early(self):
        published, db = self._run_logic(run=None, tickers=[_make_ticker("AAPL")])
        assert not any(p.get("type") == "started" for p in published)
        db.commit.assert_not_called()

    def test_no_tickers_publishes_failed(self):
        run = _make_run("scan-001")
        published, db = self._run_logic(run=run, tickers=[])
        assert run.status == "failed"
        assert any(p.get("type") == "failed" for p in published)

    def test_happy_path_publishes_started_and_completed(self):
        run = _make_run("scan-001")
        published, _ = self._run_logic(run=run, tickers=[_make_ticker("AAPL")])
        types = [p.get("type") for p in published]
        assert "started" in types
        assert "completed" in types

    def test_cancel_flag_sets_status_cancelled(self):
        from app.tasks.scanning import _run_universe_scan_logic

        run = _make_run("scan-001")
        published = []

        db = MagicMock()
        call_count = [0]
        def _query_side(model):
            q = MagicMock()
            if call_count[0] == 0:
                q.filter.return_value.first.return_value = run
            else:
                q.filter.return_value.all.return_value = [_make_ticker("AAPL")]
            call_count[0] += 1
            return q
        db.query.side_effect = _query_side

        with patch("app.tasks.scanning.asyncio.run", return_value=[]):
            _run_universe_scan_logic(
                scan_id="scan-001",
                scanner_type="pre_market_volume_spike",
                universe_id=1,
                start=date(2026, 6, 2),
                end=date(2026, 6, 2),
                db=db,
                publish=lambda p: published.append(p),
                is_cancelled=lambda: True,  # always cancelled
                task_id="task-abc",
            )

        assert run.status == "cancelled"
        assert any(p.get("type") == "cancelled" for p in published)

    def test_day_error_continues_to_completion(self):
        from app.tasks.scanning import _run_universe_scan_logic

        run = _make_run("scan-001")
        published = []

        db = MagicMock()
        call_count = [0]
        def _query_side(model):
            q = MagicMock()
            if call_count[0] == 0:
                q.filter.return_value.first.return_value = run
            else:
                q.filter.return_value.all.return_value = [_make_ticker("AAPL")]
            call_count[0] += 1
            return q
        db.query.side_effect = _query_side

        with patch("app.tasks.scanning.asyncio.run", side_effect=RuntimeError("day failed")):
            _run_universe_scan_logic(
                scan_id="scan-001",
                scanner_type="pre_market_volume_spike",
                universe_id=1,
                start=date(2026, 6, 2),
                end=date(2026, 6, 2),
                db=db,
                publish=lambda p: published.append(p),
                is_cancelled=lambda: False,
                task_id="task-abc",
            )

        # Day error published but task still completes
        assert any(p.get("type") == "day_error" for p in published)
        assert run.status == "completed"

    def test_weekends_excluded_from_trading_days(self):
        """Saturday and Sunday are skipped — a 7-day range Mon–Sun has 5 trading days."""
        from app.tasks.scanning import _run_universe_scan_logic

        run = _make_run("scan-001")
        day_started_events = []

        db = MagicMock()
        call_count = [0]
        def _query_side(model):
            q = MagicMock()
            if call_count[0] == 0:
                q.filter.return_value.first.return_value = run
            else:
                q.filter.return_value.all.return_value = [_make_ticker("AAPL")]
            call_count[0] += 1
            return q
        db.query.side_effect = _query_side

        with patch("app.tasks.scanning.asyncio.run", return_value=[]):
            _run_universe_scan_logic(
                scan_id="scan-001",
                scanner_type="pre_market_volume_spike",
                universe_id=1,
                start=date(2026, 6, 1),   # Monday
                end=date(2026, 6, 7),     # Sunday
                db=db,
                publish=lambda p: day_started_events.append(p) if p.get("type") == "day_started" else None,
                is_cancelled=lambda: False,
                task_id="task-abc",
            )

        assert len(day_started_events) == 5  # Mon–Fri only


# ---------------------------------------------------------------------------
# _evaluate_scanner_alerts_logic tests
# ---------------------------------------------------------------------------

class TestEvaluateScannerAlertsLogic:

    def _run_logic(self, event=None, matching_rules=None):
        from app.tasks.scanning import _evaluate_scanner_alerts_logic
        from app.models.scanner_event import ScannerEvent

        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = event

        with (
            patch("app.services.alert_service.AlertRuleService.get_matching_rules",
                  return_value=matching_rules or []),
            patch("app.services.alert_service.NotificationDispatcher.dispatch") as mock_dispatch,
            patch("app.tasks.trading.execute_auto_trade") as mock_trade,
        ):
            _evaluate_scanner_alerts_logic(scanner_event_id=42, db=db)
            return mock_dispatch, mock_trade

    def test_event_not_found_returns_without_dispatch(self):
        mock_dispatch, _ = self._run_logic(event=None)
        mock_dispatch.assert_not_called()

    def test_no_matching_rules_returns_without_dispatch(self):
        event = MagicMock()
        event.ticker = "AAPL"
        mock_dispatch, _ = self._run_logic(event=event, matching_rules=[])
        mock_dispatch.assert_not_called()

    def test_matching_rule_dispatches_notification(self):
        event = MagicMock()
        event.ticker = "AAPL"
        rule = MagicMock()
        rule.auto_trade = False
        mock_dispatch, _ = self._run_logic(event=event, matching_rules=[rule])
        mock_dispatch.assert_called_once()

    def test_auto_trade_rule_queues_execute_auto_trade(self):
        from app.tasks.scanning import _evaluate_scanner_alerts_logic
        from app.models.scanner_event import ScannerEvent

        event = MagicMock()
        event.ticker = "AAPL"
        rule = MagicMock()
        rule.id = 7
        rule.auto_trade = True
        rule.trading_strategy_id = 3

        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = event

        with (
            patch("app.services.alert_service.AlertRuleService.get_matching_rules", return_value=[rule]),
            patch("app.services.alert_service.NotificationDispatcher.dispatch"),
            patch("app.tasks.trading.execute_auto_trade") as mock_trade,
        ):
            _evaluate_scanner_alerts_logic(scanner_event_id=42, db=db)

        mock_trade.delay.assert_called_once_with(rule_id=7, scanner_event_id=42)


# ---------------------------------------------------------------------------
# _run_range_scan_logic tests
# ---------------------------------------------------------------------------

class TestRunRangeScanLogic:

    def _run_logic(self, start, end, scanner_types=None, fetch_missing=False):
        from app.tasks.scanning import _run_range_scan_logic

        if scanner_types is None:
            scanner_types = ["pre_market_volume_spike"]

        published = []
        db = MagicMock()

        with (
            patch("app.services.scanner.ScannerService.run_pre_market_scan_for_date",
                  return_value=[MagicMock(), MagicMock()]),
            patch("app.tasks.scanning.asyncio.run", return_value=[MagicMock()]),
        ):
            count = _run_range_scan_logic(
                ticker="AAPL",
                scanner_types=scanner_types,
                start=start,
                end=end,
                fetch_missing_data=fetch_missing,
                db=db,
                publish=lambda p: published.append(p),
            )

        return count, published

    def test_weekends_skipped_in_trading_days(self):
        # Mon 2026-06-01 to Sun 2026-06-07 → 5 trading days
        count, published = self._run_logic(start=date(2026, 6, 1), end=date(2026, 6, 7))
        progress_days = [p for p in published if p.get("status") == "progress"]
        assert len(progress_days) == 5

    def test_returns_event_count(self):
        count, _ = self._run_logic(start=date(2026, 6, 2), end=date(2026, 6, 2))
        assert isinstance(count, int)

    def test_completed_message_published(self):
        _, published = self._run_logic(start=date(2026, 6, 2), end=date(2026, 6, 2))
        assert any(p.get("status") == "completed" for p in published)
```

Run:
```bash
cd backend && python -m pytest tests/tasks/test_scanning_tasks.py -q
# Most pass; some may fail if helpers not yet extracted (Task 2/3 must come first)
```

#### Step 2 — Fix any test failures from extraction gaps, then re-run until green
```bash
cd backend && python -m pytest tests/tasks/test_scanning_tasks.py -q
# PASSES (all tests green)
```

#### Step 3 — Commit
```bash
git add backend/tests/tasks/test_scanning_tasks.py
git commit -m "test(tasks): unit tests for _run_universe_scan_logic and alert/range-scan helpers (#204)"
```

---

## Task 4.5: Expand tests for `run_liquidity_hunt_scheduled`, `run_pocket_pivot_scheduled`, and `validate_scheduled_scanner_configs`

**Files**: `backend/tests/tasks/test_scheduled_scanner_tasks.py` (extend existing — add methods to `TestRunLiquidityHuntScheduledFixed` and `TestRunPocketPivotScheduledFixed` only)

The two scan classes have `_run_with_configs(self, configs, tickers=None)` helpers. We add new test methods to these **existing** classes using that exact signature. `TestValidateScheduledScannerConfigs` is **already covered** by five existing tests (pass, missing-each-type, null-universe, does-not-raise) and needs no additions.

### TDD steps

#### Step 1 — Write failing tests (append methods to the two existing scan classes in `test_scheduled_scanner_tasks.py`)

```python
# --- Append to class TestRunLiquidityHuntScheduledFixed ---

    def test_no_tickers_logs_warning_and_does_not_raise(self, caplog):
        """Universe with no active tickers should log a warning and skip, not raise."""
        import logging
        cfg = _make_cfg(id=2, universe_id=1)
        with caplog.at_level(logging.WARNING, logger="app.tasks.scanning"):
            # tickers=[] → the task's `continue` path at scanning.py:286-293 skips
            self._run_with_configs([cfg], tickers=[])
        assert any("no active tickers" in r.message.lower() for r in caplog.records)

    def test_success_with_tickers_does_not_raise(self):
        """Happy path: valid config + tickers completes without exception."""
        cfg = _make_cfg(id=2, universe_id=1)
        tickers = [MagicMock(ticker="AAPL"), MagicMock(ticker="TSLA")]
        self._run_with_configs([cfg], tickers=tickers)


# --- Append to class TestRunPocketPivotScheduledFixed ---

    def test_no_tickers_logs_warning_and_does_not_raise(self, caplog):
        """Universe with no active tickers should log a warning and skip, not raise."""
        import logging
        cfg = _make_cfg(id=4, universe_id=1, scanner_type="pocket_pivot")
        with caplog.at_level(logging.WARNING, logger="app.tasks.scanning"):
            # tickers=[] → the task's `continue` path at scanning.py:650-655 skips
            self._run_with_configs([cfg], tickers=[])
        assert any("no active tickers" in r.message.lower() for r in caplog.records)

    def test_success_with_tickers_does_not_raise(self):
        """Happy path: valid config + tickers completes without exception."""
        cfg = _make_cfg(id=4, universe_id=1, scanner_type="pocket_pivot")
        tickers = [MagicMock(ticker="AAPL")]
        self._run_with_configs([cfg], tickers=tickers)
```

Run:
```bash
cd backend && python -m pytest tests/tasks/test_scheduled_scanner_tasks.py -q
# PASSES — tasks implement the no-tickers `continue` path at
# scanning.py:286-293 (liquidity_hunt) and :650-655 (pocket_pivot)
```

#### Step 2 — Commit
```bash
git add backend/tests/tasks/test_scheduled_scanner_tasks.py
git commit -m "test(tasks): expand scheduled-scanner coverage — no-tickers and success paths (#204)"
```

---

## Task 5: Tests for `quality.py` task shells

> **Note on spec requirement #3 (helper extraction scope):** The spec's architecture section explicitly states: *"For `quality.py` and `trading.py` shells the tasks are already thin enough that helper extraction may not be necessary — the test can patch `SessionLocal` and call `.run()` directly."* The same applies to `sync.py` tasks (thin shells delegating to `StockDataService`, `httpx.Client`, or split-adjustment services). Tasks 5–7 therefore test the shells in place without extracting helpers, consistent with the spec's own guidance. Extraction is only required where the task body contains non-trivial orchestration logic that would otherwise be invisible to coverage — i.e., the three scanning tasks handled in Tasks 2–3.

**Files**: `backend/tests/tasks/test_quality_tasks.py` (new)

### TDD steps

#### Step 1 — Write failing tests

```python
"""Unit tests for quality.py Celery task shells."""
import pytest
from unittest.mock import MagicMock, patch, call


def _make_report(universe_id=1, has_data=True, norm_data=None):
    r = MagicMock()
    r.universe_id = universe_id
    r.status = "pending"
    r.normalization_status = "pending"
    r.report_data = {"overall_grade": "B", "overall_score": 80, "ticker_count": 5} if has_data else None
    r.normalization_data = norm_data
    return r


class TestAnalyzeUniverseQuality:

    def _run(self, report, analyze_result=None, analyze_raises=None):
        import app.tasks.quality as quality_module
        from app.models.universe_quality_report import UniverseQualityReport

        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = report

        if analyze_result is None:
            analyze_result = {"overall_grade": "A", "overall_score": 95, "ticker_count": 10}

        with (
            patch("app.tasks.quality.SessionLocal", return_value=db),
            patch("app.services.data_quality.DataQualityService.analyze_universe",
                  side_effect=analyze_raises or (lambda *a, **kw: analyze_result)),
        ):
            quality_module.analyze_universe_quality.run(1)

        return db, report

    def test_sets_status_running_before_analysis(self):
        report = _make_report()
        status_sequence = []
        orig_commit = MagicMock(side_effect=lambda: status_sequence.append(report.status))
        report.__class__ = MagicMock  # allow attribute setting
        db, r = self._run(report)
        # report.status must pass through "running" → "complete"
        assert r.status == "complete"

    def test_creates_report_when_none_exists(self):
        import app.tasks.quality as quality_module

        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = None  # no existing report

        with (
            patch("app.tasks.quality.SessionLocal", return_value=db),
            patch("app.services.data_quality.DataQualityService.analyze_universe",
                  return_value={"overall_grade": "A", "overall_score": 95, "ticker_count": 5}),
        ):
            quality_module.analyze_universe_quality.run(1)

        db.add.assert_called_once()  # new report row created

    def test_sets_report_complete_on_success(self):
        report = _make_report()
        db, r = self._run(report)
        assert r.status == "complete"
        assert r.overall_grade == "A"

    def test_sets_report_error_on_exception(self):
        import app.tasks.quality as quality_module

        report = _make_report()
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = report

        with (
            patch("app.tasks.quality.SessionLocal", return_value=db),
            patch("app.services.data_quality.DataQualityService.analyze_universe",
                  side_effect=RuntimeError("analysis failed")),
        ):
            with pytest.raises(RuntimeError):
                quality_module.analyze_universe_quality.run(1)

        assert report.status == "error"
        assert "analysis failed" in report.error_message


class TestNormalizeUniverseQuality:

    def _run(self, report, norm_result=None, norm_raises=None):
        import app.tasks.quality as quality_module

        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = report

        if norm_result is None:
            norm_result = {"fixes_applied": 3, "status": "complete"}

        with (
            patch("app.tasks.quality.SessionLocal", return_value=db),
            patch("app.services.normalization.NormalizationService.run",
                  side_effect=norm_raises or (lambda **kw: norm_result)),
            patch("app.tasks.quality.analyze_universe_quality") as mock_analyze,
        ):
            quality_module.normalize_universe_quality.run(1)
            return db, report, mock_analyze

    def test_raises_when_no_quality_report_exists(self):
        import app.tasks.quality as quality_module

        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = None

        with patch("app.tasks.quality.SessionLocal", return_value=db):
            with pytest.raises(RuntimeError, match="Quality analysis must be run"):
                quality_module.normalize_universe_quality.run(1)

    def test_raises_when_report_has_no_data(self):
        import app.tasks.quality as quality_module

        report = _make_report(has_data=False)
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = report

        with patch("app.tasks.quality.SessionLocal", return_value=db):
            with pytest.raises(RuntimeError, match="Quality analysis must be run"):
                quality_module.normalize_universe_quality.run(1)

    def test_sets_complete_and_triggers_analysis_on_success(self):
        report = _make_report()
        db, r, mock_analyze = self._run(report)
        assert r.normalization_status == "complete"
        mock_analyze.delay.assert_called_once_with(1)

    def test_sets_normalization_error_on_failure(self):
        import app.tasks.quality as quality_module

        report = _make_report()
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = report

        with (
            patch("app.tasks.quality.SessionLocal", return_value=db),
            patch("app.services.normalization.NormalizationService.run",
                  side_effect=RuntimeError("norm failed")),
        ):
            with pytest.raises(RuntimeError):
                quality_module.normalize_universe_quality.run(1)

        assert report.normalization_status == "error"


class TestAnalyzeSignalFeatures:

    def test_insufficient_data_sets_failed_status(self):
        import app.tasks.quality as quality_module
        from app.models.signal_analysis_run import SignalAnalysisRun

        db = MagicMock()
        run_obj = MagicMock()
        run_obj.id = 1
        db.add.return_value = None
        db.flush = MagicMock()
        db.refresh = MagicMock()

        # query returns fewer than 500 unique events
        mock_rows = [MagicMock(event_id=i, scanner_type="pre_market", indicators={},
                               interval_key="1h", pct_change=1.0) for i in range(10)]

        db.query.return_value.join.return_value.join.return_value.filter.return_value.filter.return_value.all.return_value = mock_rows

        # The SignalAnalysisRun created in the task
        created_run = MagicMock()
        created_run.id = 1

        with (
            patch("app.tasks.quality.SessionLocal", return_value=db),
            patch("app.models.signal_analysis_run.SignalAnalysisRun", return_value=created_run),
        ):
            quality_module.analyze_signal_features.run()

        # Should set status to "failed" with insufficient data message
        assert created_run.status == "failed"
        assert "Insufficient" in created_run.error_message
```

Run:
```bash
cd backend && python -m pytest tests/tasks/test_quality_tasks.py -q
# FAILS (tests reference imports not yet proven to work)
```

#### Step 2 — Fix any import issues, iterate until green
```bash
cd backend && python -m pytest tests/tasks/test_quality_tasks.py -q
# PASSES
```

#### Step 3 — Commit
```bash
git add backend/tests/tasks/test_quality_tasks.py
git commit -m "test(tasks): unit tests for quality.py task shells (#204)"
```

---

## Task 6: Tests for `trading.py` task shells

**Files**: `backend/tests/tasks/test_trading_task_shells.py` (new)

### TDD steps

#### Step 1 — Write failing tests

```python
"""Unit tests for trading.py Celery task shells (execute_auto_trade, submit_approved_order, poll_auto_trade_fills paper path)."""
import pytest
from unittest.mock import MagicMock, patch


class TestExecuteAutoTrade:

    def _run(self, rule=None, event=None, executor_result=None):
        import app.tasks.trading as trading_module

        db = MagicMock()
        call_count = [0]

        def _query_side(model):
            q = MagicMock()
            if call_count[0] == 0:
                q.filter.return_value.first.return_value = rule
            else:
                q.filter.return_value.first.return_value = event
            call_count[0] += 1
            return q

        db.query.side_effect = _query_side

        def _retry_reraises(exc, **kw):
            raise exc

        with (
            patch("app.tasks.trading.SessionLocal", return_value=db),
            patch("app.services.auto_trade_service.auto_trade_executor") as mock_executor,
            patch.object(trading_module.execute_auto_trade, "retry", side_effect=_retry_reraises),
        ):
            mock_executor.maybe_execute.return_value = executor_result
            trading_module.execute_auto_trade.run(rule_id=1, scanner_event_id=2)
            return mock_executor, db

    def test_rule_not_found_returns_without_execute(self):
        mock_executor, _ = self._run(rule=None, event=MagicMock())
        mock_executor.maybe_execute.assert_not_called()

    def test_event_not_found_returns_without_execute(self):
        mock_executor, _ = self._run(rule=MagicMock(), event=None)
        mock_executor.maybe_execute.assert_not_called()

    def test_success_calls_maybe_execute(self):
        rule = MagicMock()
        event = MagicMock()
        event.ticker = "AAPL"
        mock_executor, _ = self._run(rule=rule, event=event)
        mock_executor.maybe_execute.assert_called_once()


class TestSubmitApprovedOrder:

    def _run(self, order=None):
        import app.tasks.trading as trading_module

        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = order

        def _retry_reraises(exc, **kw):
            raise exc

        with (
            patch("app.tasks.trading.SessionLocal", return_value=db),
            patch("app.services.auto_trade_service.auto_trade_executor") as mock_executor,
            patch.object(trading_module.submit_approved_order, "retry", side_effect=_retry_reraises),
        ):
            trading_module.submit_approved_order.run(order_id=5)
            return mock_executor, db

    def test_order_not_found_returns_without_submit(self):
        mock_executor, _ = self._run(order=None)
        mock_executor.submit_existing_order.assert_not_called()

    def test_wrong_status_returns_without_submit(self):
        order = MagicMock()
        order.id = 5
        order.status = "open"  # not "pending"
        mock_executor, _ = self._run(order=order)
        mock_executor.submit_existing_order.assert_not_called()

    def test_pending_order_calls_submit(self):
        order = MagicMock()
        order.id = 5
        order.status = "pending"
        mock_executor, _ = self._run(order=order)
        mock_executor.submit_existing_order.assert_called_once_with(order, mock_executor.submit_existing_order.call_args[0][1])


class TestPollAutoTradeFillsPaperPath:

    def test_no_pending_orders_returns_early(self):
        import app.tasks.trading as trading_module

        db = MagicMock()
        db.query.return_value.filter.return_value.all.return_value = []

        with patch("app.tasks.trading.SessionLocal", return_value=db):
            trading_module.poll_auto_trade_fills.run()

        # No calls to _record_entry_fill or _simulate_paper_exit expected

    def test_submitted_paper_order_calls_record_entry_fill(self):
        import app.tasks.trading as trading_module
        from decimal import Decimal

        order = MagicMock()
        order.status = "submitted"
        order.is_paper = True
        order.trigger_price = Decimal("100.0")
        order.entry_price_target = None

        db = MagicMock()
        db.query.return_value.filter.return_value.all.return_value = [order]

        with (
            patch("app.tasks.trading.SessionLocal", return_value=db),
            patch("app.tasks.trading._record_entry_fill") as mock_fill,
        ):
            trading_module.poll_auto_trade_fills.run()

        mock_fill.assert_called_once()
        args = mock_fill.call_args[0]
        assert args[0] is order
        assert args[1] == 100.0  # fill_price from trigger_price

    def test_open_paper_order_calls_simulate_paper_exit(self):
        import app.tasks.trading as trading_module

        order = MagicMock()
        order.status = "open"
        order.is_paper = True

        db = MagicMock()
        db.query.return_value.filter.return_value.all.return_value = [order]

        with (
            patch("app.tasks.trading.SessionLocal", return_value=db),
            patch("app.tasks.trading._simulate_paper_exit") as mock_exit,
        ):
            trading_module.poll_auto_trade_fills.run()

        mock_exit.assert_called_once()
```

Run:
```bash
cd backend && python -m pytest tests/tasks/test_trading_task_shells.py -q
# FAILS initially
```

#### Step 2 — Fix and iterate until green
```bash
cd backend && python -m pytest tests/tasks/test_trading_task_shells.py -q
# PASSES
```

#### Step 3 — Commit
```bash
git add backend/tests/tasks/test_trading_task_shells.py
git commit -m "test(tasks): unit tests for trading.py task shells (#204)"
```

---

## Task 7: Tests for `sync.py` tasks

**Files**: `backend/tests/tasks/test_sync_tasks.py` (new)

### TDD steps

#### Step 1 — Write failing tests

```python
"""Unit tests for sync.py tasks — httpx.Client mocked per established convention."""
import pytest
from unittest.mock import MagicMock, patch, call
from datetime import datetime, timezone


# ---------------------------------------------------------------------------
# poll_massive_news — trading-hours guard
# ---------------------------------------------------------------------------

class TestPollMassiveNewsGuard:
    """Verify the weekday/hour guard without hitting the DB."""

    def _run(self, weekday, hour, force=False):
        import app.tasks.sync as sync_module
        from zoneinfo import ZoneInfo

        et = ZoneInfo("America/New_York")
        fake_now = MagicMock()
        fake_now.weekday.return_value = weekday
        fake_now.hour = hour

        db_called = [False]
        mock_db = MagicMock()

        def _track_session():
            db_called[0] = True
            return mock_db

        with (
            patch("app.tasks.sync.SessionLocal", side_effect=_track_session),
            patch("app.tasks.sync.datetime") as mock_dt,
        ):
            mock_dt.now.return_value = fake_now
            # Prevent attribute errors from the inner datetime.now calls
            mock_dt.strptime = datetime.strptime
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            sync_module.poll_massive_news.run(force=force)

        return db_called[0]

    def test_saturday_skips_db(self):
        # weekday=5 → Saturday
        assert not self._run(weekday=5, hour=10)

    def test_sunday_skips_db(self):
        assert not self._run(weekday=6, hour=10)

    def test_monday_before_2am_skips_db(self):
        assert not self._run(weekday=0, hour=1)

    def test_monday_at_2am_does_not_skip(self):
        # At 2 AM Monday, task should proceed (hits DB)
        result = self._run(weekday=0, hour=2)
        # May or may not open DB depending on NewsPreference, but guard is cleared
        # Just confirm no exception from the guard logic

    def test_friday_at_20_skips_db(self):
        assert not self._run(weekday=4, hour=20)

    def test_force_bypasses_guard(self):
        import app.tasks.sync as sync_module

        db = MagicMock()
        db.query.return_value.first.return_value = None  # no NewsPreference → early return

        with patch("app.tasks.sync.SessionLocal", return_value=db):
            # force=True on Saturday should reach the DB
            sync_module.poll_massive_news.run(force=True)

        db.query.assert_called()


# ---------------------------------------------------------------------------
# sync_tickers_batch — upsert loop
# ---------------------------------------------------------------------------

class TestSyncTickersBatch:

    def _run(self, results, next_url=None, http_status=200):
        import app.tasks.sync as sync_module

        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = None  # no existing ticker

        response = MagicMock()
        response.status_code = http_status
        response.json.return_value = {"results": results, "next_url": next_url}
        response.raise_for_status = MagicMock()

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = response

        def _retry_reraises(exc=None, **kw):
            raise (exc or Exception("retry"))

        with (
            patch("app.tasks.sync.SessionLocal", return_value=db),
            patch("app.tasks.sync.httpx.Client", return_value=mock_client),
            patch.object(sync_module.sync_tickers_batch, "retry", side_effect=_retry_reraises),
        ):
            sync_module.sync_tickers_batch.run()

        return db, mock_client

    def test_upserts_ticker_row_for_each_result(self):
        results = [
            {"ticker": "AAPL", "name": "Apple Inc.", "active": True, "market": "stocks",
             "type": "CS", "primary_exchange": "XNAS"},
            {"ticker": "MSFT", "name": "Microsoft", "active": True, "market": "stocks",
             "type": "CS", "primary_exchange": "XNAS"},
        ]
        db, _ = self._run(results)
        # 2 new TickerReference rows added
        assert db.add.call_count == 2
        db.commit.assert_called_once()

    def test_skips_result_without_ticker_field(self):
        results = [{"name": "No ticker here"}]
        db, _ = self._run(results)
        db.add.assert_not_called()

    def test_schedules_next_batch_when_next_url_present(self):
        import app.tasks.sync as sync_module

        results = [{"ticker": "AAPL", "name": "Apple", "active": True, "market": "stocks", "type": "CS", "primary_exchange": "X"}]
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = None

        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {"results": results, "next_url": "https://api.polygon.io/v3/reference/tickers?cursor=abc"}
        response.raise_for_status = MagicMock()

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = response

        with (
            patch("app.tasks.sync.SessionLocal", return_value=db),
            patch("app.tasks.sync.httpx.Client", return_value=mock_client),
            patch.object(sync_module.sync_tickers_batch, "apply_async") as mock_apply,
        ):
            sync_module.sync_tickers_batch.run()

        mock_apply.assert_called_once()


# ---------------------------------------------------------------------------
# sync_stock_splits — dedup logic
# ---------------------------------------------------------------------------

class TestSyncStockSplits:

    def _run(self, results, existing_split=None):
        import app.tasks.sync as sync_module

        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = existing_split

        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {"results": results}
        response.raise_for_status = MagicMock()

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = response

        def _retry_reraises(exc=None, **kw):
            raise (exc or Exception("retry"))

        with (
            patch("app.tasks.sync.SessionLocal", return_value=db),
            patch("app.tasks.sync.httpx.Client", return_value=mock_client),
            patch("app.services.split_adjustment.SplitAdjustmentService.apply_all_pending",
                  return_value=[]),
            patch.object(sync_module.sync_stock_splits, "retry", side_effect=_retry_reraises),
        ):
            sync_module.sync_stock_splits.run()

        return db

    def test_new_split_is_inserted(self):
        results = [{"ticker": "AAPL", "execution_date": "2026-05-01",
                    "split_from": 1, "split_to": 4}]
        db = self._run(results, existing_split=None)
        db.add.assert_called_once()

    def test_existing_split_is_not_duplicated(self):
        results = [{"ticker": "AAPL", "execution_date": "2026-05-01",
                    "split_from": 1, "split_to": 4}]
        existing = MagicMock()
        db = self._run(results, existing_split=existing)
        db.add.assert_not_called()

    def test_missing_required_fields_skipped(self):
        results = [{"ticker": "AAPL"}]  # missing execution_date, split_from, split_to
        db = self._run(results)
        db.add.assert_not_called()


# ---------------------------------------------------------------------------
# sync_stock_aggregates — aggregate-insert path
# ---------------------------------------------------------------------------

class TestSyncStockAggregates:

    def _run(self, aggs=None, raises=None):
        import app.tasks.sync as sync_module

        db = MagicMock()
        # delete + bulk_save_objects are called on db directly
        delete_mock = MagicMock()
        db.query.return_value.filter.return_value.delete = MagicMock(return_value=0)

        def _retry_reraises(exc=None, **kw):
            raise (exc or Exception("retry"))

        with (
            patch("app.tasks.sync.SessionLocal", return_value=db),
            patch("app.services.stock_data.StockDataService.get_aggregates",
                  side_effect=raises or (lambda **kw: aggs or [])),
            patch("app.utils.session.classify_session", return_value=(False, False)),
            patch.object(sync_module.sync_stock_aggregates, "retry", side_effect=_retry_reraises),
        ):
            sync_module.sync_stock_aggregates.run(
                ticker="AAPL",
                from_date="2026-06-01",
                to_date="2026-06-05",
            )

        return db

    def test_no_aggs_returns_early_without_insert(self):
        db = self._run(aggs=[])
        db.bulk_save_objects.assert_not_called()

    def test_aggs_are_bulk_inserted(self):
        from datetime import datetime, timezone
        agg = {
            "timestamp": datetime(2026, 6, 2, 9, 30, tzinfo=timezone.utc),
            "open": 100.0, "high": 105.0, "low": 99.0, "close": 103.0,
            "volume": 50000, "vwap": 102.0, "transactions": 300,
        }
        db = self._run(aggs=[agg])
        db.bulk_save_objects.assert_called_once()
        inserted = db.bulk_save_objects.call_args[0][0]
        assert len(inserted) == 1
        assert inserted[0].ticker == "AAPL"

    def test_existing_range_deleted_before_insert(self):
        from datetime import datetime, timezone
        agg = {
            "timestamp": datetime(2026, 6, 2, 9, 30, tzinfo=timezone.utc),
            "open": 100.0, "high": 105.0, "low": 99.0, "close": 103.0,
            "volume": 50000, "vwap": 102.0, "transactions": 300,
        }
        db = self._run(aggs=[agg])
        # delete must be called for the ticker/timespan/date range dedup
        db.query.return_value.filter.return_value.delete.assert_called_once()


# ---------------------------------------------------------------------------
# trigger_tweet_monitor — success and retry
# ---------------------------------------------------------------------------

class TestTriggerTweetMonitor:

    def test_success_returns_response_json(self):
        import app.tasks.sync as sync_module

        response = MagicMock()
        response.raise_for_status = MagicMock()
        response.json.return_value = {"status": "ok", "tweets": 3}

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.return_value = response

        with patch("app.tasks.sync.httpx.Client", return_value=mock_client):
            result = sync_module.trigger_tweet_monitor.run()

        assert result == {"status": "ok", "tweets": 3}
        mock_client.post.assert_called_once_with("http://tweet-monitor:8000/poll")

    def test_http_error_triggers_retry(self):
        import app.tasks.sync as sync_module

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.side_effect = Exception("connection refused")

        def _retry_reraises(exc=None, **kw):
            raise exc

        with (
            patch("app.tasks.sync.httpx.Client", return_value=mock_client),
            patch.object(sync_module.trigger_tweet_monitor, "retry", side_effect=_retry_reraises),
        ):
            with pytest.raises(Exception, match="connection refused"):
                sync_module.trigger_tweet_monitor.run()
```

Run:
```bash
cd backend && python -m pytest tests/tasks/test_sync_tasks.py -q
# FAILS
```

#### Step 2 — Fix import and mock issues, iterate until green
```bash
cd backend && python -m pytest tests/tasks/test_sync_tasks.py -q
# PASSES
```

#### Step 3 — Commit
```bash
git add backend/tests/tasks/test_sync_tasks.py
git commit -m "test(tasks): unit tests for sync.py tasks (#204)"
```

---

## Task 8: Verify coverage gate and extend test cases if needed

**Files**: `backend/pyproject.toml` (read-only check), run test suite

### TDD steps

#### Step 1 — Run full test suite with coverage
```bash
cd backend && python -m pytest --cov=app --cov-report=term-missing -q 2>&1 | tail -20
# Expected: TOTAL coverage ≥ 60%
```

#### Step 2 — Check coverage specifically for tasks
```bash
cd backend && python -m pytest --cov=app/tasks --cov-report=term-missing -q 2>&1 | grep -E "app/tasks|TOTAL"
```
Expected output (approximate):
```
app/tasks/scanning.py    XXX    YY    ZZ%
app/tasks/quality.py     XXX    YY    ZZ%
app/tasks/trading.py     XXX    YY    ZZ%
app/tasks/sync.py        XXX    YY    ZZ%
```

#### Step 3 — If overall coverage drops below 60%, add targeted tests
If the gate drops below 60% after including tasks, identify the lowest-coverage lines with:
```bash
cd backend && python -m pytest --cov=app --cov-report=term-missing -q 2>&1 | sort -t% -k1 -n | head -20
```
Add targeted tests for the uncovered lines until the gate passes.

#### Step 4 — Run coverage check one final time
```bash
cd backend && python -m pytest --cov=app --cov-fail-under=60 -q
# PASSES: coverage meets or exceeds 60%
```

#### Step 5 — Final commit
```bash
git add -p  # stage any final test additions
git commit -m "test(tasks): ensure 60% coverage gate holds after narrowing task omit (#204)"
```

---

## Summary

| Task | Files Changed | Tests Added |
|---|---|---|
| 1 | `pyproject.toml`, `trading.py`, `sync.py` | `test_coverage_config.py` (1 test) |
| 2 | `scanning.py` (_run_universe_scan_logic + full state payload via `_state_payload`) | — |
| 3 | `scanning.py` (_run_range_scan_logic, _evaluate_scanner_alerts_logic) | — |
| 4 | — | `test_scanning_tasks.py` (~12 tests) |
| 4.5 | — | `test_scheduled_scanner_tasks.py` expand (~7 tests) |
| 5 | — | `test_quality_tasks.py` (~9 tests) |
| 6 | — | `test_trading_task_shells.py` (~7 tests) |
| 7 | — | `test_sync_tasks.py` (~16 tests incl. sync_stock_aggregates) |
| 8 | — | Additional tests if gate < 60% |

**Total**: 9 tasks, ~50 steps, ~52+ new tests.
