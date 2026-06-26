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

## Replay Engine (#484)

- [PATTERN] Create new `replay_runs`/`replay_trades` tables as a parallel design alongside `backtest_runs`/`backtest_trades` — do not extend or modify the live backtest tables. The two schemas diverge on manifest freezing (universe snapshot, data_hash, exit_fidelity), per-trade fields (MFE/MAE, regime, fill_source), and strategy nullability. <!-- issue:#484 date:2026-06-26 expires:2026-12-26 source:refine -->
- [AVOID] Do not extend `BacktestRun`/`BacktestTrade` with replay-engine columns — the live backtest tables have a running service, Celery task, and tests; mixing replay concerns entangles two feature areas and risks regressions in the production path. <!-- issue:#484 date:2026-06-26 expires:2026-12-26 source:refine -->

- [PATTERN] Compute `data_hash` synchronously at ReplayRun creation in the same DB transaction that writes the ReplayRun row — the hash pins the data state before execution begins, guaranteeing determinism. If bar data is absent for the window, fail at creation rather than deferring. <!-- issue:#484 date:2026-06-26 expires:2026-12-26 source:refine -->
- [AVOID] Do not defer `data_hash` computation (e.g. NULL initially, populated later) — a deferred hash lets the run start executing before its inputs are pinned, defeating the reproducibility guarantee of the replay engine. <!-- issue:#484 date:2026-06-26 expires:2026-12-26 source:refine -->

- [PATTERN] `trading_strategy_id` on `ReplayRun` is nullable — scanner-only replays (pure signal analysis without trade simulation) are a legitimate first-class use case. When NULL, `strategy_snapshot` is also NULL and ManifestResolver skips strategy freezing. <!-- issue:#484 date:2026-06-26 expires:2026-12-26 source:refine -->
