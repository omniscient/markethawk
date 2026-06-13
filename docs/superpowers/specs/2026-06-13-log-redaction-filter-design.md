# Log Redaction Filter for Secrets (F-LOG-01)

**Date:** 2026-06-13
**Issue:** #382
**Epic:** #372 (Defensive Security Review 2026-06-12)
**Status:** Spec

---

## Problem

All Docker container stdout is forwarded to Seq via the `seq-gelf` GELF bridge,
meaning every Python `logging` call in the backend and Celery processes is
centralized in Seq. There is no redaction layer — log lines may contain
`DATABASE_URL` (with embedded password), `POLYGON_API_KEY`, `SMTP_PASSWORD`, and
other secrets interpolated by exception handlers, DEBUG SQL logging, or
inadvertent `logger.info(f"settings: {settings}")` calls.

Prod correctly hides stack traces from HTTP responses (`ENVIRONMENT=production`),
but this is orthogonal to what lands in the centralized log store.

---

## Requirements

1. A `logging.Filter` subclass scrubs secret patterns from every log record before
   it reaches the handler (and thus stdout → Seq).
2. Sensitive `Settings` fields have `repr=False` so they are excluded from
   Pydantic's default `__repr__` — belt-and-suspenders against
   `logger.info(f"config: {settings}")` calls that the regex filter may not catch.
3. The filter is installed in **both** entry points:
   - FastAPI backend (`create_app()` in `main.py`)
   - Celery worker/beat (via `after_setup_logger` / `after_setup_task_logger`
     signals in `celery_app.py`)
4. `LOG_LEVEL=DEBUG` must not appear in the production compose file (existing
   default is `INFO` — verify and document).
5. Unit test: a log record containing
   `DATABASE_URL=postgresql://u:p@h/db` is emitted with the password redacted.

---

## Architecture

### New file: `backend/app/core/log_filters.py`

Contains the `RedactingFilter` class and a shared `install_redacting_filter()`
helper called from both entry points.

#### Redaction patterns

Two classes of secrets need different treatment:

| Pattern | Example input | Output |
|---------|--------------|--------|
| Key-value env var names | `POLYGON_API_KEY=abc123` | `POLYGON_API_KEY=[REDACTED]` |
| URL-embedded passwords | `postgresql://user:pass@host/db` | `postgresql://user:[REDACTED]@host/db` |

Regex targets:
- **Key-value**: `(?i)((?:\w*_KEY|\w*_PASSWORD|\w*_SECRET|DATABASE_URL|access_token)\s*[=:]\s*)\S+`
- **URL password**: `((?:postgresql|redis|amqp|mysql)://[^:@\s/]+:)[^@\s]+(@)`

#### Filter implementation

```python
class RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        # Format first (interpolates %s/%d args), then redact, then store as
        # a plain string so the formatter doesn't re-interpolate.
        try:
            msg = record.getMessage()
        except Exception:
            msg = str(record.msg)
        record.msg = _redact(msg)
        record.args = None
        return True
```

Formatting before redacting is critical: it prevents the filter from having to
parse `record.args` (which may contain integers, Decimals, etc.) and avoids
false negatives when the secret is split across `msg` and `args`.

#### Install helper

```python
def install_redacting_filter() -> None:
    logging.getLogger().addFilter(RedactingFilter())
```

Called once per process; the root logger propagates to all child loggers.

### `backend/app/main.py` — backend entry point

After the existing `logging.basicConfig(...)` / `OtelTraceIdFilter` setup:

```python
from app.core.log_filters import install_redacting_filter
install_redacting_filter()
```

### `backend/app/core/celery_app.py` — Celery entry point

Celery resets the root logger after import; the correct hook is
`after_setup_logger` + `after_setup_task_logger` (fires after Celery's own
logging setup, so the filter survives):

```python
from celery.signals import after_setup_logger, after_setup_task_logger
from app.core.log_filters import install_redacting_filter

@after_setup_logger.connect
@after_setup_task_logger.connect
def _install_log_redaction(logger, **kwargs):
    install_redacting_filter()
```

### `backend/app/core/config.py` — Settings repr protection

Add `Field(repr=False)` to sensitive fields so Pydantic's `__repr__` never
renders their values:

```python
from pydantic import Field

DATABASE_URL: str = Field(repr=False)
POLYGON_API_KEY: str = Field(repr=False)
JWT_SECRET_KEY: str = Field(default="", repr=False)
SMTP_PASSWORD: str = Field(default="", repr=False)
VAPID_PRIVATE_KEY: str = Field(default="", repr=False)
```

Required fields (`DATABASE_URL`, `POLYGON_API_KEY`) use `Field(repr=False)`
without a default; they remain required but are excluded from repr output.

---

## Alternatives Considered

### A: Pure logging.Filter, no Settings repr change

Simpler, but leaves a gap: if anyone logs `settings` the Pydantic repr renders
`DATABASE_URL='postgresql://user:pass@host/db'`. The key-value regex would match
`DATABASE_URL=value` (with `=`) but Pydantic repr uses `=` or `='...'`
depending on quoting — matching all variants reliably requires more regex
complexity. `repr=False` is the cleaner fix at the source.

### C: Replace stdlib logging with structlog

Structlog has a built-in `redact` processor and native Seq/GELF support, but
it's a new dependency, requires migrating all `logging.getLogger(...)` calls
across the codebase, and is well beyond the S-size scope.

**Selected: Approach B (both layers)** — small delta (one new ~40-line module,
five `Field(repr=False)` annotations, two install call-sites), fits S scope,
defends two distinct failure modes.

---

## Open Questions

- Should SQL parameters logged under `LOG_LEVEL=DEBUG` (the SQLAlchemy event
  in `main.py:189-250`) be additionally suppressed at the `before_cursor_execute`
  handler rather than relying solely on the regex filter? Out of scope for this
  issue — a follow-up can add a note to the debug-SQL block.

---

## Assumptions

- `A` The regex patterns are sufficient for all currently-known secret field
  names in `Settings`. If new secrets are added to `Settings`, they must also
  receive `Field(repr=False)` and match one of the existing regex categories
  (e.g. `*_KEY`, `*_PASSWORD`) or the pattern list must be extended.
- `B` The Celery containers (`celery-worker`, `celery-beat`) do not override
  `after_setup_logger` elsewhere; the signal fires once per process after Celery's
  internal logging configuration.

---

## Files to Change

| File | Change |
|------|--------|
| `backend/app/core/log_filters.py` | **New** — `RedactingFilter`, `_redact()`, `install_redacting_filter()` |
| `backend/app/core/config.py` | Add `Field(repr=False)` to 5 sensitive fields |
| `backend/app/main.py` | Import + call `install_redacting_filter()` after `basicConfig` |
| `backend/app/core/celery_app.py` | Add `after_setup_logger` / `after_setup_task_logger` signal handler |
| `backend/tests/core/test_log_redaction.py` | **New** — unit tests for redaction filter and Settings repr |

---

## Verification

1. Unit test passes: log record with `DATABASE_URL=postgresql://u:p@h/db` →
   password segment `p` is replaced with `[REDACTED]`.
2. Unit test passes: log record with `POLYGON_API_KEY=secret123` →
   `POLYGON_API_KEY=[REDACTED]`.
3. Unit test passes: `repr(Settings(..., DATABASE_URL="postgresql://u:p@h/db"))` does
   not contain `p@h`.
4. `LOG_LEVEL` in `docker-compose.yml` backend service is `INFO` (confirm, no change needed).
