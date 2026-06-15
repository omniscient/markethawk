# Plan: F-LOG-01 — Log Redaction Filter for Secrets (Seq)

**Date:** 2026-06-15  
**Issue:** #382  
**Spec:** docs/superpowers/specs/2026-06-13-log-redaction-filter-design.md  
**Goal:** Add a `RedactingFilter` that scrubs known-secret patterns from every log record before it reaches stdout (and thus Seq via the GELF bridge), and add `Field(repr=False)` on five sensitive `Settings` fields as belt-and-suspenders.

---

## Architecture

No model changes, no migration. All changes are in `backend/app/core/` and its tests:

- `backend/app/core/log_filters.py` — new module with `RedactingFilter`, `_redact()`, `install_redacting_filter()`
- `backend/app/core/config.py` — `Field(repr=False)` on 5 sensitive settings fields + add `Field` to import
- `backend/app/main.py` — call `install_redacting_filter()` after the existing `OtelTraceIdFilter` install
- `backend/app/core/celery_app.py` — wire `install_redacting_filter()` via `after_setup_logger` + `after_setup_task_logger` signals
- `backend/tests/core/test_log_redaction.py` — new unit test file

Pattern reference: `OtelTraceIdFilter` in `backend/app/core/tracing.py` is the existing `logging.Filter` subclass in this codebase — follow its style.

---

## Tech Stack

Python `logging` module (stdlib, no new dependencies). Celery `celery.signals` (already a project dependency). `pydantic.Field` — needs adding to the existing `from pydantic import field_validator` import in `config.py`.

---

## File Structure

| File | Change |
|------|--------|
| `backend/app/core/log_filters.py` | **New** — `_redact()`, `RedactingFilter`, `install_redacting_filter()` |
| `backend/app/core/config.py` | Add `Field` to pydantic import; `Field(repr=False)` on 5 sensitive fields |
| `backend/app/main.py` | Add `install_redacting_filter` import + call after `OtelTraceIdFilter` line |
| `backend/app/core/celery_app.py` | Import `after_setup_logger`, `after_setup_task_logger`; add signal handler |
| `backend/tests/core/test_log_redaction.py` | **New** — unit tests for filter, Settings repr, and wiring smoke-tests |

---

## Task 1: Implement `RedactingFilter` in `backend/app/core/log_filters.py`

**Files:** `backend/tests/core/test_log_redaction.py`, `backend/app/core/log_filters.py`

### TDD

**Step 1 — Write failing tests**

Create `backend/tests/core/test_log_redaction.py`:

