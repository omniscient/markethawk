# Redis Application Caching for Hot Endpoints

**Issue:** #98  
**Date:** 2026-05-28  
**Branch:** refine/issue-98-implement-redis-application-caching-for-

---

## Goal

Add application-level Redis caching to six hot endpoints using a new `core/cache.py` utility module. Reduces PostgreSQL load, speeds up frontend polling endpoints, and migrates the ad-hoc inline Redis block in `stocks.py` to the new unified pattern.

---

## Architecture

A new `backend/app/core/cache.py` provides four building blocks:

- `get_redis()` — process-scoped `@lru_cache(maxsize=1)` singleton returning a `redis.Redis | None`
- `get_cached(key, ttl, fn)` — read-through helper; calls `fn()`, caches result as JSON; on hit, returns `json.loads` of stored string; transparent on Redis failure
- `invalidate(key)` — deletes a single key; no-op when Redis unavailable
- `invalidate_pattern(pattern)` — SCAN + DEL for glob patterns; no-op when Redis unavailable
- `cache_response(key, ttl)` — thin decorator over `get_cached` for parameter-less GET handlers

All keys use the `mh:` prefix to avoid collisions with Celery and live-scanner keys. Sync `redis.Redis` client throughout (matches existing usage in `services/scanner.py`). `decode_responses=True`, `socket_connect_timeout=1`, `socket_timeout=0.5` for fast failure.

---

## Tech Stack

- Python `functools.lru_cache`, `json`, `redis.Redis`
- FastAPI route handlers (sync `def`)
- Existing `settings.REDIS_URL` from `core/config.py`
- `unittest.mock` for tests

---

## File Structure

| File | Action | Purpose |
|------|--------|---------|
| `backend/app/core/cache.py` | **Create** | Redis singleton, `get_cached`, `invalidate`, `invalidate_pattern`, `cache_response` |
| `backend/tests/api/test_cache.py` | **Create** | Unit tests for cache.py using mocked Redis |
| `backend/app/routers/scanner.py` | **Modify** | Cache `/types` (decorator) and `/configs` (inline) |
| `backend/app/routers/system.py` | **Modify** | Cache `/status` (30 s) and `/storage` (300 s) |
| `backend/app/routers/universe.py` | **Modify** | Cache `/list` (60 s, `include_stats=True` only) + invalidation in 4 mutations |
| `backend/app/routers/stocks.py` | **Modify** | Replace inline Redis block with `get_cached` |

---

## Cache Key Table

| Endpoint | Key | TTL |
|----------|-----|-----|
| `GET /api/scanner/types` | `mh:scanner:types` | 3600 s |
| `GET /api/scanner/configs` | `mh:scanner:configs` | 300 s |
| `GET /api/system/status` | `mh:system:status` | 30 s |
| `GET /api/system/storage` | `mh:system:storage` | 300 s |
| `GET /api/universe/list` | `mh:universe:list` | 60 s |
| `GET /api/stocks/details/{ticker}` | `mh:stocks:details:{ticker}` | 60 s |

---

## Tasks

### Task 1 — Create `backend/app/core/cache.py` with unit tests

**Files:**
- `backend/app/core/cache.py` (create)
- `backend/tests/api/test_cache.py` (create)

#### Step 1.1 — Write failing unit tests

Create `backend/tests/api/test_cache.py`:

