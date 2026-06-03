# Scheduled Scanner Beat Tasks Fix — Design Spec
<!-- spec for issue #156 -->

## Overview

The nightly Celery beat tasks `run_pocket_pivot_scheduled` and `run_liquidity_hunt_scheduled` are silent no-ops because they read `universe_id` from the freeform `parameters` JSON blob on `ScannerConfig`, and the seeded configs omit that key — causing every scheduled run to hit a `logger.warning` + `continue` branch and exit without scanning. The root cause is that `universe_id` is not a first-class column on `ScannerConfig`, making it invisible to the DB schema, unenforceable by a FK constraint, and easy to omit from seed data. The fix promotes `universe_id` to a proper FK column on `scanner_configs`, backfills all existing rows with the system-default universe (id=1), updates the scheduled task logic to read the column directly and fail loudly on NULL, updates the seed SQL to include `universe_id` on existing and new config rows, and adds a Celery worker startup validation that asserts all beat-scheduled scanner types have at least one active config with a non-null `universe_id`.

## Requirements

- Add a `universe_id` integer FK column to `scanner_configs` referencing `stock_universes(id)`. The migration must: add the column as nullable, backfill all existing rows with `universe_id = 1`, then alter the column to non-nullable.
- `ScannerConfig` SQLAlchemy model must declare the new column. No ORM `relationship()` is required — the tasks only need the integer ID.
- `run_pocket_pivot_scheduled` and `run_liquidity_hunt_scheduled` must read `cfg.universe_id` (the column) instead of `cfg.parameters.get("universe_id")`. The warning-and-continue branch must be removed. If `cfg.universe_id` is NULL (data integrity violation post-migration), the task must raise a clear, actionable error rather than silently skip.
- Both tasks must also fail loudly (log a clear error, do not silently return) when they find zero active `ScannerConfig` rows for their type.
- The seed SQL (`dark-factory/seed/seed/01_scanner_configs.sql`) must be updated: the existing `liquidity_hunt` config (id=2) must include `universe_id=1`, and a new `pocket_pivot` config row must be added with `universe_id=1` and its existing parameters (`lookback_days`, `min_lookback_days`, `price_floor`, `volume_floor`).
- A startup validation must run at Celery worker/beat boot. For each beat-scheduled scanner type (`liquidity_hunt`, `pocket_pivot`), it must assert that at least one active `ScannerConfig` row with a non-null `universe_id` exists. On failure it must log a clear, actionable error message (not raise an unhandled exception that crashes the entire worker).
- No change to the FastAPI async router layer, no new Docker containers, no Redis usage for durable state.
- Manual on-demand scanner runs from the Scanner UI must be unaffected.

## Architecture / Approach

**Chosen approach: Option (c) — promote `universe_id` to a first-class FK column on `ScannerConfig`.**

This aligns `ScannerConfig` with the pattern already established throughout the codebase: `MonitoredStock` has a `universe_id` integer column, `UserPreferences` has a `default_universe_id` FK, and the system config seed already sets `scanner.default_universe = 1`. Burying `universe_id` in the freeform `parameters` JSON blob was an inconsistency, not a deliberate design choice. Making it a proper FK column makes the relationship explicit, queryable, and enforceable, and permanently eliminates the footgun for all future scheduled scanner types.

**Migration strategy:** The column is added as nullable, all existing rows are backfilled with `universe_id = 1` (the "Large Cap Tech" universe, confirmed as the system default by the `scanner.default_universe = 1` config seed), then the column is altered to non-nullable. This standard two-phase pattern is required because PostgreSQL cannot add a non-nullable column without a default to a table that already has rows.

**Task logic:** The Celery tasks are synchronous workers using `SessionLocal()` and the `db.query()` ORM pattern throughout `scanning.py`. No async session changes are needed. The change is purely: replace `cfg.parameters.get("universe_id")` with `cfg.universe_id`, remove the warning-and-continue branch, and add explicit error logging when zero configs are found or when `universe_id` is NULL.

**Startup validation:** A validation function is called once at Celery worker/beat startup (e.g., from the `on_after_configure` signal or an app-level `setup()` hook). It opens a short-lived DB session, queries for the expected scanner types, and logs a clear error if any type has no active config with a non-null `universe_id`. It does not raise an unhandled exception (which would crash the entire worker process); the failure is surfaced at 02:00 UTC when the task itself finds zero configs and logs loudly.

**Seed SQL:** Universe id=1 is safe to hardcode in the seed because (a) it is seeded as the first row in the universes table, (b) `scanner.default_universe` is already seeded to `1`, and (c) the seed is applied to a fresh DB where the id sequence is deterministic.

### Files Changed

