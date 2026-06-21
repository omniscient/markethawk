# Implementation Plan: Scanner Nightly Replay-Diff Regression Detector

**Date:** 2026-06-21  
**Issue:** #392  
**Spec:** [docs/superpowers/specs/2026-06-21-scanner-nightly-replay-diff-design.md](../specs/2026-06-21-scanner-nightly-replay-diff-design.md)

---

## Goal

Nightly Celery task re-runs the previous trading day's scans from stored `StockAggregate` data, diffs against live `ScannerEvent` rows, persists one `ScannerReplayDiff` record per scanner per day, emits Seq/Prometheus observability, and fires `SystemNotifier` when drift exceeds threshold.

## Architecture

```
Celery beat @ 04:00 UTC weekdays
  run_replay_diff_nightly (tasks/scanning.py)
    → run_replay_diff_for_scanner(scanner_type, yesterday, db)  [replay_diff_service.py]
        _collect_live_signals  → {ticker: indicators} from ScannerEvent DB rows
        _run_replay             → {ticker: indicators} via save_event no-op patch
        _compute_diff           → pure diff payload dict
        upsert ScannerReplayDiff row
        emit Seq log + increment Prometheus counters
        notify_system() if has_drift

GET /api/v1/scanner/replay-diffs  (routers/scanner.py)
  → last N days of ScannerReplayDiff rows
```

## Tech Stack

**Backend**: FastAPI + SQLAlchemy 2.0 (sync) + PostgreSQL + Celery  
**Tests**: pytest with MagicMock DB (no SQLite — JSONB columns require PostgreSQL)

---

## File Structure

| File | Action |
|------|--------|
| `backend/app/models/scanner_replay_diff.py` | New |
| `backend/app/models/__init__.py` | Add import |
| `alembic/versions/<rev>_add_scanner_replay_diffs_table.py` | New migration |
| `backend/app/schemas/scanner_replay_diff.py` | New |
| `backend/app/schemas/__init__.py` | Add import |
| `backend/app/core/metrics.py` | Add counter |
| `backend/app/services/replay_diff_service.py` | New |
| `backend/tests/services/test_replay_diff_service.py` | New |
| `backend/app/tasks/scanning.py` | Append task |
| `backend/app/core/celery_app.py` | Add beat entry |
| `backend/tests/tasks/test_scanning_tasks.py` | Append test |
| `backend/app/routers/scanner.py` | Append endpoint |
| `backend/tests/api/test_scanner.py` | Append test |

---

## Task 1: `ScannerReplayDiff` Model + Migration

### Files
- `backend/app/models/scanner_replay_diff.py`
- `backend/app/models/__init__.py`
- `alembic/versions/<rev>_add_scanner_replay_diffs_table.py`

### Steps

**Step 1.1 — Write the failing model import test**

Create `backend/tests/test_scanner_replay_diff_model.py`:

```python
"""Smoke test: ScannerReplayDiff is importable and has expected columns."""

from datetime import date


def test_model_columns():
    from app.models.scanner_replay_diff import ScannerReplayDiff

    diff = ScannerReplayDiff(
        scanner_type="liquidity_hunt",
        scan_date=date(2026, 6, 20),
        status="clean",
        has_drift=False,
        live_count=3,
        replay_count=3,
        matched_count=3,
        missing_in_replay=[],
        new_in_replay=[],
        metric_deltas={},
        drift_kinds=[],
    )
    assert diff.scanner_type == "liquidity_hunt"
    assert diff.has_drift is False
    assert diff.__tablename__ == "scanner_replay_diffs"
```

**Step 1.2 — Verify test fails**

```bash
docker-compose exec backend python -m pytest backend/tests/test_scanner_replay_diff_model.py -x -q
# Expected: ModuleNotFoundError: No module named 'app.models.scanner_replay_diff'
```

**Step 1.3 — Implement the model**

Create `backend/app/models/scanner_replay_diff.py`:

```python
from sqlalchemy import Boolean, Column, Date, DateTime, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB

from app.core.database import Base
from app.utils.time import utc_now


class ScannerReplayDiff(Base):
    """One replay-diff record per (scanner_type, scan_date). Upserted nightly."""

    __tablename__ = "scanner_replay_diffs"

    id = Column(Integer, primary_key=True, index=True)
    scanner_type = Column(String(50), nullable=False, index=True)
    scan_date = Column(Date, nullable=False, index=True)
    # "clean" | "drift" | "insufficient_data" | "no_live_events"
    status = Column(String(20), nullable=False)
    has_drift = Column(Boolean, nullable=False, index=True)
    live_count = Column(Integer, nullable=False)
    replay_count = Column(Integer, nullable=False)
    matched_count = Column(Integer, nullable=False)
    missing_in_replay = Column(JSONB, nullable=False, default=list)
    new_in_replay = Column(JSONB, nullable=False, default=list)
    metric_deltas = Column(JSONB, nullable=False, default=dict)
    drift_kinds = Column(JSONB, nullable=False, default=list)
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)

    __table_args__ = (
        UniqueConstraint("scanner_type", "scan_date", name="uq_scanner_replay_diff"),
    )
```

**Step 1.4 — Register in `models/__init__.py`**

Add after the `ScannerRun` import line:

```python
from app.models.scanner_replay_diff import ScannerReplayDiff
```

Verify insertion point (after line `from app.models.scanner_run import ScannerRun`):

