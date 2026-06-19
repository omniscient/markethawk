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

---
<!-- PROVISIONAL — entries below are from a single observed run; unverified.
     Do not rely on these as authoritative guidance. They are excluded from
     plan/implement prompt injection except as advisory context.
     Each will be promoted to [PATTERN] on second-run confirmation (different issue number) or dropped at TTL. -->

## AI Feature Flags and Narrative State (issue #482)

- [PATTERN] Cost-bearing backend operations (LLM narrative generation, auto-trading) use backend SystemConfig (PostgreSQL key/value) for their enable/disable feature flags, not localStorage. All sessions and browser tabs must see the same operational state; localStorage is only appropriate for per-browser display preferences with no backend cost. <!-- issue:#482 date:2026-06-19 expires:2026-12-19 source:refine -->
- [AVOID] Do not use localStorage for feature flags that gate backend LLM or other cost-bearing operations — it cannot prevent other sessions from triggering generation and it diverges from the server-side enabled/disabled state from backend controls. <!-- issue:#482 date:2026-06-19 expires:2026-12-19 source:refine -->

- [PATTERN] AI narrative staleness is backend-owned: the API response includes a `stale: boolean` field (meaning the cached narrative no longer matches the current deterministic brief), and the frontend renders whatever the backend reports. Client-side time-threshold staleness computation diverges from real cache validity because only the backend knows whether source data changed. <!-- issue:#482 date:2026-06-19 expires:2026-12-19 source:refine -->
- [AVOID] Do not compute narrative staleness client-side from `generated_at` timestamps — wall-clock age does not indicate whether the underlying ai_signal_brief changed, which is the actual staleness condition. <!-- issue:#482 date:2026-06-19 expires:2026-12-19 source:refine -->
