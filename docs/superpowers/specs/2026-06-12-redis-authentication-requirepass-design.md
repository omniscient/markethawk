# Redis Authentication — requirepass Implementation

**Date:** 2026-06-12  
**Issue:** #370  
**Source:** Defensive Security Review 2026-06-12, finding F-NET-01  
**Status:** Spec

---

## Problem

Redis runs inside the `stockscanner-network` Docker bridge with no authentication
(`requirepass` unset). Any container on that network — a compromised sidecar, a
malicious transitive dependency, or a foothold via the `docker-socket-proxy` path —
can read the application cache, inject arbitrary Celery tasks (including
`execute_auto_trade`), and publish to the WebSocket pub/sub channels
(`tweet_signals:all`, `watchlist:live_data`, `watchlist:alerts`) that stream
directly to authenticated browser clients.

CWE-306 (Missing Authentication for Critical Function) · CIS Docker network controls.

---

## Requirements

1. The Redis service must require a password on every connection (`requirepass`).
2. `REDIS_PASSWORD` must be set in `.env` (≥ 16 characters); startup fails with a
   clear error message if it is absent, empty, or too short.
3. All services that connect to Redis must use the authenticated URL form
   `redis://:${REDIS_PASSWORD}@redis:6379/<db>`.
4. The health check must continue to pass once authentication is enabled.
5. Local development is fully authenticated end-to-end; developers do not need to
   disable authentication to run the stack.
6. The `REDIS_URL` consumed by application code is always the authenticated form —
   no consumer needs to be changed.
7. Celery's `task_serializer` / `accept_content` must be explicitly set to `'json'`
   (currently the effective default; making it explicit prevents any future `pickle`
   regression).

---

## Architecture / Approach

### Approach chosen: simple `requirepass`, password-derived `REDIS_URL`

**Rejected: Full Redis 6 ACLs (one user per service).** ACLs add significant
complexity — a `redis.conf` file per environment, least-privilege command sets per
role, per-service usernames in each URL — and the label is `size: M`. ACLs are the
right follow-on hardening; they are out of scope here. File as a separate
`should-have` ticket if desired.

---

### 1. `REDIS_PASSWORD` field in `backend/app/core/config.py`

Add a `REDIS_PASSWORD` field alongside the existing `REDIS_URL`:

```python
# Redis / Celery
REDIS_PASSWORD: str = ""
REDIS_URL: str = "redis://redis:6379/0"
RATE_LIMITING_ENABLED: bool = True
```

Add a `field_validator` that mirrors the `JWT_SECRET_KEY` style:

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
```

Add a `model_validator(mode='after')` that rebuilds `REDIS_URL` with the password
so consumers never need to change and the password is never duplicated across
compose env vars:

```python
@model_validator(mode='after')
def _build_redis_url(self) -> 'Settings':
    if self.REDIS_PASSWORD:
        scheme, rest = self.REDIS_URL.split("://", 1)
        # Drop any existing auth info
        if "@" in rest:
            rest = rest.split("@", 1)[1]
        self.REDIS_URL = f"{scheme}://:{self.REDIS_PASSWORD}@{rest}"
    return self
```

`rate_limits.py` derives DB `/1` via `REDIS_URL.rsplit("/", 1)[0] + "/1"` — this
continues to work correctly with the password-bearing URL
(`redis://:pass@redis:6379/1`).

The validator follows the `REDIS_PASSWORD` → `REDIS_URL` dependency: because
`field_validator` runs before `model_validator`, the password is already validated
to be ≥ 16 chars when `_build_redis_url` runs.

**Note:** Add `os.environ.setdefault("REDIS_PASSWORD", "devpassword1234567890abc")` at
the top of `backend/tests/conftest.py` (before the app import) so existing tests
that construct `Settings()` without an env var don't break. This follows the
established pattern for `JWT_SECRET_KEY` and `DATABASE_URL` in that file.

---

### 2. Redis service in `docker-compose.yml`

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
```

Key points:
- `--requirepass ${REDIS_PASSWORD}` — enables authentication.
- `--appendonly yes` — preserves AOF persistence that the current volume-backed
  setup implies (no regression on restart).
- `REDISCLI_AUTH: ${REDIS_PASSWORD}` — the `redis-cli` binary reads this env var
  automatically, so the healthcheck `["CMD", "redis-cli", ...]` passes without
  `-a` in the command array (avoids the password appearing in process listings).
- `--no-auth-warning` — suppresses the `Warning: Using a password with '-a' or
  '-u' option on the command line interface may not be safe.` log line that would
  clutter healthcheck output.

---

### 3. Backend-derived services in `docker-compose.yml`

For `backend`, `celery-worker`, `celery-beat`, and `live-scanner` (all use the
Python `Settings` model_validator):

- **Remove** `REDIS_URL: redis://redis:6379/0` from each service's `environment:`
  block — the Settings model_validator builds the authenticated URL from
  `REDIS_PASSWORD`.
