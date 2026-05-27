# Redis Application Caching Design

**Issue:** #98 — Implement Redis application caching for hot endpoints  
**Date:** 2026-05-27

## Overview

Redis is already running as a first-class service in MarketHawk but is only used as a Celery broker and for scan/sync state keys. Every API request hits PostgreSQL directly, including for data that changes on timescales of seconds to minutes. This issue adds application-level caching to six hot endpoints using a new `core/cache.py` utility module, bringing Performance Readiness from its current 2/5 baseline.

The primary benefit is DB load reduction and faster responses on endpoints that the frontend polls repeatedly (React Query refetch intervals, dashboard status checks). The secondary benefit is migrating ad-hoc inline Redis code in the stocks router to a single consistent pattern.

## Requirements

1. Create `backend/app/core/cache.py` with a shared Redis client factory and read-through cache helpers.
2. Apply caching to six identified endpoints with endpoint-appropriate TTLs.
3. Implement mutation-driven cache invalidation for universe endpoints (create/update/delete/refresh-stats).
4. Migrate the existing inline Redis caching in `/api/stocks/details/{ticker}` to use the new utility.
5. Redis failures must be transparent to callers — if Redis is down, fall through to the database/provider.
6. No stale-while-revalidate, no Prometheus metrics integration (deferred — see §Alternatives).
7. All existing route handler signatures remain unchanged (no forced async conversion).

## Architecture

### `backend/app/core/cache.py`

The module provides four building blocks:

```python
# 1. Shared client factory — process-scoped singleton
@lru_cache(maxsize=1)
def get_redis() -> redis.Redis | None:
    """Return a sync Redis client, or None if REDIS_URL is unset.
    The redis.Redis() constructor does not connect eagerly; connection errors
    surface at command time and are caught inside get_cached/invalidate."""

# 2. Read-through helper — the primary pattern
def get_cached(key: str, ttl: int, fn: Callable[[], T]) -> T:
    """Return cached value if present; otherwise call fn(), cache the result, return it.
    If Redis is unavailable, calls fn() and returns without caching."""

# 3. Invalidation helpers
def invalidate(key: str) -> None:
    """Delete a single cache key. No-op if Redis is unavailable."""

def invalidate_pattern(pattern: str) -> None:
    """Delete all keys matching a glob pattern (SCAN + DEL). No-op if Redis unavailable."""

# 4. Convenience decorator for the simplest GET-only endpoints
def cache_response(key: str, ttl: int):
    """Decorator for parameter-less GET handlers. Wraps the handler body in get_cached()."""
```

The decorator is a thin convenience layer over `get_cached` — no separate implementation path.

#### Client configuration

- Uses `settings.REDIS_URL` (already present in `core/config.py`)
- Synchronous `redis.Redis` client (matches all existing sync route handlers and the existing usage in `services/scanner.py:check_concurrency`)
- `decode_responses=True` (strings, not bytes)
- `socket_connect_timeout=1`, `socket_timeout=0.5` — Redis failures fail fast and fall through

#### Cache key namespace

All keys are prefixed `mh:` to avoid collisions with Celery and live-scanner keys:

| Endpoint | Cache Key | TTL |
|----------|-----------|-----|
| `GET /api/scanner/types` | `mh:scanner:types` | 3600 s (1 hour) |
| `GET /api/scanner/configs` | `mh:scanner:configs` | 300 s (5 min) |
| `GET /api/system/status` | `mh:system:status` | 30 s |
| `GET /api/system/storage` | `mh:system:storage` | 300 s (5 min) |
| `GET /api/universe/list` | `mh:universe:list` | 60 s (1 min) |
| `GET /api/stocks/details/{ticker}` | `mh:stocks:details:{ticker}` | 60 s |

### Endpoint changes

#### `GET /api/scanner/types` (`routers/scanner.py`)

Wrap with `@cache_response("mh:scanner:types", ttl=3600)`. The handler builds from the in-memory `_REGISTRY` — already fast — but caching removes even that overhead and is consistent with the other endpoints.

#### `GET /api/scanner/configs` (`routers/scanner.py`)

Replace direct DB query with `get_cached("mh:scanner:configs", 300, lambda: ...)`.

No mutation invalidation is wired because no mutation endpoints for `ScannerConfig` exist. The 5-minute TTL is sufficient: scanner configs are seeded from SQL and managed outside the API (admin-only, three records in production). When mutation endpoints are introduced in a future issue, they must call `invalidate("mh:scanner:configs")`.

#### `GET /api/system/status` (`routers/system.py`)

Wrap the `get_system_status` handler body with `get_cached("mh:system:status", 30, ...)`. The 30-second TTL is intentional: market status transitions (pre-market, open, post-market, closed) happen on fixed ET boundaries, and the IBKR reachability check is best-effort.

