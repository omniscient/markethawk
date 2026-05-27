# SQLAlchemy Connection Pooling — Design Spec

**Issue**: [#85 — Configure SQLAlchemy connection pooling](https://github.com/omniscient/markethawk/issues/85)
**Date**: 2026-05-27
**Status**: Pending Review

## Overview

`backend/app/core/database.py` calls `create_engine()` with no pool arguments, leaving SQLAlchemy at its default `pool_size=5` with no reconnect safety. The system runs five services that each create their own engine instance against the same PostgreSQL database (backend API, celery-worker, celery-beat, forecast-worker, live-scanner). Under concurrent load this risks connection exhaustion; after a PostgreSQL restart, stale connections silently fail until the worker process is recycled.

This spec adds explicit, environment-configurable pool parameters to `create_engine()` using conservative defaults that stay well within PostgreSQL's default `max_connections=100`.

## Changes

### `backend/app/core/config.py`

Add five new settings to the `Settings` class following the existing `os.getenv()` + typed default pattern used throughout the file:

```python
# ── Database connection pool ────────────────────────────────────────────
DB_POOL_SIZE: int = int(os.getenv("DB_POOL_SIZE", "5"))
DB_MAX_OVERFLOW: int = int(os.getenv("DB_MAX_OVERFLOW", "10"))
DB_POOL_PRE_PING: bool = os.getenv("DB_POOL_PRE_PING", "true").lower() == "true"
DB_POOL_RECYCLE: int = int(os.getenv("DB_POOL_RECYCLE", "3600"))
DB_POOL_TIMEOUT: int = int(os.getenv("DB_POOL_TIMEOUT", "30"))
```

No changes to `get_settings()` or `@lru_cache` — the new fields are picked up automatically.

### `backend/app/core/database.py`

Replace the bare `create_engine(settings.DATABASE_URL)` call with one that passes all five pool parameters from `settings`:

```python
engine = create_engine(
    settings.DATABASE_URL,
    pool_size=settings.DB_POOL_SIZE,
    max_overflow=settings.DB_MAX_OVERFLOW,
    pool_pre_ping=settings.DB_POOL_PRE_PING,
    pool_recycle=settings.DB_POOL_RECYCLE,
    pool_timeout=settings.DB_POOL_TIMEOUT,
)
```

No other changes to `database.py` — `SessionLocal`, `Base`, and `get_db()` are unchanged.

## Default Values and Rationale

| Parameter | Default | Rationale |
|-----------|---------|-----------|
| `DB_POOL_SIZE` | `5` | Matches SQLAlchemy's current implicit default; safe for all services with room to grow |
| `DB_MAX_OVERFLOW` | `10` | Allows burst to 15 connections per service × 5 services = 75 max, well within PostgreSQL's default 100 |
| `DB_POOL_PRE_PING` | `true` | Reconnects stale connections automatically after PostgreSQL restarts without propagating errors to callers |
| `DB_POOL_RECYCLE` | `3600` | Recycles connections every hour, preventing OS-level TCP keepalive timeouts on long-idle pools |
| `DB_POOL_TIMEOUT` | `30` | Waits up to 30 seconds for a pool slot before raising; prevents indefinite hangs under saturation |

## Operator Tuning

Operators who need higher throughput can override per-service in `docker-compose.yml` or `.env`. For example, to give the backend API a larger pool:

```yaml
backend:
  environment:
    DB_POOL_SIZE: "20"
    DB_MAX_OVERFLOW: "20"
```

Operators who increase pool sizes are responsible for also raising PostgreSQL's `max_connections` (e.g., via `command: postgres -c max_connections=200` in docker-compose). That tuning is outside the scope of this issue.

## Out of Scope

- Raising PostgreSQL `max_connections` in docker-compose (separate infrastructure concern)
- Adding a PgBouncer connection pooling proxy
- Async engine configuration (the current engine is synchronous; async migration is a separate effort)
- Changes to Celery worker concurrency settings

## Verification

After deployment, confirm:

```bash
# Backend reloaded cleanly with new pool config
docker-compose logs backend --tail=20

# Confirm engine is reachable and pool params took effect
docker-compose exec backend python -c "
from app.core.database import engine
print('pool_size:', engine.pool.size())
print('pool_pre_ping:', engine.dialect.pool_pre_ping)
"
```

No migration required — this is a pure configuration change with no schema impact.

## Acceptance Criteria

- [ ] `create_engine()` in `database.py` passes all five pool parameters sourced from `settings`
- [ ] All five settings have `os.getenv()` defaults in `config.py` with the values above
- [ ] Backend starts cleanly with default env (no new env vars required in `.env`)
- [ ] Setting `DB_POOL_SIZE=20` in the environment is reflected at runtime
- [ ] `pool_pre_ping=True` reconnects after `docker-compose restart postgres` without manual backend restart