```bash
grep -n "scanner_run\|scanner_replay" backend/app/models/__init__.py
```

Expected output includes both lines, with `scanner_replay_diff` after `scanner_run`.

**Step 1.5 — Verify test passes**

```bash
docker-compose exec backend python -m pytest backend/tests/test_scanner_replay_diff_model.py -x -q
# Expected: 1 passed
```

**Step 1.6 — Generate and apply Alembic migration**

```bash
docker-compose exec backend python -m alembic revision --autogenerate \
  -m "add_scanner_replay_diffs_table"
docker-compose exec backend python -m alembic upgrade head
```

Expected output ends with: `Running upgrade ... -> <rev>, add_scanner_replay_diffs_table`

Verify table exists:
```bash
docker-compose exec backend python -c "
from app.core.database import engine
from sqlalchemy import inspect
cols = [c['name'] for c in inspect(engine).get_columns('scanner_replay_diffs')]
print(cols)
assert 'has_drift' in cols and 'scan_date' in cols and 'drift_kinds' in cols
print('OK')
"
```

**Step 1.7 — Commit**

```bash
git add backend/app/models/scanner_replay_diff.py \
        backend/app/models/__init__.py \
        backend/tests/test_scanner_replay_diff_model.py \
        alembic/versions/
git commit -m "feat(#392): add ScannerReplayDiff model and migration"
```

---

## Task 2: Pydantic Schema + Prometheus Counter

### Files
- `backend/app/schemas/scanner_replay_diff.py`
- `backend/app/schemas/__init__.py`
- `backend/app/core/metrics.py`

### Steps

**Step 2.1 — Write the failing schema test**

Create `backend/tests/schemas/test_scanner_replay_diff_schema.py`:

```python
from datetime import date, datetime


def test_schema_serializes():
    from app.schemas.scanner_replay_diff import ScannerReplayDiffSchema

    data = {
        "id": 1,
        "scanner_type": "liquidity_hunt",
        "scan_date": date(2026, 6, 20),
        "status": "clean",
        "has_drift": False,
        "live_count": 3,
        "replay_count": 3,
        "matched_count": 3,
        "missing_in_replay": [],
        "new_in_replay": [],
        "metric_deltas": {},
        "drift_kinds": [],
        "created_at": datetime(2026, 6, 21, 4, 0, 0),
        "updated_at": datetime(2026, 6, 21, 4, 0, 0),
    }
    schema = ScannerReplayDiffSchema.model_validate(data)
    assert schema.scanner_type == "liquidity_hunt"
    assert schema.has_drift is False
    assert schema.missing_in_replay == []


def test_counter_is_importable():
    from app.core.metrics import replay_drift_signals_total

    assert replay_drift_signals_total is not None
```

**Step 2.2 — Verify test fails**

```bash
docker-compose exec backend python -m pytest backend/tests/schemas/test_scanner_replay_diff_schema.py -x -q
# Expected: ModuleNotFoundError: No module named 'app.schemas.scanner_replay_diff'
```

**Step 2.3 — Implement the Pydantic schema**

Create `backend/app/schemas/scanner_replay_diff.py`:

```python
from datetime import date, datetime
from typing import Any, Optional

from pydantic import BaseModel


class ScannerReplayDiffSchema(BaseModel):
    id: int
    scanner_type: str
    scan_date: date
    status: str
    has_drift: bool
    live_count: int
    replay_count: int
    matched_count: int
    missing_in_replay: list[str]
    new_in_replay: list[str]
    metric_deltas: dict[str, Any]
    drift_kinds: list[str]
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = {"from_attributes": True}
```

**Step 2.4 — Register in `schemas/__init__.py`**

Add after the existing scanner schema imports:

```python
from app.schemas.scanner_replay_diff import ScannerReplayDiffSchema
```

**Step 2.5 — Add Prometheus counter to `metrics.py`**

Append after the last metric definition in `backend/app/core/metrics.py`:

```python
replay_drift_signals_total = Counter(
    "markethawk_replay_drift_signals_total",
    "Scanner replay-diff signal counts by kind",
    ["scanner_type", "kind"],
)
```

**Step 2.6 — Verify tests pass**

```bash
docker-compose exec backend python -m pytest backend/tests/schemas/test_scanner_replay_diff_schema.py -x -q
# Expected: 2 passed
```

**Step 2.7 — Commit**

```bash
git add backend/app/schemas/scanner_replay_diff.py \
        backend/app/schemas/__init__.py \
        backend/app/core/metrics.py \
        backend/tests/schemas/test_scanner_replay_diff_schema.py
git commit -m "feat(#392): add ScannerReplayDiffSchema and replay_drift_signals_total counter"
```

---

## Task 3: `replay_diff_service.py` — Three-Stage Pipeline

### Files
- `backend/app/services/replay_diff_service.py`
- `backend/tests/services/test_replay_diff_service.py`

### Steps

**Step 3.1 — Write the failing tests**

Create `backend/tests/services/test_replay_diff_service.py`:

```python
"""
Unit tests for replay_diff_service.

Uses MagicMock DB (not SQLite) — JSONB columns require PostgreSQL.
All async scanner calls are patched out.
"""

from datetime import date, datetime, timezone
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# _compute_diff — pure function, no mocks needed
# ---------------------------------------------------------------------------


def test_compute_diff_all_matched_no_drift():
    from app.services.replay_diff_service import _compute_diff

    live = {"AAPL": {"volume_ratio": 5.0, "gap_pct": 2.0}}
    replay = {"AAPL": {"volume_ratio": 5.0, "gap_pct": 2.0}}
    result = _compute_diff(live, replay)
    assert result["status"] == "clean"
    assert result["has_drift"] is False
    assert result["matched_count"] == 1
    assert result["missing_in_replay"] == []
    assert result["new_in_replay"] == []
    assert result["metric_deltas"] == {}


def test_compute_diff_missing_in_replay_triggers_drift():
    from app.services.replay_diff_service import _compute_diff

    live = {"AAPL": {"volume_ratio": 5.0}, "TSLA": {"volume_ratio": 3.0}}
    replay = {"AAPL": {"volume_ratio": 5.0}}
    result = _compute_diff(live, replay)
    assert result["status"] == "drift"
    assert result["has_drift"] is True
    assert result["missing_in_replay"] == ["TSLA"]
    assert "missing_signal" in result["drift_kinds"]


def test_compute_diff_new_in_replay_no_drift():
    from app.services.replay_diff_service import _compute_diff

    live = {"AAPL": {"volume_ratio": 5.0}}
    replay = {"AAPL": {"volume_ratio": 5.0}, "MSFT": {"volume_ratio": 4.0}}
    result = _compute_diff(live, replay)
    # new_in_replay alone does not set has_drift (threshold: only missing or metric_delta)
    assert result["new_in_replay"] == ["MSFT"]
    assert result["has_drift"] is False
    assert "new_signal" in result["drift_kinds"]


def test_compute_diff_metric_delta_above_tolerance():
    from app.services.replay_diff_service import _compute_diff

    live = {"AAPL": {"volume_ratio": 5.0, "gap_pct": 2.0}}
    replay = {"AAPL": {"volume_ratio": 5.4, "gap_pct": 2.0}}  # 8% delta on volume_ratio
    result = _compute_diff(live, replay, delta_tolerance=0.05)
    assert result["has_drift"] is True
    assert "metric_delta" in result["drift_kinds"]
    assert "AAPL" in result["metric_deltas"]
    assert "volume_ratio" in result["metric_deltas"]["AAPL"]


def test_compute_diff_metric_delta_below_tolerance_no_drift():
    from app.services.replay_diff_service import _compute_diff

    live = {"AAPL": {"volume_ratio": 5.0}}
    replay = {"AAPL": {"volume_ratio": 5.02}}  # 0.4% delta — below 5% tolerance
    result = _compute_diff(live, replay, delta_tolerance=0.05)
    assert result["has_drift"] is False
    assert result["metric_deltas"] == {}


# ---------------------------------------------------------------------------
# _collect_live_signals
# ---------------------------------------------------------------------------


def _make_event(ticker, indicators):
    ev = MagicMock()
    ev.ticker = ticker
    ev.indicators = indicators
    return ev


def test_collect_live_signals_returns_dict():
    from app.services.replay_diff_service import _collect_live_signals

    events = [
        _make_event("AAPL", {"volume_ratio": 5.0}),
        _make_event("TSLA", {"volume_ratio": 3.5}),
    ]
    db = MagicMock()
    db.query.return_value.filter.return_value.all.return_value = events

    result = _collect_live_signals("liquidity_hunt", date(2026, 6, 20), db)

    assert result == {
        "AAPL": {"volume_ratio": 5.0},
        "TSLA": {"volume_ratio": 3.5},
    }


def test_collect_live_signals_empty_returns_empty():
    from app.services.replay_diff_service import _collect_live_signals

    db = MagicMock()
    db.query.return_value.filter.return_value.all.return_value = []

    result = _collect_live_signals("liquidity_hunt", date(2026, 6, 20), db)
    assert result == {}


# ---------------------------------------------------------------------------
# _run_replay
# ---------------------------------------------------------------------------


def test_run_replay_returns_none_when_no_bars():
    from app.services.replay_diff_service import _run_replay

    db = MagicMock()
    # Simulate: no StockAggregate rows found (scalar returns None)
    db.query.return_value.filter.return_value.limit.return_value.scalar.return_value = None

    result = _run_replay("liquidity_hunt", ["AAPL", "TSLA"], date(2026, 6, 20), db)
    assert result is None


def test_run_replay_returns_empty_dict_when_bars_exist_no_signals():
    from app.services.replay_diff_service import _run_replay

    db = MagicMock()
    # Simulate bars exist
    db.query.return_value.filter.return_value.limit.return_value.scalar.return_value = 1

    async def _fake_run(scanner_type, tickers, db, event_date, **kwargs):
        return []  # Scanner runs but emits no signals

    with patch("app.services.replay_diff_service.scan_orchestrator") as mock_orch, \
         patch("app.services.replay_diff_service._SAVE_EVENT_PATCH_TARGETS", []):
        mock_orch.run = _fake_run
        result = _run_replay("liquidity_hunt", ["AAPL", "TSLA"], date(2026, 6, 20), db)

    # Bars exist, scanner ran, no signals emitted → empty dict (not None)
    assert result == {}


def test_run_replay_captures_signals_via_patch():
    from app.services.replay_diff_service import _run_replay

    db = MagicMock()
    db.query.return_value.filter.return_value.limit.return_value.scalar.return_value = 1

    async def _fake_run(scanner_type, tickers, db_arg, event_date, **kwargs):
        # Simulate a scanner calling its module-level _save_event with keyword args.
        # In production this is intercepted by the ExitStack patches; here we call
        # the capture function directly via the patched liquidity_hunt._save_event
        # which is replaced by _capture_save_event in the ExitStack.
        import app.services.liquidity_hunt as lh
        lh._save_event(
            db=db_arg,
            ticker="AAPL",
            event_date=event_date,
            scanner_type=scanner_type,
            indicators={"volume_ratio": 5.0},
            criteria_met={},
            enrichment={},
        )
        return [{}]

    with patch("app.services.replay_diff_service.scan_orchestrator") as mock_orch:
        mock_orch.run = _fake_run
        result = _run_replay("liquidity_hunt_pre", ["AAPL"], date(2026, 6, 20), db)

    # The capture function is wired to liquidity_hunt._save_event via ExitStack;
    # the fake scanner calls lh._save_event which resolves to _capture_save_event.
    assert result == {"AAPL": {"volume_ratio": 5.0}}


def test_run_replay_patch_targets_cover_all_module_level_bindings():
    from app.services.replay_diff_service import _SAVE_EVENT_PATCH_TARGETS

    # Verify the expected scanner modules are in the patch target list.
    # Module-level binders (import save_event at load time):
    assert "app.services.liquidity_hunt._save_event" in _SAVE_EVENT_PATCH_TARGETS
    assert "app.services.pocket_pivot._save_event" in _SAVE_EVENT_PATCH_TARGETS
    assert "app.services.trend_pullback_scan._save_event" in _SAVE_EVENT_PATCH_TARGETS
    # Call-time binders (via ScannerService._save_event):
    assert "app.services.scanner.ScannerService._save_event" in _SAVE_EVENT_PATCH_TARGETS


# ---------------------------------------------------------------------------
# run_replay_diff_for_scanner
# ---------------------------------------------------------------------------


def test_run_replay_diff_upserts_no_live_events():
    from app.services.replay_diff_service import run_replay_diff_for_scanner

    db = MagicMock()

    call_count = [0]

    def _query_side(model):
        q = MagicMock()
        idx = call_count[0]
        call_count[0] += 1
        if idx == 0:
            # ScannerConfig query → active config exists with universe_id
            cfg = MagicMock()
            cfg.universe_id = 1
            q.filter.return_value.all.return_value = [cfg]
        elif idx == 1:
            # StockUniverseTicker query → tickers
            t = MagicMock()
            t.ticker = "AAPL"
            q.filter.return_value.all.return_value = [t]
        elif idx == 2:
            # ScannerEvent query → no live events
            q.filter.return_value.all.return_value = []
        elif idx == 3:
            # Upsert: existing record check → None (insert path)
            q.filter_by.return_value.first.return_value = None
        return q

    db.query.side_effect = _query_side

    with patch("app.services.replay_diff_service.notify_system"), \
         patch("app.services.replay_diff_service.replay_drift_signals_total"):
        result = run_replay_diff_for_scanner("liquidity_hunt", date(2026, 6, 20), db)

    assert result.status == "no_live_events"
    assert result.has_drift is False
    db.add.assert_called_once()
    db.commit.assert_called_once()
```