#### `GET /api/system/storage` (`routers/system.py`)

Wrap with `get_cached("mh:system:storage", 300, ...)`. The pg_stat query is the most expensive call in scope; a 5-minute TTL significantly reduces DB catalog load.

#### `GET /api/universe/list` (`routers/universe.py`)

Wrap `list_stock_universes()` with `get_cached("mh:universe:list", 60, ...)`. Add `invalidate("mh:universe:list")` calls to the following mutation endpoints in the same router:

| Mutation endpoint | Invalidation point |
|------------------|--------------------|
| `POST /api/universe/create` | After `db.commit()` |
| `PUT /api/universe/{id}` | After `db.commit()` |
| `DELETE /api/universe/{id}` | After `db.commit()` |
| `POST /api/universe/{id}/refresh-stats` | After stats update |

The `include_stats=False` query variant returns a subset of the same data. Key the cache on the full response (`include_stats=True`) since that is the frontend default. If `include_stats=False` is requested, bypass the cache (the call is cheap — reads from pre-computed DB fields with no extra queries).

#### `GET /api/stocks/details/{ticker}` (`routers/stocks.py`)

This endpoint already contains inline Redis caching (`redis_lib.from_url(...)`, `r.get(key)`, `r.setex(key, 60, ...)`). Replace the entire inline block with `get_cached(f"mh:stocks:details:{ticker}", 60, ...)`. This is the key migration use case — remove the scattered `redis_lib.from_url` call and unify under `get_redis()`.

### Serialization

Cache values are stored as JSON strings. `get_cached` handles serialization internally: before storing, it calls `json.dumps` on the value returned by `fn`; on cache hit, it calls `json.loads` and returns the resulting dict/list. `fn` must return a JSON-serializable Python object — route handlers should call `.model_dump()` on Pydantic response models before building the lambda passed to `get_cached`. On retrieval, the caller deserializes the dict back to the response type via `.model_validate()` if needed, or returns the dict directly (FastAPI serializes it).

## Alternatives Considered

### 1. Third-party caching library (aiocache, fastapi-cache2)

**Rejected.** Adds a dependency for a straightforward use case. The existing codebase has no precedent for third-party caching middleware; a focused `core/cache.py` module is consistent with how `core/error_tracking.py` and `core/config.py` isolate cross-cutting concerns.

### 2. Async Redis client throughout

**Rejected for this issue.** The target route handlers are all synchronous `def` functions. Converting them to `async def` to use `redis.asyncio` is a separate refactor with its own risks (thread pool behaviour, SQLAlchemy async session handling). The existing codebase uses sync Redis in `services/scanner.py`; this issue follows the same pattern. Async Redis migration can be pursued separately.

### 3. Stale-while-revalidate for market data

**Deferred.** Would require either `asyncio.create_task` (forces async conversion) or FastAPI `BackgroundTasks` (requires route signature changes). The 30-second TTL on `mh:system:status` is adequate for the current polling frequency. Revisit after #95 (Prometheus) lands — cache hit rate metrics will show whether SWR is worth the complexity.

### 4. HTTP caching headers (Cache-Control, ETag)

**Out of scope.** Reverse proxy/CDN layer does not exist in this stack. Redis-layer caching is more appropriate for an internal API accessed exclusively by the React frontend.

## Open Questions

- **`GET /api/universe/list` with `include_stats=False`**: If this variant turns out to be called heavily in production, a separate cache key `mh:universe:list:no-stats` can be added with a matching invalidation in the same mutation hooks.
- **Cache warming on startup**: Currently, the first request after a deployment or Redis flush will miss. Not an issue at current traffic levels, but worth revisiting if the system sees sustained high load.

## Assumptions

- **Redis is reachable at startup.** The `main.py` lifespan already tests Redis connectivity on startup and logs warnings. `get_redis()` returning `None` (Redis down) must be a gracefully handled non-blocking condition for all six endpoints.
- **Serialized response size fits in Redis memory.** Universe list and scanner configs are small (< 10 KB per entry). Stock details may be larger; confirmed acceptable within the default Redis `maxmemory` policy (`noeviction` until configured otherwise).
- **No multi-process invalidation race condition.** The backend runs as a single Uvicorn process in development. In production (multiple workers or Celery), the shared Redis key is the single source of truth; invalidation from any process propagates to all. This is the correct behaviour.
- **`mh:` key prefix does not conflict with any existing keys.** Verified: existing keys follow `universe:{id}:scan:*`, `universe:*:sync`, and Celery internal patterns. No `mh:` prefix exists.
