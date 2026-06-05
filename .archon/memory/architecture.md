# Architecture Decisions — Accumulated Lessons

This file is maintained automatically by the dark factory refine agent. Do not edit manually.
Entries represent design-time decisions (source:refine). Implement agents may treat source:implement
entries as higher-confidence than source:refine entries when the two conflict.

## State Storage

- [PATTERN] Use PostgreSQL for all durable application state — scanner events, memory, configs. The existing `AsyncSession` infrastructure handles connection pooling, migrations, and transactional safety. <!-- bootstrap date:2026-06-02 expires:2026-12-02 source:refine -->

- [AVOID] Do not introduce Redis for durable state — Redis is volatile (data lost on flush/restart) and not committed to git history. Reserve Redis for ephemeral queues and rate-limit counters only. <!-- bootstrap date:2026-06-02 expires:2026-12-02 source:refine -->

## Services Topology

- [PATTERN] Extend existing services rather than adding new Docker containers. The stack already runs postgres, redis, backend, frontend, celery-worker, celery-beat, seq, prometheus, grafana, and jaeger. Each new service adds operational overhead and a new port to document. <!-- bootstrap date:2026-06-02 expires:2026-12-02 source:refine -->

- [AVOID] Do not introduce a vector database, embedding model, or semantic search service for memory retrieval. At the scale of this codebase (< 200 memory entries) flat file reading is faster and more predictable than a retrieval pipeline. <!-- bootstrap date:2026-06-02 expires:2026-12-02 source:refine -->

## Agent Memory Design (issue #149)

- [PATTERN] Agent memory is stored as plain markdown files in `.archon/memory/`, committed to the repo. Files are read at Phase 1 load time and updated post-run. This keeps memory human-readable, version-controlled, and accessible to all agents without any extra tooling. <!-- bootstrap date:2026-06-02 expires:2026-12-02 source:refine -->

- [AVOID] Do not store agent memory in CLAUDE.md — that file is the primary developer reference and polluting it with machine-generated observations makes it harder to maintain. Memory files are the designated separation. <!-- bootstrap date:2026-06-02 expires:2026-12-02 source:refine -->

## Prometheus Multiprocess Metrics (issue #194)

- [PATTERN] Use a regular (non-tmpfs) Docker named volume for `prometheus_multiproc` so all containers (backend, celery-worker) write to the same real filesystem. The backend's `MultiProcessCollector` in `main.py` then aggregates all process `.db` files and serves them at `/metrics`; Prometheus only needs to scrape `backend:8000`. Add `rm -rf $PROMETHEUS_MULTIPROC_DIR/*` to the container startup command to prevent stale-file accumulation across restarts. Wire `worker_process_shutdown` signal → `mark_process_dead(pid)` in `celery_app.py` for per-process cleanup during Celery pool recycling. <!-- issue:#194 date:2026-06-05 expires:2026-12-05 source:refine -->

- [AVOID] Do not use `driver_opts: type: tmpfs` for Docker named volumes that must be shared between containers. Docker's local-driver tmpfs volumes give each mounting container its own private tmpfs instance — files written by the celery-worker are invisible to the backend even though both mount the "same" volume name. Use a plain named volume (no `driver_opts`) instead. <!-- issue:#194 date:2026-06-05 expires:2026-12-05 source:refine -->
