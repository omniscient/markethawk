# Backend Patterns — Accumulated Lessons

This file is maintained automatically by the dark factory implement agent. Do not edit manually.
Entries are advisory. If an entry conflicts with CLAUDE.md or ARCHITECTURE.md, follow those documents.

## Backend: Models

- [INVALID: app uses synchronous SQLAlchemy (Session/psycopg2), not AsyncSession — ADR-0004] Never use synchronous SQLAlchemy patterns (`session.query()`, sync `relationship()` lazy loads) — the app uses `AsyncSession` throughout. All queries use `select()` + `await session.execute()`. Sync lazy-loading raises `MissingGreenlet` in asyncpg. <!-- bootstrap date:2026-06-02 expires:2026-12-02 source:implement -->

## Backend: API Routes

- [PATTERN] `AuthMiddleware` in `main.py` short-circuits for non-HTTP scopes — WebSocket routes are NOT covered. Protect WS endpoints by adding `_user: User = Depends(ws_get_current_user)` from `app.core.auth`; this raises `WebSocketException(code=1008)` before `accept()` if the cookie is absent or invalid. <!-- issue:#191 date:2026-06-05 expires:2026-12-05 source:implement -->

- [AVOID] Do not raise `HTTPException` inside a WebSocket dependency — FastAPI will not convert it to a WS close frame. Use `WebSocketException(code=1008, reason="...")` (importable from `fastapi`) instead, which FastAPI closes gracefully before `accept()` is called. <!-- issue:#191 date:2026-06-05 expires:2026-12-05 source:implement -->

- [AVOID] Never wrap a DB call in bare `except Exception` inside a WebSocket dependency to convert errors to 1008 — it hides outages as auth failures and diverges from HTTP behavior. Guard only auth-specific failures (missing token, JWTError, bad UUID) and let DB errors propagate. <!-- issue:#191 date:2026-06-06 expires:2026-12-06 source:implement -->

## Backend: Celery Tasks

- [AVOID] For `bind=True` Celery tasks in tests, never call `task.run(mock_self)` — `.run` is already partially bound to the task instance, so passing `mock_self` adds an extra positional arg and raises `TypeError`. Instead call `task.run()` (no args) and use `patch.object(task, 'retry', side_effect=...)` to control retry behavior. <!-- issue:#156 date:2026-06-03 expires:2026-12-03 source:implement -->

- [PATTERN] When importing a symbol inside a Celery task function body (e.g. `from app.utils.session import get_market_today`), patch it at its source module (`app.utils.session.get_market_today`), not at `app.tasks.scanning.get_market_today` — the latter name doesn't exist at module level and `patch()` will raise `AttributeError`. <!-- issue:#156 date:2026-06-03 expires:2026-12-03 source:implement -->

- [PATTERN] When adding a NOT NULL FK column to a table that already has rows: (1) add nullable, (2) UPDATE to backfill default, (3) ALTER to NOT NULL — all in the same Alembic migration. The universe_id migration (c7d8e9f0a1b2) demonstrates this three-step pattern for `scanner_configs`. <!-- issue:#156 date:2026-06-03 expires:2026-12-03 source:implement -->

## Backend: Cookie Security

- [PATTERN] Use a dedicated `COOKIE_SECURE: bool = True` field in `Settings` rather than deriving the secure flag from `ENVIRONMENT == "production"` — the dedicated field is overridable independently, defaults secure-by-default, and avoids a regression if `ENVIRONMENT` is not set. Add `COOKIE_SECURE: "false"` to the `backend` service in `docker-compose.override.yml` so local HTTP dev works automatically. <!-- issue:#202 date:2026-06-05 expires:2026-12-05 source:implement -->

- [PATTERN] Set `SameSite=Lax` on the `access_token` cookie and `SameSite=Strict` on the `refresh_token` cookie — Strict on the access cookie breaks top-level inbound navigation to the SPA (user lands logged-out), while the refresh token's narrow `/api/auth/refresh` path makes Strict safe there. <!-- issue:#202 date:2026-06-07 expires:2026-12-07 source:implement -->

## Backend: Config / Settings

- [PATTERN] When adding a `field_validator` to `Settings` in `config.py`, add a matching `os.environ.setdefault("FIELD_NAME", valid_value)` at the top of `backend/tests/conftest.py` (before app imports) — otherwise bare `Settings()` calls in existing tests will hit the new validator with the default value and fail. <!-- issue:#190 date:2026-06-05 expires:2026-12-05 source:implement -->

- [PATTERN] Test a pydantic-settings validator by passing the invalid value as an init kwarg — `Settings(JWT_SECRET_KEY="")` — since init kwargs override env vars. This gives a clean, deterministic test without manipulating environment state. <!-- issue:#190 date:2026-06-05 expires:2026-12-05 source:implement -->

## Backend: Migrations

