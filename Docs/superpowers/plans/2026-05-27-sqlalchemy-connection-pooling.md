# SQLAlchemy Connection Pooling — Implementation Plan

**Issue**: [#85 — Configure SQLAlchemy connection pooling](https://github.com/omniscient/markethawk/issues/85)
**Spec**: `Docs/superpowers/specs/2026-05-27-sqlalchemy-connection-pooling-design.md`
**Date**: 2026-05-27

## Goal

Add explicit, environment-configurable connection pool parameters to `create_engine()` in `database.py`, sourced from five new settings in `config.py`. Conservative defaults stay within PostgreSQL's default `max_connections=100`.

## Architecture

Two-file change. No schema impact, no migration required.

- `backend/app/core/config.py` — add 5 pool settings
- `backend/app/core/database.py` — pass pool settings to `create_engine()`

## Tech Stack

- **Python / SQLAlchemy 2.x** — `create_engine()` pool keyword arguments
- **pytest + monkeypatch** — unit tests for settings and engine configuration

---

## File Structure

| File | Change |
|------|--------|
| `backend/app/core/config.py` | Add 5 `DB_POOL_*` settings using existing `os.getenv()` pattern |
| `backend/app/core/database.py` | Expand `create_engine()` call with pool kwargs |
| `backend/tests/core/__init__.py` | New — makes `tests/core` a package |
| `backend/tests/core/test_config.py` | New — tests default values and types of pool settings |
| `backend/tests/core/test_database.py` | New — tests engine pool parameters match settings |

---

## Task 1: Add pool settings to `config.py`

**Files**: `backend/app/core/config.py`, `backend/tests/core/__init__.py`, `backend/tests/core/test_config.py`

### Step 1.1 — Create test package and write failing test

```bash
mkdir -p backend/tests/core
touch backend/tests/core/__init__.py
```

Write `backend/tests/core/test_config.py`:

```python
from app.core.config import Settings


def test_db_pool_size_default():
    assert Settings.DB_POOL_SIZE == 5


def test_db_max_overflow_default():
    assert Settings.DB_MAX_OVERFLOW == 10


def test_db_pool_pre_ping_default():
    assert Settings.DB_POOL_PRE_PING is True


def test_db_pool_recycle_default():
    assert Settings.DB_POOL_RECYCLE == 3600


def test_db_pool_timeout_default():
    assert Settings.DB_POOL_TIMEOUT == 30


def test_pool_settings_are_correct_types():
    assert isinstance(Settings.DB_POOL_SIZE, int)
    assert isinstance(Settings.DB_MAX_OVERFLOW, int)
    assert isinstance(Settings.DB_POOL_PRE_PING, bool)
    assert isinstance(Settings.DB_POOL_RECYCLE, int)
    assert isinstance(Settings.DB_POOL_TIMEOUT, int)
```

### Step 1.2 — Verify tests fail

```bash
cd backend && python -m pytest tests/core/test_config.py -v
```

Expected output (all 6 tests fail with `AttributeError: type object 'Settings' has no attribute 'DB_POOL_SIZE'`):
```
FAILED tests/core/test_config.py::test_db_pool_size_default
FAILED tests/core/test_config.py::test_db_max_overflow_default
FAILED tests/core/test_config.py::test_db_pool_pre_ping_default
FAILED tests/core/test_config.py::test_db_pool_recycle_default
FAILED tests/core/test_config.py::test_db_pool_timeout_default
FAILED tests/core/test_config.py::test_pool_settings_are_correct_types
6 failed
```

### Step 1.3 — Add pool settings to `config.py`

In `backend/app/core/config.py`, insert after the `CORS_ORIGINS` line (line 49) and before the `IBKR` block:

```python
    # ── Database connection pool ────────────────────────────────────────────
    DB_POOL_SIZE: int = int(os.getenv("DB_POOL_SIZE", "5"))
    DB_MAX_OVERFLOW: int = int(os.getenv("DB_MAX_OVERFLOW", "10"))
    DB_POOL_PRE_PING: bool = os.getenv("DB_POOL_PRE_PING", "true").lower() == "true"
    DB_POOL_RECYCLE: int = int(os.getenv("DB_POOL_RECYCLE", "3600"))
    DB_POOL_TIMEOUT: int = int(os.getenv("DB_POOL_TIMEOUT", "30"))
```

### Step 1.4 — Verify tests pass

```bash
cd backend && python -m pytest tests/core/test_config.py -v
```

Expected output:
```
PASSED tests/core/test_config.py::test_db_pool_size_default
PASSED tests/core/test_config.py::test_db_max_overflow_default
PASSED tests/core/test_config.py::test_db_pool_pre_ping_default
PASSED tests/core/test_config.py::test_db_pool_recycle_default
PASSED tests/core/test_config.py::test_db_pool_timeout_default
PASSED tests/core/test_config.py::test_pool_settings_are_correct_types
6 passed
```

### Step 1.5 — Commit

```bash
git add backend/app/core/config.py backend/tests/core/__init__.py backend/tests/core/test_config.py
git commit -m "feat(config): add DB_POOL_* settings with env-configurable defaults"
```

---

## Task 2: Wire pool params into `create_engine()` in `database.py`

**Files**: `backend/app/core/database.py`, `backend/tests/core/test_database.py`

### Step 2.1 — Write failing test

Write `backend/tests/core/test_database.py`:

```python
from sqlalchemy.pool import QueuePool

from app.core.config import settings
from app.core.database import engine


def test_engine_uses_queue_pool():
    assert isinstance(engine.pool, QueuePool)


def test_engine_pool_size_matches_settings():
    assert engine.pool.size() == settings.DB_POOL_SIZE


def test_engine_max_overflow_matches_settings():
    assert engine.pool._max_overflow == settings.DB_MAX_OVERFLOW


def test_engine_pool_timeout_matches_settings():
    assert engine.pool._timeout == settings.DB_POOL_TIMEOUT


def test_engine_pool_recycle_matches_settings():
    assert engine.pool._recycle == settings.DB_POOL_RECYCLE


def test_engine_pre_ping_matches_settings():
    assert engine.pool._pre_ping == settings.DB_POOL_PRE_PING
```

### Step 2.2 — Verify tests fail

```bash
cd backend && python -m pytest tests/core/test_database.py -v
```

Expected failures (pre_ping and recycle mismatch SQLAlchemy defaults before our changes):
```
PASSED tests/core/test_database.py::test_engine_uses_queue_pool
PASSED tests/core/test_database.py::test_engine_pool_size_matches_settings
PASSED tests/core/test_database.py::test_engine_max_overflow_matches_settings
PASSED tests/core/test_database.py::test_engine_pool_timeout_matches_settings
FAILED tests/core/test_database.py::test_engine_pool_recycle_matches_settings
FAILED tests/core/test_database.py::test_engine_pre_ping_matches_settings
2 failed, 4 passed
```

(`_recycle` defaults to `-1` and `_pre_ping` defaults to `False` in SQLAlchemy before we pass them explicitly.)

### Step 2.3 — Update `database.py`

Replace the bare `create_engine()` call in `backend/app/core/database.py`:

**Before (line 13):**
```python
engine = create_engine(settings.DATABASE_URL)
```

**After:**
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

### Step 2.4 — Verify all tests pass

```bash
cd backend && python -m pytest tests/core/ -v
```

Expected output:
```
PASSED tests/core/test_config.py::test_db_pool_size_default
PASSED tests/core/test_config.py::test_db_max_overflow_default
PASSED tests/core/test_config.py::test_db_pool_pre_ping_default
PASSED tests/core/test_config.py::test_db_pool_recycle_default
PASSED tests/core/test_config.py::test_db_pool_timeout_default
PASSED tests/core/test_config.py::test_pool_settings_are_correct_types
PASSED tests/core/test_database.py::test_engine_uses_queue_pool
PASSED tests/core/test_database.py::test_engine_pool_size_matches_settings
PASSED tests/core/test_database.py::test_engine_max_overflow_matches_settings
PASSED tests/core/test_database.py::test_engine_pool_timeout_matches_settings
PASSED tests/core/test_database.py::test_engine_pool_recycle_matches_settings
PASSED tests/core/test_database.py::test_engine_pre_ping_matches_settings
12 passed
```

### Step 2.5 — Run the full test suite to check for regressions

```bash
cd backend && python -m pytest --tb=short -q
```

All existing tests must remain green. No test touches `create_engine()` internals, so no regressions are expected.

### Step 2.6 — Validate backend reloaded with new pool config (Docker)

```bash
docker-compose restart backend
docker-compose logs backend --tail=20
```

Confirm no startup errors. Then verify pool parameters at runtime:

```bash
docker-compose exec backend python -c "
from app.core.database import engine
print('pool_size:', engine.pool.size())
print('max_overflow:', engine.pool._max_overflow)
print('pool_timeout:', engine.pool._timeout)
print('pool_recycle:', engine.pool._recycle)
print('pool_pre_ping:', engine.pool._pre_ping)
"
```

Expected output:
```
pool_size: 5
max_overflow: 10
pool_timeout: 30
pool_recycle: 3600
pool_pre_ping: True
```

### Step 2.7 — Commit

```bash
git add backend/app/core/database.py backend/tests/core/test_database.py
git commit -m "feat(database): configure explicit connection pool params from settings"
```

---

## Acceptance Criteria Checklist

- [ ] `create_engine()` passes all 5 pool params sourced from `settings`
- [ ] All 5 settings have `os.getenv()` defaults in `config.py`
- [ ] Backend starts cleanly with default env (no new env vars required)
- [ ] Setting `DB_POOL_SIZE=20` in the environment is reflected at runtime
- [ ] `pool_pre_ping=True` reconnects after `docker-compose restart postgres` without manual backend restart
- [ ] 12 new tests pass; full suite green; no regressions
