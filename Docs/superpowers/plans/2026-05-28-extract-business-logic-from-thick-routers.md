# Extract Business Logic from Thick Routers into Services

**Date:** 2026-05-28  
**Issue:** #96  
**Spec:** `Docs/superpowers/specs/2026-05-27-extract-business-logic-from-thick-routers-design.md`  
**Status:** Draft

---

## Goal

Extract non-trivial business logic from three oversized FastAPI routers into service modules. No API behaviour changes — identical HTTP contract before and after. Delivered as three independent PRs in risk order.

## Architecture

Pattern: each router becomes a thin HTTP adapter (request validation → service call → response formatting). Business logic moves to:
- `services/system_service.py` — new `SystemService` class (Phase 1)
- `services/scan_orchestrator.py` — extended with orchestration functions (Phase 2)
- `services/scanner_query_service.py` — new `ScannerQueryService` class (Phase 2)
- `services/auto_trade_service.py` — extended with router business logic (Phase 3)
- `schemas/auto_trade.py` — new Pydantic response models replacing ad-hoc serialisers (Phase 3)

## Tech Stack

FastAPI + SQLAlchemy (sync `Session`) + Redis + Celery + pytest/testcontainers

## File Structure

| Phase | New / Modified File | Purpose |
|-------|---------------------|---------|
| 1 | `backend/app/services/system_service.py` | New — SystemService class |
| 1 | `backend/tests/services/test_system_service.py` | New — unit tests |
| 1 | `backend/app/routers/system.py` | Modified — delegate to SystemService |
| 2 | `backend/app/services/scan_orchestrator.py` | Modified — add orchestration fns |
| 2 | `backend/app/services/scanner_query_service.py` | New — ScannerQueryService class |
| 2 | `backend/tests/services/test_scanner_query_service.py` | New — unit tests |
| 2 | `backend/tests/services/test_scan_orchestrator.py` | Modified — add new fn tests |
| 2 | `backend/app/routers/scanner.py` | Modified — delegate to services |
| 3 | `backend/app/schemas/auto_trade.py` | New — Pydantic response models |
| 3 | `backend/app/schemas/__init__.py` | Modified — export new models |
| 3 | `backend/app/services/auto_trade_service.py` | Modified — add 4 service methods |
| 3 | `backend/tests/services/test_auto_trade_service.py` | Modified — extend tests |
| 3 | `backend/app/routers/auto_trading.py` | Modified — delegate to services |

---

## Phase 1 — `system.py` → `system_service.py`

### Task 1.1 — Write failing tests for SystemService

**Files:** `backend/tests/services/test_system_service.py`

**TDD steps:**

1. Write the test file:

```python
"""Tests for SystemService."""
import socket
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import fakeredis.aioredis
import pytest

from app.services.system_service import SystemService


# ── get_market_status ──────────────────────────────────────────────────────
# SystemService.get_market_status() delegates to _now_et() for the current
# time, which is a module-level function we can monkeypatch cleanly.

@pytest.mark.parametrize("hour,minute,weekday,expected", [
    (3, 59, 0, "closed"),      # before pre-market on Monday
    (4, 0, 0, "pre_market"),   # 04:00 ET Monday
    (9, 29, 1, "pre_market"),  # 09:29 ET Tuesday
    (9, 30, 2, "open"),        # 09:30 ET Wednesday
    (15, 59, 3, "open"),       # 15:59 ET Thursday
    (16, 0, 4, "post_market"), # 16:00 ET Friday
    (19, 59, 4, "post_market"),# 19:59 ET Friday
    (20, 0, 4, "closed"),      # 20:00 ET Friday
    (12, 0, 5, "closed"),      # Saturday
    (12, 0, 6, "closed"),      # Sunday
])
def test_get_market_status(hour, minute, weekday, expected):
    fake_now = MagicMock()
    fake_now.weekday.return_value = weekday
    fake_now.hour = hour
    fake_now.minute = minute
    with patch("app.services.system_service._now_et", return_value=fake_now):
        result = SystemService.get_market_status()
    assert result == expected


# ── check_ibkr_reachable ──────────────────────────────────────────────────

def test_check_ibkr_reachable_returns_true_on_success():
    with patch("socket.create_connection") as mock_conn:
        mock_conn.return_value.__enter__ = MagicMock()
        mock_conn.return_value.__exit__ = MagicMock(return_value=False)
        mock_conn.return_value.close = MagicMock()
        assert SystemService.check_ibkr_reachable("127.0.0.1", 7497) is True


def test_check_ibkr_reachable_returns_false_on_oserror():
    with patch("socket.create_connection", side_effect=OSError("refused")):
        assert SystemService.check_ibkr_reachable("127.0.0.1", 7497) is False


# ── format_bytes ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("size,expected", [
    (0, "0.0 B"),
    (512, "512.0 B"),
    (1024, "1.0 KB"),
    (1024 * 1024, "1.0 MB"),
    (1024 ** 3, "1.0 GB"),
])
def test_format_bytes(size, expected):
    assert SystemService.format_bytes(size) == expected


# ── get_storage_stats ─────────────────────────────────────────────────────

def test_get_storage_stats_returns_dict(db):
    result = SystemService.get_storage_stats(db)
    assert "scanner" in result
    assert "historical" in result
    assert "settings" in result
    assert "total" in result
    assert "bytes" in result["total"]
    assert "formatted" in result["total"]


# ── get_active_tasks ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_active_tasks_empty_on_no_keys(db):
    redis_client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    tasks = await SystemService.get_active_tasks(redis_client, db)
    assert tasks == []


@pytest.mark.asyncio
async def test_get_active_tasks_skips_stale_sync_key(db):
    redis_client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    import json
    from datetime import timezone, timedelta
    old_ts = (datetime.now(timezone.utc) - timedelta(hours=5)).isoformat()
    await redis_client.set("universe:1:sync", json.dumps({
        "started_at": old_ts,
        "task_ids": ["abc"],
    }))
    tasks = await SystemService.get_active_tasks(redis_client, db)
    assert tasks == []
    # Key must be deleted after stale detection
    assert await redis_client.get("universe:1:sync") is None
```

2. Verify the tests fail (SystemService does not exist yet):

```bash
cd backend && python -m pytest tests/services/test_system_service.py -x 2>&1 | head -20
# Expected: ImportError or ModuleNotFoundError
```

**Commit:** `test(system_service): add failing unit tests for SystemService`

---

### Task 1.2 — Implement `system_service.py`

**Files:** `backend/app/services/system_service.py`