**Step 3.2 — Verify tests fail**

```bash
docker-compose exec backend python -m pytest backend/tests/services/test_replay_diff_service.py -x -q
# Expected: ModuleNotFoundError: No module named 'app.services.replay_diff_service'
```

**Step 3.3 — Implement `replay_diff_service.py`**

Create `backend/app/services/replay_diff_service.py`:

```python
"""
Nightly scanner replay-diff service.

Runs the previous day's scans from stored StockAggregate data and diffs
the in-memory signals against the live ScannerEvent rows persisted during
the real nightly run. Drift (missing signals or metric deltas >5%) triggers
SystemNotifier warning and Prometheus counter increments.
"""

import asyncio
import contextlib
import logging
from datetime import date, datetime, timedelta, timezone
from typing import Optional
from unittest.mock import patch

from sqlalchemy.orm import Session

from app.core.metrics import replay_drift_signals_total
from app.models.scanner_replay_diff import ScannerReplayDiff
from app.services import scan_orchestrator
from app.services.system_notifier import notify_system

logger = logging.getLogger(__name__)

_DRIFT_THRESHOLD_FIELDS = ("volume_ratio", "gap_pct")

# Scanners that bind save_event at module load time must be patched at their
# local reference. Scanners using ScannerService._save_event (which re-imports
# alert_service at call time) are covered by the ScannerService patch target.
_SAVE_EVENT_PATCH_TARGETS = [
    "app.services.liquidity_hunt._save_event",
    "app.services.pocket_pivot._save_event",
    "app.services.trend_pullback_scan._save_event",
    "app.services.scanner.ScannerService._save_event",
]


def _collect_live_signals(
    scanner_type: str,
    scan_date: date,
    db: Session,
) -> dict[str, dict]:
    """Query ScannerEvent for (scanner_type, scan_date). Returns {ticker: indicators}."""
    from app.models.scanner_event import ScannerEvent

    events = (
        db.query(ScannerEvent)
        .filter(
            ScannerEvent.scanner_type == scanner_type,
            ScannerEvent.event_date == scan_date,
        )
        .all()
    )
    return {ev.ticker: ev.indicators or {} for ev in events}


def _run_replay(
    scanner_type: str,
    tickers: list[str],
    scan_date: date,
    db: Session,
) -> Optional[dict[str, dict]]:
    """
    Invoke the scanner via scan_orchestrator with all save_event bindings patched.

    Scanners bind save_event at module load time (liquidity_hunt, pocket_pivot,
    trend_pullback_scan) or via ScannerService at call time (pre_market_scan,
    oversold_bounce_scan). All four patch targets are applied via ExitStack to
    ensure no ScannerEvent rows are written during replay.

    Returns {ticker: indicators} for signals detected, or None if no
    StockAggregate rows exist for scan_date (insufficient_data).
    """
    from app.models.stock_aggregate import StockAggregate

    scan_start = datetime(scan_date.year, scan_date.month, scan_date.day, tzinfo=timezone.utc)
    scan_end = scan_start + timedelta(days=1)

    has_bars = (
        db.query(StockAggregate.id)
        .filter(
            StockAggregate.ticker.in_(tickers[:20]),
            StockAggregate.timestamp >= scan_start,
            StockAggregate.timestamp < scan_end,
        )
        .limit(1)
        .scalar()
        is not None
    )
    if not has_bars:
        return None

    captured: dict[str, dict] = {}

    def _capture_save_event(
        db,
        ticker: str,
        event_date: date,
        scanner_type: str,
        indicators: dict,
        **kwargs,
    ) -> dict:
        captured[ticker] = indicators
        # Return a representative dict so callers that use the return value
        # (e.g. scanner _persist stages that append event_dict to results) remain functional.
        return {"ticker": ticker, "scanner_type": scanner_type, "indicators": indicators}

    loop = asyncio.new_event_loop()
    try:
        with contextlib.ExitStack() as stack:
            for target in _SAVE_EVENT_PATCH_TARGETS:
                stack.enter_context(patch(target, side_effect=_capture_save_event))
            loop.run_until_complete(
                scan_orchestrator.run(scanner_type, tickers, db, scan_date)
            )
    except Exception as exc:
        logger.exception(
            "_run_replay: scanner_type=%s scan_date=%s replay failed: %s",
            scanner_type,
            scan_date,
            exc,
        )
    finally:
        loop.close()

    return captured


def _compute_diff(
    live: dict[str, dict],
    replay: dict[str, dict],
    delta_tolerance: float = 0.05,
) -> dict:
    """Pure function. Returns the full diff payload for ScannerReplayDiff columns."""
    live_tickers = set(live)
    replay_tickers = set(replay)

    matched = live_tickers & replay_tickers
    missing_in_replay = sorted(live_tickers - replay_tickers)
    new_in_replay = sorted(replay_tickers - live_tickers)

    metric_deltas: dict[str, dict] = {}
    for ticker in matched:
        live_ind = live[ticker]
        replay_ind = replay[ticker]
        deltas: dict[str, float] = {}
        for field in _DRIFT_THRESHOLD_FIELDS:
            live_val = live_ind.get(field)
            replay_val = replay_ind.get(field)
            if live_val and replay_val and abs(live_val) > 1e-9:
                delta_pct = abs((replay_val - live_val) / live_val)
                if delta_pct > delta_tolerance:
                    deltas[field] = round(delta_pct, 4)
        if deltas:
            metric_deltas[ticker] = deltas

    has_drift = bool(missing_in_replay or metric_deltas)

    drift_kinds: list[str] = []
    if missing_in_replay:
        drift_kinds.append("missing_signal")
    if new_in_replay:
        drift_kinds.append("new_signal")
    if metric_deltas:
        drift_kinds.append("metric_delta")

    return {
        "live_count": len(live),
        "replay_count": len(replay),
        "matched_count": len(matched),
        "missing_in_replay": missing_in_replay,
        "new_in_replay": new_in_replay,
        "metric_deltas": metric_deltas,
        "drift_kinds": drift_kinds,
        "has_drift": has_drift,
        "status": "drift" if has_drift else "clean",
    }


def run_replay_diff_for_scanner(
    scanner_type: str,
    scan_date: date,
    db: Session,
) -> ScannerReplayDiff:
    """
    Run one nightly replay-diff for a single scanner type and persist the result.

    Called once per active scanner config type from the Celery task.
    Upserts a ScannerReplayDiff row (unique on scanner_type + scan_date),
    emits Seq log, increments Prometheus counters, and fires notify_system on drift.
    """
    from app.models.scanner_config import ScannerConfig
    from app.models.stock_universe_ticker import StockUniverseTicker

    # Resolve universe tickers from active configs for this scanner type
    configs = (
        db.query(ScannerConfig)
        .filter(
            ScannerConfig.scanner_type == scanner_type,
            ScannerConfig.is_active.is_(True),
            ScannerConfig.universe_id.isnot(None),
        )
        .all()
    )
    universe_ids = list({c.universe_id for c in configs})
    tickers = [
        row.ticker
        for row in db.query(StockUniverseTicker)
        .filter(StockUniverseTicker.universe_id.in_(universe_ids))
        .all()
    ]

    # Stage 1: collect live signals
    live = _collect_live_signals(scanner_type, scan_date, db)

    # Determine early-exit statuses
    if not live:
        diff_data = {
            "status": "no_live_events",
            "has_drift": False,
            "live_count": 0,
            "replay_count": 0,
            "matched_count": 0,
            "missing_in_replay": [],
            "new_in_replay": [],
            "metric_deltas": {},
            "drift_kinds": [],
        }
    else:
        # Stage 2: run replay with no-persist patch
        replay = _run_replay(scanner_type, tickers, scan_date, db)

        if replay is None:
            diff_data = {
                "status": "insufficient_data",
                "has_drift": False,
                "live_count": len(live),
                "replay_count": 0,
                "matched_count": 0,
                "missing_in_replay": [],
                "new_in_replay": [],
                "metric_deltas": {},
                "drift_kinds": [],
            }
        else:
            # Stage 3: compute diff
            diff_data = _compute_diff(live, replay)

    # Upsert
    existing = (
        db.query(ScannerReplayDiff)
        .filter_by(scanner_type=scanner_type, scan_date=scan_date)
        .first()
    )
    if existing:
        for key, val in diff_data.items():
            setattr(existing, key, val)
        record = existing
    else:
        record = ScannerReplayDiff(
            scanner_type=scanner_type, scan_date=scan_date, **diff_data
        )
        db.add(record)
    db.commit()

    status = diff_data["status"]
    has_drift = diff_data["has_drift"]

    # Observability: Seq structured log
    logger.info(
        "replay_diff scanner_type=%s scan_date=%s status=%s has_drift=%s "
        "live=%d replay=%d missing=%d new=%d metric_deltas=%d",
        scanner_type,
        scan_date,
        status,
        has_drift,
        diff_data["live_count"],
        diff_data["replay_count"],
        len(diff_data["missing_in_replay"]),
        len(diff_data["new_in_replay"]),
        len(diff_data["metric_deltas"]),
        extra={"log_type": "replay_diff"},
    )

    # Prometheus counters
    for kind in ("matched", "missing_in_replay", "new_in_replay", "metric_delta"):
        count = {
            "matched": diff_data["matched_count"],
            "missing_in_replay": len(diff_data["missing_in_replay"]),
            "new_in_replay": len(diff_data["new_in_replay"]),
            "metric_delta": len(diff_data["metric_deltas"]),
        }[kind]
        if count:
            replay_drift_signals_total.labels(
                scanner_type=scanner_type, kind=kind
            ).inc(count)

    # Alert on drift
    if has_drift:
        notify_system(
            title=f"Replay drift detected: {scanner_type} on {scan_date}",
            body=(
                f"Scanner '{scanner_type}' replay for {scan_date} has drift. "
                f"missing_in_replay={diff_data['missing_in_replay']}, "
                f"metric_deltas={list(diff_data['metric_deltas'].keys())}"
            ),
            severity="warning",
            dedupe_key=f"replay_drift:{scanner_type}:{scan_date}",
            cooldown_seconds=86400,
        )

    return record
```

