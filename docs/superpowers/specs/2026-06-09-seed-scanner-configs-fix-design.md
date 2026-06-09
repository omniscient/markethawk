# Seed Scanner Configs Fix — Design Spec

**Date:** 2026-06-09
**Issue:** #223
**Status:** Spec generated
**Author:** Refinement Pipeline (Claude)

## Overview

Two regressions in `01_scanner_configs.sql` prevent fresh preview stacks from bootstrapping:

1. **Missing `universe_id`** — three `INSERT INTO scanner_configs` statements omit the `universe_id` column, causing a NOT NULL constraint violation (`universe_id` is `nullable=False`, no server default) and breaking `test_seed_liquidity_hunt_has_universe_id`.

2. **Missing/stale Pocket Pivot row** — the Pocket Pivot (`id=4`) seed row is either absent entirely or present with stale values from before issue #233 (wrong name, wrong criteria format, wrong parameters, wrong `is_active`), breaking `test_seed_pocket_pivot_row_exists`.

Both bugs exist in the two git-tracked copies of the file. The recurrence root cause (why the factory keeps re-dirtying this file) is tracked separately under Epic #262.

## Requirements

1. Both git-tracked seed files must be corrected:
   - `dark-factory/seed/01_scanner_configs.sql` — the primary copy mounted and run by the preview stack
   - `dark-factory/seed/seed/01_scanner_configs.sql` — the subdirectory copy referenced by the issue; also git-tracked and must stay consistent

2. All three existing `scanner_configs` INSERT statements must include `universe_id = 1` in the column list and values.

3. The Pocket Pivot row must be inserted with exactly these values (canonical source: migration `1bf5e10f1111_seed_pocket_pivot_scanner_config.py`):

   | Column | Value |
   |--------|-------|
   | `id` | `4` |
   | `uuid` | `gen_random_uuid()` |
   | `name` | `'Pocket Pivot (Evening)'` |
   | `description` | `'Detects up-days where session volume exceeds the highest down-day volume in the prior 10 trading days (classic Morales/Kacher pocket pivot).'` |
   | `scanner_type` | `'pocket_pivot'` |
   | `parameters` | `'{"lookback_days": 10, "min_lookback_days": 5, "price_floor": 5.00, "volume_floor": 100000}'` |
   | `criteria` | `'{}'` |
   | `is_active` | `false` |
   | `run_frequency` | `'evening'` |
   | `universe_id` | `1` |

   Conflict handling: `ON CONFLICT (id) DO NOTHING` (idempotent — migration may have already seeded this row).

4. The deeply-nested untracked artifact at `dark-factory/seed/seed/seed/01_scanner_configs.sql` is out of scope for this fix. It is not git-tracked and not executed by any known process. The implement agent should note it in `$ARTIFACTS_DIR/out-of-scope.md` and leave it untouched.

5. No schema changes, no Alembic migration, no backend code changes.

## Architecture / Approach

**Direct SQL patch** — edit both git-tracked copies to match the canonical correct state derived from the model (`ScannerConfig.universe_id`, `nullable=False`) and migration `1bf5e10f1111`. No programmatic generation; the files are small and manually maintained.

The corrected INSERT for each of the three existing rows adds `, universe_id` to the column list and `, 1` to the values. The Pocket Pivot row is added after the Oversold Bounce row and before the system_config INSERTs.

Both files must be byte-for-byte identical after the fix (they serve the same purpose; divergence was the source of the bug).

## Alternatives Considered

**A (Chosen): Direct SQL edit of both tracked files**
Simple, auditable, matches the existing hand-curated seed style. No risk of side effects.

**B: `ON CONFLICT (id) DO UPDATE SET ...` for Pocket Pivot**
Would force correction even if the migration had already seeded a stale row. Rejected: the migration `1bf5e10f1111` already uses the correct name/values, so a stale row from it is not possible on fresh stacks. Adds complexity without benefit.

**C: Regenerate seed from migration source of truth**
Generate seed SQL from the Alembic migration chain programmatically. Rejected: introduces tooling overhead and changes the nature of the seed files from curated to generated — out of scope for this bug fix.

## Open Questions

None blocking implementation.

## Assumptions

- `universe_id = 1` is always valid in preview stacks because `dark-factory/seed/00_base_tickers.sql` (or equivalent) inserts the default universe with `id=1` before the scanner configs seed runs.
- The postgres sequence for `scanner_configs.id` will assign id=4 to the Pocket Pivot row when migration `1bf5e10f1111` runs on a fresh preview stack, so `ON CONFLICT (id) DO NOTHING` correctly suppresses the seed INSERT without creating a duplicate.
- `run_frequency` in the seed file columns does not need to be listed for rows 1–3 (Pre-Market, Liquidity Hunt, Oversold Bounce) unless those rows use explicit `run_frequency` values — checking the current HEAD content of both files confirms they do not.
