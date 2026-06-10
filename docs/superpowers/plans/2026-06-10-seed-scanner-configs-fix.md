# Implementation Plan: Seed Scanner Configs Fix

**Date:** 2026-06-10  
**Issue:** #223  
**Spec:** [2026-06-09-seed-scanner-configs-fix-design.md](../specs/2026-06-09-seed-scanner-configs-fix-design.md)  
**Branch:** `refine/issue-223-fix-seed---restore-universe-id---correct`

## Goal

Fix two regressions in `01_scanner_configs.sql` that break fresh preview stack bootstrapping:
1. All three existing INSERT statements are missing `universe_id = 1` (NOT NULL column, no server default).
2. The Pocket Pivot row (id=4) is absent.

Both git-tracked copies must be fixed and made byte-for-byte identical.

## Architecture

**Direct SQL patch** — no schema changes, no Alembic migration, no backend code changes. Edit both copies to match the canonical correct state derived from the `ScannerConfig` model and migration `1bf5e10f1111_seed_pocket_pivot_scanner_config.py`.

## Tech Stack

SQL only. Verification via `pytest` in the backend Docker container.

## File Structure

| File | Change |
|------|--------|
| `dark-factory/seed/01_scanner_configs.sql` | Add `universe_id = 1` to 3 rows; add Pocket Pivot row (id=4) |
| `dark-factory/seed/seed/01_scanner_configs.sql` | Same — must be byte-for-byte identical to primary |
| `$ARTIFACTS_DIR/out-of-scope.md` | Note the untracked nested artifact |

---

## Task 1 — Confirm the failing tests

**Files:** `backend/tests/tasks/test_scheduled_scanner_tasks.py`

### Steps

1. Run the two failing tests to confirm their current failure state:

   ```bash
   docker-compose exec backend pytest \
     backend/tests/tasks/test_scheduled_scanner_tasks.py::test_seed_liquidity_hunt_has_universe_id \
     backend/tests/tasks/test_scheduled_scanner_tasks.py::test_seed_pocket_pivot_row_exists \
     -v
   ```

   **Expected output** (both fail):
   ```
   FAILED tests/tasks/test_scheduled_scanner_tasks.py::test_seed_liquidity_hunt_has_universe_id
   FAILED tests/tasks/test_scheduled_scanner_tasks.py::test_seed_pocket_pivot_row_exists
   2 failed
   ```

---

## Task 2 — Fix both git-tracked seed files

**Files:**
- `dark-factory/seed/01_scanner_configs.sql`
- `dark-factory/seed/seed/01_scanner_configs.sql`

Memory notes baked in:
- `[AVOID]` from `dark-factory-ops.md`: Seed SQL that INSERTs into `scanner_configs` must always include `universe_id` (NOT NULL, no server default).
- `[PATTERN]` from `dark-factory-ops.md`: Only files at the root of `dark-factory/seed/` are executed by the preview stack; the subdirectory copy is git-tracked for consistency but not directly run.

### Steps

