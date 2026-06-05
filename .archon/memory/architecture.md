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

## Circuit Breakers (issue #205)

- [PATTERN] Use one coarse-grained circuit breaker per external provider (one for Polygon/MassiveDataProvider, one for IBKR/IBKRDataProvider). All operations on a provider share one breaker because they share one client/host/API key and fail together. Breaker trips must surface as `ProviderError(is_retryable=False)` so the existing graceful-degradation path in `stock_data.py` handles them unchanged. <!-- issue:#205 date:2026-06-05 expires:2026-12-05 source:refine -->

- [AVOID] Do not use per-operation-type circuit breakers (e.g., separate breakers for get_bars vs get_snapshots). All Polygon operations share one RESTClient instance and fail together during API outages, so per-operation breakers add complexity without isolation benefit. <!-- issue:#205 date:2026-06-05 expires:2026-12-05 source:refine -->

- [PATTERN] Use `pybreaker` (1.x+) for both sync and async circuit breakers in this codebase — it detects coroutine functions automatically. Central instances live in `backend/app/core/circuit_breakers.py`. Do not introduce `aiobreaker` (smaller community) or a manual boolean-flag state machine (no half-open state). <!-- issue:#205 date:2026-06-05 expires:2026-12-05 source:refine -->

- [PATTERN] Circuit breaker parameters (fail_max, reset_timeout) belong in `Settings` (`backend/app/core/config.py`) so they are tunable via env vars without code changes, consistent with the existing pattern for POLYGON_API_KEY, IBKR_HOST, etc. <!-- issue:#205 date:2026-06-05 expires:2026-12-05 source:refine -->

- [AVOID] Do not implement distributed (Redis-backed) circuit breaker state. Each Celery worker maintains independent breaker state; losing state on restart is acceptable. The goal is per-worker fast-fail, not fleet-wide coordination. <!-- issue:#205 date:2026-06-05 expires:2026-12-05 source:refine -->
