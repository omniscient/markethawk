# ADR-006: Celery + Redis for Background Tasks

**Date**: 2026-05-28  
**Status**: Accepted

## Context

Several operations in MarketHawk cannot run synchronously in an HTTP request: full scanner runs (tens of Polygon API calls, several seconds per ticker), nightly stock split syncs, news polling, and auto-trade fill polling. These need to be dispatched from route handlers and run in a separate process.

### Options considered

**A. FastAPI `BackgroundTasks`** — Built-in; no infrastructure. Tasks run in the same process as the ASGI server. Under load, long-running tasks compete with request handling for the event loop. No persistence: if the process restarts, queued tasks are lost. No visibility (no queue depth, no task status, no retry). Suitable for fire-and-forget notifications, not for multi-second compute.

**B. Celery + Redis** — Battle-tested distributed task queue. Tasks persist in Redis across restarts. Workers run in a separate process (or container), fully isolated from the ASGI server. Built-in retry, rate limiting, and scheduled tasks (Celery Beat). Flower provides real-time monitoring. The cost is operational: Redis and a worker process/container must run alongside the backend.

**C. Apache Airflow** — DAG-based workflow orchestrator. Excellent for data pipelines with complex dependencies. Requires a scheduler, web server, and metadata DB. Overkill for a set of independent periodic tasks with no inter-task DAG dependencies.

**D. Prefect** — Modern alternative to Airflow. Cloud or self-hosted server required for the full feature set. Same over-engineering concern as Airflow for this use case.

## Decision

**Option B**: Celery with Redis as both broker and result backend.

Redis is already required for other features (rate limiter storage, live scanner pub/sub, refresh token storage). Adding Celery uses an already-running service rather than introducing new infrastructure. The worker runs as a separate container (`celery-worker` in `docker-compose.yml`), keeping it isolated from the FastAPI ASGI process.

Celery Beat handles the scheduled tasks (nightly splits, news polling, evening liquidity scan, signal analysis, tweet monitoring). A single Beat scheduler process avoids the overhead of cron-inside-container patterns.

## Consequences

- The `celery-worker` container must be running for any background task to execute. If it crashes, no tasks run until it restarts (observable via Flower at `:5555`).
- Task results stored in Redis expire after the default TTL; tasks that need durable output write directly to PostgreSQL.
- Redis is a single point of failure for both the broker and the backend. Restarting Redis loses any tasks that were queued but not yet acknowledged by a worker.
- Airflow or Prefect would be appropriate if scan orchestration grows into a DAG with inter-task dependencies. Until then, Celery's simpler model is sufficient.
