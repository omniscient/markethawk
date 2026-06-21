# Plan: Aggregate Gap & Staleness Detection (#387)

**Date:** 2026-06-21  
**Issue:** #387  
**Spec:** docs/superpowers/specs/2026-06-21-aggregate-gap-staleness-detection-design.md  
**Goal:** Add lightweight nightly gap/staleness health checks across all active universes — Prometheus gauges, Seq warnings, `ScannerRun.data_degraded`, a `/data-health` API endpoint, and a Scanner page banner.

---

## Architecture

No new Docker services. All changes are additive to existing layers:

- Extract shared gap helpers into `quality_helpers.py` (prerequisite refactor)
- Two new `Gauge` definitions in `core/metrics.py` with `multiprocess_mode="livemax"`
- `ScannerRun.data_degraded` nullable Boolean + Alembic migration
- `check_aggregate_staleness` Celery task in `tasks/quality.py` + beat schedule at 03:00 UTC weekdays
- `_run_universe_scan_logic` annotates `run.data_degraded` from the latest `UniverseQualityReport` before the scan body
- `DataHealthResponse` Pydantic schema + `GET /api/v1/universe/{id}/data-health` endpoint (5-min cache)
- Frontend: `getDataHealth` Axios client + React Query call + amber banner on Scanner page

> **Note on router path:** The existing universe router prefix is `/api/v1/universe` (singular). The endpoint is therefore `GET /api/v1/universe/{id}/data-health`, not `/universes/{id}/...` as the spec draft says.

---

## Tech Stack

Backend: SQLAlchemy 2.0 (sync), FastAPI, Celery Beat, prometheus_client.  
Frontend: React 18, React Query, TypeScript.  
No new dependencies.

---

## File Structure

| File | Change |
|------|--------|
| `backend/app/services/quality_helpers.py` | **New** — `_count_weekdays_between`, `_detect_gaps` |
| `backend/app/services/data_quality.py` | Import from `quality_helpers`; remove local definitions |
| `backend/tests/services/test_data_quality_helpers.py` | Update import path to `quality_helpers`; add `_detect_gaps` tests |
| `backend/app/core/metrics.py` | Add `aggregate_gap_days`, `aggregate_staleness_hours` Gauges |
| `backend/app/models/scanner_run.py` | Add `data_degraded = Column(Boolean, nullable=True)` |
| `backend/app/alembic/versions/<hash>_add_data_degraded_to_scanner_runs.py` | **New** — ADD COLUMN migration |
| `backend/app/tasks/quality.py` | Add `check_aggregate_staleness` task |
| `backend/app/core/celery_app.py` | Add `aggregate-quality-nightly` beat entry |
| `backend/app/tasks/scanning.py` | Populate `run.data_degraded` in `_run_universe_scan_logic` |
| `backend/app/schemas/universe.py` | Add `DataHealthResponse` schema |
| `backend/app/routers/universe.py` | Add `GET /{universe_id}/data-health` endpoint + gauge cleanup on delete |
| `backend/tests/api/test_universe.py` | Add data-health endpoint tests |
| `backend/tests/tasks/test_quality_tasks.py` | Add `check_aggregate_staleness` unit tests |
| `frontend/src/api/universe.ts` | Add `DataHealthResponse` type + `getDataHealth` function |
| `frontend/src/pages/Scanner/index.tsx` | React Query call + amber degradation banner |

---

## Task 1: Extract `_count_weekdays_between` and `_detect_gaps` into `quality_helpers.py`

**Files:** `backend/app/services/quality_helpers.py` (new), `backend/app/services/data_quality.py`, `backend/tests/services/test_data_quality_helpers.py`

### TDD

**Step 1 — Write failing tests**

Update `backend/tests/services/test_data_quality_helpers.py`. Change the import of `_count_weekdays_between` from `app.services.data_quality` to `app.services.quality_helpers`, and add `_detect_gaps` tests:

```python
from datetime import date, datetime, timedelta, timezone

from app.services.quality_helpers import _count_weekdays_between, _detect_gaps
# _grade_color and _score_to_grade stay in data_quality; keep those imports as-is
from app.services.data_quality import _grade_color, _score_to_grade
```

Add at the end of the file:

```python
# ── _detect_gaps ──────────────────────────────────────────────────────────────

def _ts(d: str) -> datetime:
    return datetime.fromisoformat(d)


def test_no_gaps_returns_empty():
    # daily bars: consecutive weekdays — no gap
    ts = [_ts("2024-01-01"), _ts("2024-01-02"), _ts("2024-01-03")]
    assert _detect_gaps(ts, "day", 1) == []


def test_gap_detected_across_multiple_weekdays():
    # Jan 1 (Mon) → Jan 10 (Wed): 6 weekdays gap → reported
    ts = [_ts("2024-01-01"), _ts("2024-01-10")]
    gaps = _detect_gaps(ts, "day", 1)
    assert len(gaps) == 1
    assert gaps[0]["missing_bars"] > 0


def test_weekend_not_flagged_as_gap():
    # Fri Jan 5 → Mon Jan 8: 0 weekdays between → no gap
    ts = [_ts("2024-01-05"), _ts("2024-01-08")]
    gaps = _detect_gaps(ts, "day", 1)
    assert gaps == []


def test_single_timestamp_returns_empty():
    assert _detect_gaps([_ts("2024-01-01")], "day", 1) == []
```

**Step 2 — Verify tests fail**

```bash
docker-compose exec backend python -m pytest backend/tests/services/test_data_quality_helpers.py -x -q 2>&1 | tail -10
# Expected: ImportError or AttributeError — quality_helpers does not exist yet
```

**Step 3 — Create `backend/app/services/quality_helpers.py`**

Move both functions verbatim from `data_quality.py`:

```python
"""
Shared gap-detection helpers used by DataQualityService and the nightly
check_aggregate_staleness task.
"""

from datetime import datetime, timedelta
from typing import Dict, List


def _count_weekdays_between(d1, d2) -> int:
    """Count weekdays (Mon–Fri) strictly between two dates."""
    count = 0
    current = d1 + timedelta(days=1)
    while current < d2:
        if current.weekday() < 5:
            count += 1
        current += timedelta(days=1)
    return count


def _detect_gaps(
    timestamps: List[datetime], timespan: str, multiplier: int
) -> List[Dict]:
    """
    Return a list of data gaps.

    A gap is a consecutive-timestamp pair where:
      • the elapsed time exceeds 5 × the expected bar interval, AND
      • more than 1 weekday falls between the two timestamps
        (this filters out weekends and single-day holidays naturally).
    """
    if len(timestamps) < 2:
        return []

    expected_seconds = {
        "minute": 60,
        "hour": 3600,
        "day": 86400,
        "week": 604800,
        "month": 2592000,
    }.get(timespan, 60) * multiplier

    threshold_seconds = expected_seconds * 5

    gaps = []
    for i in range(1, len(timestamps)):
        prev = timestamps[i - 1]
        curr = timestamps[i]
        diff_seconds = (curr - prev).total_seconds()

        if diff_seconds < threshold_seconds:
            continue

        calendar_days = (curr.date() - prev.date()).days
        if calendar_days <= 3:
            weekdays = _count_weekdays_between(prev.date(), curr.date())
            if weekdays <= 1:
                continue

        missing_bars = max(0, int(diff_seconds / expected_seconds) - 1)
        gaps.append(
            {
                "from": prev,
                "to": curr,
                "duration_hours": round(diff_seconds / 3600, 1),
                "missing_bars": missing_bars,
            }
        )

    return gaps
```

**Step 4 — Update `backend/app/services/data_quality.py`**

Replace the two local function bodies with an import at the top of the file (after the existing imports):

```python
from app.services.quality_helpers import _count_weekdays_between, _detect_gaps
```

Remove the two function definitions (`_count_weekdays_between` and `_detect_gaps`) from `data_quality.py`. All call-sites in `_analyze_ticker_timespan` already use those names, which are now resolved via the import.

**Step 5 — Verify tests pass**

```bash
docker-compose exec backend python -m pytest backend/tests/services/test_data_quality_helpers.py -v 2>&1 | tail -20
# Expected: all tests pass (including the new _detect_gaps tests)
```

**Step 6 — Commit**

```bash
git add backend/app/services/quality_helpers.py backend/app/services/data_quality.py backend/tests/services/test_data_quality_helpers.py
git commit -m "refactor: extract _detect_gaps and _count_weekdays_between into quality_helpers (#387)"
```

---

## Task 2: Add Prometheus Gauges for aggregate health

**Files:** `backend/app/core/metrics.py`

### TDD

**Step 1 — Write failing test**

Add to `backend/tests/core/test_metrics_instrumentation.py`:

```python
def test_aggregate_staleness_gauge_registered():
    from app.core.metrics import aggregate_staleness_hours
    # Prometheus Gauge exposes _name attribute
    assert aggregate_staleness_hours._name == "markethawk_aggregate_staleness_hours"


def test_aggregate_gap_days_gauge_registered():
    from app.core.metrics import aggregate_gap_days
    assert aggregate_gap_days._name == "markethawk_aggregate_gap_days"
```

**Step 2 — Verify tests fail**

```bash
docker-compose exec backend python -m pytest backend/tests/core/test_metrics_instrumentation.py::test_aggregate_staleness_gauge_registered -x -q 2>&1 | tail -5
# Expected: ImportError
```

**Step 3 — Add gauges to `backend/app/core/metrics.py`**

Append at the end of the file:

```python
aggregate_gap_days = Gauge(
    "markethawk_aggregate_gap_days",
    "Worst gap (weekdays) across tickers in a universe",
    ["universe_id"],
    multiprocess_mode="livemax",
)

aggregate_staleness_hours = Gauge(
    "markethawk_aggregate_staleness_hours",
    "Worst staleness (hours since newest aggregate) across tickers in a universe",
    ["universe_id"],
    multiprocess_mode="livemax",
)
```

**Step 4 — Verify tests pass**

```bash
docker-compose exec backend python -m pytest backend/tests/core/test_metrics_instrumentation.py -v -q 2>&1 | tail -10
```

**Step 5 — Commit**

```bash
git add backend/app/core/metrics.py backend/tests/core/test_metrics_instrumentation.py
git commit -m "feat(metrics): add aggregate_gap_days and aggregate_staleness_hours gauges (#387)"
```

---

## Task 3: Add `data_degraded` Boolean to `ScannerRun` + Alembic migration

**Files:** `backend/app/models/scanner_run.py`, `backend/app/alembic/versions/<hash>_add_data_degraded_to_scanner_runs.py`

### TDD

**Step 1 — Write failing test**

Add to `backend/tests/api/test_scanner.py` (or create `backend/tests/test_scanner_run_model.py`):

```python
def test_scanner_run_has_data_degraded_column():
    import inspect
    from sqlalchemy import Boolean
    from app.models.scanner_run import ScannerRun
    col = ScannerRun.__table__.columns.get("data_degraded")
    assert col is not None, "data_degraded column missing from ScannerRun"
    assert isinstance(col.type, Boolean)
    assert col.nullable is True
```

**Step 2 — Verify test fails**

```bash
docker-compose exec backend python -m pytest -k "test_scanner_run_has_data_degraded_column" -x -q 2>&1 | tail -5
# Expected: AssertionError — column does not exist yet
```

**Step 3 — Add column to model**

In `backend/app/models/scanner_run.py`, add the import and column:

```python
from sqlalchemy import Boolean, Column, Date, DateTime, ForeignKey, Integer, String, Text
```

(add `Boolean` to the existing import)

Add after `celery_task_id`:

```python
    data_degraded = Column(Boolean, nullable=True)
```