```python
"""Unit tests for core/cache.py — all Redis calls are mocked."""
import json
import pytest
from unittest.mock import MagicMock, patch, call


# ---------------------------------------------------------------------------
# get_redis
# ---------------------------------------------------------------------------

def test_get_redis_returns_none_when_no_url(monkeypatch):
    """If REDIS_URL is empty, get_redis() returns None."""
    import app.core.cache as cache_mod
    # Clear lru_cache so the test gets a fresh call
    cache_mod.get_redis.cache_clear()
    monkeypatch.setattr("app.core.config.settings.REDIS_URL", "")
    result = cache_mod.get_redis()
    assert result is None
    cache_mod.get_redis.cache_clear()


def test_get_redis_returns_client_when_url_set(monkeypatch):
    """When REDIS_URL is set, get_redis() returns a redis.Redis instance."""
    import app.core.cache as cache_mod
    cache_mod.get_redis.cache_clear()
    monkeypatch.setattr("app.core.config.settings.REDIS_URL", "redis://localhost:6379/0")
    with patch("app.core.cache.redis.Redis") as mock_redis_cls:
        mock_redis_cls.return_value = MagicMock()
        result = cache_mod.get_redis()
        assert result is not None
        mock_redis_cls.assert_called_once()
    cache_mod.get_redis.cache_clear()


# ---------------------------------------------------------------------------
# get_cached — cache miss
# ---------------------------------------------------------------------------

def test_get_cached_calls_fn_on_cache_miss():
    """On a cache miss, get_cached calls fn() and returns its result."""
    from app.core.cache import get_cached
    mock_redis = MagicMock()
    mock_redis.get.return_value = None

    fn = MagicMock(return_value={"key": "value"})

    with patch("app.core.cache.get_redis", return_value=mock_redis):
        result = get_cached("test:key", 60, fn)

    assert result == {"key": "value"}
    fn.assert_called_once()


def test_get_cached_stores_json_on_cache_miss():
    """On cache miss, get_cached stores json.dumps(fn()) in Redis with the given TTL."""
    from app.core.cache import get_cached
    mock_redis = MagicMock()
    mock_redis.get.return_value = None

    fn = MagicMock(return_value={"key": "value"})

    with patch("app.core.cache.get_redis", return_value=mock_redis):
        get_cached("test:key", 60, fn)

    mock_redis.setex.assert_called_once_with("test:key", 60, json.dumps({"key": "value"}))


# ---------------------------------------------------------------------------
# get_cached — cache hit
# ---------------------------------------------------------------------------

def test_get_cached_returns_cached_value_on_hit():
    """On a cache hit, get_cached returns the deserialized value without calling fn."""
    from app.core.cache import get_cached
    mock_redis = MagicMock()
    mock_redis.get.return_value = json.dumps({"cached": True})

    fn = MagicMock()

    with patch("app.core.cache.get_redis", return_value=mock_redis):
        result = get_cached("test:key", 60, fn)

    assert result == {"cached": True}
    fn.assert_not_called()


# ---------------------------------------------------------------------------
# get_cached — Redis unavailable
# ---------------------------------------------------------------------------

def test_get_cached_falls_through_when_redis_none():
    """When get_redis() returns None, get_cached calls fn() without caching."""
    from app.core.cache import get_cached
    fn = MagicMock(return_value={"live": True})

    with patch("app.core.cache.get_redis", return_value=None):
        result = get_cached("test:key", 60, fn)

    assert result == {"live": True}
    fn.assert_called_once()


def test_get_cached_falls_through_on_redis_error():
    """When Redis.get() raises, get_cached calls fn() and returns without caching."""
    from app.core.cache import get_cached
    mock_redis = MagicMock()
    mock_redis.get.side_effect = Exception("connection refused")

    fn = MagicMock(return_value={"live": True})

    with patch("app.core.cache.get_redis", return_value=mock_redis):
        result = get_cached("test:key", 60, fn)

    assert result == {"live": True}
    fn.assert_called_once()


# ---------------------------------------------------------------------------
# invalidate
# ---------------------------------------------------------------------------

def test_invalidate_calls_delete():
    """invalidate() calls Redis.delete() with the given key."""
    from app.core.cache import invalidate
    mock_redis = MagicMock()

    with patch("app.core.cache.get_redis", return_value=mock_redis):
        invalidate("mh:universe:list")

    mock_redis.delete.assert_called_once_with("mh:universe:list")


def test_invalidate_is_noop_when_redis_none():
    """invalidate() does nothing when Redis is unavailable."""
    from app.core.cache import invalidate
    with patch("app.core.cache.get_redis", return_value=None):
        invalidate("mh:universe:list")  # must not raise


def test_invalidate_is_noop_on_redis_error():
    """invalidate() swallows Redis errors."""
    from app.core.cache import invalidate
    mock_redis = MagicMock()
    mock_redis.delete.side_effect = Exception("timeout")

    with patch("app.core.cache.get_redis", return_value=mock_redis):
        invalidate("mh:universe:list")  # must not raise


# ---------------------------------------------------------------------------
# invalidate_pattern
# ---------------------------------------------------------------------------

def test_invalidate_pattern_scans_and_deletes():
    """invalidate_pattern() scans for matching keys and deletes each one."""
    from app.core.cache import invalidate_pattern
    mock_redis = MagicMock()
    mock_redis.scan_iter.return_value = ["mh:stocks:details:AAPL", "mh:stocks:details:MSFT"]

    with patch("app.core.cache.get_redis", return_value=mock_redis):
        invalidate_pattern("mh:stocks:details:*")

    mock_redis.scan_iter.assert_called_once_with("mh:stocks:details:*")
    assert mock_redis.delete.call_count == 2


def test_invalidate_pattern_is_noop_when_redis_none():
    """invalidate_pattern() does nothing when Redis is unavailable."""
    from app.core.cache import invalidate_pattern
    with patch("app.core.cache.get_redis", return_value=None):
        invalidate_pattern("mh:*")  # must not raise


# ---------------------------------------------------------------------------
# cache_response decorator
# ---------------------------------------------------------------------------

def test_cache_response_wraps_handler():
    """@cache_response delegates to get_cached on invocation."""
    from app.core.cache import cache_response
    mock_redis = MagicMock()
    mock_redis.get.return_value = None

    @cache_response("mh:test:key", 300)
    def handler():
        return [{"item": 1}]

    with patch("app.core.cache.get_redis", return_value=mock_redis):
        result = handler()

    assert result == [{"item": 1}]


def test_cache_response_returns_cached_value():
    """@cache_response returns cached value without calling the handler body."""
    from app.core.cache import cache_response

    call_count = {"n": 0}

    @cache_response("mh:test:key", 300)
    def handler():
        call_count["n"] += 1
        return [{"item": 1}]

    mock_redis = MagicMock()
    mock_redis.get.return_value = json.dumps([{"item": 99}])

    with patch("app.core.cache.get_redis", return_value=mock_redis):
        result = handler()

    assert result == [{"item": 99}]
    assert call_count["n"] == 0
```

Verify tests fail:
```bash
cd /workspace/markethawk
docker-compose exec backend python -m pytest tests/api/test_cache.py -v 2>&1 | tail -20
# Expected: ModuleNotFoundError or ImportError for app.core.cache
```

#### Step 1.2 — Implement `backend/app/core/cache.py`

Create the file:

