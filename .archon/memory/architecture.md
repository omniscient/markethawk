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

## Scanner Explanation Stamping (issue #462)

- [PATTERN] Stamp `explanation` on `ScannerEvent` inline at write time (same transaction as `indicators`, `criteria_met`, `metadata_`), not via a deferred Celery task. Events must never be API-readable without their explanation — a deferred task opens a race between event creation and explanation population that the API can expose. <!-- issue:#462 date:2026-06-19 expires:2026-12-19 source:refine -->

- [AVOID] Do not defer scanner event explanation population to `evaluate_scanner_alerts` or any post-write async path. The alert evaluation task runs after the event is already committed to DB and potentially returned by API queries; attaching explanation logic there creates an eventually-consistent explanation field that downstream consumers (UI, outcome tracking) cannot rely on. <!-- issue:#462 date:2026-06-19 expires:2026-12-19 source:refine -->

## Cross-Container Schema Sharing (issue #462)

- [PATTERN] When a separate Docker service (e.g. tweet-monitor) must write to a shared DB schema that includes a JSONB payload shape defined by the backend, build the payload as an inline plain dict in the service itself — do not attempt to import the backend's builder class. Enforce schema conformance via the shared Pydantic model (from the backend's schema definitions, used in tests), not class reuse. The contract is the schema, not the builder. <!-- issue:#462 date:2026-06-19 expires:2026-12-19 source:refine -->

- [AVOID] Do not share builder classes across container boundaries (e.g. importing `backend/app/services/ExplanationBuilder` from the tweet-monitor). The builder may be designed for a different data context (e.g. Polygon historical bars vs live IBKR bars), and cross-container imports create implicit coupling to an evolving interface. Inline dict construction + shared schema validation is the correct pattern. <!-- issue:#462 date:2026-06-19 expires:2026-12-19 source:refine -->

---
<!-- PROVISIONAL — entries below are from a single observed run; unverified.
     Do not rely on these as authoritative guidance. They are excluded from
     plan/implement prompt injection except as advisory context.
     Each will be promoted to [PATTERN] on second-run confirmation (different issue number) or dropped at TTL. -->
