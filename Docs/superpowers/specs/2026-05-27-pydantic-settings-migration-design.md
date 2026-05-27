# Migrate config.py to pydantic-settings BaseSettings — Design Spec

**Issue**: [#91 — Migrate config.py to pydantic-settings BaseSettings](https://github.com/omniscient/markethawk/issues/91)
**Date**: 2026-05-27
**Status**: Pending Review

## Overview

`backend/app/core/config.py` uses raw `os.getenv()` with manual `int()` coercions instead of pydantic-settings `BaseSettings`. The class docstring says "pydantic-settings" but the implementation never inherited from it. This causes crashes on malformed env vars (e.g. a non-numeric `IBKR_PORT`), no startup validation for missing required fields, and no clear error messages. This migration replaces the custom class with a proper `BaseSettings` subclass, adds field validators for critical fields, and makes `CORS_ORIGINS` env-configurable.

## Requirements

1. `Settings` inherits from `pydantic_settings.BaseSettings`
2. `DATABASE_URL` and `POLYGON_API_KEY` are required — no default; app fails at startup with a clear error if either is missing
3. `CORS_ORIGINS` is a `list[str]` with default `["http://localhost:3333"]`; env var parsed as a JSON array
4. `field_validator` on `DATABASE_URL` checks it starts with `"postgresql"` (accepts `postgresql://` or `postgresql+asyncpg://`)
5. `field_validator` on `IBKR_PORT` and `SMTP_PORT` checks value is in range 1–65535
6. `load_dotenv()` call and `python-dotenv` import removed from `config.py`
7. `SettingsConfigDict(env_file=".env")` used as local-dev convenience; in Docker, env vars arrive via Compose `environment:` block (pydantic-settings reads `os.environ` regardless of `env_file`)
8. `python-dotenv` kept as an explicit pinned dependency in `requirements.txt` (pydantic-settings uses it at runtime for `env_file` support)
9. `pydantic-settings` added to `requirements.txt`
10. All caller interfaces unchanged — `settings.<FIELD>` attribute access is preserved
11. `.env.example` updated to mark `DATABASE_URL` and `POLYGON_API_KEY` as required, and add `CORS_ORIGINS` example

## Architecture

### Files Changed

| File | Change |
|------|--------|
| `backend/requirements.txt` | Add `pydantic-settings` |
| `backend/app/core/config.py` | Rewrite `Settings` class |
| `.env.example` | Add `CORS_ORIGINS`, mark required fields |

No callers change — `settings.*` attribute access works identically whether `Settings` is a plain class or `BaseSettings`.

### New `config.py`

```python
from functools import lru_cache
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
    )

    # Required — app cannot start without these
    DATABASE_URL: str
    POLYGON_API_KEY: str

    # Polygon.io
    POLYGON_DELAYED: bool = True

    # Redis / Celery
    REDIS_URL: str = "redis://redis:6379/0"

    # Application
    APP_NAME: str = "Stock Scanner API"
    APP_VERSION: str = "1.0.0"
    LOG_LEVEL: str = "INFO"
    ENVIRONMENT: str = "production"

    # Error Tracking
    SEQ_URL: str = "http://seq:5341"

    # CORS — JSON array in .env: CORS_ORIGINS=["http://localhost:3333"]
    CORS_ORIGINS: list[str] = ["http://localhost:3333"]

    # IBKR
    IBKR_HOST: str = "127.0.0.1"
    IBKR_PORT: int = 7496
    IBKR_CLIENT_ID: int = 10
    IBKR_TRADING_CLIENT_ID: int = 11

    # SMTP
    SMTP_HOST: str = "smtp.gmail.com"
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM_EMAIL: str = "MarketHawk Alerts <noreply@example.com>"

    # VAPID
    VAPID_PRIVATE_KEY: str = ""
    VAPID_PUBLIC_KEY: str = ""
    VAPID_CLAIMS_EMAIL: str = "mailto:admin@example.com"

    @field_validator("DATABASE_URL")
    @classmethod
    def validate_database_url(cls, v: str) -> str:
        if not v.startswith("postgresql"):
            raise ValueError("DATABASE_URL must start with 'postgresql'")
        return v

    @field_validator("IBKR_PORT", "SMTP_PORT")
    @classmethod
    def validate_port_range(cls, v: int) -> int:
        if not (1 <= v <= 65535):
            raise ValueError(f"Port must be between 1 and 65535, got {v}")
        return v


@lru_cache()
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
```

### `.env.example` additions

```
# --- Required (app will not start without these) ---
DATABASE_URL=postgresql://username:password@localhost/stockscanner
POLYGON_API_KEY=your_polygon_api_key_here

# CORS origins — JSON array (default allows localhost:3333 only)
# CORS_ORIGINS=["http://localhost:3333","http://localhost:3000"]
```

### Behavior Change: `POLYGON_API_KEY` now required

The current code defaults `POLYGON_API_KEY` to `""`. After this migration, the app will fail at startup if the key is not set. This is intentional — callers that receive an empty key make API calls that fail with HTTP 401, producing confusing errors. Failing fast at startup with a clear validation message is strictly better. Any dev environment missing this key will need it added to `.env`.

## Alternatives Considered

### A — Minimal: only fix the `int()` crash cases

Add `IBKR_PORT: int = 7496` etc. without inheriting from `BaseSettings`. Keep `os.getenv()` but wrap with pydantic `validator`-style manual parsing. Rejected: doesn't address the root cause (no type coercion, no startup validation, no `.env` native support), only fixes one symptom.

### B — Full migration with testing infrastructure *(chosen)*

Inherit from `BaseSettings`, add validators, remove `load_dotenv`, make `CORS_ORIGINS` env-configurable. No test-fixture infrastructure added (that's a testability benefit the caller gets for free — tests can now instantiate `Settings(DATABASE_URL=..., POLYGON_API_KEY=...)` directly without env var mocking).

### C — Staged: migrate now, leave `CORS_ORIGINS` for issue #84

Defer `CORS_ORIGINS` env-configurability to the auth issue. Rejected: the issue explicitly lists it in scope, it's trivially done alongside the migration, and issue #84 (authentication) needs it to lock down CORS origins.

## Open Questions

- **`POLYGON_API_KEY` default removal**: Any CI pipeline or test suite that runs without `POLYGON_API_KEY` set will now fail at import time (when `settings = get_settings()` executes). Tests should set this env var or patch `get_settings`. No dedicated settings tests exist today — if this surfaces problems, a test fixture that patches `get_settings()` can be added separately.

## Assumptions

- `pydantic-settings` version is not pinned in the issue; use the latest stable release compatible with pydantic v2 (the project already uses pydantic v2 for schema validation).
- `case_sensitive=True` is appropriate — all existing env var names are uppercase, matching the Docker Compose `environment:` keys exactly.
- `lru_cache` on `get_settings()` is preserved; the cache is cleared in tests by calling `get_settings.cache_clear()` if needed.
- The existing hardcoded `CORS_ORIGINS: list = ["*"]` is a security gap; changing the default to `["http://localhost:3333"]` is intentional and aligned with issue #84.

## Acceptance Criteria

- [ ] `Settings` inherits from `BaseSettings`; no `os.getenv()` calls remain in `config.py`
- [ ] Starting the app without `DATABASE_URL` or `POLYGON_API_KEY` produces a clear pydantic `ValidationError` at startup
- [ ] Invalid `IBKR_PORT` or `SMTP_PORT` (non-numeric or out of range) produces a clear error at startup
- [ ] `CORS_ORIGINS` reads from env var when set; defaults to `["http://localhost:3333"]` when not set
- [ ] `load_dotenv` import and call removed from `config.py`
- [ ] `pydantic-settings` present in `requirements.txt`; `python-dotenv` remains
- [ ] All 30+ callers of `settings.*` work without changes
- [ ] Backend reloads cleanly with a valid `.env` after migration