```python
import json
import functools
from typing import Any, Callable, TypeVar

import redis

from app.core.config import settings

T = TypeVar("T")


@functools.lru_cache(maxsize=1)
def get_redis() -> "redis.Redis | None":
    if not settings.REDIS_URL:
        return None
    return redis.Redis.from_url(
        settings.REDIS_URL,
        decode_responses=True,
        socket_connect_timeout=1,
        socket_timeout=0.5,
    )


def get_cached(key: str, ttl: int, fn: Callable[[], T]) -> T:
    r = get_redis()
    if r is not None:
        try:
            cached = r.get(key)
            if cached is not None:
                return json.loads(cached)
        except Exception:
            pass

    value = fn()

    if r is not None:
        try:
            r.setex(key, ttl, json.dumps(value))
        except Exception:
            pass

    return value


def invalidate(key: str) -> None:
    r = get_redis()
    if r is None:
        return
    try:
        r.delete(key)
    except Exception:
        pass


def invalidate_pattern(pattern: str) -> None:
    r = get_redis()
    if r is None:
        return
    try:
        for key in r.scan_iter(pattern):
            r.delete(key)
    except Exception:
        pass


def cache_response(key: str, ttl: int):
    def decorator(fn: Callable) -> Callable:
        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            return get_cached(key, ttl, lambda: fn(*args, **kwargs))
        return wrapper
    return decorator
```

#### Step 1.3 — Verify tests pass

```bash
docker-compose exec backend python -m pytest tests/api/test_cache.py -v 2>&1 | tail -30
# Expected: all 14 tests PASSED
```

#### Step 1.4 — Commit

```bash
git add backend/app/core/cache.py backend/tests/api/test_cache.py
git commit -m "feat(cache): add core/cache.py with Redis read-through helpers and unit tests"
```

---

### Task 2 — Cache `GET /api/scanner/types` with `@cache_response`

**Files:**
- `backend/app/routers/scanner.py` (modify `list_scanner_types`)

#### Step 2.1 — Write failing test

Add to `backend/tests/api/test_scanner.py`:

```python
# ---------------------------------------------------------------------------
# GET /api/scanner/types — caching
# ---------------------------------------------------------------------------

def test_scanner_types_returns_200():
    """Endpoint still returns 200 with valid response shape."""
    response = client.get("/api/scanner/types")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert all("key" in t and "display_name" in t for t in data)


def test_scanner_types_served_from_cache_on_hit():
    """On a cache hit, the handler body is not executed."""
    import json
    from unittest.mock import MagicMock, patch

    cached_data = [{"key": "cached_type", "display_name": "Cached", "description": "", "supports_date_range": False}]
    mock_redis = MagicMock()
    mock_redis.get.return_value = json.dumps(cached_data)

    with patch("app.core.cache.get_redis", return_value=mock_redis):
        response = client.get("/api/scanner/types")

    assert response.status_code == 200
    assert response.json() == cached_data
```

Verify test fails:
```bash
docker-compose exec backend python -m pytest tests/api/test_scanner.py::test_scanner_types_served_from_cache_on_hit -v 2>&1 | tail -10
# Expected: FAILED — handler body always executes (no cache yet)
```

#### Step 2.2 — Apply `@cache_response` decorator

In `backend/app/routers/scanner.py`, modify `list_scanner_types`:

Before:
```python
@router.get("/types")
def list_scanner_types():
    """Return all registered scanner types for frontend scanner pickers."""
    from app.services.scan_orchestrator import get_all
    return [
        {
            "key": d.key,
            "display_name": d.display_name,
            "description": d.description,
            "supports_date_range": d.supports_date_range,
        }
        for d in get_all()
    ]
```

After:
```python
from app.core.cache import cache_response, get_cached, invalidate

@router.get("/types")
@cache_response("mh:scanner:types", 3600)
def list_scanner_types():
    """Return all registered scanner types for frontend scanner pickers."""
    from app.services.scan_orchestrator import get_all
    return [
        {
            "key": d.key,
            "display_name": d.display_name,
            "description": d.description,
            "supports_date_range": d.supports_date_range,
        }
        for d in get_all()
    ]
```

#### Step 2.3 — Verify tests pass

```bash
docker-compose exec backend python -m pytest tests/api/test_scanner.py::test_scanner_types_returns_200 tests/api/test_scanner.py::test_scanner_types_served_from_cache_on_hit -v 2>&1 | tail -15
# Expected: both PASSED
```

#### Step 2.4 — Commit

```bash
git add backend/app/routers/scanner.py
git commit -m "feat(cache): cache GET /api/scanner/types with 1-hour TTL"
```

---

### Task 3 — Cache `GET /api/scanner/configs`

**Files:**
- `backend/app/routers/scanner.py` (modify `get_scanner_configs`)

#### Step 3.1 — Write failing test

Add to `backend/tests/api/test_scanner.py`:

```python
# ---------------------------------------------------------------------------
# GET /api/scanner/configs — caching
# ---------------------------------------------------------------------------

def test_scanner_configs_returns_200(db: Session):
    seed_scanner_configs(db)

    response = client.get("/api/scanner/configs")

    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) > 0


def test_scanner_configs_served_from_cache_on_hit(db: Session):
    """On a cache hit, the DB is not queried."""
    import json
    from unittest.mock import MagicMock, patch

    cached_data = [{"id": 99, "name": "Cached Config", "is_active": True}]
    mock_redis = MagicMock()
    mock_redis.get.return_value = json.dumps(cached_data)

    with patch("app.core.cache.get_redis", return_value=mock_redis):
        response = client.get("/api/scanner/configs")

    assert response.status_code == 200
    assert response.json() == cached_data
```

Verify fail:
```bash
docker-compose exec backend python -m pytest tests/api/test_scanner.py::test_scanner_configs_served_from_cache_on_hit -v 2>&1 | tail -10
# Expected: FAILED
```