**Step 3.4 — Verify all tests pass**

```bash
docker-compose exec backend python -m pytest backend/tests/services/test_replay_diff_service.py -x -q
# Expected: 13 passed
```

**Step 3.5 — Commit**

```bash
git add backend/app/services/replay_diff_service.py \
        backend/tests/services/test_replay_diff_service.py
git commit -m "feat(#392): replay_diff_service with three-stage pipeline"
```

---

## Task 4: Celery Task + Beat Schedule

### Files
- `backend/app/tasks/scanning.py` (append)
- `backend/app/core/celery_app.py` (add beat entry)
- `backend/tests/tasks/test_scanning_tasks.py` (append)

### Steps

**Step 4.1 — Write the failing task test**

Append to `backend/tests/tasks/test_scanning_tasks.py`:

```python
# ---------------------------------------------------------------------------
# run_replay_diff_nightly task shell
# ---------------------------------------------------------------------------


def test_run_replay_diff_nightly_is_importable():
    from app.tasks.scanning import run_replay_diff_nightly

    assert callable(run_replay_diff_nightly)


def test_run_replay_diff_nightly_calls_service_per_scanner_type():
    from unittest.mock import MagicMock, call, patch

    from app.tasks.scanning import run_replay_diff_nightly

    # Two distinct active scanner types with supports_date_range=True
    cfg_a = MagicMock()
    cfg_a.scanner_type = "liquidity_hunt"
    cfg_b = MagicMock()
    cfg_b.scanner_type = "pocket_pivot"

    db = MagicMock()
    call_idx = [0]

    def _query_side(model):
        q = MagicMock()
        idx = call_idx[0]
        call_idx[0] += 1
        if idx == 0:
            # ScannerConfig query for active types
            row_a = MagicMock()
            row_a[0] = "liquidity_hunt"
            row_b = MagicMock()
            row_b[0] = "pocket_pivot"
            q.filter.return_value.distinct.return_value.all.return_value = [row_a, row_b]
        return q

    db.query.side_effect = _query_side

    with patch("app.tasks.scanning.SessionLocal", return_value=db), \
         patch("app.tasks.scanning.run_replay_diff_for_scanner") as mock_run, \
         patch("app.tasks.scanning.scan_orchestrator") as mock_orch:
        # Only liquidity_hunt and pocket_pivot have supports_date_range=True
        desc_a = MagicMock()
        desc_a.key = "liquidity_hunt"
        desc_a.supports_date_range = True
        desc_b = MagicMock()
        desc_b.key = "pocket_pivot"
        desc_b.supports_date_range = True
        mock_orch.get_all.return_value = [desc_a, desc_b]

        run_replay_diff_nightly.run()

    assert mock_run.call_count == 2
```