```python
"""SystemService — extracted business logic from routers/system.py."""

import json
import socket
from datetime import datetime, timezone, timedelta
import zoneinfo
from typing import Any

import redis.asyncio as aioredis
from sqlalchemy.orm import Session
from sqlalchemy import text

logger = __import__("logging").getLogger(__name__)

ET = zoneinfo.ZoneInfo("America/New_York")


def _now_et() -> datetime:
    """Return the current datetime in ET. Exists as a module-level function so tests can monkeypatch it."""
    return datetime.now(ET)


class SystemService:

    @staticmethod
    def get_market_status() -> str:
        now_et = _now_et()
        if now_et.weekday() >= 5:
            return "closed"
        t = now_et.hour * 60 + now_et.minute
        if 240 <= t < 570:
            return "pre_market"
        if 570 <= t < 960:
            return "open"
        if 960 <= t < 1200:
            return "post_market"
        return "closed"

    @staticmethod
    def check_ibkr_reachable(host: str, port: int, timeout: float = 2.0) -> bool:
        try:
            sock = socket.create_connection((host, port), timeout=timeout)
            sock.close()
            return True
        except OSError:
            return False

    @staticmethod
    def format_bytes(size: int) -> str:
        for unit in ["B", "KB", "MB", "GB", "TB"]:
            if size < 1024:
                return f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} PB"

    @staticmethod
    def get_storage_stats(db: Session) -> dict[str, Any]:
        table_groups = {
            "scanner": ["volume_events", "scanner_runs"],
            "historical": ["stock_aggregates", "stock_metrics", "ticker_references", "news_articles"],
            "settings": ["news_preferences", "scanner_configs"],
        }
        results: dict[str, Any] = {
            "scanner": {"bytes": 0, "formatted": "0.0 B"},
            "historical": {"bytes": 0, "formatted": "0.0 B"},
            "settings": {"bytes": 0, "formatted": "0.0 B"},
            "total": {"bytes": 0, "formatted": "0.0 B"},
        }
        try:
            dialect = db.bind.dialect.name
            if dialect == "postgresql":
                all_tables: list[str] = []
                for group in table_groups.values():
                    all_tables.extend(group)
                query = text("""
                    SELECT relname as table_name,
                           pg_total_relation_size(relid) as total_size
                    FROM pg_catalog.pg_statio_user_tables
                    WHERE relname = ANY(:tables)
                """)
                db_results = db.execute(query, {"tables": all_tables}).fetchall()
                table_sizes = {row.table_name: row.total_size for row in db_results}
                for group_name, tables in table_groups.items():
                    group_size = sum(table_sizes.get(t, 0) for t in tables)
                    results[group_name]["bytes"] = group_size
                    results[group_name]["formatted"] = SystemService.format_bytes(group_size)
                    results["total"]["bytes"] += group_size
            elif dialect == "sqlite":
                import os
                db_url = str(db.bind.url)
                db_path = db_url.replace("sqlite:///", "")
                total_size = os.path.getsize(db_path) if os.path.exists(db_path) else 0
                results["historical"]["bytes"] = total_size
                results["historical"]["formatted"] = f"{SystemService.format_bytes(total_size)} (SQLite)"
                results["total"]["bytes"] = total_size
            else:
                results["total"]["formatted"] = f"Unknown DB ({dialect})"
            # Unconditional overwrite preserves existing router behaviour (original system.py line 129
            # also overwrites the SQLite "(Full DB)" suffix). No behaviour change intended.
            results["total"]["formatted"] = SystemService.format_bytes(results["total"]["bytes"])
        except Exception as exc:
            logger.error(f"Error fetching storage stats: {exc}", exc_info=True)
            return {
                "scanner": {"bytes": 0, "formatted": "N/A"},
                "historical": {"bytes": 0, "formatted": "N/A"},
                "settings": {"bytes": 0, "formatted": "N/A"},
                "total": {"bytes": 0, "formatted": "Service Error"},
            }
        return results

    @staticmethod
    async def get_active_tasks(
        redis_client: aioredis.Redis,
        db: Session,
    ) -> list[dict]:
        from celery.result import AsyncResult
        from app.core.celery_app import celery_app
        from app.models.universe_quality_report import UniverseQualityReport
        from app.models.stock_universe import StockUniverse

        active_tasks: list[dict] = []

        async def _scan_pattern(pattern: str) -> list[str]:
            keys: list[str] = []
            cursor = "0"
            while True:
                cursor, batch = await redis_client.scan(cursor=cursor, match=pattern, count=100)
                keys.extend(batch)
                if str(cursor) == "0":
                    break
            return keys

        def _is_stale(data: dict) -> bool:
            ts_str = data.get("started_at")
            if not ts_str:
                return False
            try:
                started = datetime.fromisoformat(ts_str).replace(tzinfo=timezone.utc)
                return (datetime.now(timezone.utc) - started).total_seconds() / 3600 > 4
            except (ValueError, TypeError):
                return False

        def _has_pending_tasks(data: dict) -> bool:
            tids = data.get("task_ids") or []
            return any(
                AsyncResult(tid, app=celery_app).state in ("PENDING", "STARTED", "RETRY")
                for tid in tids
            )

        # universe:*:sync
        for key in await _scan_pattern("universe:*:sync"):
            parts = key.split(":")
            if len(parts) < 2 or not parts[1].isdigit():
                continue
            uid = int(parts[1])
            raw = await redis_client.get(key)
            if not raw:
                continue
            data = json.loads(raw)
            if _is_stale(data):
                await redis_client.delete(key)
                continue
            if not _has_pending_tasks(data):
                await redis_client.delete(key)
                continue
            universe = db.query(StockUniverse).filter(StockUniverse.id == uid).first()
            name = universe.name if universe else f"Universe {uid}"
            active_tasks.append({
                "id": f"sync_{uid}",
                "type": "sync",
                "title": f"Syncing Data: {name}",
                "status": "running",
            })

        # ticker:*:sync
        for key in await _scan_pattern("ticker:*:sync"):
            parts = key.split(":")
            if len(parts) < 2:
                continue
            ticker = parts[1]
            raw = await redis_client.get(key)
            if not raw:
                continue
            data = json.loads(raw)
            if _is_stale(data):
                await redis_client.delete(key)
                continue
            if not _has_pending_tasks(data):
                await redis_client.delete(key)
                continue
            active_tasks.append({
                "id": f"sync_ticker_{ticker}",
                "type": "sync",
                "title": f"Syncing Data: {ticker}",
                "status": "running",
            })

        # scan:*:range
        for key in await _scan_pattern("scan:*:range"):
            parts = key.split(":")
            ticker_name = parts[1] if len(parts) >= 2 else "?"
            raw = await redis_client.get(key)
            if not raw:
                continue
            data = json.loads(raw)
            if _is_stale(data):
                await redis_client.delete(key)
                continue
            if not _has_pending_tasks(data):
                await redis_client.delete(key)
                continue
            active_tasks.append({
                "id": f"scan_{ticker_name}",
                "type": "scan",
                "title": f"Range Scan: {ticker_name}",
                "status": "running",
            })

        # universe:*:scan:*
        for key in await _scan_pattern("universe:*:scan:*"):
            parts = key.split(":")
            if len(parts) < 4 or not parts[1].isdigit():
                continue
            uid = int(parts[1])
            scanner_type = parts[3]
            raw = await redis_client.get(key)
            if not raw:
                continue
            data = json.loads(raw)
            if _is_stale(data):
                await redis_client.delete(key)
                continue
            if not _has_pending_tasks(data):
                await redis_client.delete(key)
                continue
            universe = db.query(StockUniverse).filter(StockUniverse.id == uid).first()
            universe_name = universe.name if universe else f"Universe {uid}"
            day_idx = data.get("day_index", 0) if isinstance(data, dict) else 0
            total_days = data.get("total_days", 0) if isinstance(data, dict) else 0
            active_tasks.append({
                "id": f"scan_{uid}_{scanner_type}",
                "type": "scan",
                "title": (
                    f"Scanning {universe_name}: {scanner_type.replace('_', ' ')}"
                    + (f" — day {day_idx}/{total_days}" if total_days else "")
                ),
                "status": "running",
            })

        # DB: quality + normalization tasks
        stale_cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - __import__("datetime").timedelta(hours=4)
        quality_reports = db.query(UniverseQualityReport).filter(
            (UniverseQualityReport.status.in_(["pending", "running"])) |
            (UniverseQualityReport.normalization_status.in_(["pending", "running"]))
        ).all()

        for report in quality_reports:
            is_stale = report.started_at and report.started_at < stale_cutoff
            if is_stale:
                if report.status in ("pending", "running"):
                    report.status = "failed"
                if report.normalization_status in ("pending", "running"):
                    report.normalization_status = "failed"
                db.add(report)
                db.commit()
                continue
            universe = db.query(StockUniverse).filter(StockUniverse.id == report.universe_id).first()
            name = universe.name if universe else f"Universe {report.universe_id}"
            if report.status in ("pending", "running"):
                active_tasks.append({
                    "id": f"qa_{report.universe_id}",
                    "type": "analysis",
                    "title": f"Quality Analysis: {name}",
                    "status": report.status,
                })
            if report.normalization_status in ("pending", "running"):
                active_tasks.append({
                    "id": f"norm_{report.universe_id}",
                    "type": "normalization",
                    "title": f"Normalizing Data: {name}",
                    "status": report.normalization_status,
                })

        return active_tasks
```