```python
"""Unit tests for RedactingFilter and install_redacting_filter."""
import logging

import pytest

from app.core.log_filters import RedactingFilter, install_redacting_filter


# ── _redact internals via filter ──────────────────────────────────────────────

def _emit(filter_: logging.Filter, msg: str, *args) -> str:
    """Run a log record through the filter and return the formatted message."""
    record = logging.LogRecord(
        name="test", level=logging.INFO, pathname="", lineno=0,
        msg=msg, args=args, exc_info=None,
    )
    filter_.filter(record)
    return record.msg


def test_url_password_redacted():
    f = RedactingFilter()
    result = _emit(f, "conn: postgresql://user:s3cr3t@db:5432/mydb")
    assert "s3cr3t" not in result
    assert "[REDACTED]" in result
    assert "user" in result
    assert "db:5432" in result


def test_key_value_redacted():
    f = RedactingFilter()
    result = _emit(f, "POLYGON_API_KEY=abc123xyz")
    assert "abc123xyz" not in result
    assert "POLYGON_API_KEY=[REDACTED]" in result


def test_database_url_key_value_redacted():
    f = RedactingFilter()
    result = _emit(f, "DATABASE_URL=postgresql://u:p@h/db")
    assert "=postgresql" not in result
    assert "[REDACTED]" in result


def test_password_field_redacted():
    f = RedactingFilter()
    result = _emit(f, "SMTP_PASSWORD=hunter2")
    assert "hunter2" not in result
    assert "SMTP_PASSWORD=[REDACTED]" in result


def test_access_token_redacted():
    f = RedactingFilter()
    result = _emit(f, "access_token=eyJhbGciOiJSUzI1NiJ9.payload.sig")
    assert "eyJhbGciOiJSUzI1NiJ9" not in result
    assert "[REDACTED]" in result


def test_normal_message_passes_through():
    f = RedactingFilter()
    result = _emit(f, "Scanner run complete: 5 signals found")
    assert result == "Scanner run complete: 5 signals found"


def test_percent_args_interpolated_before_redact():
    f = RedactingFilter()
    # The secret lives in args, not in msg — filter must call getMessage() first.
    result = _emit(f, "key=%s", "DATABASE_URL=postgresql://u:p@h/db")
    assert "p@h" not in result
    assert "[REDACTED]" in result


def test_filter_clears_args():
    """After filter(), record.args must be None so the formatter doesn't re-interpolate."""
    f = RedactingFilter()
    record = logging.LogRecord(
        name="test", level=logging.INFO, pathname="", lineno=0,
        msg="val=%s", args=("secret",), exc_info=None,
    )
    f.filter(record)
    assert record.args is None


def test_filter_always_returns_true():
    """RedactingFilter must never suppress records."""
    f = RedactingFilter()
    record = logging.LogRecord(
        name="test", level=logging.DEBUG, pathname="", lineno=0,
        msg="hello", args=(), exc_info=None,
    )
    assert f.filter(record) is True


def test_redis_url_password_redacted():
    f = RedactingFilter()
    result = _emit(f, "broker: redis://:mypassword@redis:6379/0")
    assert "mypassword" not in result
    assert "[REDACTED]" in result


# ── install_redacting_filter wiring ───────────────────────────────────────────

def test_install_adds_filter_to_root_logger():
    root = logging.getLogger()
    original_filters = root.filters[:]
    try:
        install_redacting_filter()
        assert any(isinstance(f, RedactingFilter) for f in root.filters)
    finally:
        root.filters = original_filters


def test_install_idempotent_single_instance():
    """Calling install twice must not double-add the filter."""
    root = logging.getLogger()
    original_filters = root.filters[:]
    try:
        install_redacting_filter()
        install_redacting_filter()
        count = sum(1 for f in root.filters if isinstance(f, RedactingFilter))
        assert count == 1
    finally:
        root.filters = original_filters
```

**Step 2 — Verify they fail**

```bash
docker-compose exec backend python -m pytest backend/tests/core/test_log_redaction.py -x 2>&1 | head -20
# Expected: ModuleNotFoundError: No module named 'app.core.log_filters'
```

**Step 3 — Implement `backend/app/core/log_filters.py`**

```python
"""
Logging filter that redacts known-secret patterns from log records before
they reach stdout (and thus the Seq GELF bridge).

Two pattern families:
  - Key-value env var names (*_KEY, *_PASSWORD, *_SECRET, DATABASE_URL, access_token)
  - URL-embedded passwords (postgresql/redis/amqp/mysql://user:<password>@...)
"""
import logging
import re

_PATTERNS = [
    # Key-value: POLYGON_API_KEY=abc123  ->  POLYGON_API_KEY=[REDACTED]
    (
        re.compile(
            r"(?i)((?:\w*_KEY|\w*_PASSWORD|\w*_SECRET|DATABASE_URL|access_token)"
            r"\s*[=:]\s*)\S+"
        ),
        r"\1[REDACTED]",
    ),
    # URL-embedded password: postgresql://user:pass@host  ->  postgresql://user:[REDACTED]@host
    (
        re.compile(
            r"((?:postgresql|redis|amqp|mysql)://[^:@\s/]+:)[^@\s]+(@)"
        ),
        r"\1[REDACTED]\2",
    ),
]


def _redact(text: str) -> str:
    for pattern, replacement in _PATTERNS:
        text = pattern.sub(replacement, text)
    return text


class RedactingFilter(logging.Filter):
    """Scrubs secret patterns from every log record before it reaches any handler."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
        except Exception:
            msg = str(record.msg)
        record.msg = _redact(msg)
        record.args = None
        return True


def install_redacting_filter() -> None:
    """Install RedactingFilter on the root logger (idempotent)."""
    root = logging.getLogger()
    if not any(isinstance(f, RedactingFilter) for f in root.filters):
        root.addFilter(RedactingFilter())
```

