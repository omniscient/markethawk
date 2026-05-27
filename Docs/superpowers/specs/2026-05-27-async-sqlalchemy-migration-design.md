# Async SQLAlchemy Migration

**Date:** 2026-05-27
**Status:** Spec — Pending Review
**Issue:** #101
**Scope:** `backend/app/core/database.py`, `backend/app/routers/`, `backend/app/core/config.py`, `backend/tests/conftest.py`, `backend/requirements.txt`

## Problem

The backend uses synchronous SQLAlchemy (`psycopg2`) despite FastAPI supporting async natively. Every database operation blocks an OS thread. FastAPI's async request handling is unused — all routes are `def`, not `async def`. Meanwhile, `asyncpg==0.31.0` is already installed but unreferenced.

The result: under concurrent load, the worker thread pool fills with blocked DB calls. New requests queue behind them. Non-DB async work (e.g., WebSocket management, Polygon HTTP calls) is serialised with DB-bound work unnecessarily.

## Goals

1. Replace sync `create_engine` + `psycopg2` with `create_async_engine` + `asyncpg`
2. Convert all FastAPI router endpoints to `async def`
3. Free the event loop during database I/O
4. Keep Celery tasks and Alembic migrations on a dedicated sync engine — they cannot go async
5. Preserve the existing SAVEPOINT-based test isolation model

## Non-Goals

- Converting Celery task bodies to `async def` — Celery workers are synchronous by design
- Removing the sync `SessionLocal` — Celery tasks will always need it
- Migrating service layer methods to `async def` — out of scope for this migration (see Alternatives)
- Live scanner (`backend/live_scanner/`) — it is already a standalone asyncio process with its own DB handling

## Requirements

### R1 — Async engine and session factory
`backend/app/core/database.py` must expose:
- `async_engine` created with `create_async_engine` and the `postgresql+asyncpg://` URL
- `AsyncSessionLocal = async_sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)`
- `async def get_async_db()` as an async generator yielding `AsyncSession`
- Existing `engine`, `SessionLocal`, and `get_db()` kept for Celery tasks and Alembic

The async URL is derived from `settings.DATABASE_URL` by substituting the driver scheme:
```python
async_url = settings.DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1)
```

### R2 — Connection pool configuration
`create_async_engine` must be configured with `pool_size`, `max_overflow`, and `pool_pre_ping=True`. Exact values come from Issue #85 (connection pooling), which must be merged before Phase 1 of this migration.

### R3 — Router conversion
All router endpoints that use `db: Session = Depends(get_db)` must be converted to:
```python
async def endpoint_name(..., db: AsyncSession = Depends(get_async_db)):
```

### R4 — Service calls remain synchronous; routers use run_in_executor
Service methods (`ScannerService`, `AlertRuleService`, `StockDataService`, etc.) are called from both routers and Celery tasks. They will **not** become `async def` in this migration. Routers delegate blocking service calls to a thread pool:
```python
import asyncio
loop = asyncio.get_event_loop()
result = await loop.run_in_executor(None, lambda: some_service.method(sync_session))
```
When a router calls `run_in_executor`, it must create a fresh sync `Session` from `SessionLocal` inside the lambda — the `AsyncSession` from `get_async_db()` must not be shared with sync service code.

### R5 — Celery tasks unchanged
All tasks in `app/tasks/` continue to use `SessionLocal()` directly. No changes to task bodies, retry logic, or scheduling.

### R6 — Alembic migrations unchanged
`alembic/env.py` keeps the sync `engine` for migration execution. No async migration runner is introduced.

### R7 — Test infrastructure: sync TestClient preserved
`TestClient` from Starlette runs `async def` endpoints correctly via an internal event loop. The `TestClient` wrapper in `tests/conftest.py` is not changed. The `db` fixture is updated per router module as it migrates: once a router's tests need `AsyncSession`, that module's `conftest.py` gets an async `db` fixture. The global SAVEPOINT rollback model stays as-is for modules that have not yet migrated.

### R8 — psycopg2-binary removed
After all routers are converted and Celery tasks verified, `psycopg2-binary` is removed from `requirements.txt`. The sync `engine` in `database.py` switches to the `postgresql+asyncpg://` URL as well (asyncpg can back a sync engine for Alembic via the `run_sync` pattern).

## Architecture

### Phase 1 — Async engine setup (1 PR)

Scope: `backend/app/core/database.py` only.

Add async engine and session factory **alongside** existing sync engine. No routers change. Both `get_db()` (sync) and `get_async_db()` (async) are exported. Backend still starts and behaves identically.

```python
# new additions
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

_async_url = settings.DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1)
async_engine = create_async_engine(_async_url, pool_size=10, max_overflow=5, pool_pre_ping=True)
AsyncSessionLocal = async_sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)

async def get_async_db():
    async with AsyncSessionLocal() as session:
        yield session
```