**Verify tests pass:**
```bash
cd backend && python -m pytest tests/services/test_system_service.py -v
# Expected: all tests pass
```

**Commit:** `feat(system_service): implement SystemService with extracted router logic`

---

### Task 1.3 — Update `routers/system.py` to delegate to SystemService

**Files:** `backend/app/routers/system.py`

Replace the three private functions and inline logic:

1. Add import at the top (after existing imports):
```python
from app.services.system_service import SystemService
```

2. Delete the three private functions (`_market_status`, `_ibkr_reachable`, `format_bytes`) entirely from the router file.

3. Update `get_storage_stats` to delegate:
```python
@router.get("/storage")
def get_storage_stats(db: Session = Depends(get_db)):
    return SystemService.get_storage_stats(db)
```

4. Update `get_system_status` to use `SystemService`:
```python
@router.get("/status")
def get_system_status(db: Session = Depends(get_db)):
    from app.core.config import settings
    from app.models.scanner_run import ScannerRun

    last_run = db.query(ScannerRun).order_by(ScannerRun.created_at.desc()).first()
    last_scan_at = None
    if last_run and last_run.created_at:
        ts = last_run.created_at
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        last_scan_at = ts.isoformat()

    ibkr_host = getattr(settings, "IBKR_HOST", "127.0.0.1")
    ibkr_port = int(getattr(settings, "IBKR_PORT", 7497))

    return {
        "market_status": SystemService.get_market_status(),
        "last_scan_at": last_scan_at,
        "ibkr_reachable": SystemService.check_ibkr_reachable(ibkr_host, ibkr_port),
        "ibkr_host": ibkr_host,
        "ibkr_port": ibkr_port,
    }
```

5. Update `system_tasks_websocket` to delegate the polling block:
```python
@router.websocket("/ws/tasks")
async def system_tasks_websocket(websocket: WebSocket):
    from app.core.config import settings
    from app.core.database import SessionLocal
    await websocket.accept()
    redis_client = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
    try:
        while True:
            db = SessionLocal()
            try:
                tasks = await SystemService.get_active_tasks(redis_client, db)
            finally:
                db.close()
            await websocket.send_json({"tasks": tasks})
            await asyncio.sleep(2.5)
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.error(f"System tasks websocket error: {e}")
    finally:
        await redis_client.close()
```

6. Remove unused imports from router: `json`, `socket`, `zoneinfo` (keep `asyncio`, `aioredis`, `datetime/timezone`).

**Verify backend reloads cleanly:**
```bash
docker-compose logs backend --tail=20
# Expected: no import errors
curl -s http://localhost:8000/api/system/status | python -m json.tool
# Expected: market_status, ibkr_reachable keys present
curl -s http://localhost:8000/api/system/storage | python -m json.tool
# Expected: scanner, historical, settings, total keys present
```

**Commit:** `refactor(system): delegate router logic to SystemService (Phase 1)`

---

## Phase 2 — `scanner.py` → `scan_orchestrator.py` + `scanner_query_service.py`

### Task 2.1 — Write failing tests for `scan_orchestrator` extensions

**Files:** `backend/tests/services/test_scan_orchestrator.py` (extend existing file)

Append these tests to the existing file:

```python
# ── New orchestration functions ────────────────────────────────────────────

import fakeredis
from datetime import timezone as _tz

from app.services.scan_orchestrator import (
    compute_next_run,
    get_scan_progress,
    request_scan_cancel,
)


def test_compute_next_run_returns_none_for_non_scheduled():
    assert compute_next_run("pre_market_volume_spike") is None


def test_compute_next_run_returns_future_weekday_for_liquidity_hunt():
    result = compute_next_run("liquidity_hunt")
    assert result is not None
    from datetime import datetime, timezone
    assert result > datetime.now(timezone.utc)
    assert result.weekday() < 5  # not weekend


def test_compute_next_run_returns_none_for_pre_variant():
    result = compute_next_run("liquidity_hunt_pre")
    assert result is not None


def test_get_scan_progress_returns_none_when_no_key():
    server = fakeredis.FakeRedis(decode_responses=True)
    # Patch the aliased _redis module inside scan_orchestrator, not the global redis namespace
    with __import__("unittest.mock", fromlist=["patch"]).patch(
        "app.services.scan_orchestrator._redis.Redis.from_url", return_value=server
    ):
        result = get_scan_progress("redis://localhost", universe_id=1, scanner_type="liquidity_hunt")
    assert result is None


def test_request_scan_cancel_sets_redis_key():
    server = fakeredis.FakeRedis(decode_responses=True)
    with __import__("unittest.mock", fromlist=["patch"]).patch(
        "app.services.scan_orchestrator._redis.Redis.from_url", return_value=server
    ):
        request_scan_cancel("redis://localhost", "test-scan-uuid")
        assert server.get("scan_cancel:test-scan-uuid") == "1"
```

**Verify they fail:**
```bash
cd backend && python -m pytest tests/services/test_scan_orchestrator.py -x 2>&1 | tail -10
# Expected: ImportError for compute_next_run, get_scan_progress, request_scan_cancel
```

**Commit:** `test(scan_orchestrator): add failing tests for new orchestration functions`

---

### Task 2.2 — Extend `scan_orchestrator.py` with orchestration functions

**Files:** `backend/app/services/scan_orchestrator.py`

Replace the top-level imports block of the existing file with the following merged block (the original file only imports `from typing import Any, Awaitable, Callable, Optional`, `from dataclasses import dataclass`, `from datetime import date`, and custom types — append the new imports below the existing ones, before the `_REGISTRY` definition):

```python
# -- Add after existing imports --
import json
import uuid as _uuid
from datetime import datetime, timezone, timedelta
from typing import Optional, Tuple

import redis as _redis
from sqlalchemy.orm import Session
```

Then append the following functions after the existing `run` function:

