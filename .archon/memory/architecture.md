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

## Scanner Explanation Backfill (issue #458)

- [PATTERN] Backfill tasks that write to `scanner_events.explanation` must filter exclusively to rows where `explanation IS NULL` or `evidence.reconstructed = true`; `force=True` only allows re-writing previously-reconstructed explanations — live explanations (`evidence.reconstructed = false`) must never be overwritten, even with force. Reconstruction from stored fields is strictly lower-fidelity than live generation (no re-fetched market data, current-config thresholds used). <!-- issue:#458 date:2026-06-19 expires:2026-12-19 source:refine -->

- [PATTERN] Use a reconstructor registry pattern for multi-scanner backfill: each scanner type registers a `HistoricalReconstructor` instance; the backfill task delegates to the registry and skips (leaves explanation NULL) for unregistered scanner types. This lets future scanner migrations (liquidity_hunt, oversold_bounce, trend_pullback) add their reconstructors and re-run the same task without touching task code. <!-- issue:#458 date:2026-06-19 expires:2026-12-19 source:refine -->

- [AVOID] Do not produce a generic confidence-only partial explanation for scanner types that lack a registered reconstructor — it would mislead consumers by implying criteria coverage that does not exist. "Unsupported" scanner types should have their explanation left NULL until a dedicated reconstructor is registered. <!-- issue:#458 date:2026-06-19 expires:2026-12-19 source:refine -->

## Agent Memory Design (issue #149)

- [PATTERN] Agent memory is stored as plain markdown files in `.archon/memory/`, committed to the repo. Files are read at Phase 1 load time and updated post-run. This keeps memory human-readable, version-controlled, and accessible to all agents without any extra tooling. <!-- bootstrap date:2026-06-02 expires:2026-12-02 source:refine -->

- [AVOID] Do not store agent memory in CLAUDE.md — that file is the primary developer reference and polluting it with machine-generated observations makes it harder to maintain. Memory files are the designated separation. <!-- bootstrap date:2026-06-02 expires:2026-12-02 source:refine -->

---
<!-- PROVISIONAL — entries below are from a single observed run; unverified.
     Do not rely on these as authoritative guidance. They are excluded from
     plan/implement prompt injection except as advisory context.
     Each will be promoted to [PATTERN] on second-run confirmation (different issue number) or dropped at TTL. -->