- [FIX] If `alembic revision --autogenerate` produces an empty migration (no `op.` calls in the body), verify that the model is imported in `backend/app/models/__init__.py` and that `Base` is the same `DeclarativeBase` instance as in `backend/app/core/database.py`. <!-- bootstrap date:2026-06-02 expires:2026-12-02 source:implement -->

- [FIX] When a migration backfills a FK column (e.g. `UPDATE scanner_configs SET universe_id = 1`), ensure the referenced row exists BEFORE the UPDATE by inserting it with `ON CONFLICT (id) DO NOTHING` — CI databases start empty (no seed SQL applied), so the FK constraint will fail if the parent row is absent. See migration `c7d8e9f0a1b2` for the pattern. <!-- issue:#156 date:2026-06-03 expires:2026-12-03 source:implement -->

## Backend: Circuit Breakers

- [PATTERN] Circuit breakers live in `app/core/circuit_breakers.py` as two module-level singletons (`POLYGON_BREAKER`, `IBKR_BREAKER`) built from `settings` at import time. Add new breakers here, not in provider files. <!-- issue:#205 date:2026-06-05 expires:2026-12-05 source:implement -->

- [PATTERN] For sync provider methods (e.g. Polygon), wrap with `POLYGON_BREAKER.call(self._impl, *args)` and catch `pybreaker.CircuitBreakerError` → `ProviderError(is_retryable=False)`. For async methods (e.g. IBKR), use `await IBKR_BREAKER.call_async(self._impl, *args)`. <!-- issue:#205 date:2026-06-05 expires:2026-12-05 source:implement -->

- [AVOID] Never place connection availability checks (e.g. `if not ib: raise ProviderError(is_retryable=True)`) inside `IBKR_BREAKER.call_async()` — transient disconnects will increment the failure counter and can open the breaker on non-provider faults. Move connection checks BEFORE the breaker call so only real provider failures count. <!-- issue:#205 date:2026-06-07 expires:2026-12-07 source:implement -->

- [PATTERN] Circuit-open error handling must be consistent across all methods of the same provider: all three of `get_bars`, `get_snapshots`, `get_ticker_details` on `MassiveDataProvider` must raise `ProviderError(is_retryable=False)` on `CircuitBreakerError`. Do not silently return `[]`/`{}` for some methods and raise for others — callers need uniform behavior. <!-- issue:#205 date:2026-06-07 expires:2026-12-07 source:implement -->

- [AVOID] Never use `except (pybreaker.CircuitBreakerError, Exception)` — `CircuitBreakerError` is an `Exception` subclass so the tuple is redundant, and the broad catch masks real defects as missing data. Use two separate handlers: `except pybreaker.CircuitBreakerError` → raise `ProviderError`, `except Exception` → log and return empty. <!-- issue:#205 date:2026-06-07 expires:2026-12-07 source:implement -->

## Backend: Utilities

- [PATTERN] Use `from app.utils.time import utc_now, to_utc_naive` for any naive-UTC datetime need: `utc_now()` replaces `datetime.now(timezone.utc).replace(tzinfo=None)`, `to_utc_naive(dt)` replaces `.astimezone(timezone.utc).replace(tzinfo=None)`. Column defaults use the callable ref (`default=utc_now`), inline expressions call it (`utc_now()`). <!-- issue:#286 date:2026-06-11 expires:2026-12-11 source:implement -->

- [PATTERN] Use `from app.utils.db import get_or_404` to replace Shape A 404 boilerplate (`db.query(Model).filter(Model.id==id).first(); if not obj: raise HTTPException(404)`). Call without storing the result (`get_or_404(db, Model, id, "Name")`) when the result isn't used downstream. <!-- issue:#286 date:2026-06-11 expires:2026-12-11 source:implement -->

## Backend: Middleware

- [PATTERN] Pure-ASGI middleware classes (like `CSRFMiddleware`) should be defined at module level in `main.py`, not inside `create_app()` — module-level placement makes them importable by the test suite without triggering the full app factory. The `AuthMiddleware` is an exception because it closes over `EXEMPT_PREFIXES`. <!-- issue:#192 date:2026-06-05 expires:2026-12-05 source:implement -->

- [PATTERN] CSRF_EXEMPT_PREFIXES and AUTH EXEMPT_PREFIXES serve different concerns and must remain separate tuples in `main.py`. Do not merge them — CSRF exempts pre-authentication paths; auth exempts docs/health/metrics paths that are unrelated to CSRF. <!-- issue:#192 date:2026-06-05 expires:2026-12-05 source:implement -->

---
<!-- PROVISIONAL — entries below are from a single observed run; unverified.
     Do not rely on these as authoritative guidance. They are excluded from
     plan/implement prompt injection except as advisory context.
     Each will be promoted to [PATTERN] on second-run confirmation (different issue number) or dropped at TTL. -->