**Step 4 — Generate and apply Alembic migration**

```bash
docker-compose exec backend python -m alembic revision --autogenerate \
  -m "add_data_degraded_to_scanner_runs"
# Note the generated file path, e.g. app/alembic/versions/abc123_add_data_degraded_to_scanner_runs.py

docker-compose exec backend python -m alembic upgrade head
# Expected: INFO  Running upgrade ... -> abc123, add_data_degraded_to_scanner_runs
```

**Step 5 — Verify migration applied and test passes**

```bash
docker-compose exec backend python -m pytest -k "test_scanner_run_has_data_degraded_column" -x -q 2>&1 | tail -5
# Expected: 1 passed
```

**Step 6 — Commit**

```bash
git add backend/app/models/scanner_run.py backend/app/alembic/versions/*add_data_degraded*
git commit -m "feat(model): add data_degraded nullable Boolean to ScannerRun (#387)"
```

---

## Task 4: Implement `check_aggregate_staleness` Celery task + beat schedule

**Files:** `backend/app/tasks/quality.py`, `backend/app/core/celery_app.py`, `backend/tests/tasks/test_quality_tasks.py`

### TDD

**Step 1 — Write failing unit tests**

Add to `backend/tests/tasks/test_quality_tasks.py`:

```python
class TestCheckAggregateStaleness:
    def _make_universe(self, uid=1):
        u = MagicMock()
        u.id = uid
        return u

    def _make_ticker(self, ticker="AAPL", asset_class="stocks"):
        t = MagicMock()
        t.ticker = ticker
        t.asset_class = asset_class
        return t

    def _run(self, universes, tickers_by_uid, max_ts_by_ticker, cfg_overrides=None):
        import app.tasks.quality as q_mod
        from datetime import datetime, timezone

        db = MagicMock()

        cfg_keys = {
            "quality_staleness_hours": "48",
            "quality_gap_min_weekdays": "2",
            "quality_alert_pct": "20",
        }
        if cfg_overrides:
            cfg_keys.update(cfg_overrides)

        def _cfg_rows():
            rows = []
            for k, v in cfg_keys.items():
                r = MagicMock()
                r.key = k
                r.value = v
                rows.append(r)
            return rows

        call_count = [0]

        def _query_side_effect(model):
            name = model.__name__ if hasattr(model, "__name__") else str(model)
            mock_q = MagicMock()
            if "StockUniverse" in name:
                mock_q.filter.return_value.all.return_value = universes
            elif "SystemConfig" in name:
                mock_q.filter.return_value.all.return_value = _cfg_rows()
            elif "StockUniverseTicker" in name:
                uid = call_count[0] % len(universes)
                mock_q.filter.return_value.all.return_value = tickers_by_uid.get(
                    universes[uid].id, []
                )
                call_count[0] += 1
            return mock_q

        db.query.side_effect = _query_side_effect

        with (
            patch("app.tasks.quality.SessionLocal", return_value=db),
            patch("app.tasks.quality.aggregate_staleness_hours") as mock_staleness,
            patch("app.tasks.quality.aggregate_gap_days") as mock_gaps,
        ):
            q_mod.check_aggregate_staleness.run()
            return mock_staleness, mock_gaps

    def test_emits_gauge_for_active_universe(self):
        universes = [self._make_universe(1)]
        tickers = [self._make_ticker("AAPL")]
        mock_s, mock_g = self._run(
            universes,
            {1: tickers},
            {"AAPL": None},  # no data
        )
        mock_s.labels.assert_called_once_with(universe_id="1")
        mock_g.labels.assert_called_once_with(universe_id="1")

    def test_no_tickers_skips_universe(self):
        universes = [self._make_universe(1)]
        mock_s, mock_g = self._run(universes, {1: []}, {})
        mock_s.labels.assert_not_called()
        mock_g.labels.assert_not_called()
```

**Step 2 — Verify tests fail**

```bash
docker-compose exec backend python -m pytest backend/tests/tasks/test_quality_tasks.py::TestCheckAggregateStaleness -x -q 2>&1 | tail -5
# Expected: ImportError (task not yet defined)
```

**Step 3 — Implement `check_aggregate_staleness` in `backend/app/tasks/quality.py`**

