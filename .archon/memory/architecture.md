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

## Schema Design — Versioned Contracts vs. Internal Reports (issue #492)

- [PATTERN] Use Pydantic `BaseModel` in `backend/app/schemas/` for any output that will be serialized over HTTP or pinned with a `schema_version` field. Use Python `@dataclass` only for internal-only analysis results that are never exposed as API responses. The distinction: `DataReadinessService` uses `@dataclass` (internal); `QualityGateAssessment` uses `Pydantic` because future sub-issues will expose it via preflight API. Add `ConfigDict(extra="forbid")` to catch contract drift. <!-- issue:#492 date:2026-06-19 expires:2026-12-19 source:refine -->

- [AVOID] Do not use `@dataclass` for versioned, machine-readable contracts that will be serialized over HTTP — callers lose Pydantic's schema validation, `extra="forbid"` drift detection, and automatic JSON serialization. The presence of a `schema_version` field is a reliable signal that a shape needs Pydantic. <!-- issue:#492 date:2026-06-19 expires:2026-12-19 source:refine -->

## Service Design — Producer/Consumer Split (issue #492)

- [PATTERN] When a new service *consumes* output from an existing service, put it in a separate file rather than extending the producer. `quality_gate_service.py` consumes `UniverseQualityReport.report_data` produced by `data_quality.py` — keeping them separate preserves one-directional dependency (consumer imports producer, never reverse) and avoids bloating the producer. This mirrors the existing `data_readiness.py` split from `data_quality.py`. <!-- issue:#492 date:2026-06-19 expires:2026-12-19 source:refine -->

- [PATTERN] For services that apply policy logic to pre-fetched data, split into a pure inner function `_build_assessment(data, scope, policy)` (no Session, no I/O) plus a thin DB-aware wrapper `ServiceClass.assess(db, id, ...)`. The pure function becomes the unit-testable core; the wrapper does only I/O. This pattern is required when acceptance criteria include "unit tests cover policy behavior" — the pure function enables testing with plain dicts without DB mocking. <!-- issue:#492 date:2026-06-19 expires:2026-12-19 source:refine -->

## Agent Memory Design (issue #149)

- [PATTERN] Agent memory is stored as plain markdown files in `.archon/memory/`, committed to the repo. Files are read at Phase 1 load time and updated post-run. This keeps memory human-readable, version-controlled, and accessible to all agents without any extra tooling. <!-- bootstrap date:2026-06-02 expires:2026-12-02 source:refine -->

- [AVOID] Do not store agent memory in CLAUDE.md — that file is the primary developer reference and polluting it with machine-generated observations makes it harder to maintain. Memory files are the designated separation. <!-- bootstrap date:2026-06-02 expires:2026-12-02 source:refine -->

---
<!-- PROVISIONAL — entries below are from a single observed run; unverified.
     Do not rely on these as authoritative guidance. They are excluded from
     plan/implement prompt injection except as advisory context.
     Each will be promoted to [PATTERN] on second-run confirmation (different issue number) or dropped at TTL. -->
