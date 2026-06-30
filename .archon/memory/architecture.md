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

- [PATTERN] memory_write.py is flat-file only: writes to .archon/memory/*.md (source of truth, preserving cap/expiry/dedup) and appends to .archon/memory/index.jsonl (best-effort stub, skip when markdown is no-op). agentId derived from SOURCE arg verbatim; scope derived from target filename stem. No REST sidecar or external HTTP. <!-- issue:#648 date:2026-06-30 expires:2026-12-30 source:refine -->
- [AVOID] Do not add agentmemory REST sidecar, external HTTP, or network I/O to the memory write path — per #644 spike verdict, write adapter is flat-file only (.archon/memory/*.md + local index.jsonl). <!-- issue:#648 date:2026-06-30 expires:2026-12-30 source:refine -->
---
<!-- PROVISIONAL — entries below are from a single observed run; unverified.
     Do not rely on these as authoritative guidance. They are excluded from
     plan/implement prompt injection except as advisory context.
     Each will be promoted to [PATTERN] on second-run confirmation (different issue number) or dropped at TTL. -->
- [INVALID: agentmemory POST superseded by flat-file-only re-spec, issue:#648 2026-06-30] In the write-through memory adapter (memory_write.py), always write to .archon/memory/*.md first (markdown is the source of truth), then POST to agentmemory as a best-effort step — agentmemory failures log a WARNING but do not affect the exit code. Skip agentmemory when the markdown write is a no-op (dedup hit or cap reached) to keep both stores consistent. <!-- issue:#648 date:2026-06-27 expires:2026-12-27 source:refine -->
- [AVOID] Do not use agentmemory queries to drive duplicate detection in the write adapter — semantic/vector dedup makes the skip decision dependent on an optional sidecar (violating the markdown-first guarantee) and contradicts the architecture ban on vector/embedding pipelines for memory retrieval at this scale. Use normalized substring match (lowercase, collapse whitespace, strip trailing punctuation) instead. <!-- issue:#648 date:2026-06-27 expires:2026-12-27 source:refine -->
