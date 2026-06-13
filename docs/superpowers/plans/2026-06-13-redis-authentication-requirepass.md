# Plan: Redis Authentication — requirepass Implementation

**Date:** 2026-06-13  
**Issue:** #370  
**Branch:** `refine/issue-370--security--f-net-01--redis-has-no-authen`  
**Spec:** `docs/superpowers/specs/2026-06-12-redis-authentication-requirepass-design.md`

---

## Goal

Enable Redis `requirepass` authentication across the entire MarketHawk stack.
Every container that speaks to Redis must use a password; startup fails fast if
`REDIS_PASSWORD` is absent or too short; no application consumer needs to be
changed because `Settings._build_redis_url` injects the password into `REDIS_URL`
transparently.

---

## Architecture

- `backend/app/core/config.py` holds the single `REDIS_PASSWORD` field and a
  `model_validator` that rewrites `REDIS_URL` to the authenticated form.
- `docker-compose.yml` passes `REDIS_PASSWORD` to the Redis container as
  `--requirepass` and to each Python service as a plain env var (not a URL).
- Flower and tweet-monitor receive a pre-composed authenticated URL because they
  do not use the Python `Settings` class.
- `celery_app.conf.update` explicitly pins serialisation to JSON to prevent
  future pickle regressions.

---

## Tech Stack

**Backend:** FastAPI + pydantic-settings + Celery  
**Infrastructure:** Docker Compose, Redis 7 Alpine  
**Tests:** pytest, monkeypatch

---

## File Structure

| File | Change |
|------|--------|
| `backend/app/core/config.py` | Add `REDIS_PASSWORD` field, `field_validator`, `model_validator` |
| `backend/tests/conftest.py` | Add `setdefault("REDIS_PASSWORD", ...)` before app imports |
| `backend/tests/test_settings.py` | Add `TestRedisPasswordValidator` test class |
| `backend/app/core/celery_app.py` | Add explicit JSON serialisation config |
| `backend/tests/core/test_celery_app.py` | Add serialisation config test |
| `docker-compose.yml` | Redis container hardening + env updates for all consumers |
| `.env.example` | Replace optional Redis section with required `REDIS_PASSWORD` |
| `ENV_VARIABLES.md` | Add `REDIS_PASSWORD` row to Redis/Celery table |

---

## Task 1 — `REDIS_PASSWORD` field, validator, and URL injection in Settings

**Files:**
- `backend/app/core/config.py`
- `backend/tests/conftest.py`
- `backend/tests/test_settings.py`

### Steps

**Step 1.1 — Write failing tests**

Add `TestRedisPasswordValidator` to `backend/tests/test_settings.py`:

```python
class TestRedisPasswordValidator:
    def test_password_too_short_raises(self):
        from app.core.config import Settings

        with pytest.raises(ValidationError, match="REDIS_PASSWORD must be at least 16 characters"):
            Settings(
                DATABASE_URL="postgresql://test:test@localhost/test",
                POLYGON_API_KEY="test-key",
                REDIS_PASSWORD="short",
            )

    def test_empty_password_raises(self):
        from app.core.config import Settings

        with pytest.raises(ValidationError, match="REDIS_PASSWORD must be at least 16 characters"):
            Settings(
                DATABASE_URL="postgresql://test:test@localhost/test",
                POLYGON_API_KEY="test-key",
                REDIS_PASSWORD="",
            )

    def test_valid_password_builds_authenticated_url(self):
        from app.core.config import Settings

        s = Settings(
            DATABASE_URL="postgresql://test:test@localhost/test",
            POLYGON_API_KEY="test-key",
            REDIS_PASSWORD="devpassword1234567890abc",
        )
        assert s.REDIS_URL == "redis://:devpassword1234567890abc@redis:6379/0"

    def test_preexisting_auth_in_redis_url_is_stripped(self):
        from app.core.config import Settings

        s = Settings(
            DATABASE_URL="postgresql://test:test@localhost/test",
            POLYGON_API_KEY="test-key",
            REDIS_URL="redis://:oldpass@redis:6379/0",
            REDIS_PASSWORD="devpassword1234567890abc",
        )
        assert s.REDIS_URL == "redis://:devpassword1234567890abc@redis:6379/0"

    def test_db_path_preserved_in_authenticated_url(self):
        """rate_limits.py uses rsplit('/', 1) — the /0 db path must survive injection."""
        from app.core.config import Settings

        s = Settings(
            DATABASE_URL="postgresql://test:test@localhost/test",
            POLYGON_API_KEY="test-key",
            REDIS_PASSWORD="devpassword1234567890abc",
        )
        assert s.REDIS_URL.endswith("/0")
```

