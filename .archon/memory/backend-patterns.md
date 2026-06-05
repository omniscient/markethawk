# Backend Patterns — Accumulated Lessons

This file is maintained automatically by the dark factory implement agent. Do not edit manually.
Entries are advisory. If an entry conflicts with CLAUDE.md or ARCHITECTURE.md, follow those documents.

## Backend: Models

- [PATTERN] Every new SQLAlchemy model must be imported in `backend/app/models/__init__.py` or it will not be included in `Base.metadata` and alembic will not generate a migration for it. <!-- bootstrap date:2026-06-02 expires:2026-12-02 source:implement -->

- [AVOID] Never use synchronous SQLAlchemy patterns (`session.query()`, sync `relationship()` lazy loads) — the app uses `AsyncSession` throughout. All queries use `select()` + `await session.execute()`. Sync lazy-loading raises `MissingGreenlet` in asyncpg. <!-- bootstrap date:2026-06-02 expires:2026-12-02 source:implement -->

## Backend: API Routes

- [PATTERN] New routers must be registered in `backend/app/main.py` via `app.include_router(router, prefix="/api/v1/<resource>")`. The router file itself should not set a prefix — it lives in the `include_router` call. <!-- bootstrap date:2026-06-02 expires:2026-12-02 source:implement -->

- [PATTERN] The SlowAPI `limiter` instance is in `app/core/rate_limits.py`, not `app/main.py`. Import from `core.rate_limits` to avoid the circular import that would arise if the limiter were in `main.py`. <!-- bootstrap date:2026-06-02 expires:2026-12-02 source:implement -->

## Backend: Celery Tasks

- [AVOID] For `bind=True` Celery tasks in tests, never call `task.run(mock_self)` — `.run` is already partially bound to the task instance, so passing `mock_self` adds an extra positional arg and raises `TypeError`. Instead call `task.run()` (no args) and use `patch.object(task, 'retry', side_effect=...)` to control retry behavior. <!-- issue:#156 date:2026-06-03 expires:2026-12-03 source:implement -->

- [AVOID] Never read `universe_id` from `ScannerConfig.parameters.get("universe_id")` in scheduled tasks — if the seeded config lacks this key the task silently skips all work. `universe_id` is now a first-class NOT NULL FK column on `scanner_configs`; read it as `cfg.universe_id`. <!-- issue:#156 date:2026-06-03 expires:2026-12-03 source:implement -->

- [PATTERN] When importing a symbol inside a Celery task function body (e.g. `from app.utils.session import get_market_today`), patch it at its source module (`app.utils.session.get_market_today`), not at `app.tasks.scanning.get_market_today` — the latter name doesn't exist at module level and `patch()` will raise `AttributeError`. <!-- issue:#156 date:2026-06-03 expires:2026-12-03 source:implement -->

- [PATTERN] When adding a NOT NULL FK column to a table that already has rows: (1) add nullable, (2) UPDATE to backfill default, (3) ALTER to NOT NULL — all in the same Alembic migration. The universe_id migration (c7d8e9f0a1b2) demonstrates this three-step pattern for `scanner_configs`. <!-- issue:#156 date:2026-06-03 expires:2026-12-03 source:implement -->

- [PATTERN] Test fixtures that create ScannerConfig rows must now supply `universe_id`; if no universe exists in the test transaction, create one inline (see `seed_scanner_configs` in `tests/fixtures/core.py` for the pattern). <!-- issue:#156 date:2026-06-03 expires:2026-12-03 source:implement -->

## Backend: Middleware

- [PATTERN] All middleware in `main.py` is implemented as pure ASGI classes (not `BaseHTTPMiddleware`). Pure ASGI leaves the app's single-message response intact so `GZipMiddleware` compresses it correctly; `BaseHTTPMiddleware` re-emits responses as a stream, causing chunked-gzip bodies that browsers never terminate. See the comment at `main.py:242` for details. <!-- issue:#192 date:2026-06-05 expires:2026-12-05 source:refine -->

- [PATTERN] Middleware registration order in Starlette is LIFO for "outermost": the last `app.add_middleware()` call is outermost (processes inbound requests first). Equivalently: "first added = innermost, closest to route handlers." To make middleware B run *after* middleware A on inbound requests (i.e., B is between A and the routes), register B before A in the code. <!-- issue:#192 date:2026-06-05 expires:2026-12-05 source:refine -->

## Backend: Migrations

- [PATTERN] After any model change: `cd backend && python -m alembic revision --autogenerate -m "description" && python -m alembic upgrade head`. Never skip the `upgrade head` step — the preview stack applies migrations at startup, but the local test suite does not. <!-- bootstrap date:2026-06-02 expires:2026-12-02 source:implement -->

- [FIX] If `alembic revision --autogenerate` produces an empty migration (no `op.` calls in the body), verify that the model is imported in `backend/app/models/__init__.py` and that `Base` is the same `DeclarativeBase` instance as in `backend/app/core/database.py`. <!-- bootstrap date:2026-06-02 expires:2026-12-02 source:implement -->

- [FIX] When a migration backfills a FK column (e.g. `UPDATE scanner_configs SET universe_id = 1`), ensure the referenced row exists BEFORE the UPDATE by inserting it with `ON CONFLICT (id) DO NOTHING` — CI databases start empty (no seed SQL applied), so the FK constraint will fail if the parent row is absent. See migration `c7d8e9f0a1b2` for the pattern. <!-- issue:#156 date:2026-06-03 expires:2026-12-03 source:implement -->
