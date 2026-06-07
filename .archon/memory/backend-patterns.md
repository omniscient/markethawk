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

## Backend: Config / Settings

- [PATTERN] When adding a `field_validator` to `Settings` in `config.py`, add a matching `os.environ.setdefault("FIELD_NAME", valid_value)` at the top of `backend/tests/conftest.py` (before app imports) — otherwise bare `Settings()` calls in existing tests will hit the new validator with the default value and fail. <!-- issue:#190 date:2026-06-05 expires:2026-12-05 source:implement -->

- [PATTERN] Test a pydantic-settings validator by passing the invalid value as an init kwarg — `Settings(JWT_SECRET_KEY="")` — since init kwargs override env vars. This gives a clean, deterministic test without manipulating environment state. <!-- issue:#190 date:2026-06-05 expires:2026-12-05 source:implement -->

## Backend: Circuit Breakers

- [PATTERN] Circuit breakers live in `app/core/circuit_breakers.py` as two module-level singletons (`POLYGON_BREAKER`, `IBKR_BREAKER`) built from `settings` at import time. Add new breakers here, not in provider files. <!-- issue:#205 date:2026-06-05 expires:2026-12-05 source:implement -->

- [PATTERN] For sync provider methods (e.g. Polygon), wrap with `POLYGON_BREAKER.call(self._impl, *args)` and catch `pybreaker.CircuitBreakerError` → `ProviderError(is_retryable=False)`. For async methods (e.g. IBKR), use `await IBKR_BREAKER.call_async(self._impl, *args)`. <!-- issue:#205 date:2026-06-05 expires:2026-12-05 source:implement -->

- [PATTERN] With pybreaker 1.x `fail_max=N`, the circuit opens when fail_counter reaches N; on the Nth call `CircuitBreakerError` is raised instead of the original exception (the breaker opens before re-raising). Test with `fail_max=2`: two real failures open the circuit on the 3rd call. <!-- issue:#205 date:2026-06-05 expires:2026-12-05 source:implement -->

- [AVOID] Never place connection availability checks (e.g. `if not ib: raise ProviderError(is_retryable=True)`) inside `IBKR_BREAKER.call_async()` — transient disconnects will increment the failure counter and can open the breaker on non-provider faults. Move connection checks BEFORE the breaker call so only real provider failures count. <!-- issue:#205 date:2026-06-07 expires:2026-12-07 source:implement -->

- [PATTERN] Circuit-open error handling must be consistent across all methods of the same provider: all three of `get_bars`, `get_snapshots`, `get_ticker_details` on `MassiveDataProvider` must raise `ProviderError(is_retryable=False)` on `CircuitBreakerError`. Do not silently return `[]`/`{}` for some methods and raise for others — callers need uniform behavior. <!-- issue:#205 date:2026-06-07 expires:2026-12-07 source:implement -->

- [AVOID] Never use `except (pybreaker.CircuitBreakerError, Exception)` — `CircuitBreakerError` is an `Exception` subclass so the tuple is redundant, and the broad catch masks real defects as missing data. Use two separate handlers: `except pybreaker.CircuitBreakerError` → raise `ProviderError`, `except Exception` → log and return empty. <!-- issue:#205 date:2026-06-07 expires:2026-12-07 source:implement -->

- [AVOID] Do not use `asyncio.get_event_loop().run_until_complete()` in pytest tests — deprecated on Python 3.10+ and inconsistent with `@pytest.mark.asyncio`. Use `async def test_...(self)` with `@pytest.mark.asyncio` decorator and `await` instead. <!-- issue:#205 date:2026-06-07 expires:2026-12-07 source:implement -->

## Backend: Middleware

- [PATTERN] Pure-ASGI middleware classes (like `CSRFMiddleware`) should be defined at module level in `main.py`, not inside `create_app()` — module-level placement makes them importable by the test suite without triggering the full app factory. The `AuthMiddleware` is an exception because it closes over `EXEMPT_PREFIXES`. <!-- issue:#192 date:2026-06-05 expires:2026-12-05 source:implement -->

- [PATTERN] When adding new middleware that the test suite needs to pass, update the `inject_auth_into_module_client` autouse fixture in `tests/api/conftest.py` to inject required headers (e.g. `module.client.headers.update({"X-Requested-With": "XMLHttpRequest"})`) so all module-level `TestClient` instances satisfy the new check automatically. <!-- issue:#192 date:2026-06-05 expires:2026-12-05 source:implement -->

- [PATTERN] CSRF_EXEMPT_PREFIXES and AUTH EXEMPT_PREFIXES serve different concerns and must remain separate tuples in `main.py`. Do not merge them — CSRF exempts pre-authentication paths; auth exempts docs/health/metrics paths that are unrelated to CSRF. <!-- issue:#192 date:2026-06-05 expires:2026-12-05 source:implement -->

## Backend: Migrations

- [PATTERN] After any model change: `cd backend && python -m alembic revision --autogenerate -m "description" && python -m alembic upgrade head`. Never skip the `upgrade head` step — the preview stack applies migrations at startup, but the local test suite does not. <!-- bootstrap date:2026-06-02 expires:2026-12-02 source:implement -->

- [FIX] If `alembic revision --autogenerate` produces an empty migration (no `op.` calls in the body), verify that the model is imported in `backend/app/models/__init__.py` and that `Base` is the same `DeclarativeBase` instance as in `backend/app/core/database.py`. <!-- bootstrap date:2026-06-02 expires:2026-12-02 source:implement -->

- [FIX] When a migration backfills a FK column (e.g. `UPDATE scanner_configs SET universe_id = 1`), ensure the referenced row exists BEFORE the UPDATE by inserting it with `ON CONFLICT (id) DO NOTHING` — CI databases start empty (no seed SQL applied), so the FK constraint will fail if the parent row is absent. See migration `c7d8e9f0a1b2` for the pattern. <!-- issue:#156 date:2026-06-03 expires:2026-12-03 source:implement -->

## Backend: Dependency Constraints

- [AVOID] `python-jose 3.4.0` pins `pyasn1<0.5.0,>=0.4.1`; the patched pyasn1 (CVE-2026-30922) requires 0.6.3 which is incompatible. Add `CVE-2026-30922` to `--ignore-vuln` in CI pip-audit instead of trying to bump pyasn1 alongside python-jose 3.x. <!-- issue:#197 date:2026-06-05 expires:2026-12-05 source:implement -->