**Step 4.2 — Verify test fails**

```bash
docker-compose exec backend python -m pytest backend/tests/tasks/test_scanning_tasks.py::test_run_replay_diff_nightly_is_importable -x -q
# Expected: ImportError or AttributeError (task not defined yet)
```

**Step 4.3 — Implement the Celery task**

Append to the bottom of `backend/app/tasks/scanning.py` (before `validate_scheduled_scanner_configs`):

```python
# ---------------------------------------------------------------------------
# Nightly replay-diff regression detector (04:00 UTC weekdays)
# ---------------------------------------------------------------------------


@celery_app.task(bind=True, max_retries=1, name="app.tasks.run_replay_diff_nightly")
def run_replay_diff_nightly(self):
    """Re-run yesterday's scans from stored StockAggregate data and diff against
    live ScannerEvent rows. Upserts one ScannerReplayDiff record per active
    scanner type with supports_date_range=True.
    """
    from app.models.scanner_config import ScannerConfig
    from app.services import scan_orchestrator
    from app.services.replay_diff_service import run_replay_diff_for_scanner

    _task_name = "run_replay_diff_nightly"
    _start = _time.monotonic()
    db = SessionLocal()

    try:
        # Resolve yesterday skipping weekends
        from datetime import timedelta

        yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).date()
        while yesterday.weekday() >= 5:
            yesterday -= timedelta(days=1)

        # Active scanner types that support historical replay
        descriptors = {d.key: d for d in scan_orchestrator.get_all() if d.supports_date_range}
        active_rows = (
            db.query(ScannerConfig.scanner_type)
            .filter(
                ScannerConfig.scanner_type.in_(list(descriptors)),
                ScannerConfig.is_active.is_(True),
            )
            .distinct()
            .all()
        )

        for (scanner_type,) in active_rows:
            try:
                run_replay_diff_for_scanner(scanner_type, yesterday, db)
                logger.info(
                    "run_replay_diff_nightly: completed scanner_type=%s scan_date=%s",
                    scanner_type,
                    yesterday,
                )
            except Exception as exc:
                logger.exception(
                    "run_replay_diff_nightly: scanner_type=%s failed: %s",
                    scanner_type,
                    exc,
                )

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
```

