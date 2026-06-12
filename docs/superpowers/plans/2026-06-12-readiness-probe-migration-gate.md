# Readiness Probe + Migration Gate — Implementation Plan

**Goal**: Eliminate two deployment-ordering hazards: (1) false-green liveness probe that declares backend healthy before DB/Redis are reachable; (2) backend starting on stale schema because migrations run after `docker compose up -d`.

**Architecture**: Add `/api/ready` readiness endpoint to `backend/app/routers/health.py`; wire Docker Compose healthcheck and `depends_on`; add `alembic check` drift gate via a shared `backend/entrypoint.sh` (Dockerfile `ENTRYPOINT`); fix `deploy.yml` to run migrations before starting services; write ADR-0012.

**Tech Stack**: FastAPI (sync), SQLAlchemy (`SessionLocal`, sync `Session`), Redis sync client (`get_redis()`), Docker Compose, Alembic 1.18.4 (`alembic check` available — >= 1.9 required), GitHub Actions.

**Issue**: [#289 — Add readiness probe (DB/Redis) + migration gate in deploy path](https://github.com/omniscient/markethawk/issues/289)

---

## File Structure

| File | Change |
|---|---|
| `backend/app/routers/health.py` | Add `GET /ready` endpoint with DB + Redis probes |
| `backend/app/main.py` | Add `"/api/ready"` to `EXEMPT_PREFIXES` |
| `backend/tests/api/test_health.py` | Add ready-endpoint tests |
| `docker-compose.yml` | Add backend healthcheck + frontend `depends_on` |
| `backend/entrypoint.sh` | New: `alembic check` drift gate + `exec "$@"` |
| `backend/Dockerfile` | Add `COPY entrypoint.sh`, set `ENTRYPOINT` |
| `.github/workflows/deploy.yml` | Move migration step before `docker compose up -d` |
| `docs/adr/0012-migration-gate-not-auto-migrate.md` | New: ADR documenting rejected auto-migrate |

---

## Task 1: Write failing tests for `/api/ready`

**Files**: `backend/tests/api/test_health.py`

### TDD Steps

**Step 1.1 — Write failing tests (append to existing file)**

```python
# backend/tests/api/test_health.py — append after existing tests

from unittest.mock import MagicMock, patch

def test_ready_all_ok():
    mock_session = MagicMock()
    mock_redis = MagicMock()
    mock_redis.ping.return_value = True

    with patch("app.routers.health.SessionLocal", return_value=mock_session), \
         patch("app.routers.health.get_redis", return_value=mock_redis):
        response = client.get("/api/ready")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ready"
    assert data["checks"]["db"]["status"] == "ok"
    assert isinstance(data["checks"]["db"]["latency_ms"], int)
    assert data["checks"]["redis"]["status"] == "ok"
    assert isinstance(data["checks"]["redis"]["latency_ms"], int)


def test_ready_db_failure():
    mock_session = MagicMock()
    mock_session.execute.side_effect = Exception("Connection refused")
    mock_redis = MagicMock()
    mock_redis.ping.return_value = True

    with patch("app.routers.health.SessionLocal", return_value=mock_session), \
         patch("app.routers.health.get_redis", return_value=mock_redis):
        response = client.get("/api/ready")

    assert response.status_code == 503
    data = response.json()
    assert data["status"] == "unavailable"
    assert data["checks"]["db"]["status"] == "failed"
    assert data["checks"]["db"]["latency_ms"] is None
    assert "Connection refused" in data["checks"]["db"]["error"]
    # Redis probe still ran — no short-circuit
    assert data["checks"]["redis"]["status"] == "ok"
    mock_redis.ping.assert_called_once()


def test_ready_redis_failure():
    mock_session = MagicMock()
    mock_redis = MagicMock()
    mock_redis.ping.side_effect = Exception("NOAUTH Authentication required")

    with patch("app.routers.health.SessionLocal", return_value=mock_session), \
         patch("app.routers.health.get_redis", return_value=mock_redis):
        response = client.get("/api/ready")

    assert response.status_code == 503
    data = response.json()
    assert data["status"] == "unavailable"
    assert data["checks"]["db"]["status"] == "ok"  # DB probe still ran
    assert data["checks"]["redis"]["status"] == "failed"
    assert data["checks"]["redis"]["latency_ms"] is None


def test_ready_both_probes_always_run():
    """Both probes run even when the first one fails — no short-circuit."""
    mock_session = MagicMock()
    mock_session.execute.side_effect = Exception("DB timeout")
    mock_redis = MagicMock()
    mock_redis.ping.return_value = True

    with patch("app.routers.health.SessionLocal", return_value=mock_session), \
         patch("app.routers.health.get_redis", return_value=mock_redis):
        response = client.get("/api/ready")

    data = response.json()
    assert "db" in data["checks"]
    assert "redis" in data["checks"]
    mock_redis.ping.assert_called_once()


def test_ready_exempt_from_auth():
    c = TestClient(app)
    mock_session = MagicMock()
    mock_redis = MagicMock()
    mock_redis.ping.return_value = True

    with patch("app.routers.health.SessionLocal", return_value=mock_session), \
         patch("app.routers.health.get_redis", return_value=mock_redis):
        response = c.get("/api/ready")

    assert response.status_code != 401
```

**Step 1.2 — Verify tests fail**

```bash
cd /workspace/markethawk
docker compose exec backend python -m pytest backend/tests/api/test_health.py::test_ready_all_ok -x 2>&1 | tail -10
```

Expected: `FAILED` or `ImportError` — confirms tests are failing before implementation.

**Step 1.3 — Commit**

```bash
git add backend/tests/api/test_health.py
git commit -m "test: failing tests for /api/ready readiness endpoint (#289)"
```

---

## Task 2: Implement `/api/ready` endpoint

**Files**: `backend/app/routers/health.py`, `backend/app/main.py`

### TDD Steps

**Step 2.1 — Implement the endpoint in health.py**

Replace the entire `backend/app/routers/health.py` with:

```python
"""
Health and readiness check routers.
"""

import time
from datetime import datetime, timezone

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.core.cache import get_redis
from app.core.config import settings
from app.core.database import SessionLocal
from app.core.rate_limits import limiter

router = APIRouter(prefix="/api", tags=["health"])


@router.get("/health")
@limiter.exempt
def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "version": settings.APP_VERSION,
    }


@router.get("/ready")
@limiter.exempt
def readiness_check():
    """Readiness probe — checks DB and Redis connectivity.

    Returns HTTP 200 when all probes pass, HTTP 503 when any probe fails.
    Both probes always run regardless of the other's result.
    """
    checks: dict = {}

    # DB probe — SELECT 1 against PostgreSQL
    db = SessionLocal()
    try:
        start = time.monotonic()
        db.execute(text("SELECT 1"))
        checks["db"] = {
            "status": "ok",
            "latency_ms": int((time.monotonic() - start) * 1000),
        }
    except Exception as exc:
        checks["db"] = {
            "status": "failed",
            "latency_ms": None,
            "error": str(exc)[:200],
        }
    finally:
        db.close()

    # Redis probe — PING
    try:
        r = get_redis()
        if r is None:
            checks["redis"] = {
                "status": "failed",
                "latency_ms": None,
                "error": "REDIS_URL not configured",
            }
        else:
            start = time.monotonic()
            r.ping()
            checks["redis"] = {
                "status": "ok",
                "latency_ms": int((time.monotonic() - start) * 1000),
            }
    except Exception as exc:
        checks["redis"] = {
            "status": "failed",
            "latency_ms": None,
            "error": str(exc)[:200],
        }

    all_ok = all(v["status"] == "ok" for v in checks.values())
    return JSONResponse(
        content={
            "status": "ready" if all_ok else "unavailable",
            "checks": checks,
        },
        status_code=200 if all_ok else 503,
    )
```

**Step 2.2 — Add `/api/ready` to EXEMPT_PREFIXES in main.py**

In `backend/app/main.py`, at line ~266, the `EXEMPT_PREFIXES` tuple currently reads:

```python
    EXEMPT_PREFIXES = (
        "/api/auth/",
        "/api/health",
        "/metrics",
        "/api/alerts/infrastructure",
        "/docs",
        "/redoc",
        "/openapi.json",
    )
```

Add `"/api/ready"` immediately after `"/api/health"`:

```python
    EXEMPT_PREFIXES = (
        "/api/auth/",
        "/api/health",
        "/api/ready",
        "/metrics",
        "/api/alerts/infrastructure",
        "/docs",
        "/redoc",
        "/openapi.json",
    )
```

**Step 2.3 — Verify all health tests pass**

```bash
docker compose exec backend python -m pytest backend/tests/api/test_health.py -v 2>&1 | tail -20
```

Expected output (all 8 tests passing):
```
PASSED backend/tests/api/test_health.py::test_health_check
PASSED backend/tests/api/test_health.py::test_health_is_exempt_from_auth
PASSED backend/tests/api/test_health.py::test_protected_endpoint_returns_401_without_cookie
PASSED backend/tests/api/test_health.py::test_ready_all_ok
PASSED backend/tests/api/test_health.py::test_ready_db_failure
PASSED backend/tests/api/test_health.py::test_ready_redis_failure
PASSED backend/tests/api/test_health.py::test_ready_both_probes_always_run
PASSED backend/tests/api/test_health.py::test_ready_exempt_from_auth
```

**Step 2.4 — Validate live (if backend is running)**

```bash
curl -s http://localhost:8000/api/ready | python -m json.tool
```

Expected (when DB and Redis are healthy):
```json
{
    "status": "ready",
    "checks": {
        "db": {"status": "ok", "latency_ms": 3},
        "redis": {"status": "ok", "latency_ms": 1}
    }
}
```

**Step 2.5 — Commit**

```bash
git add backend/app/routers/health.py backend/app/main.py
git commit -m "feat: add /api/ready readiness probe with DB and Redis checks (#289)"
```

---

## Task 3: Docker Compose healthcheck + frontend depends_on

**Files**: `docker-compose.yml`

### TDD Steps

**Step 3.1 — Add healthcheck to the `backend` service**

In `docker-compose.yml`, locate the `backend:` service block (currently has no `healthcheck:` key). Add a `healthcheck:` block after the `restart: unless-stopped` line:

```yaml
  backend:
    ...
    restart: unless-stopped
    healthcheck:
      test:
        - "CMD"
        - "python"
        - "-c"
        - "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/api/ready').status==200 else 1)"
      interval: 10s
      timeout: 5s
      retries: 6
      start_period: 30s
    deploy:
      ...
```

**Note**: The `python:3.12-slim` base image does not include `curl` or `wget`, so Python's stdlib `urllib.request` is used. This matches the spec's assumption A1.

**Step 3.2 — Add `depends_on` to the `frontend` service**

In `docker-compose.yml`, the `frontend:` service currently has no `depends_on:`. Add it:

```yaml
  frontend:
    ...
    networks:
      - stockscanner-network
    depends_on:
      backend:
        condition: service_healthy
    restart: unless-stopped
```

**Step 3.3 — Validate compose syntax**

```bash
docker compose config --quiet && echo "compose config OK"
```

Expected: `compose config OK` (no errors).

**Step 3.4 — Commit**

```bash
git add docker-compose.yml
git commit -m "feat: add backend healthcheck and frontend depends_on condition (#289)"
```

---

## Task 4: Shared entrypoint with alembic check drift gate

**Files**: `backend/entrypoint.sh`, `backend/Dockerfile`

### TDD Steps

**Step 4.1 — Create `backend/entrypoint.sh`**

```bash
#!/bin/sh
set -e

if ! python -m alembic check 2>&1; then
    echo "ERROR: Alembic schema drift detected. Run 'alembic upgrade head' before starting services." >&2
    exit 1
fi

exec "$@"
```

Make it executable and verify:

```bash
chmod +x backend/entrypoint.sh
git ls-files --others --exclude-standard backend/entrypoint.sh  # should show as untracked
file backend/entrypoint.sh  # should confirm it's a shell script
```

**Why `exec "$@"` is safe**: All backend-image services set their `command:` in `docker-compose.yml` (e.g., `sh -c "rm -rf /tmp/prometheus_multiproc/* 2>/dev/null; uvicorn ..."`). The `ENTRYPOINT` + `CMD` split means `exec "$@"` receives those compose commands as arguments and executes them with the same PID — preserving signal handling and all existing service startup logic. `docker-compose.override.yml` restores `--reload` via `command:`, which still passes through `exec "$@"` correctly.

**Step 4.2 — Update `backend/Dockerfile`**

Current tail of `backend/Dockerfile`:
```dockerfile
COPY --chown=appuser:appuser . .

USER appuser

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
```

Replace with:
```dockerfile
COPY --chown=appuser:appuser . .

# Copy entrypoint to / (outside WORKDIR /app) so the local-dev bind-mount
# (./backend:/app:ro) does not shadow it. The execute bit is preserved from
# the source file committed with chmod +x.
COPY --chown=appuser:appuser entrypoint.sh /entrypoint.sh

USER appuser

EXPOSE 8000

ENTRYPOINT ["/entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

**Note**: `--reload` is removed from the default `CMD` because `docker-compose.yml` already overrides `command:` for all services. The baked-image default is a production-mode `uvicorn`. Local dev restores `--reload` via `docker-compose.override.yml`'s `command:` key.

**Note on path**: The spec places the entrypoint at `/entrypoint.sh` (root), NOT `/app/entrypoint.sh`. This is important: `docker-compose.override.yml` bind-mounts `./backend:/app:ro`, which would shadow `/app/entrypoint.sh` with the host tree in local dev. By placing the script at `/entrypoint.sh`, it lives outside the bind-mount path and the image copy is always used — both in production and local dev. The `chmod +x` on the host file (Step 4.1) sets the execute bit in git so Docker `COPY` preserves it.

**Note on alembic version**: `alembic==1.18.4` is pinned in `requirements.txt` — `alembic check` was introduced in Alembic 1.9, so it is available.

**Step 4.3 — Verify the entrypoint script syntax**

```bash
sh -n backend/entrypoint.sh && echo "shell syntax OK"
```

Expected: `shell syntax OK`

**Step 4.4 — Test entrypoint behavior (if backend running)**

```bash
docker compose build backend 2>&1 | tail -5
docker compose run --rm backend sh -c "echo ENTRYPOINT_PASSED"
```

Expected: `alembic check` passes (schema is current), then prints `ENTRYPOINT_PASSED`.

**Step 4.5 — Commit**

```bash
git add backend/entrypoint.sh backend/Dockerfile
git commit -m "feat: add alembic check drift gate to backend entrypoint (#289)"
```

---

## Task 5: Fix deploy.yml migration ordering

**Files**: `.github/workflows/deploy.yml`

### TDD Steps

**Step 5.1 — Understand the current (broken) ordering**

Current order in the deploy script:
1. `docker compose pull` (images pulled)
2. `docker compose up -d backend celery-worker ...` ← backend starts on stale schema
3. DOMAIN/Caddy/scheduler restarts
4. `if run_migrations: docker compose exec -T backend python -m alembic upgrade head` ← migration runs after startup

Two problems:
- Migrations run **after** services start — backend serves on stale schema during the migration window.
- `docker compose exec -T backend` requires the container to already be running — `exec` approach works but defeats the ordering fix.

**Step 5.2 — Rewrite the deploy script block**

Replace the current script body in `.github/workflows/deploy.yml`:

```yaml
          script: |
            set -e
            export IMAGE_TAG="${{ inputs.image_tag }}"

            # Pull updated images for all deployed services
            docker compose pull \
              backend celery-worker celery-beat live-scanner flower frontend backlog-scheduler

            # Pull dark-factory image (profile-gated — updated via pull, not auto-restarted)
            docker compose --profile factory pull dark-factory

            # Run migrations against the new image BEFORE starting services.
            # Uses docker compose run --rm (one-off container from the new image) so
            # alembic upgrade head runs before any service starts on the new schema.
            if [ "${{ inputs.run_migrations }}" = "true" ]; then
              docker compose run --rm backend python -m alembic upgrade head
            fi

            # Start services — schema is current at this point
            docker compose up -d \
              backend celery-worker celery-beat live-scanner flower frontend

            # Source DOMAIN from .env — docker-compose reads it automatically, but the
            # shell session does not; without this export ${DOMAIN:-} is always empty.
            if [ -f .env ]; then
              export $(grep -E '^DOMAIN=' .env || true)
            fi

            # Restart Caddy only when DOMAIN is set — fails loudly if DOMAIN is missing
            if [ -n "${DOMAIN:-}" ]; then
              docker compose --profile tls up -d caddy
            else
              echo "DOMAIN not set — skipping Caddy (TLS profile). Set DOMAIN in .env for HTTPS."
            fi

            # Restart backlog-scheduler if deployed with the scheduler profile
            docker compose --profile scheduler up -d backlog-scheduler
```

**Key changes**:
- Migration block **moved before** `docker compose up -d`
- `docker compose exec -T backend` → `docker compose run --rm backend` — the one-off container uses the newly pulled image and has `.env` in scope automatically (same compose file)
- Migration block at the **end of the script is removed**

**Step 5.3 — Validate YAML syntax**

```bash
python3 -c "import yaml; yaml.safe_load(open('.github/workflows/deploy.yml'))" && echo "YAML OK"
```

Expected: `YAML OK`

**Step 5.4 — Commit**

```bash
git add .github/workflows/deploy.yml
git commit -m "fix: run alembic migrations before docker compose up in deploy workflow (#289)"
```

---

## Task 6: Write ADR-0012

**Files**: `docs/adr/0012-migration-gate-not-auto-migrate.md`

### TDD Steps

**Step 6.1 — Create the ADR file**

```markdown
# ADR-0012: Migration gate (alembic check) instead of auto-migrate on start

**Date**: 2026-06-12  
**Status**: Accepted  
**Issue**: [#289 — Add readiness probe (DB/Redis) + migration gate in deploy path](https://github.com/omniscient/markethawk/issues/289)

## Context

The backend image is shared by five services: `backend`, `celery-worker`, `celery-beat`,
`live-scanner`, and `flower`. On `docker compose up`, all five containers start concurrently.

A naive entrypoint could run `alembic upgrade head` automatically before exec-ing uvicorn or
celery, ensuring each container self-migrates before serving. This approach was evaluated and
rejected. The existing `deploy.yml` workflow already had an explicit `run_migrations` step,
establishing the pattern that migrations are a deploy-time operator action, not a container
startup side-effect.

## Decision

The shared `backend/entrypoint.sh` runs `alembic check` and exits non-zero on schema drift.
It does NOT run `alembic upgrade head` automatically.

The `deploy.yml` workflow is the single runner responsible for applying migrations. It runs
`docker compose run --rm backend python -m alembic upgrade head` (one-off container from the
new image, before `docker compose up -d`) so the schema is always current before any service
starts. The entrypoint gate is a safety net: if a container somehow starts with drift, it
refuses to serve rather than operating on a stale schema.

## Consequences

**Why auto-migrate on entrypoint was rejected**: All five containers start concurrently on
`docker compose up`. If the entrypoint ran `alembic upgrade head`, multiple containers would
execute concurrent DDL against the same database. Single-SQL idempotent migrations may survive
concurrent execution by coincidence; multi-step migrations do not. Lock-sensitive operations —
column drops, type changes, index builds — are not safe under concurrent apply. Alembic does not
hold a distributed lock across the full migration chain; two containers can both pass the
`alembic_version` read, both attempt to apply the next revision, and race on the DDL or the
`INSERT INTO alembic_version`. The result is data corruption or a partially applied migration
that is invisible until the next `SELECT` hits the changed schema.

**Rejected alternative — check-only with startup delay**: An alternative drift gate: sleep 30
seconds before checking, to let another service apply migrations first. Rejected because it is
flaky (depends on wall-clock timing) and removes the clear-failure semantics. The entrypoint
check should be eager: fail fast, fail loudly.

**The entrypoint drift gate is a safety net, not the primary mechanism.** Operators must apply
migrations explicitly before deploying (via `run_migrations: true` in the deploy workflow, or
manually). The gate ensures that if the explicit step is skipped, no container silently serves
a stale schema.

**New constraint**: Any deploy path that bypasses `deploy.yml` must include an explicit
`alembic upgrade head` step before starting services, or the entrypoint drift gate will refuse
to start all five backend-image containers simultaneously.
```

**Step 6.2 — Commit**

```bash
git add docs/adr/0012-migration-gate-not-auto-migrate.md
git commit -m "docs: ADR-0012 — migration gate (alembic check) not auto-migrate on start (#289)"
```

---

## Validation Checklist

After all tasks are committed:

```bash
# 1. All health tests pass
docker compose exec backend python -m pytest backend/tests/api/test_health.py -v

# 2. /api/ready returns 200 live
curl -s http://localhost:8000/api/ready | python -m json.tool

# 3. /api/ready is not auth-gated
curl -s http://localhost:8000/api/ready  # should NOT return 401

# 4. Compose config is valid
docker compose config --quiet && echo "OK"

# 5. Entrypoint script syntax is valid
sh -n backend/entrypoint.sh && echo "OK"

# 6. deploy.yml YAML is valid
python3 -c "import yaml; yaml.safe_load(open('.github/workflows/deploy.yml'))" && echo "OK"

# 7. ADR file exists
ls docs/adr/0012-migration-gate-not-auto-migrate.md
```
