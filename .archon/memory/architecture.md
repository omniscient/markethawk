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

## Audit + Optimization Issues (issue #213)

- [PATTERN] For must-have priority issues that ask to "audit" and "optimize" a pipeline loop, deliver both an analysis document (HTML) and concrete pipeline fixes for the highest-confidence gaps. Analysis-only deliverables leave the "optimize" requirement unaddressed. <!-- issue:#213 date:2026-06-05 expires:2026-12-05 source:refine -->
- [AVOID] Stopping at an HTML analysis report for a must-have priority improvement issue — the "find ways to optimize" phrasing signals that concrete pipeline changes are expected alongside the report, not just recommendations. <!-- issue:#213 date:2026-06-05 expires:2026-12-05 source:refine -->

- [PATTERN] Tag auto-written memory entries with source:conformance or source:code-review (not source:implement) to distinguish gate-generated entries from runtime-proven lessons. source:implement entries are highest confidence; source:conformance and source:code-review entries are gate-validated but may not be globally applicable. <!-- issue:#213 date:2026-06-05 expires:2026-12-05 source:refine -->
- [AVOID] Using source:implement for memory entries written by conformance/code-review gate stages — this conflates gate-caught violations with runtime-proven patterns and makes confidence level ambiguous for future agents reading the memory. <!-- issue:#213 date:2026-06-05 expires:2026-12-05 source:refine -->

- [PATTERN] For memory path-tag filtering in the dark factory, use string prefix matching (grep -q "^${path_tag}") rather than shell glob expansion or PCRE — the container ships mawk and POSIX grep, making PCRE and Bash 4+ glob features unavailable. Prefix matching is portable and sufficient for the common case. <!-- issue:#213 date:2026-06-05 expires:2026-12-05 source:refine -->