```python
def compute_next_run(scanner_type: str) -> Optional[datetime]:
    """Return next scheduled fire time, or None if scanner_type is not scheduled."""
    if scanner_type not in {"liquidity_hunt", "liquidity_hunt_pre", "liquidity_hunt_post"}:
        return None
    now = datetime.now(timezone.utc)
    candidate = now.replace(minute=0, second=0, microsecond=0, hour=2)
    if candidate <= now:
        candidate += timedelta(days=1)
    while candidate.weekday() >= 5:
        candidate += timedelta(days=1)
    return candidate


def get_scan_progress(
    redis_url: str,
    universe_id: int,
    scanner_type: str,
) -> Optional[dict]:
    """Return the Redis progress payload for an in-flight scan, or None."""
    try:
        r = _redis.Redis.from_url(redis_url, decode_responses=True)
        state = r.get(f"universe:{universe_id}:scan:{scanner_type}")
        return json.loads(state) if state else None
    except Exception:
        return None


def request_scan_cancel(redis_url: str, scan_id: str) -> None:
    """Set the Redis cancel flag that the worker polls at each day boundary."""
    r = _redis.Redis.from_url(redis_url, decode_responses=True)
    r.set(f"scan_cancel:{scan_id}", "1", ex=3600)


def enqueue_scan(db: Session, request: Any) -> Tuple["ScannerRun", "AsyncResult"]:
    """Create a ScannerRun row and dispatch the Celery task.

    Returns (scanner_run, async_result).
    Raises ValueError if universe has no active tickers.
    The concurrency guard (check_concurrency / 409) stays in the router because
    it raises HTTPException — a FastAPI concern that does not belong in the service layer.
    """
    from app.tasks import run_universe_scan
    from app.models.scanner_run import ScannerRun
    from app.services.scanner import ScannerService

    start_date, end_date = ScannerService.resolve_date_range(
        request.start_date, request.end_date
    )
    ticker_count = ScannerService.count_active_tickers(db, request.universe_id)
    if ticker_count == 0:
        raise ValueError("No tickers found in the selected universe")

    scan_id = str(_uuid.uuid4())
    scanner_run = ScannerRun(
        uuid=_uuid.UUID(scan_id),
        scanner_type=request.scanner_type,
        universe_id=request.universe_id,
        status="queued",
        stocks_scanned=ticker_count,
        scan_start_date=start_date,
        scan_end_date=end_date,
    )
    db.add(scanner_run)
    db.commit()
    db.refresh(scanner_run)

    async_result = run_universe_scan.delay(
        scan_id=scan_id,
        scanner_type=request.scanner_type,
        universe_id=request.universe_id,
        start_date_iso=start_date.isoformat(),
        end_date_iso=end_date.isoformat(),
    )

    scanner_run.celery_task_id = async_result.id
    db.commit()
    return scanner_run, async_result
```

**Verify tests pass:**
```bash
cd backend && python -m pytest tests/services/test_scan_orchestrator.py -v
# Expected: all tests pass
```

**Commit:** `feat(scan_orchestrator): add compute_next_run, get_scan_progress, request_scan_cancel, enqueue_scan`

---

### Task 2.3 — Write failing tests for `ScannerQueryService`

**Files:** `backend/tests/services/test_scanner_query_service.py`

```python
"""Tests for ScannerQueryService."""
import pytest
from datetime import date, timezone, datetime

from app.models.scanner_run import ScannerRun
from app.models.scanner_event import ScannerEvent
from app.models.signal_review import SignalReview
from app.models.scanner_outcome_summary import ScannerOutcomeSummary
from app.services.scanner_query_service import ScannerQueryService


@pytest.fixture
def seeded_runs(db):
    runs = [
        ScannerRun(
            scanner_type="liquidity_hunt",
            universe_id=1,
            status="completed",
            stocks_scanned=10,
            events_detected=5,
            execution_time_ms=1000,
        ),
        ScannerRun(
            scanner_type="liquidity_hunt",
            universe_id=1,
            status="failed",
            stocks_scanned=10,
            events_detected=0,
            execution_time_ms=500,
        ),
    ]
    for r in runs:
        db.add(r)
    db.flush()
    return runs


@pytest.fixture
def seeded_events(db):
    events = []
    for i in range(5):
        e = ScannerEvent(
            ticker=f"SYM{i}",
            scanner_type="liquidity_hunt",
            event_date=date(2026, 5, 1),
            signal_quality_score=i * 0.2,
        )
        db.add(e)
        db.flush()
        summary = ScannerOutcomeSummary(
            scanner_event_id=e.id,
            reference_price=100.0,  # NOT NULL in model
            eod_pct_change=float(i),
            follow_through=bool(i % 2),
        )
        db.add(summary)
        events.append(e)
    db.flush()
    return events


# ── get_scan_status_block ──────────────────────────────────────────────────

def test_get_scan_status_block_returns_expected_keys(db, seeded_runs):
    result = ScannerQueryService.get_scan_status_block(db, "liquidity_hunt", universe_id=1)
    assert "last_run" in result
    assert "success_rate" in result
    assert "sparkline" in result
    assert "total_events" in result
    assert "next_run" in result
    assert result["success_rate"] == 50.0  # 1 completed out of 2


def test_get_scan_status_block_no_runs_returns_nones(db):
    result = ScannerQueryService.get_scan_status_block(db, "no_such_scanner")
    assert result["last_run"] is None
    assert result["success_rate"] is None
    assert result["sparkline"] == []


# ── get_signal_quality_distribution ────────────────────────────────────────

def test_get_signal_quality_distribution_returns_10_deciles(db, seeded_events):
    result = ScannerQueryService.get_signal_quality_distribution(db, scanner_type=None)
    assert len(result["deciles"]) == 10
    assert "signal_ranker_version" in result


def test_get_signal_quality_distribution_filters_by_type(db, seeded_events):
    result = ScannerQueryService.get_signal_quality_distribution(
        db, scanner_type="liquidity_hunt"
    )
    populated = [d for d in result["deciles"] if d["count"] > 0]
    assert len(populated) > 0


# ── get_review_stats ───────────────────────────────────────────────────────

def test_get_review_stats_returns_expected_shape(db, seeded_events):
    event = seeded_events[0]
    review = SignalReview(
        scanner_event_id=event.id,
        verdict="confirmed",
    )
    db.add(review)
    db.flush()
    result = ScannerQueryService.get_review_stats(db, scanner_type="liquidity_hunt")
    assert "total_events" in result
    assert "reviewed_count" in result
    assert "acceptance_rate" in result
    assert isinstance(result["by_scanner_type"], list)
    assert isinstance(result["top_rejection_reasons"], list)
```

**Verify they fail:**
```bash
cd backend && python -m pytest tests/services/test_scanner_query_service.py -x 2>&1 | head -15
# Expected: ImportError for ScannerQueryService
```

**Commit:** `test(scanner_query_service): add failing tests for ScannerQueryService`

---

### Task 2.4 — Implement `scanner_query_service.py`

**Files:** `backend/app/services/scanner_query_service.py`

