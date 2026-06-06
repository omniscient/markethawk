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

## Memory Correctness Gate (issue #254)

- [PATTERN] Gate empirical runtime claims (container behavior, CLI tool output, framework quirks) behind a `[PROVISIONAL]` entry tier: excluded from authoritative prompt injection, promoted to `[PATTERN]` only when a second run (different issue) independently confirms the same behavior with its own `evidence:` comment. This uses repeated autonomous runs as the validation signal rather than adding a reviewer LLM call. <!-- issue:#254 date:2026-06-06 expires:2026-12-06 source:refine -->

- [AVOID] Do not add a "memory reviewer" subagent that approves entries before commit — an LLM reviewing its own output has low independence, adds per-run cost, and is factory-plumbing complexity (the root cause being fixed). The provisional tier provides correctness through independent cross-run confirmation instead. <!-- issue:#254 date:2026-06-06 expires:2026-12-06 source:refine -->

- [PATTERN] Default the memory write prompt to nothing-by-default: an entry is written only if it would cause a future agent to make a materially different decision compared to reading CLAUDE.md and ARCHITECTURE.md alone. Factory-environment trivia (bash compat quirks, awk edge cases, grep exit codes) is dropped, not stored in a separate runbook file — no agent reads a non-injected file, and low-durability quirks rot silently. <!-- issue:#254 date:2026-06-06 expires:2026-12-06 source:refine -->

- [AVOID] Do not create a `.archon/memory/factory-runbook.md` or equivalent non-injected file for factory-ops trivia — it creates an ambiguous "memory that isn't memory" category, no agent reads it, and the provisional promotion path is the correct home for any factory quirk that proves durable enough to warrant memory. <!-- issue:#254 date:2026-06-06 expires:2026-12-06 source:refine -->

- [PATTERN] Enforce a hard 30-entry cap per memory file (authoritative `[PATTERN]`/`[AVOID]`/`[FIX]` entries combined; `[PROVISIONAL]` capped separately at 10). After each append, if the cap would be exceeded, drop the oldest expired or lowest-signal entries inline in Phase 5 before committing — no separate compaction tool needed. <!-- issue:#254 date:2026-06-06 expires:2026-12-06 source:refine -->