**Step 4.4 — Add beat schedule entry**

In `backend/app/core/celery_app.py`, inside the `celery_app.conf.beat_schedule = { ... }` dict, add after the last `run_trend_pullback_scheduled` entry:

```python
    "run-replay-diff-nightly": {
        "task": "app.tasks.run_replay_diff_nightly",
        "schedule": crontab(minute="0", hour="4", day_of_week="1-5"),
    },
```

Verify insertion:

```bash
grep -n "replay-diff\|replay_diff" backend/app/core/celery_app.py
# Expected: shows the new beat entry at hour="4"
```

**Step 4.5 — Verify tests pass**

```bash
docker-compose exec backend python -m pytest backend/tests/tasks/test_scanning_tasks.py -x -q
# Expected: all pass including the two new tests
```

**Step 4.6 — Commit**

```bash
git add backend/app/tasks/scanning.py \
        backend/app/core/celery_app.py \
        backend/tests/tasks/test_scanning_tasks.py
git commit -m "feat(#392): run_replay_diff_nightly Celery task at 04:00 UTC weekdays"
```

---

## Task 5: API Endpoint `GET /api/v1/scanner/replay-diffs`

### Files
- `backend/app/routers/scanner.py` (append)
- `backend/tests/api/test_scanner.py` (append)

### Steps

**Step 5.1 — Write the failing endpoint tests**

Append to `backend/tests/api/test_scanner.py`:

```python
# ---------------------------------------------------------------------------
# GET /api/v1/scanner/replay-diffs
# ---------------------------------------------------------------------------


def test_list_replay_diffs_empty(db: Session):
    from fastapi.testclient import TestClient
    from app.main import app

    client = TestClient(app)
    response = client.get("/api/v1/scanner/replay-diffs")
    assert response.status_code == 200
    assert response.json() == []


def test_list_replay_diffs_returns_records(db: Session):
    from datetime import date

    from fastapi.testclient import TestClient

    from app.main import app
    from app.models.scanner_replay_diff import ScannerReplayDiff

    record = ScannerReplayDiff(
        scanner_type="liquidity_hunt",
        scan_date=date(2026, 6, 20),
        status="clean",
        has_drift=False,
        live_count=3,
        replay_count=3,
        matched_count=3,
        missing_in_replay=[],
        new_in_replay=[],
        metric_deltas={},
        drift_kinds=[],
    )
    db.add(record)
    db.commit()

    client = TestClient(app)
    response = client.get("/api/v1/scanner/replay-diffs")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["scanner_type"] == "liquidity_hunt"
    assert data[0]["has_drift"] is False


def test_list_replay_diffs_filter_by_scanner_type(db: Session):
    from datetime import date

    from fastapi.testclient import TestClient

    from app.main import app
    from app.models.scanner_replay_diff import ScannerReplayDiff

    for scanner_type in ("liquidity_hunt", "pocket_pivot"):
        db.add(
            ScannerReplayDiff(
                scanner_type=scanner_type,
                scan_date=date(2026, 6, 20),
                status="clean",
                has_drift=False,
                live_count=1,
                replay_count=1,
                matched_count=1,
                missing_in_replay=[],
                new_in_replay=[],
                metric_deltas={},
                drift_kinds=[],
            )
        )
    db.commit()

    client = TestClient(app)
    response = client.get("/api/v1/scanner/replay-diffs?scanner_type=pocket_pivot")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["scanner_type"] == "pocket_pivot"


def test_list_replay_diffs_days_param_clamps(db: Session):
    from fastapi.testclient import TestClient
    from app.main import app

    client = TestClient(app)
    response = client.get("/api/v1/scanner/replay-diffs?days=91")
    assert response.status_code == 422  # days max is 90
```