**Step 1.2 — Verify tests fail**

```bash
cd /workspace/markethawk
docker compose exec backend python -m pytest backend/tests/test_settings.py::TestRedisPasswordValidator -x 2>&1 | tail -20
```

Expected: `FAILED` — `AttributeError` or `ValidationError` on missing field.

**Step 1.3 — Update conftest.py** (memory pattern: always add `setdefault` before app import for new validators)

Add to `backend/tests/conftest.py` after the existing `setdefault` lines (line 10, before the blank line):

```python
os.environ.setdefault("REDIS_PASSWORD", "devpassword1234567890abc")
```

The full setdefault block becomes:

```python
os.environ.setdefault("RATE_LIMITING_ENABLED", "false")

os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost/test")
os.environ.setdefault("POLYGON_API_KEY", "test-key-for-unit-tests-only")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret-key-for-unit-tests-only-aaa")
os.environ.setdefault("REDIS_PASSWORD", "devpassword1234567890abc")
```

**Step 1.4 — Implement in config.py**

Update `backend/app/core/config.py` imports (line 7) to add `model_validator`:

```python
from pydantic import field_validator, model_validator
```

Add `REDIS_PASSWORD` field after `REDIS_URL` (after line 24):

```python
    # Redis / Celery
    REDIS_PASSWORD: str = ""
    REDIS_URL: str = "redis://redis:6379/0"
    RATE_LIMITING_ENABLED: bool = True
```

Add the `field_validator` for `REDIS_PASSWORD` after the `JWT_SECRET_KEY` validator (after line 145):

```python
    @field_validator("REDIS_PASSWORD")
    @classmethod
    def validate_redis_password(cls, v: str) -> str:
        if len(v) < 16:
            raise ValueError(
                "REDIS_PASSWORD must be at least 16 characters. "
                "Generate one with: python -c 'import secrets; print(secrets.token_urlsafe(24))'"
            )
        return v

    @model_validator(mode="after")
    def _build_redis_url(self) -> "Settings":
        if self.REDIS_PASSWORD:
            scheme, rest = self.REDIS_URL.split("://", 1)
            if "@" in rest:
                rest = rest.split("@", 1)[1]
            self.REDIS_URL = f"{scheme}://:{self.REDIS_PASSWORD}@{rest}"
        return self
```

**Step 1.5 — Verify tests pass**

```bash
docker compose exec backend python -m pytest backend/tests/test_settings.py -x -q 2>&1 | tail -20
```

Expected: all tests pass, including new `TestRedisPasswordValidator`.

**Step 1.6 — Commit**

```bash
git add backend/app/core/config.py backend/tests/conftest.py backend/tests/test_settings.py
git commit -m "feat(security): add REDIS_PASSWORD field_validator and model_validator to Settings

Validates password >= 16 chars at startup and rewrites REDIS_URL to the
authenticated form so no consumer changes are needed. Follows the established
JWT_SECRET_KEY validator pattern.

Closes part of #370"
```

---

## Task 2 — Explicit Celery JSON serialisation

**Files:**
- `backend/app/core/celery_app.py`
- `backend/tests/core/test_celery_app.py`

### Steps

**Step 2.1 — Write failing test**

Add to `backend/tests/core/test_celery_app.py`:

```python
def test_celery_app_uses_json_serialization():
    """celery_app must explicitly set JSON serialisation to prevent pickle regressions."""
    from app.core.celery_app import celery_app

    assert celery_app.conf.task_serializer == "json"
    assert celery_app.conf.result_serializer == "json"
    assert celery_app.conf.accept_content == ["json"]
```

**Step 2.2 — Verify test fails**

```bash
docker compose exec backend python -m pytest backend/tests/core/test_celery_app.py::test_celery_app_uses_json_serialization -x 2>&1 | tail -10
```

Expected: `FAILED` — assertion error on `celery_app.conf.task_serializer` (currently inherits implicit default).

**Step 2.3 — Implement in celery_app.py**

Add `celery_app.conf.update` immediately after the `Celery(...)` constructor call (after line 15):

```python
celery_app = Celery(
    "stockscanner",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
    include=["app.tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
)
```

**Step 2.4 — Verify tests pass**

```bash
docker compose exec backend python -m pytest backend/tests/core/test_celery_app.py -x -q 2>&1 | tail -10
```

Expected: all 3 tests pass.

**Step 2.5 — Commit**

```bash
git add backend/app/core/celery_app.py backend/tests/core/test_celery_app.py
git commit -m "feat(security): pin Celery serialisation to JSON explicitly

Makes the existing implicit default explicit, preventing any future pickle
regression if a plugin or upgrade changes the effective default.

Part of #370"
```

