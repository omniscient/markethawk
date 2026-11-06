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

- [AVOID] Seed one-time static/reference data (a new lookup table + its rows, a singleton StockUniverse row and first membership) inside the Alembic migration itself, via a guarded idempotent raw sa.text() INSERT keyed on a natural key (ticker/name), with a matching downgrade() DELETE. Do not add an app-startup seeding step — backend/app/main.py's FastAPI lifespan has never seeded data (it only resets orphaned quality reports, clears Redis sync keys, starts the websocket manager); introducing startup-time seeding would be a new pattern that re-checks existence on every boot instead of once. Repo precedent: b1c2d3e4f5a6_seed_sector_etfs_universe.py and the seed-migration family (ed1162e42f12, e9bd09ec24b0, b5e6f7a8b9c0). When seeding a singleton row (e.g. one universe), look it up by a unique name/natural key rather than copying b1c2d3e4f5a6's hardcoded id=2 + ON CONFLICT(id) shortcut, which is fragile if the id sequence ever diverges. <!-- issue:#904 date:2026-11-06 expires:2027-05-06 source:refine agent:refine scope:architecture path:backend/app/alembic/versions/ -->
---
<!-- PROVISIONAL — entries below are from a single observed run; unverified.
     Do not rely on these as authoritative guidance. They are excluded from
     plan/implement prompt injection except as advisory context.
     Each will be promoted to [PATTERN] on second-run confirmation (different issue number) or dropped at TTL. -->