```python
"""ScannerQueryService — DB aggregation queries extracted from routers/scanner.py."""

from datetime import timezone
from typing import Any, Optional

import sqlalchemy as sa
from sqlalchemy.orm import Session
from sqlalchemy import func, distinct

from app.models import ScannerEvent, ScannerRun, MonitoredStock
from app.models.scanner_outcome_summary import ScannerOutcomeSummary
from app.models.signal_review import SignalReview
from app.models.system_config import SystemConfig
from app.services.scan_orchestrator import compute_next_run


class ScannerQueryService:

    @staticmethod
    def get_scan_status_block(
        db: Session,
        scanner_type: str,
        universe_id: Optional[int] = None,
    ) -> dict[str, Any]:
        base_q = db.query(ScannerRun).filter(ScannerRun.scanner_type == scanner_type)
        if universe_id is not None:
            base_q = base_q.filter(ScannerRun.universe_id == universe_id)

        last_run_record = base_q.order_by(ScannerRun.created_at.desc()).first()
        last_run_info = None
        if last_run_record is not None:
            ts = last_run_record.created_at
            if ts is not None and ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            last_run_info = {
                "timestamp": ts,
                "status": last_run_record.status,
                "events_detected": last_run_record.events_detected or 0,
                "duration_ms": last_run_record.execution_time_ms or 0,
            }

        recent_20 = base_q.order_by(ScannerRun.created_at.desc()).limit(20).all()
        success_rate = None
        avg_events = None
        if recent_20:
            completed = [r for r in recent_20 if r.status == "completed"]
            success_rate = round(len(completed) / len(recent_20) * 100, 1)
            if completed:
                avg_events = round(
                    sum(r.events_detected or 0 for r in completed) / len(completed), 1
                )

        sparkline_rows = base_q.order_by(ScannerRun.created_at.desc()).limit(10).all()
        sparkline = [
            {
                "created_at": (
                    r.created_at.replace(tzinfo=timezone.utc).isoformat()
                    if r.created_at and r.created_at.tzinfo is None
                    else r.created_at.isoformat() if r.created_at else None
                ),
                "events_detected": r.events_detected or 0,
                "status": r.status,
            }
            for r in reversed(sparkline_rows)
        ]

        type_variants = [scanner_type]
        if scanner_type == "liquidity_hunt":
            type_variants = ["liquidity_hunt", "liquidity_hunt_pre", "liquidity_hunt_post"]

        event_q = db.query(func.count(ScannerEvent.id)).filter(
            ScannerEvent.scanner_type.in_(type_variants)
        )
        if universe_id is not None:
            event_q = event_q.join(
                MonitoredStock,
                sa.and_(
                    ScannerEvent.ticker == MonitoredStock.ticker,
                    MonitoredStock.universe_id == universe_id,
                    MonitoredStock.is_active.is_(True),
                ),
            )
        total_events: int = event_q.scalar() or 0

        return {
            "scanner_type": scanner_type,
            "universe_id": universe_id,
            "last_run": last_run_info,
            "next_run": compute_next_run(scanner_type),
            "total_events": total_events,
            "success_rate": success_rate,
            "avg_events_per_scan": avg_events,
            "sparkline": sparkline,
        }

    @staticmethod
    def get_signal_quality_distribution(
        db: Session,
        scanner_type: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> dict[str, Any]:
        ranker_version_row = db.query(SystemConfig).filter(
            SystemConfig.key == "signal_ranker_version"
        ).first()
        version = ranker_version_row.value if ranker_version_row else "unknown"

        query = (
            db.query(
                ScannerEvent.signal_quality_score,
                ScannerOutcomeSummary.eod_pct_change,
                ScannerOutcomeSummary.follow_through,
            )
            .join(ScannerOutcomeSummary, ScannerOutcomeSummary.scanner_event_id == ScannerEvent.id)
            .filter(ScannerEvent.signal_quality_score.isnot(None))
        )
        if scanner_type:
            query = query.filter(ScannerEvent.scanner_type == scanner_type)
        if start_date:
            query = query.filter(ScannerEvent.event_date >= start_date)
        if end_date:
            query = query.filter(ScannerEvent.event_date <= end_date)

        rows = query.all()
        buckets: dict[str, dict] = {
            f"{i/10:.1f}-{(i+1)/10:.1f}": {"count": 0, "eod_sum": 0.0, "ft_sum": 0, "eod_count": 0, "ft_count": 0}
            for i in range(10)
        }
        for score, eod_pct, follow_through in rows:
            idx = min(int(float(score) * 10), 9)
            label = f"{idx/10:.1f}-{(idx+1)/10:.1f}"
            b = buckets[label]
            b["count"] += 1
            if eod_pct is not None:
                b["eod_sum"] += float(eod_pct)
                b["eod_count"] += 1
            if follow_through is not None:
                b["ft_sum"] += int(follow_through)
                b["ft_count"] += 1

        deciles = [
            {
                "decile": label,
                "count": b["count"],
                "avg_eod_pct": round(b["eod_sum"] / b["eod_count"], 3) if b["eod_count"] > 0 else None,
                "follow_through_rate": round(b["ft_sum"] / b["ft_count"], 3) if b["ft_count"] > 0 else None,
            }
            for label, b in buckets.items()
        ]
        return {"deciles": deciles, "signal_ranker_version": version}

    @staticmethod
    def get_review_stats(
        db: Session,
        scanner_type: Optional[str] = None,
        start_date=None,
        end_date=None,
    ) -> dict[str, Any]:
        event_q = db.query(func.count(ScannerEvent.id))
        review_q = db.query(SignalReview).join(ScannerEvent, SignalReview.scanner_event_id == ScannerEvent.id)

        if scanner_type:
            if scanner_type == "liquidity_hunt":
                variants = ["liquidity_hunt", "liquidity_hunt_pre", "liquidity_hunt_post"]
                event_q = event_q.filter(ScannerEvent.scanner_type.in_(variants))
                review_q = review_q.filter(ScannerEvent.scanner_type.in_(variants))
            else:
                event_q = event_q.filter(ScannerEvent.scanner_type == scanner_type)
                review_q = review_q.filter(ScannerEvent.scanner_type == scanner_type)
        if start_date:
            event_q = event_q.filter(ScannerEvent.event_date >= start_date)
            review_q = review_q.filter(ScannerEvent.event_date >= start_date)
        if end_date:
            event_q = event_q.filter(ScannerEvent.event_date <= end_date)
            review_q = review_q.filter(ScannerEvent.event_date <= end_date)

        total_events = event_q.scalar() or 0
        reviewed_count = (
            review_q.with_entities(func.count(distinct(SignalReview.scanner_event_id))).scalar() or 0
        )
        confirmed_count = review_q.filter(SignalReview.verdict == "confirmed").count()
        rejected_count = review_q.filter(SignalReview.verdict == "rejected").count()
        denominator = confirmed_count + rejected_count
        acceptance_rate = round(confirmed_count / denominator, 3) if denominator > 0 else 0.0

        by_type_rows = (
            review_q.with_entities(
                ScannerEvent.scanner_type,
                SignalReview.verdict,
                func.count(SignalReview.id),
            )
            .group_by(ScannerEvent.scanner_type, SignalReview.verdict)
            .all()
        )
        type_map: dict = {}
        for stype, v, cnt in by_type_rows:
            if stype not in type_map:
                type_map[stype] = {"scanner_type": stype, "total": 0, "confirmed": 0, "rejected": 0, "uncertain": 0, "enhanced": 0}
            type_map[stype]["total"] += cnt
            if v in type_map[stype]:
                type_map[stype][v] += cnt

        reason_rows = (
            review_q.filter(SignalReview.reject_reason.isnot(None))
            .with_entities(SignalReview.reject_reason, func.count(SignalReview.id))
            .group_by(SignalReview.reject_reason)
            .order_by(func.count(SignalReview.id).desc())
            .limit(5)
            .all()
        )

        return {
            "total_events": total_events,
            "reviewed_count": reviewed_count,
            "acceptance_rate": acceptance_rate,
            "by_scanner_type": list(type_map.values()),
            "top_rejection_reasons": [{"reason": r, "count": c} for r, c in reason_rows],
        }
```

**Verify tests pass:**
```bash
cd backend && python -m pytest tests/services/test_scanner_query_service.py -v
# Expected: all tests pass
```

**Commit:** `feat(scanner_query_service): implement ScannerQueryService`

---

### Task 2.5 — Update `routers/scanner.py` to delegate to services

**Files:** `backend/app/routers/scanner.py`

1. Add imports at the top:
```python
from app.services.scan_orchestrator import (
    compute_next_run, get_scan_progress, request_scan_cancel, enqueue_scan
)
from app.services.scanner_query_service import ScannerQueryService
```