1. Replace the full contents of **both** files with the corrected SQL below. Both files must be byte-for-byte identical after the edit.

   **Corrected content** (canonical):

   ```sql
   -- Module 01: Scanner configurations and system config.
   -- Source: curated production export. Idempotent.

   BEGIN;

   -- Scanner config: Pre-Market Volume Spike
   INSERT INTO scanner_configs (id, uuid, name, description, scanner_type, parameters, criteria, is_active, universe_id)
   VALUES (
     1,
     gen_random_uuid(),
     'Pre-Market Volume Spike',
     'Detects stocks with unusual pre-market volume — 4x average with minimum liquidity',
     'pre_market_volume_spike',
     '{"lookback_days": 20, "min_volume": 50000}',
     '[{"field": "relative_volume", "op": ">=", "value": 4.0}, {"field": "price", "op": ">=", "value": 5.0}, {"field": "gap_pct", "op": ">=", "value": 1.0}]',
     true,
     1
   )
   ON CONFLICT (id) DO NOTHING;

   -- Scanner config: Liquidity Hunt (Evening)
   INSERT INTO scanner_configs (id, uuid, name, description, scanner_type, parameters, criteria, is_active, universe_id)
   VALUES (
     2,
     gen_random_uuid(),
     'Liquidity Hunt (Evening)',
     'Identifies stocks with unusual post-market volume patterns suggesting institutional activity',
     'liquidity_hunt',
     '{"lookback_days": 20, "min_volume": 100000, "scan_window": "evening"}',
     '[{"field": "volume_spike", "op": ">=", "value": 3.0}, {"field": "price", "op": ">=", "value": 10.0}, {"field": "spread_pct", "op": ">=", "value": 0.5}]',
     true,
     1
   )
   ON CONFLICT (id) DO NOTHING;

   -- Scanner config: Oversold Bounce
   INSERT INTO scanner_configs (id, uuid, name, description, scanner_type, parameters, criteria, is_active, universe_id)
   VALUES (
     3,
     gen_random_uuid(),
     'Oversold Bounce',
     'Identifies oversold conditions with early reversal signals',
     'oversold_bounce',
     '{"lookback_days": 14, "rsi_period": 14}',
     '[{"field": "rsi", "op": "<=", "value": 30.0}, {"field": "price", "op": ">=", "value": 5.0}, {"field": "volume", "op": ">=", "value": 50000}]',
     true,
     1
   )
   ON CONFLICT (id) DO NOTHING;

   -- Scanner config: Pocket Pivot (Evening)
   -- Source: migration 1bf5e10f1111_seed_pocket_pivot_scanner_config.py
   INSERT INTO scanner_configs (id, uuid, name, description, scanner_type, parameters, criteria, is_active, run_frequency, universe_id)
   VALUES (
     4,
     gen_random_uuid(),
     'Pocket Pivot (Evening)',
     'Detects up-days where session volume exceeds the highest down-day volume in the prior 10 trading days (classic Morales/Kacher pocket pivot).',
     'pocket_pivot',
     '{"lookback_days": 10, "min_lookback_days": 5, "price_floor": 5.00, "volume_floor": 100000}',
     '{}',
     false,
     'evening',
     1
   )
   ON CONFLICT (id) DO NOTHING;

   -- System config defaults
   INSERT INTO system_config (key, value)
   VALUES
     ('scanner.auto_run', 'false'),
     ('scanner.default_universe', '1'),
     ('timesfm_enabled', 'false'),
     ('timesfm_anomaly_threshold', '2.0'),
     ('timesfm_min_history_bars', '30'),
     ('timesfm_fallback_multiplier', '4.0')
   ON CONFLICT (key) DO NOTHING;

   COMMIT;
   ```

2. Verify both files are byte-for-byte identical:

   ```bash
   diff dark-factory/seed/01_scanner_configs.sql dark-factory/seed/seed/01_scanner_configs.sql
   ```

   **Expected output:** (no output — files are identical)

3. Run the two previously-failing tests to confirm they now pass:

   ```bash
   docker-compose exec backend pytest \
     backend/tests/tasks/test_scheduled_scanner_tasks.py::test_seed_liquidity_hunt_has_universe_id \
     backend/tests/tasks/test_scheduled_scanner_tasks.py::test_seed_pocket_pivot_row_exists \
     -v
   ```

   **Expected output:**
   ```
   PASSED tests/tasks/test_scheduled_scanner_tasks.py::test_seed_liquidity_hunt_has_universe_id
   PASSED tests/tasks/test_scheduled_scanner_tasks.py::test_seed_pocket_pivot_row_exists
   2 passed
   ```

4. Run the full test module to confirm no regressions:

   ```bash
   docker-compose exec backend pytest backend/tests/tasks/test_scheduled_scanner_tasks.py -v
   ```

5. Commit:

   ```bash
   git add dark-factory/seed/01_scanner_configs.sql dark-factory/seed/seed/01_scanner_configs.sql
   git commit -m "fix(seed): add universe_id and Pocket Pivot row to scanner_configs seed

   - Add universe_id = 1 to all three existing INSERT statements (id 1-3)
   - Add Pocket Pivot (Evening) row (id=4) matching migration 1bf5e10f1111
   - Sync both git-tracked copies to byte-for-byte identical state
   
   Fixes: test_seed_liquidity_hunt_has_universe_id, test_seed_pocket_pivot_row_exists
   Closes #223"
   ```

---

## Task 3 — Document out-of-scope artifact

**Files:** `$ARTIFACTS_DIR/out-of-scope.md`

Memory notes baked in:
- `[PATTERN]` from `dark-factory-ops.md`: Out-of-scope defects go in `$ARTIFACTS_DIR/out-of-scope.md` with `- <file>: <one-sentence description>`.
- The spec (§4) explicitly directs: note the nested artifact, leave it untouched.

### Steps

1. Write the out-of-scope note:

   ```bash
   mkdir -p "$ARTIFACTS_DIR"
   cat >> "$ARTIFACTS_DIR/out-of-scope.md" <<'EOF'
   - dark-factory/seed/seed/seed/01_scanner_configs.sql: Deeply-nested untracked duplicate seed file; not git-tracked and not executed by any known process — left untouched per spec §4.
   EOF
   ```

   No commit needed — `$ARTIFACTS_DIR` is outside the repo.
