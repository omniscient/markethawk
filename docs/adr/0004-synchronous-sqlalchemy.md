# ADR-004: Synchronous SQLAlchemy ORM

**Date**: 2026-05-28  
**Status**: Accepted (short-term; async migration tracked in #103)

## Context

SQLAlchemy 2.0 ships both a synchronous and an async ORM. The project also has `asyncpg` installed (a pure-async PostgreSQL driver), which looks like async SQLAlchemy is in use — it is not. The actual synchronous driver is `psycopg2-binary`.

At the time the project was bootstrapped, the REST API surface was small, the team was more familiar with synchronous SQLAlchemy patterns, and FastAPI's `Depends(get_db)` model works naturally with sync generators. Introducing async SQLAlchemy at that stage would have added complexity (all session access becomes `await session.execute(...)`, all relationships become `await session.run_sync(...)`) without a clear bottleneck to justify it.

`asyncpg` was added for a future async migration and for Celery compatibility experiments; it is not currently wired into the ORM.

### ARCHITECTURE.md note

The architecture diagram currently shows `asyncpg ──> postgres:5432`. This is inaccurate — the backend uses `psycopg2`. The diagram correction is a separate follow-up change.

### Options considered

**A. Synchronous SQLAlchemy (psycopg2)** — Simple, well-understood, fits FastAPI sync route handlers. Known downside: each DB call blocks the event loop thread.

**B. Async SQLAlchemy (asyncpg)** — Non-blocking I/O; route handlers must be `async def` throughout; relationship loading needs explicit `selectinload`/`joinedload` or `run_sync`. Correct choice at scale but requires an all-or-nothing migration.

**C. Encode Databases / raw asyncpg** — Lightweight alternative for async DB access without the full SQLAlchemy ORM. Rejects the ORM entirely; would require rewriting all model queries.

## Decision

**Option A**: synchronous SQLAlchemy with `psycopg2-binary`. This is a deliberate short-term choice, not a permanent one.

The consequence — that route handlers block the event loop when a DB query runs — is acceptable at the current scale (single-operator, low concurrency). The async migration is tracked as issue #103. ADR-004 should be superseded by that work.

## Consequences

- Route handlers that call `get_db()` block the event loop for the duration of the DB round-trip.
- Under high concurrency (many simultaneous users or automated scan submissions) this becomes a throughput ceiling before connection pool exhaustion.
- `asyncpg` in `requirements.txt` is not used by the ORM today; it is retained for the future migration.
- Any new service or router added before #103 lands should follow the existing sync pattern to avoid a half-async, half-sync ORM setup.