2. Replace `run_scanner` body:
```python
@router.post("/run", response_model=ScannerRunAsyncResponse, status_code=202)
def run_scanner(request: ScannerRunRequest, db: Session = Depends(get_db)):
    from app.core.config import settings as _settings
    from app.services.scanner import ScannerService

    if not request.universe_id:
        raise HTTPException(status_code=400, detail="universe_id is required")

    in_flight = ScannerService.check_concurrency(
        _settings.REDIS_URL, request.universe_id, request.scanner_type
    )
    if in_flight:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "A scan is already running for this universe and scanner type",
                "scan_id": in_flight.get("scan_id"),
                "task_id": (in_flight.get("task_ids") or [None])[0],
                "started_at": in_flight.get("started_at"),
            },
        )

    try:
        scanner_run, async_result = enqueue_scan(db, request)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    started_at = scanner_run.created_at
    if started_at and started_at.tzinfo is None:
        started_at = started_at.replace(tzinfo=timezone.utc)

    return ScannerRunAsyncResponse(
        scan_id=str(scanner_run.uuid),
        task_id=async_result.id,
        started_at=started_at,
        scanner_type=request.scanner_type,
        universe_id=request.universe_id,
        scan_start_date=scanner_run.scan_start_date,
        scan_end_date=scanner_run.scan_end_date,
        status="queued",
    )
```

3. Replace `get_scan_status` body — remove inline Redis block, use `get_scan_progress`:
```python
@router.get("/runs/{scan_id}/status", response_model=ScannerRunStatusResponse)
def get_scan_status(scan_id: str, db: Session = Depends(get_db)):
    from app.core.config import settings as _settings
    try:
        scan_uuid = uuid.UUID(scan_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="invalid scan_id")
    run = db.query(ScannerRun).filter(ScannerRun.uuid == scan_uuid).first()
    if run is None:
        raise HTTPException(status_code=404, detail="scan not found")

    progress = None
    if run.status in ("queued", "running"):
        progress = get_scan_progress(_settings.REDIS_URL, run.universe_id, run.scanner_type)

    started_at = run.created_at
    if started_at and started_at.tzinfo is None:
        started_at = started_at.replace(tzinfo=timezone.utc)

    return ScannerRunStatusResponse(
        scan_id=str(run.uuid),
        task_id=run.celery_task_id,
        status=run.status,
        scanner_type=run.scanner_type,
        universe_id=run.universe_id,
        scan_start_date=run.scan_start_date,
        scan_end_date=run.scan_end_date,
        stocks_scanned=run.stocks_scanned or 0,
        events_detected=run.events_detected or 0,
        execution_time_ms=run.execution_time_ms or 0,
        error_message=run.error_message,
        started_at=started_at,
        progress=progress,
    )
```

4. Replace `cancel_scan` body — remove inline Redis block, use `request_scan_cancel`:
```python
@router.post("/runs/{scan_id}/cancel")
def cancel_scan(scan_id: str, db: Session = Depends(get_db)):
    from app.core.config import settings as _settings
    try:
        scan_uuid = uuid.UUID(scan_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="invalid scan_id")
    run = db.query(ScannerRun).filter(ScannerRun.uuid == scan_uuid).first()
    if run is None:
        raise HTTPException(status_code=404, detail="scan not found")
    if run.status not in ("queued", "running"):
        raise HTTPException(status_code=409, detail=f"scan is {run.status}, not cancellable")
    request_scan_cancel(_settings.REDIS_URL, scan_id)
    return {"status": "cancel_requested", "scan_id": scan_id}
```

5. Delete the private `_compute_next_run` function. Replace `get_scan_status_block` with delegation:
```python
@router.get("/scan-status-block", response_model=ScannerStatusBlockResponse)
def get_scan_status_block(
    scanner_type: str,
    universe_id: Optional[int] = None,
    db: Session = Depends(get_db),
):
    data = ScannerQueryService.get_scan_status_block(db, scanner_type, universe_id)
    return ScannerStatusBlockResponse(**data)
```

6. Replace `get_signal_quality_distribution` with delegation:
```python
@router.get("/signal-quality-distribution")
def get_signal_quality_distribution(
    scanner_type: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    db: Session = Depends(get_db),
):
    return ScannerQueryService.get_signal_quality_distribution(db, scanner_type, start_date, end_date)
```

7. Replace `get_review_stats` with delegation:
```python
@router.get("/reviews/stats", response_model=SignalReviewStatsResponse)
def get_review_stats(
    scanner_type: Optional[str] = Query(None),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    db: Session = Depends(get_db),
):
    data = ScannerQueryService.get_review_stats(db, scanner_type, start_date, end_date)
    return SignalReviewStatsResponse(**data)
```

8. Remove unused imports from the router: the inline `import json`, `import redis as _redis`, `from datetime import timedelta`, `from sqlalchemy import func, case, cast as sa_cast`, `from sqlalchemy.types import Float as SAFloat`.

**Verify backend and endpoints:**
```bash
docker-compose logs backend --tail=20
curl -s "http://localhost:8000/api/scanner/scan-status-block?scanner_type=liquidity_hunt" | python -m json.tool
curl -s "http://localhost:8000/api/scanner/signal-quality-distribution" | python -m json.tool
curl -s "http://localhost:8000/api/scanner/reviews/stats?scanner_type=liquidity_hunt" | python -m json.tool
```

**Commit:** `refactor(scanner): delegate router logic to scan_orchestrator and ScannerQueryService (Phase 2)`

---

## Phase 3 — `auto_trading.py` → `auto_trade_service.py` + `schemas/auto_trade.py`

### Task 3.1 — Write failing tests for new auto_trade service methods

**Files:** `backend/tests/services/test_auto_trade_service.py` (extend existing)

Append to the existing test file:

```python
# ── New service method tests ───────────────────────────────────────────────

import pytest
from datetime import date
from unittest.mock import patch, MagicMock
from decimal import Decimal

from app.models.auto_trade_order import AutoTradeOrder
from app.models.trading_strategy import TradingStrategy
from app.services.auto_trade_service import (
    approve_order,
    cancel_order,
    get_account_summary,
    get_trading_stats,
)


@pytest.fixture
def paper_strategy(db):
    s = TradingStrategy(
        name="Paper S",
        paper_mode=True,
        requires_approval=True,
        is_active=True,
        direction="long_only",
        max_trades_per_day=5,
        max_concurrent_positions=3,
        stop_pct=Decimal("2.0"),
        risk_per_trade_pct=Decimal("1.0"),
        risk_reward_ratio=Decimal("2.0"),
        allowed_sessions=["regular"],
    )
    db.add(s)
    db.flush()
    return s


@pytest.fixture
def pending_approval_order(db, paper_strategy):
    o = AutoTradeOrder(
        symbol="AAPL",
        side="long",
        status="pending_approval",
        event_date=date.today(),
        trading_strategy_id=paper_strategy.id,
        is_paper=True,
    )
    db.add(o)
    db.flush()
    return o


# ── approve_order ──────────────────────────────────────────────────────────

def test_approve_order_paper_sets_submitted(db, pending_approval_order):
    updated = approve_order(pending_approval_order.id, db)
    assert updated.status == "submitted"
    assert updated.broker_order_id.startswith("PAPER-")


def test_approve_order_raises_404_for_unknown_id(db):
    with pytest.raises(Exception) as exc_info:
        approve_order(999999, db)
    assert "404" in str(exc_info.value) or "not found" in str(exc_info.value).lower()


def test_approve_order_raises_409_if_not_pending(db, pending_approval_order, paper_strategy):
    o = pending_approval_order
    o.status = "submitted"
    db.flush()
    with pytest.raises(Exception) as exc_info:
        approve_order(o.id, db)
    assert "409" in str(exc_info.value) or "pending" in str(exc_info.value).lower()


# ── cancel_order ───────────────────────────────────────────────────────────

def test_cancel_order_paper_sets_cancelled(db, paper_strategy):
    o = AutoTradeOrder(
        symbol="TSLA",
        side="long",
        status="submitted",
        event_date=date.today(),
        trading_strategy_id=paper_strategy.id,
        is_paper=True,
        broker_order_id="PAPER-42",
    )
    db.add(o)
    db.flush()
    updated = cancel_order(o.id, db)
    assert updated.status == "cancelled"


def test_cancel_order_raises_409_for_closed_order(db, paper_strategy):
    o = AutoTradeOrder(
        symbol="TSLA",
        side="long",
        status="closed",
        event_date=date.today(),
        trading_strategy_id=paper_strategy.id,
        is_paper=True,
    )
    db.add(o)
    db.flush()
    with pytest.raises(Exception) as exc_info:
        cancel_order(o.id, db)
    assert "409" in str(exc_info.value) or "cannot" in str(exc_info.value).lower()


# ── get_trading_stats ──────────────────────────────────────────────────────

def test_get_trading_stats_returns_expected_shape(db, paper_strategy):
    o = AutoTradeOrder(
        symbol="GOOG",
        side="long",
        status="closed",
        event_date=date.today(),
        trading_strategy_id=paper_strategy.id,
        is_paper=True,
        fill_price=Decimal("100.0"),
        exit_price=Decimal("105.0"),
    )
    db.add(o)
    db.flush()
    result = get_trading_stats(30, db)
    assert "total_orders" in result
    assert "by_status" in result
    assert "win_rate" in result
    assert "total_pnl" in result


# ── get_account_summary ────────────────────────────────────────────────────

def test_get_account_summary_returns_connected_false_on_ibkr_error(db):
    # IBKROrderManager is imported locally inside get_account_summary so we patch the source module
    with patch("app.providers.ibkr_orders.IBKROrderManager", side_effect=Exception("offline")):
        result = get_account_summary(db)
    assert result["connected"] is False
    assert "error" in result
```

