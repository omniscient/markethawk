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

## Config Validation (issue #190)

- [PATTERN] For `Settings` fields that must be non-empty AND meet a strength rule (e.g. min length), keep the `= ""` default and use a single `field_validator` to reject both the empty-string and the weak-value cases with one actionable error message that includes a generation hint. <!-- issue:#190 date:2026-06-05 expires:2026-12-05 source:refine -->

- [AVOID] Do not remove the field default (making the field required at pydantic level) when a strength validator is also needed — this splits failure into two different error types (MissingField vs ValidationError) with different messages, making operator diagnostics harder. A validator on a defaulted field covers both cases in one place. <!-- issue:#190 date:2026-06-05 expires:2026-12-05 source:refine -->

- [AVOID] Do not add startup security checks in the FastAPI `lifespan` function for things that can be caught in `Settings` — config validation belongs at the `Settings` layer so it fires in tests and CLI scripts too, not just the HTTP server path. <!-- issue:#190 date:2026-06-05 expires:2026-12-05 source:refine -->

## Agent Memory Design (issue #149)

- [PATTERN] Agent memory is stored as plain markdown files in `.archon/memory/`, committed to the repo. Files are read at Phase 1 load time and updated post-run. This keeps memory human-readable, version-controlled, and accessible to all agents without any extra tooling. <!-- bootstrap date:2026-06-02 expires:2026-12-02 source:refine -->

- [AVOID] Do not store agent memory in CLAUDE.md — that file is the primary developer reference and polluting it with machine-generated observations makes it harder to maintain. Memory files are the designated separation. <!-- bootstrap date:2026-06-02 expires:2026-12-02 source:refine -->