**Step 4 — Verify tests pass**

```bash
docker-compose exec backend python -m pytest backend/tests/core/test_log_redaction.py -v 2>&1 | tail -20
# Expected: 12 passed
```

**Step 5 — Commit**

```bash
git add backend/app/core/log_filters.py backend/tests/core/test_log_redaction.py
git commit -m "feat(security): add RedactingFilter for log secret scrubbing (#382)"
```

---

## Task 2: Add `Field(repr=False)` to sensitive `Settings` fields

**Files:** `backend/tests/core/test_log_redaction.py`, `backend/app/core/config.py`

### TDD

**Step 1 — Write failing tests**

Append to `backend/tests/core/test_log_redaction.py`:

```python
# ── Settings repr protection ───────────────────────────────────────────────

def test_settings_repr_hides_database_url():
    from app.core.config import Settings
    s = Settings(
        DATABASE_URL="postgresql://u:s3cr3t@h/db",
        POLYGON_API_KEY="poly-key-123",
        JWT_SECRET_KEY="a" * 32,
    )
    r = repr(s)
    assert "s3cr3t" not in r


def test_settings_repr_hides_polygon_api_key():
    from app.core.config import Settings
    s = Settings(
        DATABASE_URL="postgresql://u:p@h/db",
        POLYGON_API_KEY="poly-secret-key",
        JWT_SECRET_KEY="a" * 32,
    )
    assert "poly-secret-key" not in repr(s)


def test_settings_repr_hides_jwt_secret_key():
    from app.core.config import Settings
    s = Settings(
        DATABASE_URL="postgresql://u:p@h/db",
        POLYGON_API_KEY="poly-key",
        JWT_SECRET_KEY="super-secret-jwt-key-aaaaaaaaaaaaaaa",
    )
    assert "super-secret-jwt-key" not in repr(s)


def test_settings_repr_hides_smtp_password():
    from app.core.config import Settings
    s = Settings(
        DATABASE_URL="postgresql://u:p@h/db",
        POLYGON_API_KEY="poly-key",
        JWT_SECRET_KEY="a" * 32,
        SMTP_PASSWORD="mail-secret",
    )
    assert "mail-secret" not in repr(s)


def test_settings_repr_hides_vapid_private_key():
    from app.core.config import Settings
    s = Settings(
        DATABASE_URL="postgresql://u:p@h/db",
        POLYGON_API_KEY="poly-key",
        JWT_SECRET_KEY="a" * 32,
        VAPID_PRIVATE_KEY="vapid-priv-key-abc",
    )
    assert "vapid-priv-key-abc" not in repr(s)
```

**Step 2 — Verify they fail**

```bash
docker-compose exec backend python -m pytest backend/tests/core/test_log_redaction.py::test_settings_repr_hides_database_url -x 2>&1 | tail -10
# Expected: AssertionError (secret visible in repr)
```

**Step 3 — Update `backend/app/core/config.py`**

Change line 7 from:
```python
from pydantic import field_validator
```
to:
```python
from pydantic import Field, field_validator
```

Then update the five sensitive fields (exact current lines shown below):

`DATABASE_URL: str` → `DATABASE_URL: str = Field(repr=False)`

`POLYGON_API_KEY: str` → `POLYGON_API_KEY: str = Field(repr=False)`

