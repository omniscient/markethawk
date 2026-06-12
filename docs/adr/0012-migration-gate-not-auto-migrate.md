# ADR-0012: Migration Gate — Check-Only, Not Auto-Migrate

**Date**: 2026-06-12  
**Status**: Accepted  
**Issue**: [#289 — Add readiness probe (DB/Redis) + migration gate in deploy path](https://github.com/omniscient/markethawk/issues/289)

## Context

After adding the `/api/ready` readiness probe, the backend image gains a shared `entrypoint.sh`
used by all backend-image services: `backend`, `celery-worker`, `celery-beat`, `live-scanner`,
and `flower`.

Two implementation options were evaluated for what the entrypoint should do about schema drift:

- **Option A — Auto-migrate**: Run `alembic upgrade head` in the entrypoint before starting the
  service. This would apply any pending migrations automatically on every container start.

- **Option B — Check-only drift gate**: Run `alembic check` (read-only, exits non-zero on drift)
  and refuse to start if the schema is behind. The explicit migration step in `deploy.yml` is
  responsible for actually applying migrations.

Option A was rejected for the following reasons:

1. **Concurrent DDL race**: All five backend-image services start in parallel on `docker compose
   up -d`. Each would race to run `alembic upgrade head` against the same database. DDL is not
   idempotent under concurrent execution — multiple processes grabbing the Alembic version lock
   simultaneously causes failures, deadlocks, or partial migrations.

2. **Privilege of the migration role**: Migrations may require elevated DB privileges or careful
   ordering that a general application container should not exercise unsupervised.

3. **Existing deploy workflow**: `deploy.yml` already has a migration step. The ordering bug
   (migrations ran *after* `docker compose up -d`) is fixed in this same issue by moving the
   migration step *before* starting services. The entrypoint gate is a safety net, not the
   primary migration mechanism.

## Decision

The shared `backend/entrypoint.sh` runs `alembic check` and exits non-zero if the schema is
behind (`MigrationRequired` exit code from Alembic ≥1.9). It does **not** run
`alembic upgrade head`.

`deploy.yml` uses `docker compose run --rm backend python -m alembic upgrade head` **before**
`docker compose up -d` so migrations are applied before any service starts serving traffic.

`alembic check` is safe to run concurrently across all five backend-image containers: it is
read-only and holds no locks. If it detects drift it fails loudly, preventing a stale-schema
container from ever accepting requests.

## Consequences

- **Deploy ordering is explicit**: migrations are applied in `deploy.yml` before any service
  starts, eliminating the window where the backend briefly serves on a stale schema.
- **Safety net on every start**: any container that somehow starts against a behind schema (e.g.
  after a manual `docker compose up` without running migrations) refuses to start rather than
  silently serving broken responses.
- **No auto-migration on rollback**: operators must run `alembic downgrade` manually before
  rolling back to an older image that expects a prior schema version. This is intentional — 
  automated downgrade is more dangerous than automated upgrade.
- **`alembic check` requires Alembic ≥1.9**: confirmed via `requirements.txt`
  (`alembic==1.18.4`).
