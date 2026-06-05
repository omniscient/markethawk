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

## Celery Task Coverage (issue #204)

- [PATTERN] For Celery tasks with non-trivial inline logic, extract the business logic into a `_<task>_logic(...)` helper that receives an injected DB session, publish callable, and cancel-check callable. The decorated task shell retains only broker-bound concerns: `self.request.id`, `SessionLocal()`, `redis.Redis.from_url(...)`, retry, OTel span, Prometheus timing. Tests call the helper directly — no broker needed. <!-- issue:#204 date:2026-06-05 expires:2026-12-05 source:refine -->

- [AVOID] Do not use a blanket `app/tasks/*.py` coverage omit — it hides ~1,800 lines of task business logic from the 60% gate. Instead, mark only the genuinely broker-bound functions (`_poll_live_orders` for live IBKR, `sync_futures_aggregates` for FuturesDataService) with `# pragma: no cover`. File-level omits should be reserved for code that physically cannot run without a live external process. <!-- issue:#204 date:2026-06-05 expires:2026-12-05 source:refine -->
