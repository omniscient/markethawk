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
- [PATTERN] The backlog-scheduler IS the dark factory's persistent daemon; enhance its durable state (scheduler_state volume at /var/lib/dark-factory/) rather than introducing a new Docker service or a persistent Claude Code session per ticket. Scheduler-owned state (retry counts, error fingerprints, per-issue decisions) belongs on the named volume; repo-committed .archon/memory/*.md is the separate in-container cross-run knowledge layer. <!-- issue:#609 date:2026-06-26 expires:2026-12-26 source:refine -->
- [AVOID] Do not attempt a 'true persistent agent daemon' — keeping a Claude Code session alive between board polls conflicts with FACTORY_WIP_LIMIT, breaks per-ticket container isolation (preview stacks, OOS gates), and fights the branch-per-issue model. The backlog-scheduler already satisfies the Hermes 'daemon that stays alive between polls' requirement. <!-- issue:#609 date:2026-06-26 expires:2026-12-26 source:refine -->
- [AVOID] Do not add a standalone escalation-rule declaration header to dark-factory prompt files — the escalation conditions are enforced by mechanism (should_trip_early(), OOS gate, stuck-detection block); prose rules that duplicate those mechanisms create a second source of truth that drifts. Embed escalation logic in mechanism, not in text. <!-- issue:#609 date:2026-06-26 expires:2026-12-26 source:refine -->