---

## Task 3 — Redis container hardening in docker-compose.yml

**Files:**
- `docker-compose.yml`

### Steps

**Step 3.1 — Update the redis service block**

Replace the current redis service (lines ~60–78) with the authenticated, AOF-enabled, healthcheck-corrected form:

```yaml
  redis:
    image: redis:7-alpine
    container_name: stockscanner-redis
    command: >
      redis-server
      --requirepass ${REDIS_PASSWORD}
      --appendonly yes
    environment:
      REDISCLI_AUTH: ${REDIS_PASSWORD}
    ports:
      - "127.0.0.1:6379:6379"
    volumes:
      - redis_data:/data
    networks:
      - stockscanner-network
    healthcheck:
      test: ["CMD", "redis-cli", "--no-auth-warning", "ping"]
      interval: 5s
      timeout: 3s
      retries: 10
    restart: unless-stopped
    deploy:
      resources:
        limits:
          memory: 512M
```

Key changes:
- `command:` adds `--requirepass ${REDIS_PASSWORD}` and `--appendonly yes`
- `environment: REDISCLI_AUTH: ${REDIS_PASSWORD}` lets `redis-cli` authenticate without `-a` in the healthcheck command
- healthcheck gains `--no-auth-warning` to suppress password-in-CLI warnings from cluttering logs

**Step 3.2 — Validate compose file**

```bash
docker compose config --quiet 2>&1 | head -20
```

Expected: no output (clean parse) or "services:" printed without errors.

**Step 3.3 — Commit**

```bash
git add docker-compose.yml
git commit -m "feat(security): enable Redis requirepass and AOF in docker-compose

Adds --requirepass \${REDIS_PASSWORD} command, REDISCLI_AUTH env var for
cli-based healthcheck, and --appendonly yes to preserve AOF persistence.

Part of #370"
```

---

## Task 4 — Remove hard-coded REDIS_URL from backend-derived services

**Files:**
- `docker-compose.yml`

### Steps

**Step 4.1 — Update backend service environment**

In the `backend` service environment block, replace:
```yaml
      REDIS_URL: redis://redis:6379/0
```
with:
```yaml
      REDIS_PASSWORD: ${REDIS_PASSWORD}
```

**Step 4.2 — Update celery-worker service environment**

In the `celery-worker` service environment block, replace:
```yaml
      REDIS_URL: redis://redis:6379/0
```
with:
```yaml
      REDIS_PASSWORD: ${REDIS_PASSWORD}
```

**Step 4.3 — Update celery-beat service environment**

In the `celery-beat` service environment block, replace:
```yaml
      REDIS_URL: redis://redis:6379/0
```
with:
```yaml
      REDIS_PASSWORD: ${REDIS_PASSWORD}
```

**Step 4.4 — Update live-scanner service environment**

In the `live-scanner` service environment block, replace:
```yaml
      REDIS_URL: redis://redis:6379/0
```
with:
```yaml
      REDIS_PASSWORD: ${REDIS_PASSWORD}
```

**Step 4.5 — Validate compose file**

```bash
docker compose config --quiet 2>&1 | head -5
```

Also confirm the old URL is gone:

```bash
grep "redis://redis:6379/0" docker-compose.yml | grep -v "flower\|tweet-monitor\|CELERY_BROKER"
```

Expected: only `flower` and `tweet-monitor` lines (not the backend-derived services).

**Step 4.6 — Commit**

```bash
git add docker-compose.yml
git commit -m "feat(security): replace static REDIS_URL with REDIS_PASSWORD for backend services

backend, celery-worker, celery-beat, live-scanner now receive REDIS_PASSWORD
and let Settings._build_redis_url compose the authenticated URL at startup.

Part of #370"
```

---

## Task 5 — Authenticated URLs for Flower and tweet-monitor

**Files:**
- `docker-compose.yml`

### Steps

**Step 5.1 — Update flower service environment**

In the `flower` service environment block, replace:
```yaml
      CELERY_BROKER_URL: redis://redis:6379/0
      CELERY_RESULT_BACKEND: redis://redis:6379/0
```
with:
```yaml
      CELERY_BROKER_URL: "redis://:${REDIS_PASSWORD}@redis:6379/0"
      CELERY_RESULT_BACKEND: "redis://:${REDIS_PASSWORD}@redis:6379/0"
```

**Step 5.2 — Update tweet-monitor service environment**