`JWT_SECRET_KEY: str = ""` → `JWT_SECRET_KEY: str = Field(default="", repr=False)`

`SMTP_PASSWORD: str = ""` → `SMTP_PASSWORD: str = Field(default="", repr=False)`

`VAPID_PRIVATE_KEY: str = ""` → `VAPID_PRIVATE_KEY: str = Field(default="", repr=False)`

Note: `DATABASE_URL` and `POLYGON_API_KEY` are required fields (no default). `Field(repr=False)` on a required field keeps it required — Pydantic `BaseSettings` still loads the value from the environment; `repr=False` only suppresses the field's value in `__repr__`. No default is added.

**Step 4 — Verify tests pass**

```bash
docker-compose exec backend python -m pytest backend/tests/core/test_log_redaction.py -v 2>&1 | tail -20
# Expected: 17 passed (12 from Task 1 + 5 new)
```

Also verify existing Settings tests still pass (regression check):

```bash
docker-compose exec backend python -m pytest backend/tests/core/test_config.py backend/tests/test_settings.py -v 2>&1 | tail -10
# Expected: all pass
```

**Step 5 — Commit**

```bash
git add backend/app/core/config.py backend/tests/core/test_log_redaction.py
git commit -m "feat(security): add Field(repr=False) to sensitive Settings fields (#382)"
```

---

## Task 3: Wire `install_redacting_filter()` into the FastAPI entry point

**Files:** `backend/tests/core/test_log_redaction.py`, `backend/app/main.py`

### TDD

**Step 1 — Write failing test**

Append to `backend/tests/core/test_log_redaction.py`:

```python
# ── FastAPI wiring smoke-test ──────────────────────────────────────────────

def test_create_app_installs_redacting_filter():
    """create_app() must install RedactingFilter on the root logger."""
    import logging
    from app.core.log_filters import RedactingFilter

    root = logging.getLogger()
    original_filters = root.filters[:]
    try:
        # Remove any existing RedactingFilter so create_app() installs a fresh one.
        root.filters = [f for f in root.filters if not isinstance(f, RedactingFilter)]

        from app.main import create_app
        create_app()

        assert any(isinstance(f, RedactingFilter) for f in root.filters), (
            "RedactingFilter not found on root logger after create_app()"
        )
    finally:
        root.filters = original_filters
```

**Step 2 — Verify it fails**

```bash
docker-compose exec backend python -m pytest backend/tests/core/test_log_redaction.py::test_create_app_installs_redacting_filter -x 2>&1 | tail -10
# Expected: AssertionError — RedactingFilter not installed
```

**Step 3 — Update `backend/app/main.py`**

At line 186 (immediately after the existing `logging.getLogger().addFilter(OtelTraceIdFilter())` call), add:

```python
from app.core.log_filters import install_redacting_filter
install_redacting_filter()
```

The logging setup block will read:

```python
# Configure logging
logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logging.getLogger().addFilter(OtelTraceIdFilter())

from app.core.log_filters import install_redacting_filter
install_redacting_filter()
```

(The local import inside `create_app()` avoids a module-level circular import risk — same pattern used for `instrument_fastapi` below.)

**Step 4 — Verify test passes**

```bash
docker-compose exec backend python -m pytest backend/tests/core/test_log_redaction.py -v 2>&1 | tail -20
# Expected: 18 passed
```

**Step 5 — Commit**

```bash
git add backend/app/main.py backend/tests/core/test_log_redaction.py
git commit -m "feat(security): wire RedactingFilter into FastAPI create_app() (#382)"
```

---

## Task 4: Wire `install_redacting_filter()` into Celery via signals

**Files:** `backend/tests/core/test_log_redaction.py`, `backend/app/core/celery_app.py`

Celery resets the root logger after import; the `after_setup_logger` and `after_setup_task_logger` signals fire after Celery's internal logging configuration is applied, so a filter installed there survives Celery's own setup.

### TDD

**Step 1 — Write failing test**

Append to `backend/tests/core/test_log_redaction.py`:

```python
# ── Celery signal wiring smoke-test ───────────────────────────────────────

def test_celery_signal_handler_installs_redacting_filter():
    """The after_setup_logger signal handler must install RedactingFilter."""
    import logging
    from app.core.log_filters import RedactingFilter

    root = logging.getLogger()
    original_filters = root.filters[:]
    try:
        root.filters = [f for f in root.filters if not isinstance(f, RedactingFilter)]

        # Import the handler directly and call it as Celery would.
        from app.core.celery_app import _install_log_redaction
        _install_log_redaction(logger=root)

        assert any(isinstance(f, RedactingFilter) for f in root.filters), (
            "RedactingFilter not installed by Celery signal handler"
        )
    finally:
        root.filters = original_filters
```

**Step 2 — Verify it fails**

```bash
docker-compose exec backend python -m pytest backend/tests/core/test_log_redaction.py::test_celery_signal_handler_installs_redacting_filter -x 2>&1 | tail -10
# Expected: ImportError — cannot import name '_install_log_redaction' from 'app.core.celery_app'
```

**Step 3 — Update `backend/app/core/celery_app.py`**

Add these imports at the top of the file (after the existing Celery signal imports):

```python
from celery.signals import (
    after_setup_logger,
    after_setup_task_logger,
    worker_process_shutdown,
    worker_ready,
)
```

Then add the signal handler function after the existing `Celery(...)` instantiation:

```python
@after_setup_logger.connect
@after_setup_task_logger.connect
def _install_log_redaction(logger, **kwargs):
    from app.core.log_filters import install_redacting_filter
    install_redacting_filter()
```

The complete updated imports block in `celery_app.py`:

```python
import os

from celery import Celery
from celery.schedules import crontab
from celery.signals import (
    after_setup_logger,
    after_setup_task_logger,
    worker_process_shutdown,
    worker_ready,
)

from app.core.config import settings
```

And the signal handler placed immediately after `celery_app = Celery(...)`:

```python
celery_app = Celery(
    "stockscanner",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
    include=["app.tasks"],
)


@after_setup_logger.connect
@after_setup_task_logger.connect
def _install_log_redaction(logger, **kwargs):
    from app.core.log_filters import install_redacting_filter
    install_redacting_filter()
```

**Step 4 — Verify tests pass**

```bash
docker-compose exec backend python -m pytest backend/tests/core/test_log_redaction.py -v 2>&1 | tail -20
# Expected: 19 passed
```

Full test-suite regression check:

```bash
docker-compose exec backend python -m pytest backend/tests/ -x --timeout=60 2>&1 | tail -20
# Expected: all pass, no regressions
```

**Step 5 — Commit**

```bash
git add backend/app/core/celery_app.py backend/tests/core/test_log_redaction.py
git commit -m "feat(security): wire RedactingFilter into Celery via after_setup_logger signal (#382)"
```

---

## Verification Checklist

After all tasks are complete, verify against the spec's Verification section:

```bash
# 1. URL-embedded password redacted
docker-compose exec backend python -m pytest backend/tests/core/test_log_redaction.py::test_url_password_redacted -v

# 2. API key key-value redacted
docker-compose exec backend python -m pytest backend/tests/core/test_log_redaction.py::test_key_value_redacted -v

# 3. Settings repr safe
docker-compose exec backend python -m pytest \
  backend/tests/core/test_log_redaction.py::test_settings_repr_hides_database_url \
  backend/tests/core/test_log_redaction.py::test_settings_repr_hides_polygon_api_key \
  -v

# 4. LOG_LEVEL default in docker-compose.yml is INFO (confirm — no change needed)
grep "LOG_LEVEL" docker-compose.yml
# Expected: LOG_LEVEL: ${LOG_LEVEL:-INFO}  (already correct on all services)

# 5. Full suite clean
docker-compose exec backend python -m pytest backend/tests/ --timeout=60 -q
```
