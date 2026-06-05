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

## Rate Limiting (issue #196)

- [PATTERN] Define a separate named constant per rate-limit concern in `backend/app/core/rate_limits.py` (e.g. `AUTH_LIMIT`, `SCANNER_LIMIT`, `TRADING_LIMIT`). Named constants make callers grep-able and let each concern evolve its numeric value independently. <!-- issue:#196 date:2026-06-05 expires:2026-12-05 source:refine -->

- [AVOID] Do not share a rate-limit constant across semantically different concerns (e.g. do not reuse SCANNER_LIMIT for auth brute-force protection even if the values happen to be identical). Shared constants couple unrelated subsystems and prevent independent tuning. <!-- issue:#196 date:2026-06-05 expires:2026-12-05 source:refine -->

- [PATTERN] Apply `@limiter.limit(AUTH_LIMIT)` to all credential-sensitive auth mutation endpoints (login, register, refresh). Leave read-only or post-authentication endpoints (status, me, logout) on the global default. Add `request: Request` to handler signatures — SlowAPI requires it. <!-- issue:#196 date:2026-06-05 expires:2026-12-05 source:refine -->

- [AVOID] Do not implement a bespoke ASGI brute-force middleware when SlowAPI decorators already cover the threat model. A custom middleware tracking failed attempts is over-engineered for a single-operator app with SlowAPI already wired. <!-- issue:#196 date:2026-06-05 expires:2026-12-05 source:refine -->