- **`backend/app/models/scanner_config.py`** — Add `universe_id = Column(Integer, ForeignKey("stock_universes.id"), nullable=False)` to the `ScannerConfig` model. No `relationship()` needed.
- **`backend/alembic/versions/<new_revision>.py`** — New migration: `ADD COLUMN universe_id INTEGER REFERENCES stock_universes(id)` (nullable), `UPDATE scanner_configs SET universe_id = 1`, `ALTER COLUMN universe_id SET NOT NULL`.
- **`backend/app/tasks/scanning.py`** — In `run_pocket_pivot_scheduled` and `run_liquidity_hunt_scheduled`: replace `cfg.parameters.get("universe_id")` with `cfg.universe_id`; remove the warning-and-continue branch; add loud error logging when zero active configs are found; add a clear error log (not silent skip) if `universe_id` is NULL post-migration.
- **`backend/app/tasks/scanning.py`** (same file) — Add a `validate_scheduled_scanner_configs()` function that checks each beat-scheduled scanner type has at least one active config with non-null `universe_id`. Wire it into Celery worker startup (e.g., `worker_ready` or `beat_init` signal, or called from the existing `celery_app.py` setup).
- **`backend/app/core/celery_app.py`** — Wire the startup validation call (import and invoke `validate_scheduled_scanner_configs` at worker/beat init, or register it on the appropriate Celery signal).
- **`dark-factory/seed/seed/01_scanner_configs.sql`** — Update the `liquidity_hunt` row (id=2) to include `universe_id=1`; add a new `pocket_pivot` row with `universe_id=1`, `is_active=true`, and parameters `{"lookback_days": 10, "min_lookback_days": 5, "price_floor": 5.0, "volume_floor": 100000}`.

## Alternatives Considered

### Option A: Add `universe_id` to seeded config parameters JSON
Update the seed SQL so that `parameters` includes `"universe_id": 1` for each scheduled scanner config, leaving the task logic's `parameters.get("universe_id")` pattern intact.

**Why rejected:** This is a band-aid that leaves the structural problem in place. Every future scheduled scanner type will hit the same footgun — a developer adds a beat entry, forgets `universe_id` in the parameters JSON, and gets a silent no-op at 02:00 UTC with no compile-time or startup-time signal that anything is wrong. There is no FK constraint to enforce referential integrity, no schema visibility, and no way to query "which universe does this config run on" without parsing freeform JSON. The inconsistency with the rest of the codebase (`MonitoredStock.universe_id`, `UserPreferences.default_universe_id`) would persist indefinitely.

### Option B: Fall back to all active universes in task logic when `universe_id` is absent
Change the scheduled tasks so that when `parameters.universe_id` is absent, they iterate over all active universes rather than skipping.

**Why rejected:** This is operationally fragile. An operator who adds a second universe (e.g., a small-cap watch list) would immediately see doubled nightly scans — the pocket_pivot and liquidity_hunt tasks would run against both universes with no explicit configuration. The implicit "absence means all" semantics are surprising and hard to discover. It also does not fix the seed, so preview environments still start in a broken state. No migration is required, but the cost is unpredictable runtime behavior as the number of universes grows.

## Assumptions

- [ASSUMPTION] Universe id=1 ("Large Cap Tech") will always be the first row inserted by the seed and its integer primary key will always be `1` on a fresh database. The seed applies to a clean DB with a deterministic sequence, so hardcoding `universe_id=1` in the migration backfill and the seed SQL is safe.
- [ASSUMPTION] The `stock_universes` table is created (and universe id=1 is inserted) before `scanner_configs` in the seed/migration application order. If the FK is added before the referenced row exists, the migration will fail. The existing seed file ordering (`00_base_tickers.sql` before `01_scanner_configs.sql`) should guarantee this, but the migration's backfill UPDATE assumes the referenced row is present.
- [ASSUMPTION] The Celery tasks in `scanning.py` remain synchronous workers using `SessionLocal()` and `db.query()`. If any future refactor moves them to async sessions, the column-read change (`cfg.universe_id`) requires no adjustment but the session management would need revisiting.
- [ASSUMPTION] Removing `universe_id` from the `parameters` JSON blob of existing configs is not required by this fix — the tasks will simply stop reading it from there. Existing rows may retain a stale `"universe_id"` key in their `parameters` JSON; this is harmless but could be cleaned up in a follow-on migration for hygiene.
- [ASSUMPTION] The startup validation does not need to block worker startup or raise an unhandled exception. Logging a clear, actionable error is sufficient; the beat task itself will also fail loudly at runtime if it finds zero configs.
- [ASSUMPTION] No `relationship()` from `ScannerConfig` to `StockUniverse` is needed. The tasks only use the integer `universe_id` to filter `MonitoredStock`; they do not need to traverse to the `StockUniverse` object.

## Open Questions

- The seed currently has no `pocket_pivot` config row at all (it was activated in PR #151 but never seeded). The new seed row will be assigned the next available id (likely id=4, since id=3 is `oversold_bounce`). If any existing data or foreign key references assume a specific id for `pocket_pivot`, the id assignment should be verified before merging. This is low-risk on a fresh seed DB but worth confirming against any live environment that has been seeded previously.
- The startup validation wiring location (`worker_ready` signal vs. `beat_init` vs. a dedicated `on_after_configure` hook) should be confirmed against whichever Celery signals are already used in `celery_app.py` to avoid double-registration.
