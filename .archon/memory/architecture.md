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

## God Module Decomposition (issue #199)

- [PATTERN] When decomposing god modules with different blast radii (different import-site counts), split them into separate PRs: do the lower-risk module first (fewer import sites, one public symbol) then the higher-risk one (more import sites, multiple public symbols). Reviewers can verify behaviour-preservation more confidently on a smaller diff. <!-- issue:#199 date:2026-06-05 expires:2026-12-05 source:refine -->

- [AVOID] Do not combine two unrelated god-module decompositions into a single PR just because they share a ticket. A 2,100-line refactor diff across two independent modules makes it hard to verify no behaviour changed. Split on module boundaries even when the issue covers both. <!-- issue:#199 date:2026-06-05 expires:2026-12-05 source:refine -->

- [PATTERN] When decomposing a service class used by tests and multiple callers, retain the original class as a thin facade that delegates to extracted modules. This preserves every import site and test reference without a migration pass. Use lazy (function-body) imports in the facade when the extracted module already imports from the original to avoid load-time cycles. <!-- issue:#199 date:2026-06-05 expires:2026-12-05 source:refine -->

- [AVOID] Do not dissolve a widely-imported service class (5+ callers, 3+ test files) when the goal is structural cleanup. Converting static methods to module-level functions forces a caller migration that contradicts the "no behavioural change / tests stay green" acceptance criterion. The facade re-export pattern achieves the same file-size improvement for zero import churn. <!-- issue:#199 date:2026-06-05 expires:2026-12-05 source:refine -->

- [PATTERN] In `app/services/`, group related extracted modules using filename prefixes (e.g., `futures_contracts.py`, `futures_aggregates.py`, `futures_rollovers.py`) rather than a subpackage. The entire `app/` tree is strictly one level deep — no nested packages exist anywhere. Filename prefixes provide the same discoverability without introducing the first subpackage. <!-- issue:#199 date:2026-06-05 expires:2026-12-05 source:refine -->

- [AVOID] Do not introduce `app/services/futures/` or any other nested subpackage in the `app/` directory. There is no precedent for subpackages in this codebase, and the organizational benefit is marginal versus the tooling/import cognitive overhead added. <!-- issue:#199 date:2026-06-05 expires:2026-12-05 source:refine -->
