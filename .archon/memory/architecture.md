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

## Data Quality Task Separation (issue #387)

- [PATTERN] Keep nightly data-health sweeps (`check_aggregate_staleness`) separate from the on-demand deep quality analysis (`analyze_universe_quality` / `DataQualityService`). The nightly task does a cheap `MAX(timestamp)` + gap-window query and emits Prometheus gauges. The deep analysis fetches every bar for every ticker×timespan and is user-triggered via `POST /api/v1/universe/{id}/quality`. Merging them would race on the shared `UniverseQualityReport` row and over-compute for a nightly health signal. <!-- issue:#387 date:2026-06-21 expires:2026-12-21 source:refine -->

- [AVOID] Do not schedule `analyze_universe_quality` as the nightly staleness sweep — it fetches all OHLCV bars for every ticker×timespan combo and writes the on-demand user report, which creates a write-race with interactive quality-modal requests and wastes compute for a signal that only needs `MAX(timestamp)` per ticker. <!-- issue:#387 date:2026-06-21 expires:2026-12-21 source:refine -->

- [PATTERN] Populate `ScannerRun.data_degraded` at scan start from the latest pre-computed `UniverseQualityReport` (one indexed query). Treat a missing or >48h stale report as `degraded=True`. Do not query staleness on-the-fly inside the scan hot-path, and do not retroactively update `ScannerRun` after the fact — the flag must reflect what was known at scan time. <!-- issue:#387 date:2026-06-21 expires:2026-12-21 source:refine -->

---
<!-- PROVISIONAL — entries below are from a single observed run; unverified.
     Do not rely on these as authoritative guidance. They are excluded from
     plan/implement prompt injection except as advisory context.
     Each will be promoted to [PATTERN] on second-run confirmation (different issue number) or dropped at TTL. -->
