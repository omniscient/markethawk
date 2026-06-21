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

## Replay Engine UI (issue #489)

- [PATTERN] The replay equity curve time-series (`{date, cumulative_r}` points) is served from `GET /api/v1/replay/runs/{id}/analytics` — cached in `replay_run.metrics` JSONB by `MetricsComputer` (#487), which already materializes it during max-drawdown computation. The UI calls the analytics endpoint once for all of View 1 and View 2 data. <!-- issue:#489 date:2026-06-21 expires:2026-12-21 source:refine -->

- [AVOID] Do not use the existing `RegimeService` HMM state labels (`risk_on`, `risk_off`, `high_volatility`, `low_vol_drift`, `transition`) for the replay engine regime grid — those form a single-dimension classifier and cannot populate a 2D `trend × vol` grid. The replay engine uses the dedicated regime classifier from issue #486, which produces orthogonal trend (up/down/flat) and vol (high/low) axes giving a 3×2 = 6-cell grid. <!-- issue:#489 date:2026-06-21 expires:2026-12-21 source:refine -->

---
<!-- PROVISIONAL — entries below are from a single observed run; unverified.
     Do not rely on these as authoritative guidance. They are excluded from
     plan/implement prompt injection except as advisory context.
     Each will be promoted to [PATTERN] on second-run confirmation (different issue number) or dropped at TTL. -->