Gating: Issue #85 must be merged first so pool config values are already known.

### Phase 2 — Per-group router conversion (4-5 PRs)

Routers are converted in logical groups. Each group PR:
1. Changes `def endpoint(... db: Session = Depends(get_db))` → `async def endpoint(... db: AsyncSession = Depends(get_async_db))`
2. Converts any direct `db.query(...)` / `db.add()` / `db.commit()` calls at the router level to `await db.execute(select(...))` / `await db.commit()` etc.
3. Wraps sync service calls with `run_in_executor` where services do their own DB work via a separate `SessionLocal()` instance

Suggested grouping:

| Group | Routers | LOC | Notes |
|-------|---------|-----|-------|
| A | `health.py`, `journal.py`, `watchlist.py`, `news.py`, `tweets.py` | ~383 | Simple CRUD; low risk |
| B | `stocks.py`, `futures.py` | ~566 | Provider calls; some inline DB work |
| C | `universe.py`, `system.py` | ~878 | Medium complexity |
| D | `alerts.py`, `outcomes.py`, `auto_trading.py` | ~1,119 | Most complex; alert dispatch chain |
| E | `scanner.py` | ~857 | Largest file; critical path; last |

`live_data.py` is already `async def` throughout and has no `Depends(get_db)` — no changes needed.

### Phase 3 — psycopg2 removal (1 PR)

After all router groups pass CI:
- Remove `psycopg2-binary` from `requirements.txt`
- Update `alembic/env.py` to use `run_sync` with the asyncpg-backed engine (standard Alembic async pattern) or keep a thin psycopg2-free sync connection
- Confirm `docker-compose build` succeeds and `alembic upgrade head` runs cleanly

### File changes summary

| File | Change |
|------|--------|
| `app/core/database.py` | Add async engine, `AsyncSessionLocal`, `get_async_db()` |
| `app/routers/*.py` (14 files) | `def` → `async def`, `Depends(get_db)` → `Depends(get_async_db)`, inline `run_in_executor` for service calls |
| `tests/conftest.py` | No change to `TestClient`; `db` fixture updated per module |
| `requirements.txt` | Remove `psycopg2-binary` (Phase 3) |
| `alembic/env.py` | Minor update for psycopg2-free sync connection (Phase 3) |

## Alternatives Considered

### Alternative A: Full service async conversion (Phase 4 as originally written)

Convert all service methods to `async def`, taking `AsyncSession`. Celery tasks call services via `asyncio.run()` or replicate DB queries inline.

**Pros:** True end-to-end non-blocking DB access; services consistent with routers; no `run_in_executor` overhead.

**Cons:** Services are also called by Celery workers (synchronous context). Using `asyncio.run()` inside a Celery task is fragile — Celery sometimes shares an event loop, causing `RuntimeError: This event loop is already running`. Replicating DB logic inline in tasks creates duplication. Total scope approximately doubles.

**Decision:** Deferred. The benefit (removing `run_in_executor` overhead) is marginal for DB-bound operations. This can be a follow-on migration after the router layer is stable.

### Alternative B: Thread pool only (no async engine)

Mark all endpoints `async def`, keep sync `get_db()`. FastAPI automatically runs sync dependencies in a thread pool executor.

**Pros:** No SQLAlchemy async API changes at all.

**Cons:** Does not introduce `asyncpg`. Thread pool continues to be the bottleneck. Doesn't achieve the stated goal of non-blocking DB access.

**Decision:** Rejected. This is already the current behaviour — FastAPI already wraps sync dependencies in executors. It provides no improvement.

## Open Questions

- **Pool sizing in Phase 1**: The correct `pool_size` and `max_overflow` values depend on Issue #85 conclusions. Phase 1 is blocked on that merge.
- **Alembic async pattern**: Some projects keep a thin `psycopg2` install solely for Alembic. Others use `asyncpg` + `run_sync`. Either approach is valid; the implementer should choose based on whether a second driver in `requirements.txt` is acceptable.

## Assumptions

- **[A1]** Issue #85 (connection pooling) is merged before Phase 1 begins. Pool config values are known.
- **[A2]** Issue #89 (integration tests / 60% coverage gate) is substantially complete before Phase 2 begins, so the router conversions have meaningful test coverage to catch regressions.
- **[A3]** The `DATABASE_URL` env var uses the `postgresql://` scheme. Environments using `postgres://` (Heroku-style) require an additional substitution step.
- **[A4]** Celery worker processes will never call `get_async_db()`. All task bodies use `SessionLocal()` directly.
- **[A5]** `expire_on_commit=False` on `AsyncSessionLocal` is appropriate — async access patterns commonly access attributes after commit without re-issuing a `SELECT`.