#### Step 3.2 — Apply `get_cached` to `get_scanner_configs`

In `backend/app/routers/scanner.py`, modify `get_scanner_configs`:

Before:
```python
@router.get("/configs", response_model=List[ScannerConfigResponse])
def get_scanner_configs(
    db: Session = Depends(get_db),
):
    """Get all available scanner configurations."""
    return db.query(ScannerConfig).filter(ScannerConfig.is_active == True).all()
```

After:
```python
@router.get("/configs", response_model=List[ScannerConfigResponse])
def get_scanner_configs(
    db: Session = Depends(get_db),
):
    """Get all available scanner configurations."""
    return get_cached(
        "mh:scanner:configs",
        300,
        lambda: [
            ScannerConfigResponse.model_validate(r).model_dump(mode="json")
            for r in db.query(ScannerConfig).filter(ScannerConfig.is_active == True).all()
        ],
    )
```

#### Step 3.3 — Verify tests pass

```bash
docker-compose exec backend python -m pytest tests/api/test_scanner.py::test_scanner_configs_returns_200 tests/api/test_scanner.py::test_scanner_configs_served_from_cache_on_hit -v 2>&1 | tail -15
# Expected: both PASSED
```

#### Step 3.4 — Commit

```bash
git add backend/app/routers/scanner.py
git commit -m "feat(cache): cache GET /api/scanner/configs with 5-minute TTL"
```

---

### Task 4 — Cache `GET /api/system/status` and `GET /api/system/storage`

**Files:**
- `backend/app/routers/system.py` (modify both handlers)

#### Step 4.1 — Write failing tests

Add to `backend/tests/api/test_system.py`:

```python
# ---------------------------------------------------------------------------
# GET /api/system/status — caching
# ---------------------------------------------------------------------------

def test_system_status_returns_200(db: Session):
    response = client.get("/api/system/status")
    assert response.status_code == 200
    data = response.json()
    assert "market_status" in data
    assert "last_scan_at" in data
    assert "ibkr_reachable" in data


def test_system_status_served_from_cache_on_hit():
    """On cache hit, handler body (DB + IBKR probe) is not executed."""
    import json
    from unittest.mock import MagicMock, patch

    cached = {"market_status": "closed", "last_scan_at": None, "ibkr_reachable": False, "ibkr_host": "127.0.0.1", "ibkr_port": 7497}
    mock_redis = MagicMock()
    mock_redis.get.return_value = json.dumps(cached)

    with patch("app.core.cache.get_redis", return_value=mock_redis):
        response = client.get("/api/system/status")

    assert response.status_code == 200
    assert response.json() == cached


# ---------------------------------------------------------------------------
# GET /api/system/storage — caching
# ---------------------------------------------------------------------------

def test_system_storage_returns_200(db: Session):
    response = client.get("/api/system/storage")
    assert response.status_code == 200
    data = response.json()
    assert "total" in data


def test_system_storage_served_from_cache_on_hit():
    """On cache hit, handler body (pg_stat query) is not executed."""
    import json
    from unittest.mock import MagicMock, patch

    cached = {"scanner": {"bytes": 0, "formatted": "0 B"}, "historical": {"bytes": 0, "formatted": "0 B"}, "settings": {"bytes": 0, "formatted": "0 B"}, "total": {"bytes": 0, "formatted": "0 B"}}
    mock_redis = MagicMock()
    mock_redis.get.return_value = json.dumps(cached)

    with patch("app.core.cache.get_redis", return_value=mock_redis):
        response = client.get("/api/system/storage")

    assert response.status_code == 200
    assert response.json() == cached
```

Verify tests fail:
```bash
docker-compose exec backend python -m pytest tests/api/test_system.py::test_system_status_served_from_cache_on_hit tests/api/test_system.py::test_system_storage_served_from_cache_on_hit -v 2>&1 | tail -10
# Expected: both FAILED
```

#### Step 4.2 — Apply `get_cached` to `get_system_status`

In `backend/app/routers/system.py`, add import at top of file:

```python
from app.core.cache import get_cached
```

Modify `get_system_status`:

Before:
```python
@router.get("/status")
def get_system_status(db: Session = Depends(get_db)):
    """Lightweight status snapshot: market session, last scan, IBKR reachability."""
    from app.core.config import settings
    from app.models.scanner_run import ScannerRun

    # Last scan
    last_run = db.query(ScannerRun).order_by(ScannerRun.created_at.desc()).first()
    last_scan_at: Optional[str] = None
    if last_run and last_run.created_at:
        ts = last_run.created_at
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        last_scan_at = ts.isoformat()

    ibkr_host = getattr(settings, "IBKR_HOST", "127.0.0.1")
    ibkr_port = int(getattr(settings, "IBKR_PORT", 7497))

    return {
        "market_status": _market_status(),
        "last_scan_at": last_scan_at,
        "ibkr_reachable": _ibkr_reachable(ibkr_host, ibkr_port),
        "ibkr_host": ibkr_host,
        "ibkr_port": ibkr_port,
    }
```

