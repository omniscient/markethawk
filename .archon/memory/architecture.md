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

## Input Validation — Centralized Types (issue #380)

- [PATTERN] Define all shared validation primitives (Ticker, FuturesSymbol, HttpsUrl, BoundedDict validator, InteractiveDateRange mixin, BatchDateRange mixin) in a single `backend/app/schemas/common.py` module; every schema imports from there. This is the F-INPUT-02 fix: one source of truth replaces scattered per-schema ad-hoc validators. <!-- issue:#380 date:2026-06-15 expires:2026-12-15 source:refine -->

- [AVOID] Do not roll per-schema ticker validators (ad-hoc `constr()` or `.upper()` calls). All ticker/symbol fields in write models must use `Ticker` (equity: `^[A-Z]{1,5}([.\-][A-Z])?$`) or `FuturesSymbol` (futures root: `^[A-Z]{1,5}$`) imported from `common.py`. <!-- issue:#380 date:2026-06-15 expires:2026-12-15 source:refine -->

- [PATTERN] Apply `extra="forbid"` only to write leaf classes (Create/Update/Request), never to `*Base` classes shared with response models (`*Schema`, `*Response`). Leaking `extra="forbid"` onto a response model breaks ORM-attribute serialization. <!-- issue:#380 date:2026-06-15 expires:2026-12-15 source:refine -->

- [PATTERN] Date-range write fields use two mixin base classes from `common.py`: `InteractiveDateRange` (366-day cap for ad-hoc/dashboard queries) and `BatchDateRange` (1830-day / 5-year cap for backtest and backfill operations). GET endpoint date params use an `OutcomeDateRange` Depends class with the same 366-day cap. Bounds return 422 with an explicit message naming the limit and the requested range. <!-- issue:#380 date:2026-06-15 expires:2026-12-15 source:refine -->

- [AVOID] Do not add per-router inline `if (end - start).days > N` date checks — that is the decentralized pattern F-INPUT-02 exists to eliminate. Centralize in the mixin; the router check at `backtest.py:67` should be deleted once the mixin is in place. <!-- issue:#380 date:2026-06-15 expires:2026-12-15 source:refine -->
