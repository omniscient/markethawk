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

## Live Scanner / IBKR Reconnect (issue #393)

- [PATTERN] When implementing mid-stream IBKR reconnect in the live-scanner, route `disconnectedEvent` through the existing asyncio queue (via `call_soon_threadsafe` + `queue.put_nowait`) using a new `TAG_DISCONNECT` tag, and handle the reconnect in `_process_loop` — do not call async publisher methods directly from the ib_insync event thread. This keeps the reconnect path consistent with the existing `TAG_BAR`/`TAG_QUOTE` pattern and avoids thread-safety issues. <!-- issue:#393 date:2026-06-21 expires:2026-12-21 source:refine -->

- [AVOID] Do not rely on container restart (`restart: unless-stopped`) as the sole recovery mechanism for ib_insync mid-stream disconnect. Container restart cannot detect network partition (TCP hangs, process doesn't crash), cannot emit `feed_loss`/`feed_recovered` events, and requires full re-seeding of `BarAggregator` state. In-process reconnect with exponential backoff is required; container restart is a last-resort backstop only. <!-- issue:#393 date:2026-06-21 expires:2026-12-21 source:refine -->

- [PATTERN] When adding an optional probe to `/api/ready`, keep it **informational only** (include in the response body but exclude from `all_ok`). `/api/ready` is the Docker healthcheck for the backend container — making it 503 on IBKR failure would mark the container unhealthy and break orchestrators that depend on it. Use `all_ok = probes["db"]["ok"] and probes["redis"]["ok"]` (not `all()`); non-core probes appear in the body without gating the HTTP status. <!-- issue:#393 date:2026-06-21 expires:2026-12-21 source:refine -->

## Agent Memory Design (issue #149)

- [PATTERN] Agent memory is stored as plain markdown files in `.archon/memory/`, committed to the repo. Files are read at Phase 1 load time and updated post-run. This keeps memory human-readable, version-controlled, and accessible to all agents without any extra tooling. <!-- bootstrap date:2026-06-02 expires:2026-12-02 source:refine -->

- [AVOID] Do not store agent memory in CLAUDE.md — that file is the primary developer reference and polluting it with machine-generated observations makes it harder to maintain. Memory files are the designated separation. <!-- bootstrap date:2026-06-02 expires:2026-12-02 source:refine -->

---
<!-- PROVISIONAL — entries below are from a single observed run; unverified.
     Do not rely on these as authoritative guidance. They are excluded from
     plan/implement prompt injection except as advisory context.
     Each will be promoted to [PATTERN] on second-run confirmation (different issue number) or dropped at TTL. -->