After:
```python
@router.get("/status")
def get_system_status(db: Session = Depends(get_db)):
    """Lightweight status snapshot: market session, last scan, IBKR reachability."""
    from app.core.config import settings
    from app.models.scanner_run import ScannerRun

    def _build_status():
        last_run = db.query(ScannerRun).order_by(ScannerRun.created_at.desc()).first()
        last_scan_at: Optional[str] = None
        if last_run and last_run.created_at:
            ts = last_run.created_at
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            last_scan_at = ts.isoformat()

        ibkr_host = getattr(settings, "IBKR_HOST", "127.0.0.1")
        ibkr_port = int(getattr(settings, "IBKR_PORT", 7497))

        return {
            "market_status": _market_status(),
            "last_scan_at": last_scan_at,
            "ibkr_reachable": _ibkr_reachable(ibkr_host, ibkr_port),
            "ibkr_host": ibkr_host,
            "ibkr_port": ibkr_port,
        }

    return get_cached("mh:system:status", 30, _build_status)
```

#### Step 4.3 — Apply `get_cached` to `get_storage_stats`

Modify `get_storage_stats`:

Before:
```python
@router.get("/storage")
def get_storage_stats(db: Session = Depends(get_db)):
    ...
    try:
        # ... table_groups, results, dialect logic ...
        return results
    except Exception as e:
        logger.error(...)
        return { ... "Service Error" ... }
```

After (wrap only the try/except body in a nested `_build_storage` lambda, cache the successful result; the except branch still returns directly):

```python
@router.get("/storage")
def get_storage_stats(db: Session = Depends(get_db)):
    """Get storage usage statistics for major database tables."""
    def _build_storage():
        table_groups = {
            "scanner": ["volume_events", "scanner_runs"],
            "historical": ["stock_aggregates", "stock_metrics", "ticker_references", "news_articles"],
            "settings": ["news_preferences", "scanner_configs"]
        }
        results = {
            "scanner": {"bytes": 0, "formatted": "0.0 B"},
            "historical": {"bytes": 0, "formatted": "0.0 B"},
            "settings": {"bytes": 0, "formatted": "0.0 B"},
            "total": {"bytes": 0, "formatted": "0.0 B"}
        }
        dialect = db.bind.dialect.name
        if dialect == "postgresql":
            all_tables = []
            for group in table_groups.values():
                all_tables.extend(group)
            query = text("""
                SELECT
                    relname as table_name,
                    pg_total_relation_size(relid) as total_size
                FROM pg_catalog.pg_statio_user_tables
                WHERE relname = ANY(:tables)
            """)
            db_results = db.execute(query, {"tables": all_tables}).fetchall()
            table_sizes = {row.table_name: row.total_size for row in db_results}
            for group_name, tables in table_groups.items():
                group_size = sum(table_sizes.get(t, 0) for t in tables)
                results[group_name]["bytes"] = group_size
                results[group_name]["formatted"] = format_bytes(group_size)
                results["total"]["bytes"] += group_size
        elif dialect == "sqlite":
            import os
            db_url = str(db.bind.url)
            db_path = db_url.replace("sqlite:///", "")
            total_size = 0
            if os.path.exists(db_path):
                total_size = os.path.getsize(db_path)
            results["historical"]["bytes"] = total_size
            results["historical"]["formatted"] = f"{format_bytes(total_size)} (SQLite)"
            results["total"]["bytes"] = total_size
            results["total"]["formatted"] = f"{format_bytes(total_size)} (Full DB)"
        else:
            results["total"]["formatted"] = f"Unknown DB ({dialect})"
        results["total"]["formatted"] = format_bytes(results["total"]["bytes"])
        return results

    try:
        return get_cached("mh:system:storage", 300, _build_storage)
    except Exception as e:
        logger.error(f"Error fetching storage stats: {e}", exc_info=True)
        return {
            "scanner": {"bytes": 0, "formatted": "N/A"},
            "historical": {"bytes": 0, "formatted": "N/A"},
            "settings": {"bytes": 0, "formatted": "N/A"},
            "total": {"bytes": 0, "formatted": "Service Error"}
        }
```

#### Step 4.4 — Verify tests pass

```bash
docker-compose exec backend python -m pytest tests/api/test_system.py -v 2>&1 | tail -20
# Expected: all tests pass including the two new cache tests
```

#### Step 4.5 — Commit

```bash
git add backend/app/routers/system.py
git commit -m "feat(cache): cache GET /api/system/status (30 s) and /storage (5 min)"
```

---

### Task 5 — Cache `GET /api/universe/list` + mutation invalidation

**Files:**
- `backend/app/routers/universe.py` (modify `list_stock_universes` + 4 mutation endpoints)

#### Step 5.1 — Write failing tests

Add to `backend/tests/api/test_universe.py`:

```python
# ---------------------------------------------------------------------------
# GET /api/universe/list — caching
# ---------------------------------------------------------------------------

def test_list_served_from_cache_on_hit():
    """When Redis has a cached list, it is returned without hitting the DB."""
    import json
    from unittest.mock import MagicMock, patch

    cached = [{"id": 1, "name": "Cached Universe", "is_active": True}]
    mock_redis = MagicMock()
    mock_redis.get.return_value = json.dumps(cached)

    with patch("app.core.cache.get_redis", return_value=mock_redis):
        response = client.get("/api/universe/list")

    assert response.status_code == 200
    assert response.json() == cached


def test_list_bypasses_cache_when_include_stats_false(db: Session):
    """include_stats=false always fetches from the DB, never Redis."""
    from unittest.mock import MagicMock, patch

    mock_redis = MagicMock()

    with patch("app.core.cache.get_redis", return_value=mock_redis):
        response = client.get("/api/universe/list?include_stats=false")

    assert response.status_code == 200
    mock_redis.get.assert_not_called()


def test_create_universe_invalidates_cache(db: Session):
    """POST /create calls invalidate('mh:universe:list') after commit."""
    from unittest.mock import MagicMock, patch

    mock_redis = MagicMock()
    mock_redis.get.return_value = None

    with patch("app.core.cache.get_redis", return_value=mock_redis):
        response = client.post("/api/universe/create", json={
            "name": "Test Universe",
            "description": "Test",
            "criteria": {},
        })

    assert response.status_code == 200
    mock_redis.delete.assert_called_with("mh:universe:list")


def test_update_universe_invalidates_cache(db: Session):
    """PUT /{id} calls invalidate('mh:universe:list') after commit."""
    from unittest.mock import MagicMock, patch
    from tests.fixtures.core import seed_universes
    from app.models import StockUniverse

    seed_universes(db)
    universe_id = db.query(StockUniverse).first().id

    mock_redis = MagicMock()
    mock_redis.get.return_value = None

    with patch("app.core.cache.get_redis", return_value=mock_redis):
        response = client.put(f"/api/universe/{universe_id}", json={"name": "Updated"})

    assert response.status_code == 200
    mock_redis.delete.assert_called_with("mh:universe:list")


def test_delete_universe_invalidates_cache(db: Session):
    """DELETE /{id} calls invalidate('mh:universe:list') after commit."""
    from unittest.mock import MagicMock, patch
    from tests.fixtures.core import seed_universes

    seed_universes(db)
    from app.models import StockUniverse
    universe_id = db.query(StockUniverse).filter(StockUniverse.is_active == True).first().id

    mock_redis = MagicMock()
    mock_redis.get.return_value = None

    with patch("app.core.cache.get_redis", return_value=mock_redis):
        response = client.delete(f"/api/universe/{universe_id}")

    assert response.status_code == 200
    mock_redis.delete.assert_called_with("mh:universe:list")
```

Verify tests fail:
```bash
docker-compose exec backend python -m pytest tests/api/test_universe.py::test_list_served_from_cache_on_hit tests/api/test_universe.py::test_create_universe_invalidates_cache -v 2>&1 | tail -15
# Expected: both FAILED
```

#### Step 5.2 — Add cache import to `universe.py`

Add at the top of `backend/app/routers/universe.py`:

```python
from app.core.cache import get_cached, invalidate
```

#### Step 5.3 — Wrap `list_stock_universes` with `get_cached`

Modify `list_stock_universes`:

Before:
```python
@router.get("/list", response_model=List[StockUniverseResponse])
def list_stock_universes(
    include_stats: bool = True,
    db: Session = Depends(get_db),
):
    """List all active stock universes. include_stats=false skips aggregate stats (for dropdowns)."""
    universes = db.query(StockUniverse).filter(StockUniverse.is_active == True).all()

    results = []
    for universe in universes:
        universe_data = StockUniverseResponse.from_orm(universe)

        if include_stats:
            universe_data.ticker_count = universe.cached_ticker_count or 0
            universe_data.aggregate_count = universe.cached_aggregate_count or 0
            universe_data.min_aggregate_date = universe.cached_min_date
            universe_data.max_aggregate_date = universe.cached_max_date
            universe_data.available_timespans = universe.cached_timespans or []
            universe_data.stats_refreshed_at = universe.stats_refreshed_at
        else:
            universe_data.ticker_count = 0
            universe_data.aggregate_count = 0
            universe_data.min_aggregate_date = None
            universe_data.max_aggregate_date = None
            universe_data.available_timespans = []

        results.append(universe_data)

    return results
```

After:
```python
@router.get("/list", response_model=List[StockUniverseResponse])
def list_stock_universes(
    include_stats: bool = True,
    db: Session = Depends(get_db),
):
    """List all active stock universes. include_stats=false skips aggregate stats (for dropdowns)."""
    def _build_list():
        universes = db.query(StockUniverse).filter(StockUniverse.is_active == True).all()
        results = []
        for universe in universes:
            universe_data = StockUniverseResponse.from_orm(universe)
            universe_data.ticker_count = universe.cached_ticker_count or 0
            universe_data.aggregate_count = universe.cached_aggregate_count or 0
            universe_data.min_aggregate_date = universe.cached_min_date
            universe_data.max_aggregate_date = universe.cached_max_date
            universe_data.available_timespans = universe.cached_timespans or []
            universe_data.stats_refreshed_at = universe.stats_refreshed_at
            results.append(universe_data.model_dump(mode="json"))
        return results

    if not include_stats:
        universes = db.query(StockUniverse).filter(StockUniverse.is_active == True).all()
        results = []
        for universe in universes:
            universe_data = StockUniverseResponse.from_orm(universe)
            universe_data.ticker_count = 0
            universe_data.aggregate_count = 0
            universe_data.min_aggregate_date = None
            universe_data.max_aggregate_date = None
            universe_data.available_timespans = []
            results.append(universe_data)
        return results

    return get_cached("mh:universe:list", 60, _build_list)
```

#### Step 5.4 — Add `invalidate` calls to mutation endpoints

Modify `create_stock_universe`:

Before:
```python
@router.post("/create", response_model=StockUniverseResponse)
def create_stock_universe(
    universe: StockUniverseCreate,
    db: Session = Depends(get_db),
):
    """Create a new stock universe."""
    db_universe = StockUniverse(**universe.dict())
    db.add(db_universe)
    db.commit()
    db.refresh(db_universe)
    return db_universe
```