**Verify they fail:**
```bash
cd backend && python -m pytest tests/services/test_auto_trade_service.py -k "approve_order or cancel_order or get_account_summary or get_trading_stats" -x 2>&1 | tail -15
# Expected: ImportError for the four new functions
```

**Commit:** `test(auto_trade_service): add failing tests for approve_order, cancel_order, get_account_summary, get_trading_stats`

---

### Task 3.2 — Implement new service methods in `auto_trade_service.py`

**Files:** `backend/app/services/auto_trade_service.py`

Append the following module-level functions after the existing `AutoTradeExecutor` class. These are free functions (not class methods) matching the service extraction pattern used in `universe_orchestrator.py`:

```python
# ── Service functions extracted from routers/auto_trading.py ───────────────

from fastapi import HTTPException
from app.models.trading_strategy import TradingStrategy
from app.models.trade import Trade


def approve_order(order_id: int, db: Session) -> AutoTradeOrder:
    """Approve a pending_approval order and dispatch it (paper or live)."""
    o = db.query(AutoTradeOrder).filter(AutoTradeOrder.id == order_id).first()
    if not o:
        raise HTTPException(status_code=404, detail="Order not found.")
    if o.status != "pending_approval":
        raise HTTPException(
            status_code=409,
            detail=f"Order is not pending approval (current status: {o.status}).",
        )
    strategy = db.query(TradingStrategy).filter(TradingStrategy.id == o.trading_strategy_id).first()
    if not strategy:
        raise HTTPException(status_code=404, detail="Strategy not found.")

    if strategy.paper_mode:
        o.status = "submitted"
        o.broker_order_id = f"PAPER-{o.id}"
        o.broker_stop_id = f"PAPER-STOP-{o.id}"
        o.broker_target_id = f"PAPER-TGT-{o.id}"
        db.commit()
        logger.info(f"Approved paper order id={o.id}")
    else:
        from app.core.celery_app import celery_app as _celery
        o.status = "pending"
        db.commit()
        _celery.send_task("app.tasks.submit_approved_order", kwargs={"order_id": o.id})
        logger.info(f"Approved live order id={o.id}, queued for IBKR submission")

    db.refresh(o)
    return o


def cancel_order(order_id: int, db: Session) -> AutoTradeOrder:
    """Cancel an active order (paper or live)."""
    o = db.query(AutoTradeOrder).filter(AutoTradeOrder.id == order_id).first()
    if not o:
        raise HTTPException(status_code=404, detail="Order not found.")

    cancellable = {"submitted", "open", "pending", "pending_approval"}
    if o.status not in cancellable:
        raise HTTPException(
            status_code=409,
            detail=f"Order cannot be cancelled (current status: {o.status}).",
        )

    if not o.is_paper and o.broker_order_id and o.status in ("submitted", "open"):
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            from app.providers.ibkr_orders import IBKROrderManager
            manager = IBKROrderManager()
            loop.run_until_complete(
                manager.cancel_bracket(
                    parent_order_id=int(o.broker_order_id),
                    stop_order_id=int(o.broker_stop_id or 0),
                    target_order_id=int(o.broker_target_id or 0),
                )
            )
        except Exception as exc:
            logger.error(f"IBKR cancel failed for order {o.id}: {exc}")
            raise HTTPException(status_code=502, detail=f"IBKR cancel failed: {exc}")
        finally:
            loop.close()

    from datetime import datetime, timezone
    o.status = "cancelled"
    o.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
    db.commit()
    db.refresh(o)
    logger.info(f"Cancelled order id={o.id}")
    return o


def get_account_summary(db: Session) -> dict:
    """Fetch IBKR account summary and open orders."""
    try:
        from app.providers.ibkr_orders import IBKROrderManager
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            manager = IBKROrderManager()
            account, open_broker_orders = loop.run_until_complete(
                manager.get_account_and_orders()
            )
        finally:
            loop.close()
        return {
            "net_liquidation": account.net_liquidation,
            "available_funds": account.available_funds,
            "buying_power": account.buying_power,
            "currency": account.currency,
            "connected": True,
            "open_broker_orders": [
                {
                    "order_id": o.order_id,
                    "symbol": o.symbol,
                    "action": o.action,
                    "order_type": o.order_type,
                    "quantity": o.total_qty,
                    "status": o.status,
                    "filled": o.filled,
                    "avg_fill_price": o.avg_fill_price,
                }
                for o in open_broker_orders
            ],
        }
    except Exception as exc:
        logger.warning(f"get_account_summary: IBKR unavailable: {exc}")
        return {
            "net_liquidation": None,
            "available_funds": None,
            "buying_power": None,
            "currency": "USD",
            "connected": False,
            "error": str(exc),
            "open_broker_orders": [],
        }


def get_trading_stats(days: int, db: Session) -> dict:
    """Return auto-trading statistics for the last N days."""
    from datetime import date as date_type, timedelta
    since = date_type.today() - timedelta(days=days)
    orders = db.query(AutoTradeOrder).filter(AutoTradeOrder.event_date >= since).all()

    total = len(orders)
    by_status: dict[str, int] = {}
    for o in orders:
        by_status[o.status] = by_status.get(o.status, 0) + 1

    closed = [o for o in orders if o.status == "closed"]
    wins = [
        o for o in closed
        if o.exit_price and o.fill_price and (
            (o.side == "long" and float(o.exit_price) > float(o.fill_price)) or
            (o.side == "short" and float(o.exit_price) < float(o.fill_price))
        )
    ]

    trade_ids = [o.trade_id for o in closed if o.trade_id]
    total_pnl = 0.0
    if trade_ids:
        trades = db.query(Trade).filter(Trade.id.in_(trade_ids)).all()
        total_pnl = sum(float(t.gross_pnl or 0) for t in trades)

    return {
        "period_days": days,
        "total_orders": total,
        "by_status": by_status,
        "closed_count": len(closed),
        "win_count": len(wins),
        "win_rate": round(len(wins) / len(closed) * 100, 1) if closed else None,
        "total_pnl": round(total_pnl, 2),
        "avg_pnl_per_trade": round(total_pnl / len(closed), 2) if closed else None,
    }
```

