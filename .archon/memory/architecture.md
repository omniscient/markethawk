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

## Dark Factory Memory Retrieval (issue #646)

- [PATTERN] memory_retrieve.py is flat-file only: no agentmemory library, no HTTP client, no vector DB. Two-layer filter: (1) file selection by area+phase, (2) entry-level filter on source:/agent_id + path: tag + status. When index.jsonl (#649) is present, use it for Layer 2 and ranking (path specificity > recency); when absent, scan .archon/memory/*.md with same logic. <!-- issue:#646 date:2026-06-27 expires:2026-12-27 source:refine -->
- [AVOID] Do not use the agentmemory Python library for Dark Factory memory retrieval — no agentmemory backend exists or is planned (#644 spike verdict). The structured memory store is index.jsonl (produced by memory_import.py from #649) consumed directly via stdlib file reads. <!-- issue:#646 date:2026-06-27 expires:2026-12-27 source:refine -->
- [PATTERN] Phase→source mapping for memory role-segregation: refine→source:refine, plan→source:refine (plans consume design decisions), implement→source:implement, validate→source:conformance, review→source:code-review. Entries in codebase-patterns.md and architecture.md are global and pass unconditionally regardless of source. Area-specific files (backend-patterns.md, frontend-patterns.md, dark-factory-ops.md) apply the source filter fully. <!-- issue:#646 date:2026-06-27 expires:2026-12-27 source:refine -->