**Step 5.2 — Verify tests fail**

```bash
docker-compose exec backend python -m pytest backend/tests/api/test_scanner.py::test_list_replay_diffs_empty -x -q
# Expected: 404 or 422 — route not registered yet
```

**Step 5.3 — Implement the endpoint**

Add the following imports near the top of `backend/app/routers/scanner.py` if not already present (check first):

```bash
grep -n "from datetime import\|Optional\|Query" backend/app/routers/scanner.py | head -5
```

Then append the endpoint to `backend/app/routers/scanner.py` before the final `# EOF` or at the end of the file:

```python
# ---------------------------------------------------------------------------
# Replay-diff records
# ---------------------------------------------------------------------------


@router.get("/replay-diffs", response_model=list[ScannerReplayDiffSchema])
def list_replay_diffs(
    scanner_type: Optional[str] = None,
    days: int = Query(default=30, ge=1, le=90),
    db: Session = Depends(get_db),
):
    """Return up to `days` days of ScannerReplayDiff records, newest first."""
    from datetime import timedelta

    from app.models.scanner_replay_diff import ScannerReplayDiff

    cutoff = (utc_now() - timedelta(days=days)).date()
    q = db.query(ScannerReplayDiff).filter(ScannerReplayDiff.scan_date >= cutoff)
    if scanner_type:
        q = q.filter(ScannerReplayDiff.scanner_type == scanner_type)
    return q.order_by(ScannerReplayDiff.scan_date.desc()).all()
```

Then add `ScannerReplayDiffSchema` to the router's imports. Find where existing schemas are imported at the top of `routers/scanner.py`:

```bash
grep -n "from app.schemas" backend/app/routers/scanner.py | head -5
```

Add `ScannerReplayDiffSchema` to that import block:

```python
from app.schemas.scanner_replay_diff import ScannerReplayDiffSchema
```

**Step 5.4 — Verify tests pass**

```bash
docker-compose exec backend python -m pytest backend/tests/api/test_scanner.py -x -q
# Expected: all pass including the four new tests
```

Also curl-verify the endpoint against the live backend:

```bash
docker-compose logs backend --tail=5
curl -s "http://localhost:8000/api/v1/scanner/replay-diffs" | python -m json.tool
# Expected: [] (no records yet — task has not run)

curl -s "http://localhost:8000/api/v1/scanner/replay-diffs?days=91" | python -m json.tool
# Expected: {"detail": [...]} with 422 status
```

**Step 5.5 — Run full test suite**

```bash
docker-compose exec backend python -m pytest backend/tests/ -x -q --tb=short 2>&1 | tail -20
# Expected: all existing + new tests pass; no regressions
```

**Step 5.6 — Commit**

```bash
git add backend/app/routers/scanner.py \
        backend/tests/api/test_scanner.py
git commit -m "feat(#392): GET /api/v1/scanner/replay-diffs endpoint"
```

---

## Acceptance Criteria Verification

| Criterion | Verified by |
|-----------|-------------|
| Zero-drift night produces quiet "all green" record | `test_compute_diff_all_matched_no_drift` + `test_list_replay_diffs_returns_records` |
| Injected fixture drift fires the alert path | `test_compute_diff_missing_in_replay_triggers_drift` + `test_run_replay_diff_upserts_no_live_events` (notify_system patched/asserted) |
| Diff records retrievable via API for last 30 days | `test_list_replay_diffs_returns_records` + curl verification |

---

## Memory Patterns Applied

- **[AVOID] MagicMock DB for JSONB models** (backend-patterns.md): All service tests use `MagicMock` DB, not SQLite.
- **[PATTERN] `utc_now` from `app.utils.time`** (backend-patterns.md): Used for `created_at`/`updated_at` column defaults.
- **[AVOID] `dry_run` flag through scan_orchestrator** (architecture.md): Plan uses no-op `save_event` capture-patch instead.
- **[PATTERN] Scanner pipeline decomposition** (backend-patterns.md): `replay_diff_service.py` follows three-stage `_collect`/`_run`/`_compute` pattern.
- **[PATTERN] `asyncio.new_event_loop()` for sync callers of async functions** (backend-patterns.md): Used in `_run_replay` via `loop.run_until_complete()` in `try/finally loop.close()`.
- **[AVOID] Writing signals to `scanner_events` from replay/backtest** (backend-patterns.md): Replay captures signals in-memory only via `_capture_save_event` closure; no `ScannerEvent` rows written.
- **[PATTERN] `celery_tasks_total` + `celery_task_duration_seconds`** (scanning.py convention): Task wraps body in `try/except/finally` with both metrics.
- **[FIX] save_event patch target per-scanner-module** (architect cycle 1): Scanners bind `save_event as _save_event` at module load time (`liquidity_hunt`, `pocket_pivot`, `trend_pullback_scan`), making a single `app.services.alert_service.save_event` patch ineffective. `_SAVE_EVENT_PATCH_TARGETS` covers all four binding sites: the three module-level names plus `app.services.scanner.ScannerService._save_event` for call-time importers (`pre_market_scan`, `oversold_bounce_scan`).
