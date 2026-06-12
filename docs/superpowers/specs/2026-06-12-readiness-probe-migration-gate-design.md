# Readiness Probe + Migration Gate — Design

**Date:** 2026-06-12  
**Status:** Spec — pending review  
**Issue:** [#289 — Add readiness probe (DB/Redis) + migration gate in deploy path](https://github.com/omniscient/markethawk/issues/289)

## Overview

Two separate deployment-ordering traps exist today:

1. **False-green liveness probe.** `/api/health` returns `{"status": "healthy"}` immediately on startup, before the backend has confirmed DB or Redis connectivity. Docker Compose and other orchestrators use this as the signal that the container is ready to serve traffic — so they declare the backend healthy before it actually is.

2. **Stale-schema gap.** There is no migration gate in the deploy path. The container command is raw uvicorn/celery, so an image deployed with a pending Alembic migration will begin serving requests against the old schema until an operator manually runs `alembic upgrade head`. The `deploy.yml` workflow does have a `run_migrations` step, but it runs *after* `docker compose up -d`, meaning the backend is already serving on the stale schema during the migration window.

This spec covers adding a `/api/ready` readiness endpoint with real dependency probes, wiring it into compose healthchecks, and adding an `alembic check` drift gate to the container entrypoint.

---

## Requirements

1. Add `GET /api/ready` — performs `SELECT 1` against PostgreSQL and `PING` against Redis; returns HTTP 200 + structured body on success, HTTP 503 + structured body on any failure.
2. Run both probes independently (no short-circuit) so the response always reports every dependency.
3. Exempt `/api/ready` from auth middleware (`EXEMPT_PREFIXES`) and rate limiting (`@limiter.exempt`), matching `/api/health`.
4. Add a Docker healthcheck to the `backend` service in `docker-compose.yml` using the new `/api/ready` endpoint.
5. Add `depends_on: backend: condition: service_healthy` to the `frontend` service.
6. Add a shared `backend/entrypoint.sh` that runs `alembic check` and exits non-zero on schema drift before exec-ing the per-service command. Set it as the Dockerfile `ENTRYPOINT` so it runs for all backend-image services (backend, celery-worker, celery-beat, live-scanner, flower).
7. Fix `deploy.yml` ordering: run migrations (`alembic upgrade head`) against the new image *before* `docker compose up -d`, so the backend never starts on a stale schema.
8. Write ADR-0012 documenting the decision to reject auto-migration-on-start in favor of an explicit migrate step.

---

## Architecture / Approach

### 1. `/api/ready` endpoint (`backend/app/routers/health.py`)

Add to the existing `health.py` router (prefix `/api`) as `@router.get("/ready")`. The endpoint:

- Opens a DB session via `SessionLocal()` (sync, matches the rest of the app — see ADR-0004)
- Executes `SELECT 1` and records latency
- Gets a Redis connection via `get_redis()` from `app.core.cache`
- Calls `.ping()` and records latency
- Returns:

```json
// HTTP 200 — all probes passed
{
  "status": "ready",
  "checks": {
    "db":    {"status": "ok",     "latency_ms": 3},
    "redis": {"status": "ok",     "latency_ms": 1}
  }
}

// HTTP 503 — one or more probes failed
{
  "status": "unavailable",
  "checks": {
    "db":    {"status": "failed", "latency_ms": null, "error": "Connection refused"},
    "redis": {"status": "ok",     "latency_ms": 1}
  }
}
```

Both probes always run regardless of the other's result. Latency is the wall-clock time of the probe call in milliseconds (int). `error` field is only present on `failed` checks, contains a short, non-sensitive description.

Wire in `main.py`:
- Add `"/api/ready"` to `EXEMPT_PREFIXES` (line ~266)
- Decorate with `@limiter.exempt` in `health.py`

### 2. Docker Compose healthcheck — backend service

The backend image (`python:3.12-slim`) does not include `curl` or `wget`, so use Python's standard library:

```yaml
# docker-compose.yml — backend service
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
```

`start_period` gives the backend time to complete startup before retries count against the health state. HTTP-probe services (celery-worker, celery-beat, live-scanner, flower) do not get HTTP healthchecks — they have no HTTP port; the shared entrypoint drift gate covers their schema safety.

### 3. Frontend `depends_on`

```yaml
# docker-compose.yml — frontend service
depends_on:
  backend:
    condition: service_healthy
```

This satisfies the acceptance criterion "`docker-compose up` with a cold DB does not report the backend healthy until DB/Redis respond" — the frontend will not start serving until the backend's `/api/ready` probe passes.

### 4. Shared entrypoint script (`backend/entrypoint.sh`)

```bash
#!/bin/sh
set -e

if ! python -m alembic check 2>&1; then
    echo "ERROR: Alembic schema drift detected. Run 'alembic upgrade head' before starting services." >&2
    exit 1
fi

exec "$@"
```

`exec "$@"` preserves the per-service `command:` already in compose (including the `sh -c "rm -rf /tmp/prometheus_multiproc/*; ..."` wrappers). The script must be executable (`chmod +x`) and committed.

Update `backend/Dockerfile`:
```dockerfile
# Replace the CMD line with:
COPY --chown=appuser:appuser entrypoint.sh /entrypoint.sh
ENTRYPOINT ["/entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

Running `alembic check` concurrently from all backend-image services is safe — it is read-only (reads `alembic_version` table, compares against migration files) with no DDL.

**Local-dev note:** `docker-compose.override.yml` restores `--reload` via the `command:` key. Because `ENTRYPOINT` and `command:` are distinct in compose, the override's `command:` still passes through to `exec "$@"` in the entrypoint. The drift gate runs in dev too — this is desirable: a developer who adds a model column without generating a migration will get an immediate, clear error on container start.

### 5. Fix `deploy.yml` ordering

In `.github/workflows/deploy.yml`, the `run_migrations` step (line ~62) currently runs *after* `docker compose up -d` (line ~41). Move the migration step before the service-start step:

```yaml
# Before: up -d  →  migrate
# After:  pull  →  migrate (one-off run)  →  up -d

- name: Run migrations
  if: inputs.run_migrations == 'true'
  run: docker compose run --rm backend python -m alembic upgrade head

- name: Start services
  run: docker compose up -d backend celery-worker celery-beat ...
```

Use `docker compose run --rm backend` (one-off container from the new image) instead of `exec` against an already-running container — `exec` requires the container to already be up, which defeats the ordering fix. The `--rm` flag cleans up the temporary container.

### 6. ADR-0012: Reject auto-migration-on-start

Write `docs/adr/0012-migration-gate-not-auto-migrate.md` following the existing ADR template. Key content:

- **Decision**: The entrypoint script checks schema drift (`alembic check`) and refuses to start on drift. It does NOT run `alembic upgrade head` automatically.
- **Rejected alternative**: Auto-migrate on entrypoint start.
- **Reason for rejection**: `celery-worker`, `celery-beat`, `live-scanner`, and `flower` all start from the same backend image. On a cold `docker compose up`, all five containers race to start simultaneously. If the entrypoint ran `alembic upgrade head`, multiple containers would execute concurrent DDL — safe only for single-SQL idempotent migrations, unsafe for multi-step migrations and guaranteed to race on lock-sensitive operations (column drops, type changes, index builds).
- **Consequence**: Operators must run migrations explicitly before deploying (or keep `run_migrations: true` in the deploy workflow). The entrypoint drift gate is a safety net that makes schema drift a startup failure rather than a silent data corruption risk.

---

## Alternatives Considered

### Auto-migrate in entrypoint (rejected)
Running `alembic upgrade head` in the entrypoint before exec-ing uvicorn appears zero-touch and simple. Rejected because all five backend-image services start concurrently and would race to apply migrations. Lock-sensitive DDL (column drops, index creates, type changes) is not safe under concurrent apply. The existing `deploy.yml` explicit migration step already establishes that migrations are a deploy-time human/CI action, not a container-start side-effect.

### Check-only with startup delay (rejected)
An alternative drift gate: sleep 30 seconds and then check, to let another service apply migrations first. Rejected because it's flaky (depends on wall-clock timing) and removes the clear-failure semantics. The entrypoint check should be eager: fail fast, fail loudly.

### Always-200 readiness response with status body (rejected)
Returning HTTP 200 even when probes fail (with `"status": "degraded"` in the body) is more informative for dashboards but incompatible with Docker Compose healthchecks, which use `curl -f` semantics (success = 2xx, failure = non-2xx). HTTP 503 on probe failure is required for the compose healthcheck mechanism to work correctly.

---

## Open Questions

- **`alembic check` availability**: `alembic check` was added in Alembic 1.9. Confirm the version pin in `requirements.txt` is ≥1.9 before implementation. If below, use `alembic current` + `alembic heads` comparison instead.
- **migrate one-off container DB access**: The `docker compose run --rm backend` migrate step needs `DATABASE_URL` in scope. Confirm the workflow env-var injection covers the one-off container (it uses the same compose file, so `.env` should apply automatically, but verify the CI env-var passing).

---

## Assumptions

- [A1] The `python:3.12-slim` image used by the backend does not include `curl` or `wget` — Python stdlib URL probe is required for the compose healthcheck.
- [A2] `alembic check` (Alembic ≥1.9) is available in the container — this should be verified against `requirements.txt`.
- [A3] The `get_redis()` singleton from `app.core.cache` is safe to call synchronously from the readiness endpoint without creating a persistent process-scoped connection; if it creates a connection pool, the probe should use a transient `.ping()` call rather than keeping the connection open.
- [A4] `deploy.yml` line ~41 is the canonical service-start step; the migration reorder targets that specific step. Verify no other workflow calls `compose up` before the migration step.