Also ensure `import asyncio` is at the top of the file (it already exists in the existing `auto_trade_service.py`).

**Verify tests pass:**
```bash
cd backend && python -m pytest tests/services/test_auto_trade_service.py -v
# Expected: all tests pass
```

**Commit:** `feat(auto_trade_service): add approve_order, cancel_order, get_account_summary, get_trading_stats`

---

### Task 3.3 — Create `schemas/auto_trade.py` with Pydantic response models

**Files:** `backend/app/schemas/auto_trade.py`

```python
"""Pydantic response models for auto-trading endpoints."""
from __future__ import annotations
from typing import Any, List, Optional
from pydantic import BaseModel, ConfigDict


class TradingStrategyResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    description: Optional[str] = None
    is_active: bool
    paper_mode: bool
    requires_approval: bool
    risk_per_trade_pct: Optional[float] = None
    max_position_usd: Optional[float] = None
    max_trades_per_day: Optional[int] = None
    max_concurrent_positions: Optional[int] = None
    entry_type: Optional[str] = None
    limit_offset_pct: float = 0.0
    stop_pct: Optional[float] = None
    risk_reward_ratio: Optional[float] = None
    max_slippage_pct: Optional[float] = None
    allowed_sessions: List[str] = []
    direction: Optional[str] = None
    created_at: Optional[Any] = None
    updated_at: Optional[Any] = None


class AutoTradeOrderResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    alert_rule_id: Optional[int] = None
    scanner_event_id: Optional[int] = None
    trading_strategy_id: Optional[int] = None
    symbol: str
    side: Optional[str] = None
    event_date: Optional[Any] = None
    status: str
    rejection_reason: Optional[str] = None
    trigger_price: Optional[float] = None
    entry_price_target: Optional[float] = None
    calculated_stop: Optional[float] = None
    calculated_target: Optional[float] = None
    quantity: Optional[int] = None
    risk_amount_usd: Optional[float] = None
    is_paper: bool = True
    broker_order_id: Optional[str] = None
    broker_stop_id: Optional[str] = None
    broker_target_id: Optional[str] = None
    fill_price: Optional[float] = None
    filled_at: Optional[Any] = None
    exit_price: Optional[float] = None
    exited_at: Optional[Any] = None
    exit_reason: Optional[str] = None
    trade_id: Optional[int] = None
    created_at: Optional[Any] = None
    updated_at: Optional[Any] = None
```

**Update `schemas/__init__.py`** — add these lines:

```python
from app.schemas.auto_trade import TradingStrategyResponse, AutoTradeOrderResponse
```

And add to `__all__`:
```python
    "TradingStrategyResponse",
    "AutoTradeOrderResponse",
```

**Commit:** `feat(schemas): add TradingStrategyResponse and AutoTradeOrderResponse`

---

### Task 3.4 — Update `routers/auto_trading.py` to delegate to services and use Pydantic schemas

**Files:** `backend/app/routers/auto_trading.py`

1. Add imports:
```python
from app.schemas.auto_trade import TradingStrategyResponse, AutoTradeOrderResponse
from app.services.auto_trade_service import (
    approve_order as svc_approve_order,
    cancel_order as svc_cancel_order,
    get_account_summary,
    get_trading_stats,
)
```

2. Delete `_strategy_to_dict` and `_order_to_dict` functions entirely.

3. Update all six places that call `_strategy_to_dict(s)` to use:
```python
TradingStrategyResponse.model_validate(s).model_dump()
```

4. Update all places that call `_order_to_dict(o)` to use:
```python
AutoTradeOrderResponse.model_validate(o).model_dump()
```

   This covers: `list_strategies`, `create_strategy`, `get_strategy`, `update_strategy`, `list_orders`, `get_order`, `reject_order`, and the returns in `approve_order`/`cancel_order` endpoints (which now delegate).

5. Replace the `approve_order` endpoint body:
```python
@router.post("/orders/{order_id}/approve")
def approve_order_endpoint(
    order_id: int,
    db: Session = Depends(get_db),
):
    o = svc_approve_order(order_id, db)
    return AutoTradeOrderResponse.model_validate(o).model_dump()
```

6. Replace the `cancel_order` endpoint body:
```python
@router.post("/orders/{order_id}/cancel")
def cancel_order_endpoint(
    order_id: int,
    db: Session = Depends(get_db),
):
    o = svc_cancel_order(order_id, db)
    return AutoTradeOrderResponse.model_validate(o).model_dump()
```

7. Replace `get_account` endpoint body:
```python
@router.get("/account")
def get_account(db: Session = Depends(get_db)):
    return get_account_summary(db)
```

8. Replace `get_stats` endpoint body:
```python
@router.get("/stats")
def get_stats(days: int = 30, db: Session = Depends(get_db)):
    return get_trading_stats(days, db)
```

9. Remove now-unused imports from the router: `asyncio`, `func` (from sqlalchemy), `Trade`.

**Verify backend reloads and endpoints return correct shapes:**
```bash
docker-compose logs backend --tail=20
curl -s http://localhost:8000/api/trading/strategies | python -m json.tool
curl -s http://localhost:8000/api/trading/stats | python -m json.tool
curl -s http://localhost:8000/api/trading/account | python -m json.tool
```

**Commit:** `refactor(auto_trading): delegate router logic to auto_trade_service + Pydantic schemas (Phase 3)`

---

## Final Validation

```bash
# All service tests pass
cd backend && python -m pytest tests/services/ -v

# Full test suite stays green
cd backend && python -m pytest --tb=short

# Coverage gate (>60%) still met
cd backend && python -m pytest --cov=app --cov-report=term-missing | grep TOTAL

# TypeScript still clean
cd frontend && npx tsc --noEmit
```

---

## Task Summary

| # | Task | Files | Steps |
|---|------|-------|-------|
| 1.1 | Write failing tests for SystemService | `test_system_service.py` | 2 |
| 1.2 | Implement SystemService | `system_service.py` | 2 |
| 1.3 | Thin-ify system.py router | `routers/system.py` | 3 |
| 2.1 | Write failing tests for orchestrator extensions | `test_scan_orchestrator.py` | 2 |
| 2.2 | Extend scan_orchestrator.py | `scan_orchestrator.py` | 2 |
| 2.3 | Write failing tests for ScannerQueryService | `test_scanner_query_service.py` | 2 |
| 2.4 | Implement ScannerQueryService | `scanner_query_service.py` | 2 |
| 2.5 | Thin-ify scanner.py router | `routers/scanner.py` | 3 |
| 3.1 | Write failing tests for new auto_trade methods | `test_auto_trade_service.py` | 2 |
| 3.2 | Implement new auto_trade service methods | `auto_trade_service.py` | 2 |
| 3.3 | Create Pydantic schemas | `schemas/auto_trade.py`, `schemas/__init__.py` | 2 |
| 3.4 | Thin-ify auto_trading.py router | `routers/auto_trading.py` | 3 |
| — | Final validation | — | 4 |

**Total: 12 tasks, 29 steps**
