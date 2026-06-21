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

## Replay Engine Data Ingestion (issue #486)

- [PATTERN] For replay benchmark ingestion (BenchmarkIngestor), use a gap-fill approach: query existing timestamps in stock_aggregates for the requested range, fetch only [min(missing), max(missing)] from Polygon in one call, dedup on insert. Do NOT delete-and-reinsert — benchmark history is deep (200+ days for SMA200 warm-up) and re-fetching it on every replay run wastes Polygon quota. Gap detection must cover interior holes, not just the trailing tail. <!-- issue:#486 date:2026-06-21 expires:2026-12-21 source:refine -->

- [AVOID] Do not use the delete-and-reinsert pattern (sync_stock_aggregates task approach) for replay benchmark ingestion — it re-fetches years of daily bars that are already stored, violating the idempotency requirement and burning Polygon API quota. Use gap-fill (refresh_stock_data pattern) instead. <!-- issue:#486 date:2026-06-21 expires:2026-12-21 source:refine -->

## Regime Classification (issue #486)

- [PATTERN] The replay engine's regime classifier (RegimeClassifier in services/replay/classifier.py) must be fully separate from RegimeService (services/regime_service.py). RegimeService uses a rolling-retrain HMM — its labels for a historical date can change after each scheduled retrain, violating the replay engine's determinism requirement. The replay classifier is rule-based (SMA200 trend + realized-vol bucket) with no DB persistence, no Redis cache, and no ML dependency. <!-- issue:#486 date:2026-06-21 expires:2026-12-21 source:refine -->

- [AVOID] Do not extend RegimeService or delegate to it from the replay RegimeClassifier. RegimeService is nondeterministic (rolling retrain changes historical labels), SPY-hardwired, and carries Redis/DB dependencies — all incompatible with replay's reproducibility and parameterized-benchmark requirements. <!-- issue:#486 date:2026-06-21 expires:2026-12-21 source:refine -->

---
<!-- PROVISIONAL — entries below are from a single observed run; unverified.
     Do not rely on these as authoritative guidance. They are excluded from
     plan/implement prompt injection except as advisory context.
     Each will be promoted to [PATTERN] on second-run confirmation (different issue number) or dropped at TTL. -->
