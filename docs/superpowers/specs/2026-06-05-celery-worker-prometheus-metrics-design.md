# Celery Worker Prometheus Metrics — Fix Never-Scraped Metrics

> Tracking issue: [#194](https://github.com/omniscient/markethawk/issues/194)

## Overview

Celery worker tasks record `celery_tasks_total` and `celery_task_duration_seconds` metrics but
those metrics never reach Prometheus. The Celery Grafana dashboard and the
`high-celery-failure-rate` alert have no data as a result.

Two bugs compound:

1. **Broken shared directory.** The `prometheus_multiproc` Docker volume is declared as a
   `tmpfs`-backed local volume (`driver_opts: type: tmpfs`). Docker's local-driver tmpfs volumes
   are not truly shared between containers — each container receives its own private tmpfs
   instance. The Celery worker writes `.db` files to `/tmp/prometheus_multiproc` inside its own
   tmpfs; the backend's `MultiProcessCollector` reads from a different (backend-only) tmpfs and
   never sees the worker's files.

2. **Prometheus only scrapes the backend.** `monitoring/prometheus/prometheus.yml` targets only
   `backend:8000`. Since the backend's `/metrics` endpoint currently only sees its own processes,
   no worker metrics are exported even if Prometheus were to receive them.

## Requirements

- `celery_tasks_total` and `celery_task_duration_seconds` must appear in Prometheus and drive the
  existing Celery Grafana dashboard panels and the `high-celery-failure-rate` alert.
- No new Docker containers or Prometheus scrape targets.
- Stale `.db` files from prior container runs must not accumulate and corrupt counters.
- Celery child-process recycling (via `max_tasks_per_child` or concurrency pool churn) must not
  leave orphaned per-PID metric files that inflate aggregates.
- live-scanner and celery-beat are out of scope — the Grafana Celery dashboard does not query
  their metrics.

## Approach

### Fix 1 — Convert the volume from tmpfs to a regular Docker named volume

In `docker-compose.yml`, remove the `driver_opts` block from the `prometheus_multiproc` volume
definition:

```yaml
# Before
prometheus_multiproc:
  driver: local
  driver_opts:
    type: tmpfs
    device: tmpfs
    o: size=256m

# After
prometheus_multiproc:
```

A plain named volume is stored on the Docker host's filesystem and is genuinely shared between
all containers that mount it. The backend and celery-worker will now write to — and read from —
the same directory, so `MultiProcessCollector` in `main.py` correctly aggregates worker metrics
at `GET /metrics`. Prometheus already scrapes `backend:8000`, so no changes to
`prometheus.yml` are needed.

### Fix 2 — Cold-start stale-file wipe (docker-compose.yml)

Because the volume is now persistent (not wiped by Docker on restart), stale `.db` files from
dead PIDs must be cleared on every container startup. Add a `sh -c` prefix to the backend and
celery-worker `command` fields:

```yaml
# backend
command: sh -c "rm -rf /tmp/prometheus_multiproc/* 2>/dev/null; uvicorn app.main:app --host 0.0.0.0 --port 8000"

# celery-worker
command: sh -c "rm -rf /tmp/prometheus_multiproc/* 2>/dev/null; celery -A app.core.celery_app:celery_app worker --loglevel=info"
```

Both containers clear the directory before launching, ensuring no leftover files from prior runs.

> **Race note:** if backend and celery-worker start at nearly the same time, the second container
> to start may delete files written by the first. In practice Celery workers record metrics at
> task execution time (not at startup), so the race window is negligible. If the race causes
> issues in a future concurrency scenario, the preferred resolution is a dedicated startup-lock
> script, not shared tmpfs.

### Fix 3 — Per-process cleanup on worker child shutdown (celery_app.py)

Celery recycles child processes during its normal lifecycle (`max_tasks_per_child`, pool
restarts). Each recycled process leaves a per-PID `.db` file whose gauge values continue to
be summed by `MultiProcessCollector`. Wire the `worker_process_shutdown` signal to call
`mark_process_dead` so file cleanup happens in-process:

```python
# backend/app/core/celery_app.py
import os
from celery.signals import worker_process_shutdown

@worker_process_shutdown.connect
def _cleanup_prometheus_on_exit(sender, pid, exitcode, **kwargs):
    if os.environ.get("PROMETHEUS_MULTIPROC_DIR"):
        from prometheus_client import multiprocess
        multiprocess.mark_process_dead(pid)
```

`mark_process_dead` removes the PID-specific gauge file so subsequent `/metrics` requests do
not aggregate dead-process data.

## Alternatives Considered

### Option B — Per-worker HTTP exporter

Each celery-worker container starts a `prometheus_client.start_http_server()` thread and
exposes its own `/metrics` on an internal port; Prometheus scrape config adds
`celery-worker:<port>` as a new job.

**Rejected:** the codebase already implements the shared-directory aggregation model
(`MultiProcessCollector` in `main.py`, `PROMETHEUS_MULTIPROC_DIR` on both services). Option B
would duplicate that mechanism with more surface area (new port, new scrape target, Python
startup hook) and produce no additional observable benefit. It also makes it harder to add
future workers (each would need its own scrape target).

### Option C — Pushgateway

A new Pushgateway container accepts metric pushes from workers and exposes a combined `/metrics`
for Prometheus to scrape.

**Rejected:** adding a new Docker container conflicts with the architecture memory entry
"Extend existing services rather than adding new Docker containers." Pushgateway also has known
semantics issues with counters (no time-series staleness, accumulation across pushes) that
require additional cleanup discipline.

## Open Questions

- None. All acceptance criteria are covered by the three fixes above.

## Assumptions

- Converting `prometheus_multiproc` to a regular named volume is acceptable (metrics survive
  container restarts; stale-file cleanup prevents accumulation).
- The race on cold-start wipe (backend and worker both run `rm -rf`) is benign given that no
  task executes during the milliseconds between the two startups.
- celery-beat emits no custom metrics (confirmed: no `celery_tasks_total.labels(...)` calls in
  `celery_app.py` or any beat-specific task file) and requires no changes.
- live-scanner metrics instrumentation is tracked separately and is not blocked by this fix.
