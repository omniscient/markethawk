# Migrate config.py to pydantic-settings BaseSettings — Implementation Plan

**Issue**: [#91 — Migrate config.py to pydantic-settings BaseSettings](https://github.com/omniscient/markethawk/issues/91)  
**Spec**: `Docs/superpowers/specs/2026-05-27-pydantic-settings-migration-design.md`  
**Date**: 2026-05-28

## Goal

Replace raw `os.getenv()` calls in `backend/app/core/config.py` with a `pydantic_settings.BaseSettings` subclass, adding startup validation for required fields (`DATABASE_URL`, `POLYGON_API_KEY`), port range validators for `IBKR_PORT` and `SMTP_PORT`, a `DATABASE_URL` scheme validator, and env-configurable `CORS_ORIGINS`. Remove `load_dotenv` from `config.py`. All 29 callers continue using `settings.<FIELD>` attribute access without changes.

## Architecture

Single backend file change with no database migration, no new routers, and no frontend changes. The `Settings` class switches base class from `object` to `BaseSettings`; the attribute interface is identical. Callers are unaffected.

## Tech Stack

- Python / FastAPI backend
- pydantic-settings 2.x (pydantic v2 compatible — FastAPI 0.135.3 already uses pydantic v2)

## File Structure

| File | Change |
|------|--------|
| `backend/requirements.txt` | Add `pydantic-settings>=2.0,<3.0` |
| `backend/tests/test_settings.py` | New: unit tests for Settings validation |
| `backend/tests/conftest.py` | Add env var defaults before app imports |
| `backend/tests/api/conftest.py` | Add env var defaults before app imports (defense-in-depth) |
| `backend/app/core/config.py` | Rewrite Settings class |
| `.env.example` | Mark required fields, add CORS_ORIGINS example |

---

## Task 1 — Add `pydantic-settings` to `requirements.txt`

**Files**: `backend/requirements.txt`

### Step 1.1 — Verify the dependency is not yet available

```bash
docker-compose exec backend python -c "from pydantic_settings import BaseSettings"
```

**Expected output**:
```
ModuleNotFoundError: No module named 'pydantic_settings'
```

### Step 1.2 — Add the dependency

Edit `backend/requirements.txt`. After the `python-dotenv==1.2.2` line in the `# Environment Variables` section:

```diff
 # Environment Variables
 python-dotenv==1.2.2
+pydantic-settings>=2.0,<3.0
```

### Step 1.3 — Install inside the container

```bash
docker-compose exec backend pip install "pydantic-settings>=2.0,<3.0"
```

**Expected output**: Successfully installed pydantic-settings-...

### Step 1.4 — Verify pass

```bash
docker-compose exec backend python -c "from pydantic_settings import BaseSettings; print('OK')"
```

**Expected output**: `OK`

### Step 1.5 — Commit

```bash
git add backend/requirements.txt
git commit -m "chore(deps): add pydantic-settings to requirements"
```

---

## Task 2 — Write failing tests for Settings validation

**Files**: `backend/tests/test_settings.py` (new file)

### Step 2.1 — Create the test file

Create `backend/tests/test_settings.py` with the following content:

```python
import os
import pytest
from pydantic import ValidationError


@pytest.fixture(autouse=True)
def clear_settings_cache():
    from app.core.config import get_settings
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


class TestSettingsRequiredFields:
    def test_missing_database_url_raises(self):
        from app.core.config import Settings
        with pytest.raises(ValidationError):
            Settings(POLYGON_API_KEY="test-key")

    def test_missing_polygon_api_key_raises(self):
        from app.core.config import Settings
        with pytest.raises(ValidationError):
            Settings(DATABASE_URL="postgresql://test:test@localhost/test")

    def test_valid_required_fields_succeeds(self):
        from app.core.config import Settings
        s = Settings(
            DATABASE_URL="postgresql://test:test@localhost/test",
            POLYGON_API_KEY="test-key",
        )
        assert s.DATABASE_URL == "postgresql://test:test@localhost/test"
        assert s.POLYGON_API_KEY == "test-key"


class TestDatabaseUrlValidator:
    def test_non_postgresql_url_raises(self):
        from app.core.config import Settings
        with pytest.raises(ValidationError):
            Settings(
                DATABASE_URL="mysql://test:test@localhost/test",
                POLYGON_API_KEY="test-key",
            )

    def test_postgresql_asyncpg_scheme_accepted(self):
        from app.core.config import Settings
        s = Settings(
            DATABASE_URL="postgresql+asyncpg://test:test@localhost/test",
            POLYGON_API_KEY="test-key",
        )
        assert s.DATABASE_URL.startswith("postgresql+asyncpg")


class TestPortValidators:
    def test_ibkr_port_zero_raises(self):
        from app.core.config import Settings
        with pytest.raises(ValidationError):
            Settings(
                DATABASE_URL="postgresql://test:test@localhost/test",
                POLYGON_API_KEY="test-key",
                IBKR_PORT=0,
            )

    def test_ibkr_port_too_high_raises(self):
        from app.core.config import Settings
        with pytest.raises(ValidationError):
            Settings(
                DATABASE_URL="postgresql://test:test@localhost/test",
                POLYGON_API_KEY="test-key",
                IBKR_PORT=65536,
            )

    def test_smtp_port_out_of_range_raises(self):
        from app.core.config import Settings
        with pytest.raises(ValidationError):
            Settings(
                DATABASE_URL="postgresql://test:test@localhost/test",
                POLYGON_API_KEY="test-key",
                SMTP_PORT=99999,
            )

    def test_valid_ports_accepted(self):
        from app.core.config import Settings
        s = Settings(
            DATABASE_URL="postgresql://test:test@localhost/test",
            POLYGON_API_KEY="test-key",
            IBKR_PORT=7497,
            SMTP_PORT=465,
        )
        assert s.IBKR_PORT == 7497
        assert s.SMTP_PORT == 465


class TestCorsOrigins:
    def test_default_cors_origins(self):
        from app.core.config import Settings
        s = Settings(
            DATABASE_URL="postgresql://test:test@localhost/test",
            POLYGON_API_KEY="test-key",
        )
        assert s.CORS_ORIGINS == ["http://localhost:3333"]

    def test_cors_origins_from_env(self, monkeypatch):
        monkeypatch.setenv(
            "CORS_ORIGINS",
            '["http://localhost:3333","http://localhost:3000"]',
        )
        from app.core.config import Settings
        s = Settings(
            DATABASE_URL="postgresql://test:test@localhost/test",
            POLYGON_API_KEY="test-key",
        )
        assert "http://localhost:3333" in s.CORS_ORIGINS
        assert "http://localhost:3000" in s.CORS_ORIGINS


class TestNoDotenvImport:
    def test_load_dotenv_not_in_source(self):
        import inspect
        from app.core import config as cfg_module
        source = inspect.getsource(cfg_module)
        assert "load_dotenv" not in source
        assert "from dotenv" not in source


class TestAttributeAccessPreserved:
    def test_settings_attributes_accessible(self):
        from app.core.config import Settings
        s = Settings(
            DATABASE_URL="postgresql://test:test@localhost/test",
            POLYGON_API_KEY="test-key",
        )
        assert isinstance(s.REDIS_URL, str)
        assert isinstance(s.APP_NAME, str)
        assert isinstance(s.IBKR_PORT, int)
        assert isinstance(s.SMTP_PORT, int)
        assert isinstance(s.CORS_ORIGINS, list)
        assert isinstance(s.IBKR_CLIENT_ID, int)
        assert isinstance(s.IBKR_TRADING_CLIENT_ID, int)
        assert isinstance(s.POLYGON_DELAYED, bool)
```

### Step 2.2 — Verify fail

```bash
docker-compose exec backend python -m pytest tests/test_settings.py -v
```

**Expected output**: Multiple test errors and failures. The current `Settings` is a plain class that does not accept constructor arguments, so `Settings(...)` raises `TypeError`. Tests that only catch `ValidationError` (including `test_missing_database_url_raises`, `test_missing_polygon_api_key_raises`, all port tests, and `test_non_postgresql_url_raises`) will ERROR because `TypeError` propagates uncaught. `test_valid_required_fields_succeeds`, `test_postgresql_asyncpg_scheme_accepted`, `test_valid_ports_accepted`, and `test_settings_attributes_accessible` will FAIL because `TypeError` is raised rather than returning a valid instance. `test_load_dotenv_not_in_source` will FAIL because `load_dotenv` is present. `test_default_cors_origins` will FAIL because the default is `["*"]`, not `["http://localhost:3333"]`. All tests should be non-passing — this is the correct red state.

### Step 2.3 — Commit tests (red state)

```bash
git add backend/tests/test_settings.py
git commit -m "test(config): add failing tests for BaseSettings migration"
```

---

## Task 3 — Set required test env vars in conftest files before app imports

**Files**: `backend/tests/conftest.py`, `backend/tests/api/conftest.py`

After Task 4 rewrites `config.py`, the module-level `settings = get_settings()` will raise `ValidationError` at import time if `DATABASE_URL` or `POLYGON_API_KEY` are absent. Both conftest files do module-level app imports that trigger `config.py`, so env vars must be set before those lines.

**Pytest conftest loading order**: pytest loads conftest files top-down (root directory first, then subdirectories). So `tests/conftest.py` executes before `tests/api/conftest.py`, which executes before any test file in `tests/api/`. Setting env vars in the root conftest is sufficient to protect all descendant imports. The guard in `tests/api/conftest.py` below is defense-in-depth and makes the requirement explicit at the file level.

### Step 3.1 — Verify existing tests pass (baseline)

```bash
docker-compose exec backend python -m pytest tests/api/test_health.py -v
```

**Expected output**: All tests pass.

### Step 3.2 — Add env var defaults to root conftest.py

Edit `backend/tests/conftest.py`. The file currently starts with `import os`. Add two `os.environ.setdefault` calls immediately after that import, before all other imports:

```diff
 import os
+
+# Must be set before any app imports — config.py validates these at module load.
+os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost/test")
+os.environ.setdefault("POLYGON_API_KEY", "test-polygon-key")
+
 import pytest
```

### Step 3.3 — Add env var defaults to tests/api/conftest.py

Edit `backend/tests/api/conftest.py`. The file currently starts with `import pytest`. Add the same env defaults at the very top, before all other imports:

```diff
+import os
+
+# Defense-in-depth: root conftest.py already sets these, but guard here too.
+os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost/test")
+os.environ.setdefault("POLYGON_API_KEY", "test-polygon-key")
+
 import pytest
 from app.main import app
 from app.core.database import get_db
```

### Step 3.4 — Verify existing tests still pass

```bash
docker-compose exec backend python -m pytest tests/api/test_health.py -v
```

**Expected output**: All tests pass (no regression from the env var defaults).

### Step 3.5 — Commit

```bash
git add backend/tests/conftest.py backend/tests/api/conftest.py
git commit -m "test: set required env defaults before app imports in conftest files"
```

---

## Task 4 — Rewrite config.py with BaseSettings

**Files**: `backend/app/core/config.py`

### Step 4.1 — Confirm tests are still failing

```bash
docker-compose exec backend python -m pytest tests/test_settings.py -v 2>&1 | tail -20
```

**Expected**: Multiple failures (same as Step 2.2).

### Step 4.2 — Rewrite config.py

Replace the entire content of `backend/app/core/config.py` with:

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

### Step 4.3 — Verify new tests pass

```bash
docker-compose exec backend python -m pytest tests/test_settings.py -v
```

**Expected output**: All tests in `test_settings.py` pass (green).

### Step 4.4 — Verify no regression in existing tests

```bash
docker-compose exec backend python -m pytest tests/ -v --ignore=tests/test_settings.py -x 2>&1 | tail -30
```

**Expected output**: All existing tests pass.

### Step 4.5 — Verify backend reloads cleanly with live .env

```bash
docker-compose restart backend
docker-compose logs backend --tail=20
```

**Expected output**: No `ValidationError` in logs. Lines containing `Application startup complete` or `Uvicorn running`.

```bash
curl -s http://localhost:8000/api/health | python -m json.tool
```

**Expected output**: JSON with `"status": "healthy"` or equivalent health response.

### Step 4.6 — Commit

```bash
git add backend/app/core/config.py
git commit -m "feat(config): migrate Settings to pydantic-settings BaseSettings

- Replace os.getenv() calls with BaseSettings field declarations
- Add field_validator for DATABASE_URL (must start with 'postgresql')
- Add field_validator for IBKR_PORT and SMTP_PORT (range 1–65535)
- Make DATABASE_URL and POLYGON_API_KEY required (no default)
- Set CORS_ORIGINS default to ['http://localhost:3333'], env-configurable as JSON array
- Remove load_dotenv() call and dotenv import
- Add SettingsConfigDict with env_file='.env' for local dev convenience

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Task 5 — Update `.env.example`

**Files**: `.env.example`

### Step 5.1 — Identify sections to update

The current `.env.example` already marks `POLYGON_API_KEY` and `DATABASE_URL` as `REQUIRED` in section headers, but does not note that the app now validates them at startup. The `CORS_ORIGINS` variable is absent.

### Step 5.2 — Edit `.env.example`

Make three changes:

**Change 1**: In the `REQUIRED: Polygon.io API Key` section, add a startup validation note:

```diff
 # =============================================================================
 # REQUIRED: Polygon.io API Key
 # =============================================================================
 # Get your API key from: https://polygon.io/dashboard
+# App will not start if this is missing or empty (validated at startup).
 POLYGON_API_KEY=your_polygon_api_key_here
```

**Change 2**: In the `REQUIRED: Database Configuration` section, add a startup validation note below the DATABASE_URL line:

```diff
 # Full connection URL referenced by backend/celery services.
 # Must stay in sync with the three variables above.
 DATABASE_URL=postgresql://postgres:change_me_db_password@postgres:5432/stockscanner
+# App will not start if DATABASE_URL is missing or does not start with 'postgresql'.
```

**Change 3**: After the `OPTIONAL: Environment Settings` section, insert a CORS section. The `.env.example` has `# ENVIRONMENT=development` as the last line in that block, followed by the `REQUIRED: Security` section header. Insert after `# ENVIRONMENT=development`:

```diff
 # Options: development, staging, production
 # Default: development
 # ENVIRONMENT=development

+# =============================================================================
+# OPTIONAL: CORS Origins
+# =============================================================================
+# Comma-free JSON array of allowed frontend origins.
+# Default: ["http://localhost:3333"]
+# CORS_ORIGINS=["http://localhost:3333","http://localhost:3000"]
+
 # =============================================================================
 # REQUIRED: Security
```

### Step 5.3 — Verify no app behavior change (docs only)

```bash
docker-compose logs backend --tail=5
```

**Expected output**: Backend still running healthy (no restart, no errors).

### Step 5.4 — Commit

```bash
git add .env.example
git commit -m "docs(env): mark required fields, add CORS_ORIGINS example"
```

---

## Acceptance Checklist

- [ ] `Settings` inherits from `BaseSettings`; no `os.getenv()` calls remain in `config.py`
- [ ] Starting app without `DATABASE_URL` or `POLYGON_API_KEY` produces `ValidationError` at startup
- [ ] Invalid `IBKR_PORT` or `SMTP_PORT` out of range produces `ValidationError` at startup
- [ ] Non-`postgresql` `DATABASE_URL` produces `ValidationError` at startup
- [ ] `CORS_ORIGINS` reads from env var when set as JSON array; defaults to `["http://localhost:3333"]`
- [ ] `load_dotenv` import and call removed from `config.py`
- [ ] `pydantic-settings` present in `requirements.txt`; `python-dotenv` remains
- [ ] All `tests/test_settings.py` tests pass
- [ ] All pre-existing tests pass without modification
- [ ] Backend reloads cleanly with a valid `.env` after migration
- [ ] `curl http://localhost:8000/api/health` returns healthy response
