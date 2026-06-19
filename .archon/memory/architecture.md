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

## Per-Event Analytical Data (issue #464)

- [PATTERN] Expose per-event analytical data (outcomes, analogs, briefs) as standalone lazy REST endpoints rather than embedding them in the scanner event response. Follow the precedent of `GET /api/v1/outcomes/event/{event_id}` — analogs and similar derived data should live at `GET /api/v1/scanner/events/{event_id}/analogs`. The scanner results list returns many events; analog computation requires secondary DB queries and joins that must not run for every list row. <!-- issue:#464 date:2026-06-19 expires:2026-12-19 source:refine -->

- [AVOID] Do not fold per-event analytical payloads (analogs, signal briefs, outcome details) into the `ScannerEventResponse` object. Embedding them inflates list-view payloads and forces analog/brief computation on every scan fetch. Service-layer consumers (e.g., AI signal brief) call the service class in-process; only UI-initiated drill-downs hit the standalone endpoint. <!-- issue:#464 date:2026-06-19 expires:2026-12-19 source:refine -->

## Historical Analog Search (issue #464)

- [PATTERN] For deterministic analog search, use `ScannerOutcomeSummary.is_complete == True` as a hard pre-filter — not a scoring dimension. Candidates without completed outcomes cannot contribute to the outcome summary (median MFE, follow-through rate), so including them in ranking would mislead the aggregate stats. Surface the excluded-incomplete count as context in the response rather than as a score penalty. <!-- issue:#464 date:2026-06-19 expires:2026-12-19 source:refine -->

- [AVOID] Do not treat "outcome availability" as a weight in the analog similarity score. If a candidate event's `ScannerOutcomeSummary.is_complete` is False, exclude it before scoring rather than penalizing it with a lower score. Mixed pools (some with outcomes, some without) produce aggregate stats that are silently biased toward the subset that has outcomes. <!-- issue:#464 date:2026-06-19 expires:2026-12-19 source:refine -->

---
<!-- PROVISIONAL — entries below are from a single observed run; unverified.
     Do not rely on these as authoritative guidance. They are excluded from
     plan/implement prompt injection except as advisory context.
     Each will be promoted to [PATTERN] on second-run confirmation (different issue number) or dropped at TTL. -->