After:
```python
@router.post("/create", response_model=StockUniverseResponse)
def create_stock_universe(
    universe: StockUniverseCreate,
    db: Session = Depends(get_db),
):
    """Create a new stock universe."""
    db_universe = StockUniverse(**universe.dict())
    db.add(db_universe)
    db.commit()
    db.refresh(db_universe)
    invalidate("mh:universe:list")
    return db_universe
```

Modify `update_stock_universe`:

Before:
```python
    db.commit()
    db.refresh(db_universe)
    return db_universe
```

After:
```python
    db.commit()
    db.refresh(db_universe)
    invalidate("mh:universe:list")
    return db_universe
```

Modify `delete_stock_universe`:

Before:
```python
    universe.is_active = False
    db.commit()
    return {"message": "Universe deleted successfully"}
```

After:
```python
    universe.is_active = False
    db.commit()
    invalidate("mh:universe:list")
    return {"message": "Universe deleted successfully"}
```

Modify `refresh_universe_stats`:

Before:
```python
    universe.stats_refreshed_at = datetime.now(timezone.utc).replace(tzinfo=None)
    db.commit()
    db.refresh(universe)
    # ... build response ...
    return universe_data
```

After:
```python
    universe.stats_refreshed_at = datetime.now(timezone.utc).replace(tzinfo=None)
    db.commit()
    db.refresh(universe)
    invalidate("mh:universe:list")
    # ... build response ...
    return universe_data
```

#### Step 5.5 — Verify tests pass

```bash
docker-compose exec backend python -m pytest tests/api/test_universe.py -v 2>&1 | tail -25
# Expected: all tests pass including the five new cache tests
```

#### Step 5.6 — Commit

```bash
git add backend/app/routers/universe.py
git commit -m "feat(cache): cache GET /api/universe/list (60 s) + invalidation on mutations"
```

---

### Task 6 — Migrate `GET /api/stocks/details/{ticker}` inline Redis to `get_cached`

**Files:**
- `backend/app/routers/stocks.py` (modify `get_stock_detail_consolidated`)

#### Step 6.1 — Write failing tests

Add to `backend/tests/api/test_stocks.py`:

```python
# ---------------------------------------------------------------------------
# GET /api/stocks/details/{ticker} — caching
# ---------------------------------------------------------------------------

def test_stock_details_served_from_cache_on_hit():
    """On a cache hit, provider calls are not made."""
    import json
    from unittest.mock import MagicMock, patch

    cached = {"ticker": "AAPL", "info": {"longName": "Apple Inc."}, "pre_market": {}, "latest_price": 150.0, "last_updated": "2026-05-28T00:00:00+00:00"}
    mock_redis = MagicMock()
    mock_redis.get.return_value = json.dumps(cached)

    with patch("app.core.cache.get_redis", return_value=mock_redis):
        response = client.get("/api/stocks/details/AAPL")

    assert response.status_code == 200
    assert response.json()["ticker"] == "AAPL"


def test_stock_details_uses_mh_key_prefix():
    """Cache key follows the mh:stocks:details:{ticker} namespace."""
    import json
    from unittest.mock import MagicMock, patch, call

    mock_redis = MagicMock()
    mock_redis.get.return_value = json.dumps({"ticker": "MSFT", "info": {}, "pre_market": {}, "latest_price": None, "last_updated": "2026-05-28T00:00:00+00:00"})

    with patch("app.core.cache.get_redis", return_value=mock_redis):
        client.get("/api/stocks/details/MSFT")

    mock_redis.get.assert_called_with("mh:stocks:details:MSFT")
```

Verify tests fail (second test fails because current key is `stock_detail:MSFT` without `mh:` prefix):
```bash
docker-compose exec backend python -m pytest tests/api/test_stocks.py::test_stock_details_uses_mh_key_prefix -v 2>&1 | tail -10
# Expected: FAILED — key is stock_detail:MSFT, not mh:stocks:details:MSFT
```

#### Step 6.2 — Replace inline Redis block with `get_cached`

In `backend/app/routers/stocks.py`, add import at top:

```python
from app.core.cache import get_cached
```

Modify `get_stock_detail_consolidated`. Replace the entire handler body with `get_cached`:

Before (lines 115–243):
```python
@router.get("/details/{ticker}")
def get_stock_detail_consolidated(
    ticker: str,
    db: Session = Depends(get_db),
):
    """Get consolidated stock detail for the frontend detail page."""
    import json
    import redis as redis_lib
    from app.core.config import settings

    ticker = ticker.upper()

    # Cache in Redis for 60s — avoids 3 consecutive Polygon calls on every page visit.
    _redis = None
    cache_key = f"stock_detail:{ticker}"
    try:
        _redis = redis_lib.from_url(settings.REDIS_URL)
        cached = _redis.get(cache_key)
        if cached:
            return json.loads(cached)
    except Exception:
        pass  # Redis unavailable — fall through to live fetch

    try:
        if StockDataService.is_futures_ticker(db, ticker):
            # ... futures block ...
            try:
                if _redis:
                    _redis.setex(cache_key, 60, json.dumps(result))
            except Exception:
                pass
            return result

        # ... stocks block ...
        try:
            if _redis:
                _redis.setex(cache_key, 60, json.dumps(result))
        except Exception:
            pass
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching stock details: {str(e)}")
```