- **Add** `REDIS_PASSWORD: ${REDIS_PASSWORD}` to each service's `environment:`
  block — the field_validator enforces length ≥ 16 at startup, giving a clear
  error before any Redis connection is attempted.

---

### 4. Flower in `docker-compose.yml`

Flower reads `CELERY_BROKER_URL` and `CELERY_RESULT_BACKEND` directly (does not
use the Python `Settings` class). Update both to the authenticated form:

```yaml
flower:
  environment:
    CELERY_BROKER_URL: "redis://:${REDIS_PASSWORD}@redis:6379/0"
    CELERY_RESULT_BACKEND: "redis://:${REDIS_PASSWORD}@redis:6379/0"
```

---

### 5. tweet-monitor in `docker-compose.yml`

`services/tweet-monitor/app/config.py` uses its own `Settings` class with a
case-insensitive `redis_url` field. Docker Compose sets `REDIS_URL` as an env var
which pydantic-settings maps to `redis_url`. Update:

```yaml
tweet-monitor:
  environment:
    REDIS_URL: "redis://:${REDIS_PASSWORD}@redis:6379/0"
```

No changes to tweet-monitor's Python code are required.

---

### 6. Celery serialization — make explicit

In `backend/app/core/celery_app.py`, add explicit serialization config to prevent
any future `pickle` regression:

```python
celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
)
```

---

### 7. `.env.example`

Change the Redis section from optional/commented to required, mirroring the
PostgreSQL password section style:

```
# =============================================================================
# REQUIRED: Redis Authentication
# =============================================================================
# Generate with: python -c 'import secrets; print(secrets.token_urlsafe(24))'
# Startup validation fails if this is absent or fewer than 16 characters.
REDIS_PASSWORD=change_me_redis_password
```

---

### 8. `ENV_VARIABLES.md`

Add a row for `REDIS_PASSWORD` in the Redis/Celery section:

| Variable | Default | Description |
|----------|---------|-------------|
| `REDIS_PASSWORD` | *(none — required)* | Redis authentication password. Minimum 16 characters. Set `requirepass` on the Redis container and injected into `REDIS_URL` at startup. |

---

### 9. `docker-compose.override.yml` — no changes required

The override file does not need changes. The `.env` file (or `.env.example` with
`REDIS_PASSWORD=change_me_redis_password`) is loaded by Docker Compose for all
environments including local dev. The base `docker-compose.yml` redis service now
carries the `--requirepass` command, so local dev is fully authenticated using
whatever `REDIS_PASSWORD` is in `.env`.

---

## Alternatives Considered

### A: Compose-level URL construction (rejected for backend services)

Set `REDIS_URL: "redis://:${REDIS_PASSWORD}@redis:6379/0"` in compose for each
service instead of using a `model_validator`. Rejected because it duplicates the
`${REDIS_PASSWORD}` placeholder in every service's env block and does not
centralise the "URL contains password" invariant in Python code. The
`model_validator` approach is a single place to audit.

### B: Full Redis ACLs (rejected — scope)

One named user per service with least-privilege command sets. Correct long-term
direction but realistically an `L` ticket. Noted as a follow-up.

---

## Open Questions (non-blocking)

- **ACL follow-up**: Should a `should-have` ticket be filed for per-service Redis
  ACLs as defence-in-depth once this fix is merged?
- **Key rotation**: No rotation mechanism is specified. If `REDIS_PASSWORD` is
  changed on a running system, all services must restart atomically. This is
  acceptable for now; automation could be added later.

---

## Assumptions

- `--appendonly yes` is safe to add to the Redis command (no data loss); the stack
  already mounts a `redis_data` named volume so persistence is expected.
- `docker-compose.override.yml` is present in all developer checkouts and the
  `.env` file is populated from `.env.example` as documented in `DEVELOPMENT.md`.
- `REDISCLI_AUTH` is supported by the Redis 7 Alpine image (it is; available since
  Redis 6.0 via the `redis-cli` binary).
- The `tweet-monitor` service does not require a password validator in its own
  Settings class; authentication is enforced at the Redis server level regardless.

---

## Verification

```bash
# 1. Restart the stack with REDIS_PASSWORD set
docker compose up -d redis backend celery-worker celery-beat flower tweet-monitor live-scanner

# 2. Confirm Redis rejects unauthenticated connections
docker compose exec redis redis-cli ping
# Expected: (error) NOAUTH Authentication required

# 3. Confirm healthcheck passes
docker compose ps redis
# Expected: status "healthy"

# 4. Confirm backend boots and processes tasks
docker compose logs backend --tail=20
docker compose logs celery-worker --tail=20
# No "NOAUTH" or "AUTH" errors

# 5. Confirm startup fails fast on missing password
REDIS_PASSWORD="" docker compose up backend
# Expected: ValueError: REDIS_PASSWORD must be at least 16 characters
```
