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

## Scheduled Scanner Universe Coupling (issue #156)

- [PATTERN] Promote `universe_id` to a first-class non-nullable FK column on `ScannerConfig` (referencing `stock_universes.id`). Migration sequence: add column as nullable → UPDATE all existing rows to `universe_id = 1` → ALTER column to NOT NULL. Celery tasks read `cfg.universe_id` directly instead of `cfg.parameters.get("universe_id")`. This aligns `ScannerConfig` with the pattern already established by `MonitoredStock.universe_id` and `UserPreferences.default_universe_id`, and makes the universe relationship explicit and queryable. <!-- issue:#156 date:2026-06-03 expires:2026-12-03 source:refine -->

- [AVOID] Do not bury `universe_id` inside the freeform `ScannerConfig.parameters` JSON blob. Silent `parameters.get("universe_id")` misses cause scheduled tasks to silently no-op (the bug in issue #156). Every future scanner type will hit the same footgun if the field stays in JSON. <!-- issue:#156 date:2026-06-03 expires:2026-12-03 source:refine -->

- [PATTERN] Universe id=1 ("Large Cap Tech") is the designated default for all scheduled equity scanners. This is confirmed by three sources: (1) the seed assigns id=1 to the large-cap equity universe, (2) the system config key `scanner.default_universe` is seeded to `1`, and (3) `UserPreferences.default_universe_id` defaults to 1. Backfill all existing `ScannerConfig` rows with `universe_id = 1` in the migration. <!-- issue:#156 date:2026-06-03 expires:2026-12-03 source:refine -->

- [AVOID] Do not fall back to "all active universes" when `universe_id` is absent from a scheduled scanner config. This is operationally fragile: adding a second universe would silently double nightly scan volume. Fail loudly instead — raise a clear error if `cfg.universe_id` is NULL after the migration backfill. <!-- issue:#156 date:2026-06-03 expires:2026-12-03 source:refine -->

- [PATTERN] Each beat-scheduled scanner type must have an explicit `ScannerConfig` seed row with `universe_id` set. Add a Celery worker/beat startup validation that asserts each scheduled scanner type (`liquidity_hunt`, `pocket_pivot`) has at least one active config row with a non-null `universe_id`. Log a clear, actionable error (do not crash the whole worker) if the assertion fails; the beat task itself should also fail loudly if it finds zero configs rather than silently returning. <!-- issue:#156 date:2026-06-03 expires:2026-12-03 source:refine -->

- [AVOID] Do not design scheduled scanner tasks to "automatically work without a seed entry." Per-scanner seed entries are intentional: each scanner type is a distinct product behavior targeting a specific universe. A missing config row should surface as a loud startup failure, not a silent no-op at 02:00 UTC. <!-- issue:#156 date:2026-06-03 expires:2026-12-03 source:refine -->

- [PATTERN] Celery task DB sessions in `scanning.py` use synchronous `SessionLocal()` + `db.query()` ORM pattern — this is correct for Celery workers, which are synchronous by design. The "never use synchronous SQLAlchemy" constraint applies to FastAPI router handlers (async def with DI), not to Celery tasks. Adding `cfg.universe_id` as a plain integer column read requires no async relationship changes, no new `relationship()` declarations, and no session changes. <!-- issue:#156 date:2026-06-03 expires:2026-12-03 source:refine -->

- [PATTERN] Both the seed SQL (`dark-factory/seed/seed/01_scanner_configs.sql`) and the task logic (`backend/app/tasks/scanning.py`) must be updated together. The seed is applied fresh on every preview/CI environment, so stale seed data directly reproduces the bug regardless of task-logic fixes. Fix both sides: seed carries explicit `universe_id=1` for liquidity_hunt (id=2) and new pocket_pivot row; tasks read the FK column directly and raise on NULL. <!-- issue:#156 date:2026-06-03 expires:2026-12-03 source:refine -->