After:
```python
@router.get("/details/{ticker}")
def get_stock_detail_consolidated(
    ticker: str,
    db: Session = Depends(get_db),
):
    """Get consolidated stock detail for the frontend detail page."""
    ticker = ticker.upper()

    def _fetch():
        if StockDataService.is_futures_ticker(db, ticker):
            from app.models import MonitoredStock
            from app.models.futures_aggregate import FuturesAggregate
            from sqlalchemy import func

            stock = (
                db.query(MonitoredStock)
                .filter(
                    MonitoredStock.ticker == ticker,
                    MonitoredStock.asset_class == "futures",
                    MonitoredStock.is_active == True,
                )
                .first()
            )
            latest_close = (
                db.query(FuturesAggregate.close)
                .filter(FuturesAggregate.symbol == ticker)
                .order_by(FuturesAggregate.timestamp.desc())
                .limit(1)
                .scalar()
            )
            return {
                "ticker": ticker,
                "info": {
                    "longName": (stock.company_name if stock else None) or ticker,
                    "shortName": ticker,
                    "sector": (stock.sector if stock else None) or "Futures",
                    "industry": "Futures",
                    "marketCap": None,
                },
                "pre_market": {
                    "pre_market_volume": 0,
                    "pre_market_high": None,
                    "pre_market_low": None,
                    "pre_market_open": None,
                    "pre_market_close": None,
                },
                "latest_price": float(latest_close) if latest_close else None,
                "last_updated": datetime.now(timezone.utc).isoformat(),
            }

        info = StockDataService.get_stock_info(ticker)
        pre_market = StockDataService.get_pre_market_data(ticker)
        today = get_market_today().strftime("%Y-%m-%d")
        minute_aggs = StockDataService.get_aggregates(ticker, 1, "minute", today, today, limit=1)
        latest_price = minute_aggs[-1]["close"] if minute_aggs else None

        from app.models.stock_split import StockSplit
        recent_splits_query = (
            db.query(StockSplit)
            .filter(StockSplit.ticker == ticker)
            .order_by(StockSplit.execution_date.desc())
            .limit(5)
            .all()
        )
        recent_splits = [
            {
                "execution_date": s.execution_date.isoformat(),
                "split_from": float(s.split_from),
                "split_to": float(s.split_to),
                "adjusted": s.adjustments_applied_at is not None,
            }
            for s in recent_splits_query
        ]
        split_adjustment_pending = any(s.adjustments_applied_at is None for s in recent_splits_query)

        return {
            "ticker": ticker,
            "info": info,
            "pre_market": pre_market,
            "latest_price": latest_price,
            "last_updated": datetime.now(timezone.utc).isoformat(),
            "recent_splits": recent_splits,
            "split_adjustment_pending": split_adjustment_pending,
        }

    try:
        return get_cached(f"mh:stocks:details:{ticker}", 60, _fetch)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching stock details: {str(e)}")
```

Also remove the now-unused `import json` and `import redis as redis_lib` from inside the function (they were inline imports).

#### Step 6.3 — Verify tests pass

```bash
docker-compose exec backend python -m pytest tests/api/test_stocks.py -v 2>&1 | tail -20
# Expected: all tests pass including the two new cache tests
```

#### Step 6.4 — Verify full test suite

```bash
docker-compose exec backend python -m pytest tests/api/ -v 2>&1 | tail -30
# Expected: all tests pass (no regressions)
```

#### Step 6.5 — Commit

```bash
git add backend/app/routers/stocks.py
git commit -m "feat(cache): migrate GET /api/stocks/details/{ticker} inline Redis to get_cached"
```

---

## Validation Checklist

After all tasks complete, run the full sequence:

```bash
# 1. Backend reloaded
docker-compose logs backend --tail=10

# 2. Verify cache keys with real Redis
docker-compose exec backend python -c "
from app.core.cache import get_redis
r = get_redis()
print('Redis connected:', r is not None)
"

# 3. Curl each endpoint — expect 200
curl -s http://localhost:8000/api/scanner/types | python -m json.tool | head -5
curl -s http://localhost:8000/api/scanner/configs | python -m json.tool | head -5
curl -s http://localhost:8000/api/system/status | python -m json.tool
curl -s http://localhost:8000/api/system/storage | python -m json.tool | head -5
curl -s http://localhost:8000/api/universe/list | python -m json.tool | head -5
curl -s http://localhost:8000/api/stocks/details/AAPL | python -m json.tool | head -5

# 4. Verify cache keys populated in Redis
docker-compose exec redis redis-cli KEYS "mh:*"
# Expected: mh:scanner:types, mh:system:status, mh:system:storage, mh:universe:list

# 5. Full test suite — no regressions
docker-compose exec backend python -m pytest tests/api/ -v 2>&1 | tail -5
```

---

## Spec Coverage Crosscheck

| Requirement | Task |
|-------------|------|
| Create `core/cache.py` with `get_redis`, `get_cached`, `invalidate`, `invalidate_pattern`, `cache_response` | Task 1 |
| Cache `GET /api/scanner/types` (3600 s) | Task 2 |
| Cache `GET /api/scanner/configs` (300 s) | Task 3 |
| Cache `GET /api/system/status` (30 s) | Task 4 |
| Cache `GET /api/system/storage` (300 s) | Task 4 |
| Cache `GET /api/universe/list` (60 s, `include_stats=True` only) | Task 5 |
| Cache `GET /api/stocks/details/{ticker}` (60 s) | Task 6 |
| Mutation invalidation: create/update/delete/refresh-stats → `mh:universe:list` | Task 5 |
| Migrate inline Redis in stocks.py | Task 6 |
| Redis failure transparent (fall through to DB/provider) | Task 1 (`get_cached`, `invalidate`) |
| Route handler signatures unchanged | All tasks — no signature changes |
| `include_stats=False` bypasses cache | Task 5 |