Add after the existing imports at the top (alongside what's already there):

```python
from app.core.metrics import (
    aggregate_gap_days,
    aggregate_staleness_hours,
    celery_task_duration_seconds,
    celery_tasks_total,
)
```

Add after `analyze_signal_features` task:

```python
_STALENESS_CONFIG_KEYS = [
    "quality_staleness_hours",
    "quality_gap_min_weekdays",
    "quality_alert_pct",
]


@celery_app.task(bind=True, max_retries=0, name="app.tasks.check_aggregate_staleness")
def check_aggregate_staleness(self):
    """
    Nightly lightweight sweep: queries MAX(timestamp) per ticker in every active
    universe, emits per-universe Prometheus gauges, and logs a Seq Warning when
    >quality_alert_pct% of tickers are stale or gapped.
    """
    from datetime import datetime

    from sqlalchemy import func

    from app.core.metrics import aggregate_gap_days, aggregate_staleness_hours
    from app.models.futures_aggregate import FuturesAggregate
    from app.models.stock_aggregate import StockAggregate
    from app.models.stock_universe import StockUniverse
    from app.models.stock_universe_ticker import StockUniverseTicker
    from app.models.system_config import SystemConfig
    from app.services.quality_helpers import _count_weekdays_between, _detect_gaps

    _task_name = "check_aggregate_staleness"
    _start = _time.monotonic()
    db: Session = SessionLocal()
    try:
        cfg_rows = (
            db.query(SystemConfig)
            .filter(SystemConfig.key.in_(_STALENESS_CONFIG_KEYS))
            .all()
        )
        cfg = {r.key: r.value for r in cfg_rows}
        staleness_hours = float(cfg.get("quality_staleness_hours", 48))
        gap_min_weekdays = int(cfg.get("quality_gap_min_weekdays", 2))
        alert_pct = float(cfg.get("quality_alert_pct", 20))

        now = utc_now()

        universes = (
            db.query(StockUniverse).filter(StockUniverse.is_active.is_(True)).all()
        )

        for universe in universes:
            tickers = (
                db.query(StockUniverseTicker)
                .filter(StockUniverseTicker.universe_id == universe.id)
                .all()
            )
            if not tickers:
                continue

            ticker_count = len(tickers)
            futures_set = {t.ticker for t in tickers if t.asset_class == "futures"}

            stale_count = 0
            gapped_count = 0
            worst_staleness_h = 0.0
            worst_gap_d = 0

            for t in tickers:
                is_futures = t.ticker in futures_set

                if is_futures:
                    max_ts = (
                        db.query(func.max(FuturesAggregate.timestamp))
                        .filter(FuturesAggregate.symbol == t.ticker)
                        .scalar()
                    )
                else:
                    max_ts = (
                        db.query(func.max(StockAggregate.timestamp))
                        .filter(StockAggregate.ticker == t.ticker)
                        .scalar()
                    )

                if max_ts is None:
                    stale_count += 1
                    worst_staleness_h = max(worst_staleness_h, staleness_hours + 1)
                    continue

                if not isinstance(max_ts, datetime):
                    continue

                age_hours = (now - max_ts).total_seconds() / 3600
                if age_hours > staleness_hours:
                    stale_count += 1
                    worst_staleness_h = max(worst_staleness_h, age_hours)

                # Gap detection: daily bars only (lighter than full multi-timespan)
                if is_futures:
                    ts_rows = (
                        db.query(FuturesAggregate.timestamp)
                        .filter(
                            FuturesAggregate.symbol == t.ticker,
                            FuturesAggregate.timespan == "day",
                            FuturesAggregate.multiplier == 1,
                        )
                        .order_by(FuturesAggregate.timestamp.asc())
                        .all()
                    )
                else:
                    ts_rows = (
                        db.query(StockAggregate.timestamp)
                        .filter(
                            StockAggregate.ticker == t.ticker,
                            StockAggregate.timespan == "day",
                            StockAggregate.multiplier == 1,
                        )
                        .order_by(StockAggregate.timestamp.asc())
                        .all()
                    )

                if ts_rows:
                    timestamps = [r[0] for r in ts_rows]
                    raw_gaps = _detect_gaps(timestamps, "day", 1)
                    real_gaps = [
                        g
                        for g in raw_gaps
                        if _count_weekdays_between(g["from"].date(), g["to"].date())
                        > gap_min_weekdays
                    ]
                    if real_gaps:
                        gapped_count += 1
                        max_gap_wd = max(
                            _count_weekdays_between(
                                g["from"].date(), g["to"].date()
                            )
                            for g in real_gaps
                        )
                        worst_gap_d = max(worst_gap_d, max_gap_wd)

            aggregate_staleness_hours.labels(universe_id=str(universe.id)).set(
                worst_staleness_h
            )
            aggregate_gap_days.labels(universe_id=str(universe.id)).set(worst_gap_d)

            affected_pct = max(stale_count, gapped_count) / ticker_count * 100
            if affected_pct > alert_pct:
                logger.warning(
                    "AggregateDataDegradation",
                    extra={
                        "event": "AggregateDataDegradation",
                        "universe_id": universe.id,
                        "stale_tickers": stale_count,
                        "gapped_tickers": gapped_count,
                        "affected_pct": round(affected_pct, 1),
                        "worst_staleness_hours": round(worst_staleness_h, 1),
                        "worst_gap_days": worst_gap_d,
                        "threshold_pct": alert_pct,
                    },
                )

        celery_tasks_total.labels(task_name=_task_name, status="success").inc()

    except Exception as exc:
        logger.error(f"check_aggregate_staleness failed: {exc}")
        celery_tasks_total.labels(task_name=_task_name, status="failure").inc()
        raise
    finally:
        celery_task_duration_seconds.labels(task_name=_task_name).observe(
            _time.monotonic() - _start
        )
        db.close()
```

**Step 4 — Add beat schedule to `backend/app/core/celery_app.py`**

Inside `celery_app.conf.beat_schedule`, add after `"analyze-signal-features-nightly"`:

```python
    "aggregate-quality-nightly": {
        "task": "app.tasks.check_aggregate_staleness",
        "schedule": crontab(minute="0", hour="3", day_of_week="1-5"),
    },
```

**Step 5 — Verify tests pass**

```bash
docker-compose exec backend python -m pytest backend/tests/tasks/test_quality_tasks.py -v 2>&1 | tail -20
```

**Step 6 — Verify task is registered**

```bash
docker-compose logs backend --tail=5
# Then:
curl -s http://localhost:8000/api/v1/health | python -m json.tool
```

**Step 7 — Commit**

```bash
git add backend/app/tasks/quality.py backend/app/core/celery_app.py backend/tests/tasks/test_quality_tasks.py
git commit -m "feat(tasks): add check_aggregate_staleness nightly Celery task (#387)"
```

---

## Task 5: Populate `data_degraded` at scan start

**Files:** `backend/app/tasks/scanning.py`, `backend/tests/tasks/test_scanning_tasks.py`

### TDD

**Step 1 — Write failing test**

Add to `backend/tests/tasks/test_scanning_tasks.py`:

```python
class TestDataDegradedAnnotation:
    """Test that _run_universe_scan_logic sets data_degraded before the scan body."""

    def _make_run(self, uid=1):
        run = MagicMock()
        run.uuid = "test-scan-id"
        run.status = "queued"
        run.universe_id = uid
        run.data_degraded = None
        return run

    def test_data_degraded_true_when_report_absent(self):
        """Missing report → data_degraded = True."""
        from unittest.mock import MagicMock, patch

        import app.tasks.scanning as scanning_mod

        run = self._make_run()
        db = MagicMock()

        def _query(model):
            q = MagicMock()
            name = getattr(model, "__name__", str(model))
            if "ScannerRun" in name:
                q.filter.return_value.first.return_value = run
            elif "MonitoredStock" in name:
                q.filter.return_value.all.return_value = [MagicMock(ticker="AAPL")]
            elif "UniverseQualityReport" in name:
                q.filter.return_value.first.return_value = None  # no report
            else:
                q.filter.return_value.all.return_value = []
                q.filter.return_value.first.return_value = None
            return q

        db.query.side_effect = _query

        with patch("app.tasks.scanning.SessionLocal", return_value=db):
            try:
                scanning_mod._run_universe_scan_logic(
                    scan_id="test-scan-id",
                    scanner_type="pre_market",
                    universe_id=1,
                    start=__import__("datetime").date(2024, 1, 2),
                    end=__import__("datetime").date(2024, 1, 2),
                    db=db,
                    publish=lambda _: None,
                    is_cancelled=lambda: False,
                    task_id="t1",
                    write_state=None,
                )
            except Exception:
                pass  # scan body may fail; we only care about data_degraded assignment

        assert run.data_degraded is True

    def test_data_degraded_false_when_report_fresh_and_clean(self):
        """Fresh report with 0% affected → data_degraded = False."""
        from datetime import datetime, timezone
        from unittest.mock import MagicMock, patch

        import app.tasks.scanning as scanning_mod

        run = self._make_run()
        db = MagicMock()
        now = datetime.now(timezone.utc).replace(tzinfo=None)

        report = MagicMock()
        report.generated_at = now  # just generated
        report.report_data = {
            "tickers": [
                {"ticker": "AAPL", "last_bar": now.isoformat(), "gap_count": 0}
            ]
        }

        def _query(model):
            q = MagicMock()
            name = getattr(model, "__name__", str(model))
            if "ScannerRun" in name:
                q.filter.return_value.first.return_value = run
            elif "MonitoredStock" in name:
                q.filter.return_value.all.return_value = [MagicMock(ticker="AAPL")]
            elif "UniverseQualityReport" in name:
                q.filter.return_value.first.return_value = report
            elif "SystemConfig" in name:
                q.filter.return_value.all.return_value = []
            else:
                q.filter.return_value.all.return_value = []
                q.filter.return_value.first.return_value = None
            return q

        db.query.side_effect = _query

        with patch("app.tasks.scanning.SessionLocal", return_value=db):
            try:
                scanning_mod._run_universe_scan_logic(
                    scan_id="test-scan-id",
                    scanner_type="pre_market",
                    universe_id=1,
                    start=__import__("datetime").date(2024, 1, 2),
                    end=__import__("datetime").date(2024, 1, 2),
                    db=db,
                    publish=lambda _: None,
                    is_cancelled=lambda: False,
                    task_id="t1",
                    write_state=None,
                )
            except Exception:
                pass

        assert run.data_degraded is False
```

**Step 2 — Verify tests fail**

```bash
docker-compose exec backend python -m pytest "backend/tests/tasks/test_scanning_tasks.py::TestDataDegradedAnnotation" -x -q 2>&1 | tail -5
# Expected: AttributeError — run.data_degraded never set
```

**Step 3 — Add `_compute_data_degraded` helper + populate in `_run_universe_scan_logic`**

Add helper function near the top of the testable-logic section in `backend/app/tasks/scanning.py` (after line ~145, before `_run_universe_scan_logic`):

```python
def _compute_data_degraded(universe_id: int, db: Session) -> bool:
    """
    Return True if the latest UniverseQualityReport indicates degradation.
    Treats a missing or >48h stale report as degraded.
    """
    from app.models.system_config import SystemConfig
    from app.models.universe_quality_report import UniverseQualityReport

    from app.utils.time import utc_now as _utc_now

    now = _utc_now()

    report = (
        db.query(UniverseQualityReport)
        .filter(UniverseQualityReport.universe_id == universe_id)
        .first()
    )
    if report is None or report.generated_at is None:
        return True

    report_age_hours = (now - report.generated_at).total_seconds() / 3600
    if report_age_hours > 48:
        return True

    if not report.report_data or "tickers" not in report.report_data:
        return True

    cfg_rows = (
        db.query(SystemConfig)
        .filter(
            SystemConfig.key.in_(
                ["quality_staleness_hours", "quality_gap_min_weekdays", "quality_alert_pct"]
            )
        )
        .all()
    )
    cfg = {r.key: r.value for r in cfg_rows}
    staleness_hours = float(cfg.get("quality_staleness_hours", 48))
    gap_min_weekdays = int(cfg.get("quality_gap_min_weekdays", 2))
    alert_pct = float(cfg.get("quality_alert_pct", 20))

    tickers = report.report_data["tickers"]
    if not tickers:
        return True

    # Deduplicate by ticker: keep the entry with the latest last_bar per ticker
    best_bar: dict = {}
    for entry in tickers:
        ticker = entry.get("ticker")
        if not ticker:
            continue
        lb = entry.get("last_bar")
        if lb is None:
            continue
        if ticker not in best_bar or lb > best_bar[ticker]["last_bar"]:
            best_bar[ticker] = entry

    from datetime import datetime as _dt

    stale = 0
    gapped = 0
    total = len(best_bar)
    if total == 0:
        return True

    for entry in best_bar.values():
        lb = entry.get("last_bar")
        if lb is None:
            stale += 1
            continue
        try:
            last_ts = _dt.fromisoformat(lb)
        except ValueError:
            stale += 1
            continue
        if last_ts.tzinfo is not None:
            last_ts = last_ts.replace(tzinfo=None)
        age_h = (now - last_ts).total_seconds() / 3600
        if age_h > staleness_hours:
            stale += 1
        if entry.get("gap_count", 0) > gap_min_weekdays:
            gapped += 1

    affected_pct = max(stale, gapped) / total * 100
    return affected_pct > alert_pct
```

In `_run_universe_scan_logic`, **after** the tickers query and **before** `run.status = "running"`, insert:

```python
    run.data_degraded = _compute_data_degraded(universe_id, db)
```

**Step 4 — Verify tests pass**

```bash
docker-compose exec backend python -m pytest "backend/tests/tasks/test_scanning_tasks.py::TestDataDegradedAnnotation" -v 2>&1 | tail -10
```

**Step 5 — Commit**

```bash
git add backend/app/tasks/scanning.py backend/tests/tasks/test_scanning_tasks.py
git commit -m "feat(scanning): populate ScannerRun.data_degraded from UniverseQualityReport at scan start (#387)"
```

---

## Task 6: Add `GET /api/v1/universe/{id}/data-health` endpoint + schema

**Files:** `backend/app/schemas/universe.py`, `backend/app/routers/universe.py`, `backend/tests/api/test_universe.py`

### TDD

**Step 1 — Write failing tests**

Add to `backend/tests/api/test_universe.py`:

```python
def test_data_health_no_report_returns_degraded(db: Session):
    """When no quality report exists, endpoint returns degraded=True."""
    from tests.fixtures.core import seed_universes
    universes = seed_universes(db)
    uid = universes[0].id

    response = client.get(f"/api/v1/universe/{uid}/data-health")

    assert response.status_code == 200
    data = response.json()
    assert data["universe_id"] == uid
    assert data["degraded"] is True
    assert data["stale_pct"] is None


def test_data_health_universe_not_found(db: Session):
    response = client.get("/api/v1/universe/99999/data-health")
    assert response.status_code == 404


def test_data_health_response_shape(db: Session):
    """Check all expected fields are present."""
    from tests.fixtures.core import seed_universes
    universes = seed_universes(db)
    uid = universes[0].id

    response = client.get(f"/api/v1/universe/{uid}/data-health")

    assert response.status_code == 200
    data = response.json()
    for field in (
        "universe_id", "degraded", "stale_pct", "gapped_pct",
        "worst_staleness_hours", "worst_gap_days", "report_age_hours", "grade",
    ):
        assert field in data, f"Missing field: {field}"
```

**Step 2 — Verify tests fail**

```bash
docker-compose exec backend python -m pytest backend/tests/api/test_universe.py::test_data_health_no_report_returns_degraded -x -q 2>&1 | tail -5
# Expected: 404 (route not yet defined)
```

**Step 3 — Add `DataHealthResponse` schema to `backend/app/schemas/universe.py`**

Append to the file:

```python
class DataHealthResponse(BaseModel):
    """Compact data-quality degradation summary for the Scanner page."""

    model_config = ConfigDict(from_attributes=False)

    universe_id: int
    degraded: bool
    stale_pct: Optional[float] = None
    gapped_pct: Optional[float] = None
    worst_staleness_hours: Optional[float] = None
    worst_gap_days: Optional[int] = None
    report_age_hours: Optional[float] = None
    grade: Optional[str] = None
```

**Step 4 — Export from `backend/app/schemas/__init__.py`**

Add to imports and `__all__`:

```python
from app.schemas.universe import DataHealthResponse
```

```python
"DataHealthResponse",
```

**Step 5 — Add endpoint to `backend/app/routers/universe.py`**

Add the import at the top alongside existing schema imports:

```python
from app.schemas.universe import DataHealthResponse
```

Add the endpoint and gauge cleanup after the existing `delete_stock_universe` handler:

```python
@router.get("/{universe_id}/data-health", response_model=DataHealthResponse)
def get_data_health(
    universe_id: int,
    db: Session = Depends(get_db),
):
    """
    Return a compact data-quality degradation summary for the active universe.
    Derived from the latest UniverseQualityReport. Missing/stale report → degraded=True.
    Response is cached 5 minutes.
    """
    from datetime import datetime as _dt

    from app.models.universe_quality_report import UniverseQualityReport
    from app.models.system_config import SystemConfig

    get_or_404(db, StockUniverse, universe_id, "Universe")

    def _fetch():
        from app.utils.time import utc_now

        report = (
            db.query(UniverseQualityReport)
            .filter(UniverseQualityReport.universe_id == universe_id)
            .first()
        )

        cfg_rows = (
            db.query(SystemConfig)
            .filter(
                SystemConfig.key.in_(
                    ["quality_staleness_hours", "quality_gap_min_weekdays", "quality_alert_pct"]
                )
            )
            .all()
        )
        cfg = {r.key: r.value for r in cfg_rows}
        staleness_hours = float(cfg.get("quality_staleness_hours", 48))
        gap_min_weekdays = int(cfg.get("quality_gap_min_weekdays", 2))
        alert_pct = float(cfg.get("quality_alert_pct", 20))

        now = utc_now()

        if report is None or report.generated_at is None or report.report_data is None:
            return DataHealthResponse(
                universe_id=universe_id,
                degraded=True,
                stale_pct=None,
                gapped_pct=None,
                worst_staleness_hours=None,
                worst_gap_days=None,
                report_age_hours=None,
                grade=None,
            ).model_dump()

        report_age_hours = round(
            (now - report.generated_at).total_seconds() / 3600, 1
        )
        if report_age_hours > 48:
            return DataHealthResponse(
                universe_id=universe_id,
                degraded=True,
                stale_pct=None,
                gapped_pct=None,
                worst_staleness_hours=None,
                worst_gap_days=None,
                report_age_hours=report_age_hours,
                grade=report.overall_grade,
            ).model_dump()

        tickers = report.report_data.get("tickers", [])
        if not tickers:
            return DataHealthResponse(
                universe_id=universe_id,
                degraded=True,
                stale_pct=None,
                gapped_pct=None,
                worst_staleness_hours=None,
                worst_gap_days=None,
                report_age_hours=report_age_hours,
                grade=report.overall_grade,
            ).model_dump()

        # Deduplicate: best (latest) last_bar per ticker symbol
        best_bar: dict = {}
        for entry in tickers:
            ticker = entry.get("ticker")
            if not ticker:
                continue
            lb = entry.get("last_bar")
            if lb is None:
                continue
            if ticker not in best_bar or lb > best_bar[ticker]["last_bar"]:
                best_bar[ticker] = entry

        total = len(best_bar)
        stale_count = 0
        gapped_count = 0
        worst_s_h = 0.0
        worst_g_d = 0

        for entry in best_bar.values():
            lb = entry.get("last_bar")
            if lb is None:
                stale_count += 1
                continue
            try:
                last_ts = _dt.fromisoformat(lb)
            except ValueError:
                stale_count += 1
                continue
            if last_ts.tzinfo is not None:
                last_ts = last_ts.replace(tzinfo=None)
            age_h = (now - last_ts).total_seconds() / 3600
            if age_h > staleness_hours:
                stale_count += 1
                worst_s_h = max(worst_s_h, age_h)
            gc = entry.get("gap_count", 0)
            if gc > gap_min_weekdays:
                gapped_count += 1
                worst_g_d = max(worst_g_d, gc)

        stale_pct = round(stale_count / total * 100, 1) if total else None
        gapped_pct = round(gapped_count / total * 100, 1) if total else None
        degraded = (
            (stale_pct is not None and stale_pct > alert_pct)
            or (gapped_pct is not None and gapped_pct > alert_pct)
        )

        return DataHealthResponse(
            universe_id=universe_id,
            degraded=degraded,
            stale_pct=stale_pct,
            gapped_pct=gapped_pct,
            worst_staleness_hours=round(worst_s_h, 1) if worst_s_h else None,
            worst_gap_days=worst_g_d if worst_g_d else None,
            report_age_hours=report_age_hours,
            grade=report.overall_grade,
        ).model_dump()

    return get_cached(f"mh:universe:data-health:{universe_id}", 300, _fetch)
```

Also update `delete_stock_universe` to call gauge cleanup on soft-delete. After `db.commit()` in that handler, add:

```python
    # Clean up per-universe Prometheus label series
    try:
        from app.core.metrics import aggregate_gap_days, aggregate_staleness_hours
        aggregate_gap_days.remove(str(universe_id))
        aggregate_staleness_hours.remove(str(universe_id))
    except Exception:
        pass
    invalidate(f"mh:universe:data-health:{universe_id}")
```

**Step 6 — Verify backend reloaded and tests pass**

```bash
docker-compose logs backend --tail=5

docker-compose exec backend python -m pytest backend/tests/api/test_universe.py \
  -k "data_health" -v 2>&1 | tail -20
```

**Step 7 — Smoke test the endpoint**

```bash
# Replace 1 with a real universe ID from your dev DB
curl -s http://localhost:8000/api/v1/universe/1/data-health | python -m json.tool
# Expected: JSON with degraded, stale_pct, gapped_pct, etc.
```

**Step 8 — Commit**

```bash
git add backend/app/schemas/universe.py backend/app/schemas/__init__.py \
  backend/app/routers/universe.py backend/tests/api/test_universe.py
git commit -m "feat(api): add GET /api/v1/universe/{id}/data-health endpoint (#387)"
```

---

## Task 7: Frontend — `getDataHealth` API client + Scanner page banner

**Files:** `frontend/src/api/universe.ts`, `frontend/src/pages/Scanner/index.tsx`

### TDD

**Step 1 — Add type and client function to `frontend/src/api/universe.ts`**

Append after the existing `QualityReport` types section:

```typescript
// ---- Data Health ---------------------------------------------------------- //

export interface DataHealthResponse {
  universe_id: number;
  degraded: boolean;
  stale_pct: number | null;
  gapped_pct: number | null;
  worst_staleness_hours: number | null;
  worst_gap_days: number | null;
  report_age_hours: number | null;
  grade: string | null;
}

export const getDataHealth = async (universeId: number): Promise<DataHealthResponse> => {
  const response = await apiClient.get(`/universe/${universeId}/data-health`);
  return response.data;
};
```

**Step 2 — Verify TypeScript compiles**

```bash
docker-compose exec frontend npx tsc --noEmit 2>&1 | tail -10
# Expected: no errors
```

**Step 3 — Write failing test for the banner**

Create `frontend/src/pages/Scanner/Scanner.degradation.test.tsx`:

```typescript
import React from 'react';
import { render, screen } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { vi } from 'vitest';

vi.mock('../../api/universe', async (importOriginal) => ({
  ...await importOriginal() as Record<string, unknown>,
  getDataHealth: vi.fn(),
}));
vi.mock('../../api/scanner', () => ({
  fetchScannerConfigs: vi.fn().mockResolvedValue([]),
  fetchStockUniverses: vi.fn().mockResolvedValue([]),
  fetchScannerHistory: vi.fn().mockResolvedValue([]),
  fetchScanStatusBlock: vi.fn().mockResolvedValue(null),
  fetchScannerResults: vi.fn().mockResolvedValue([]),
  handleApiError: vi.fn(),
}));
vi.mock('../../hooks/useScannerState', () => ({
  useScannerState: () => ({
    selectedConfig: 'pre_market',
    selectedUniverse: 1,
    isScanning: false,
    scanResults: null,
    scanError: null,
    liveProgress: null,
    activeScan: null,
    sortBy: 'volume',
    sortOrder: 'desc',
    scanStartDate: null,
    scanEndDate: null,
    setSelectedConfig: vi.fn(),
    setSelectedUniverse: vi.fn(),
    setScanResults: vi.fn(),
    setIsScanning: vi.fn(),
    setScanError: vi.fn(),
    setLiveProgress: vi.fn(),
    setActiveScan: vi.fn(),
    setSortBy: vi.fn(),
    setSortOrder: vi.fn(),
    setScanStartDate: vi.fn(),
    setScanEndDate: vi.fn(),
  }),
  ACTIVE_SCAN_LS_KEY: 'active_scan',
  EMPTY_PROGRESS: {},
}));
vi.mock('../../hooks/useScannerWs', () => ({
  useScannerWs: () => ({ attachWebSocket: vi.fn() }),
}));

import { getDataHealth } from '../../api/universe';

const mockGetDataHealth = getDataHealth as ReturnType<typeof vi.fn>;

function renderScanner() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const Scanner = require('./index').default;
  return render(
    <QueryClientProvider client={qc}>
      <Scanner />
    </QueryClientProvider>,
  );
}

describe('Scanner degradation banner', () => {
  it('shows amber banner when degraded=true', async () => {
    mockGetDataHealth.mockResolvedValue({
      universe_id: 1,
      degraded: true,
      stale_pct: 25.0,
      gapped_pct: 8.3,
      worst_staleness_hours: 72.1,
      worst_gap_days: 4,
      report_age_hours: 6.2,
      grade: 'C',
    });

    renderScanner();

    const banner = await screen.findByRole('alert');
    expect(banner).toBeInTheDocument();
    expect(banner).toHaveTextContent(/data quality warning/i);
  });

  it('does not show banner when degraded=false', async () => {
    mockGetDataHealth.mockResolvedValue({
      universe_id: 1,
      degraded: false,
      stale_pct: 5.0,
      gapped_pct: 0.0,
      worst_staleness_hours: 10.0,
      worst_gap_days: 0,
      report_age_hours: 2.0,
      grade: 'A',
    });

    renderScanner();

    // wait for query to settle
    await new Promise((r) => setTimeout(r, 50));
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });
});
```

**Step 4 — Verify tests fail**

```bash
docker-compose exec frontend npx vitest run src/pages/Scanner/Scanner.degradation.test.tsx 2>&1 | tail -10
# Expected: test fails — banner component not yet added
```

**Step 5 — Update `frontend/src/pages/Scanner/index.tsx`**

Add import at the top:

```typescript
import { getDataHealth, type DataHealthResponse } from '../../api/universe';
```

Add React Query call inside the `Scanner` component (after the existing `statusBlock` query):

```typescript
  const { data: dataHealth } = useQuery<DataHealthResponse | null>({
    queryKey: ['universeDataHealth', state.selectedUniverse],
    queryFn: () =>
      state.selectedUniverse ? getDataHealth(state.selectedUniverse) : Promise.resolve(null),
    enabled: !!state.selectedUniverse,
    staleTime: 5 * 60 * 1000, // 5 minutes — matches backend cache TTL
  });
```

Add the banner inside the JSX, immediately before `<ScanConfigPanel ...`:

```tsx
      {dataHealth?.degraded && (
        <div
          role="alert"
          className="flex items-start gap-3 rounded-lg border border-amber-400 bg-amber-50 px-4 py-3 text-amber-900 dark:border-amber-600 dark:bg-amber-900/20 dark:text-amber-200"
        >
          <span className="mt-0.5 text-lg">⚠️</span>
          <div>
            <span className="font-semibold">Data quality warning</span>
            {' — '}
            {dataHealth.stale_pct != null
              ? `${dataHealth.stale_pct}% of tickers in this universe have stale or gapped data`
              : 'Data quality issues detected'}
            {dataHealth.worst_staleness_hours != null &&
              ` (worst: ${dataHealth.worst_staleness_hours.toFixed(1)}h stale)`}
            {'. Scanner results may be distorted. '}
            <button
              type="button"
              className="underline underline-offset-2 hover:no-underline"
              onClick={() => window.location.assign('/universes')}
            >
              Run quality analysis →
            </button>
          </div>
        </div>
      )}
```

**Step 6 — TypeScript check**

```bash
docker-compose exec frontend npx tsc --noEmit 2>&1 | tail -10
# Expected: no errors
```

**Step 7 — Run tests**

```bash
docker-compose exec frontend npx vitest run src/pages/Scanner/Scanner.degradation.test.tsx 2>&1 | tail -15
# Expected: 2 passed
```

**Step 8 — Manual browser verification**

1. Confirm the backend is reloaded: `docker-compose logs backend --tail=5`
2. Open `http://localhost:3333` and navigate to the Scanner page
3. Confirm no console errors
4. To force the banner: patch `getDataHealth` in browser devtools or set up a universe with a missing report and confirm the banner appears

**Step 9 — Commit**

```bash
git add frontend/src/api/universe.ts frontend/src/pages/Scanner/index.tsx \
  frontend/src/pages/Scanner/Scanner.degradation.test.tsx
git commit -m "feat(frontend): add data-health degradation banner to Scanner page (#387)"
```

---

## Validation Checklist

Before marking the issue ready, confirm all of the following:

```bash
# 1. All backend tests pass
docker-compose exec backend python -m pytest backend/tests/ -x -q 2>&1 | tail -10

# 2. TypeScript check passes
docker-compose exec frontend npx tsc --noEmit 2>&1 | tail -5

# 3. All frontend tests pass
docker-compose exec frontend npx vitest run 2>&1 | tail -10

# 4. Migration applied
docker-compose exec backend python -m alembic current 2>&1 | tail -3

# 5. New endpoint reachable
curl -s http://localhost:8000/api/v1/universe/1/data-health | python -m json.tool

# 6. New task registered in Celery
docker-compose exec celery-worker celery -A app.core.celery_app inspect registered 2>&1 | grep staleness
# Expected: app.tasks.check_aggregate_staleness

# 7. Beat schedule includes nightly entry
docker-compose exec celery-beat cat /tmp/celerybeat-schedule 2>/dev/null || \
  grep "aggregate-quality-nightly" backend/app/core/celery_app.py
```
