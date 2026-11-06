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

- [AVOID] When a new data provider covers only a subset of tickers within an existing universe/sync pipeline (not a new asset class), route it through the per-ticker data_source column already threaded end-to-end (MonitoredStock.data_source / StockUniverseTicker.data_source -> a provider kwarg on the sync Celery task -> StockDataService.get_aggregates(provider=...) -> DataProviderFactory.get(provider)), rather than forking a parallel Celery task or branching on ticker-string patterns (e.g. a '.TO' suffix). Before #904, data_source existed on both models but was never read by the sync path -- every ticker was hard-routed to the default provider regardless of the column's value. IBKR already proves the one-task-many-providers shape works for futures (asset_class branch); the same shape extends to a data_source branch within the stocks half. <!-- issue:#904 date:2026-11-06 expires:2027-05-06 source:refine agent:refine scope:architecture path:backend/app/services/ -->
- [AVOID] For a brand-new nightly-synced table with no prior backfill surface (e.g. lt_dividend, fx_rate_daily added in #904), make the nightly Celery task self-backfill: resume from the day after the latest stored row per key, or N days back if no rows exist yet, so the first scheduled run performs the full historical backfill with no dedicated one-time backfill endpoint, management script, or manual rollout step. Reserve a new REST backfill endpoint for tables that already have an existing analog (e.g. stock_aggregates' POST /{universe_id}/sync-aggregates) or that something in the current slice actually calls. <!-- issue:#904 date:2026-11-06 expires:2027-05-06 source:refine agent:refine scope:architecture path:backend/app/tasks/ -->
- [AVOID] backend/app/tasks/quality.py's check_aggregate_staleness / compute_universe_data_health sweep looks like a general staleness check but is universe-aggregate and percentage-based, with global SystemConfig-driven calendar-hour thresholds (quality_staleness_hours, quality_alert_pct) shared by every screened universe's staleness banner -- it cannot satisfy a per-ticker, trading-day-aware staleness requirement (it only flags a universe once a threshold fraction of its tickers are stale). Do not extend or repurpose this function for a per-ticker/fixed-trading-day check; add a separate function instead (see #904's find_stale_roster_tickers) so existing screened-universe behavior and thresholds are untouched. <!-- issue:#904 date:2026-11-06 expires:2027-05-06 source:refine agent:refine scope:architecture path:backend/app/tasks/quality.py -->
---
<!-- PROVISIONAL — entries below are from a single observed run; unverified.
     Do not rely on these as authoritative guidance. They are excluded from
     plan/implement prompt injection except as advisory context.
     Each will be promoted to [PATTERN] on second-run confirmation (different issue number) or dropped at TTL. -->