In the `tweet-monitor` service environment block, replace:
```yaml
      REDIS_URL: redis://redis:6379/0
```
with:
```yaml
      REDIS_URL: "redis://:${REDIS_PASSWORD}@redis:6379/0"
```

**Step 5.3 — Verify no unauthenticated Redis URLs remain**

```bash
grep "redis://redis:6379" docker-compose.yml
```

Expected: zero matches of the *unauthenticated* form. Backend services use `REDIS_PASSWORD` directly; Flower/tweet-monitor use `redis://:${REDIS_PASSWORD}@redis:6379/0` which contains `@redis:6379` and will not match `redis://redis:6379`.

**Step 5.4 — Validate compose file**

```bash
docker compose config --quiet 2>&1 | head -5
```

**Step 5.5 — Commit**

```bash
git add docker-compose.yml
git commit -m "feat(security): authenticated Redis URLs for Flower and tweet-monitor

These services don't use the Python Settings class, so they receive the full
redis://:password@host:port/db URL directly.

Part of #370"
```

---

## Task 6 — Documentation: .env.example and ENV_VARIABLES.md

**Files:**
- `.env.example`
- `ENV_VARIABLES.md`

### Steps

**Step 6.1 — Update .env.example**

Replace the current optional Redis section in `.env.example`:
```
# =============================================================================
# OPTIONAL: Redis Configuration
# =============================================================================
# Uncomment and modify if you want to use a different Redis instance
# Default: redis://redis:6379/0
# REDIS_URL=redis://host:6379/0
```

with:
```
# =============================================================================
# REQUIRED: Redis Authentication
# =============================================================================
# Generate with: python -c 'import secrets; print(secrets.token_urlsafe(24))'
# Startup validation fails if this is absent or fewer than 16 characters.
REDIS_PASSWORD=change_me_redis_password
```

**Step 6.2 — Add REDIS_PASSWORD row to ENV_VARIABLES.md**

Find the existing Redis/Celery section in `ENV_VARIABLES.md` (currently has `REDIS_URL` row). Add a new row for `REDIS_PASSWORD` immediately before the `REDIS_URL` row:

| Variable | Default | Description |
|----------|---------|-------------|
| `REDIS_PASSWORD` | *(none — required)* | Redis authentication password. Minimum 16 characters. Injected into `REDIS_URL` at startup via `Settings._build_redis_url`. |
| `REDIS_URL` | `redis://redis:6379/0` | Redis connection string. Overriding is only needed for external Redis. |

**Step 6.3 — Commit**

```bash
git add .env.example ENV_VARIABLES.md
git commit -m "docs(security): add REDIS_PASSWORD as required in .env.example and ENV_VARIABLES.md

Converts the Redis section from optional/commented to required, matching
the PostgreSQL password section style. Adds ENV_VARIABLES.md row.

Closes #370"
```

---

## Task 7 — Integration verification

> This task has no commit. It confirms the full stack operates correctly
> with authentication enabled before the PR is raised.

### Steps

**Step 7.1 — Ensure REDIS_PASSWORD is set in .env**

```bash
grep "REDIS_PASSWORD" .env || echo "REDIS_PASSWORD not in .env — add it!"
```

If absent, add a line (generate a secure value):
```bash
python3 -c "import secrets; print('REDIS_PASSWORD=' + secrets.token_urlsafe(24))" >> .env
```

**Step 7.2 — Restart the stack**

```bash
docker compose up -d redis backend celery-worker celery-beat flower tweet-monitor live-scanner
```

**Step 7.3 — Confirm Redis rejects unauthenticated connections**

```bash
docker compose exec redis redis-cli ping
```

Expected:
```
(error) NOAUTH Authentication required
```

**Step 7.4 — Confirm healthcheck passes**

```bash
docker compose ps redis
```

Expected: `Status` column shows `healthy`.

**Step 7.5 — Confirm backend and worker boot without NOAUTH errors**

```bash
docker compose logs backend --tail=20 | grep -i "noauth\|auth\|redis"
docker compose logs celery-worker --tail=20 | grep -i "noauth\|auth\|redis"
```

Expected: no `NOAUTH` or `AUTH` errors; normal startup messages only.

**Step 7.6 — Confirm startup fails fast on missing password**

```bash
REDIS_PASSWORD="" docker compose run --rm --no-deps backend python -c "from app.core.config import Settings; Settings()"
```

Expected output contains:
```
ValueError: REDIS_PASSWORD must be at least 16 characters
```

**Step 7.7 — Run the backend test suite**

```bash
docker compose exec backend python -m pytest backend/tests/test_settings.py backend/tests/core/test_celery_app.py -q 2>&1 | tail -15
```

Expected: all tests pass.
