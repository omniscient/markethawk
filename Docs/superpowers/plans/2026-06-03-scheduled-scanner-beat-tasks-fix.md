# Scheduled Scanner Beat Tasks Fix — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the silent no-op in `run_liquidity_hunt_scheduled` and `run_pocket_pivot_scheduled` by promoting `universe_id` to a first-class FK column on `scanner_configs`, backfilling existing rows, updating task logic to read the column directly, seeding the missing `pocket_pivot` config row, and adding a Celery worker startup validation.

**Spec link:** `Docs/superpowers/specs/2026-06-03-scheduled-scanner-beat-tasks-fix-design.md`

**Architecture:** The `parameters` JSON blob on `ScannerConfig` was being used to carry `universe_id`, but the seeded rows never included that key, causing both scheduled tasks to hit a `logger.warning` + `continue` branch on every beat tick. The fix adds `universe_id` as a proper `INTEGER NOT NULL REFERENCES stock_universes(id)` column. The migration follows the standard three-step PostgreSQL pattern (add nullable, backfill, set NOT NULL) because the table already has rows. Both scheduled tasks are updated to read `cfg.universe_id` directly and fail loudly when data is missing. A startup validation function wired to the `worker_ready` Celery signal checks for correctly configured beat-scheduled scanner configs on every worker boot.

**Tech Stack:** Python 3.11, SQLAlchemy 2.0 (sync ORM + `SessionLocal()`), PostgreSQL, Alembic, Celery beat, `unittest.mock`.

---

## File Structure

| Action | Path | Responsibility |
|--------|------|----------------|
| **Modify** | `backend/app/models/scanner_config.py` | Add `universe_id` FK column |
| **Create** | `backend/app/alembic/versions/c7d8e9f0a1b2_add_universe_id_to_scanner_configs.py` | 3-step migration: add nullable, backfill, set NOT NULL |
| **Modify** | `dark-factory/seed/seed/01_scanner_configs.sql` | Add `universe_id=1` to id=2 (liquidity_hunt); add id=4 (pocket_pivot) |
| **Modify** | `backend/app/tasks/scanning.py` | Fix both scheduled tasks; add `validate_scheduled_scanner_configs()` |
| **Modify** | `backend/app/core/celery_app.py` | Wire `validate_scheduled_scanner_configs` to `worker_ready` signal |
| **Create** | `backend/tests/tasks/test_scheduled_scanner_tasks.py` | Unit tests for the fixed task logic and validation function |

---

## Task 1: Update ScannerConfig model

**Files:**
- Modify: `backend/app/models/scanner_config.py`
- Create: `backend/tests/tasks/test_scheduled_scanner_tasks.py` (stub)

**Why:** The ORM model must declare `universe_id` before any code that reads `cfg.universe_id` can work. SQLAlchemy will raise `AttributeError` at import time if the column is accessed but not declared. This task makes the failing state visible via a test before any implementation exists.

- [ ] **Step 1: Write a failing test that imports ScannerConfig and asserts the column exists**

Create `backend/tests/tasks/test_scheduled_scanner_tasks.py`:

```python
"""Unit tests for scheduled scanner task logic and startup validation."""
import pytest
from unittest.mock import MagicMock, patch, call


# ---------------------------------------------------------------------------
# Task 1 tests: ScannerConfig.universe_id column exists
# ---------------------------------------------------------------------------

def test_scanner_config_has_universe_id_column():
    """ScannerConfig must declare universe_id as a mapped column."""
    from app.models.scanner_config import ScannerConfig
    from sqlalchemy import inspect as sa_inspect

    mapper = sa_inspect(ScannerConfig)
    col_names = [c.key for c in mapper.mapper.column_attrs]
    assert "universe_id" in col_names, (
        "ScannerConfig is missing universe_id column — add it to scanner_config.py"
    )


def test_scanner_config_universe_id_is_integer():
    """universe_id must be an Integer column."""
    from app.models.scanner_config import ScannerConfig
    import sqlalchemy as sa

    col = ScannerConfig.__table__.c["universe_id"]
    assert isinstance(col.type, sa.Integer)


def test_scanner_config_universe_id_is_not_nullable():
    """universe_id must be NOT NULL (nullable=False)."""
    from app.models.scanner_config import ScannerConfig

    col = ScannerConfig.__table__.c["universe_id"]
    assert col.nullable is False, "universe_id must be NOT NULL"
```

- [ ] **Step 2: Verify the test fails**

```bash
cd /workspace/markethawk/backend && python -m pytest tests/tasks/test_scheduled_scanner_tasks.py::test_scanner_config_has_universe_id_column -v
```

Expected: `FAILED` — `AssertionError: ScannerConfig is missing universe_id column`

- [ ] **Step 3: Add `universe_id` column to ScannerConfig model**

Edit `backend/app/models/scanner_config.py`. Add `ForeignKey` to the **existing** sqlalchemy import line only — do not replace the full block, as that would lose the `Uuid as UUID` import on the next line.

Change only this line:

```python
from sqlalchemy import JSON, Boolean, Column, DateTime, Integer, String, Text
```

to:

```python
from sqlalchemy import JSON, Boolean, Column, DateTime, ForeignKey, Integer, String, Text
```

Leave the following line unchanged (it must stay):

```python
from sqlalchemy import Uuid as UUID
```

Then add the column after `data_requirements`:

```python
    data_requirements = Column(JSONB, nullable=True)
    universe_id = Column(
        Integer, ForeignKey("stock_universes.id"), nullable=False
    )
```

The complete `ScannerConfig` class body after the edit:

```python
class ScannerConfig(Base):
    """Represents a scanner configuration with criteria and scheduling."""

    __tablename__ = "scanner_configs"

    id = Column(Integer, primary_key=True, index=True)
    uuid = Column(UUID(as_uuid=True), default=uuid.uuid4, unique=True, index=True)
    name = Column(String(100), nullable=False)
    description = Column(Text)
    scanner_type = Column(String(50), nullable=False)
    parameters = Column(JSON, nullable=False)
    criteria = Column(JSON, nullable=False)
    is_active = Column(Boolean, default=True)
    run_frequency = Column(String(20))
    last_run = Column(DateTime)
    next_run = Column(DateTime)
    outcome_config = Column(JSONB, nullable=True)
    data_requirements = Column(JSONB, nullable=True)
    universe_id = Column(
        Integer, ForeignKey("stock_universes.id"), nullable=False
    )

    created_at = Column(
        DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None)
    )
    updated_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc).replace(tzinfo=None),
        onupdate=lambda: datetime.now(timezone.utc).replace(tzinfo=None),
    )
```

- [ ] **Step 4: Verify the test passes**

```bash
cd /workspace/markethawk/backend && python -m pytest tests/tasks/test_scheduled_scanner_tasks.py::test_scanner_config_has_universe_id_column tests/tasks/test_scheduled_scanner_tasks.py::test_scanner_config_universe_id_is_integer tests/tasks/test_scheduled_scanner_tasks.py::test_scanner_config_universe_id_is_not_nullable -v
```

Expected: all three pass.

- [ ] **Step 5: Validate no import regressions**

```bash
cd /workspace/markethawk/backend && python -m pytest tests/tasks/test_metrics_instrumentation.py -v
```

Expected: all pass (the existing metrics tests import `app.tasks.scanning` which imports `ScannerConfig`).

- [ ] **Step 6: Commit**

```bash
cd /workspace/markethawk && git add backend/app/models/scanner_config.py backend/tests/tasks/test_scheduled_scanner_tasks.py && git commit -m "$(cat <<'EOF'
feat(#156): promote universe_id to FK column on ScannerConfig

Add universe_id = Column(Integer, ForeignKey("stock_universes.id"),
nullable=False) to ScannerConfig. Add stub test file asserting the
column is declared with correct type and nullability.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Write Alembic migration

**Files:**
- Create: `backend/app/alembic/versions/c7d8e9f0a1b2_add_universe_id_to_scanner_configs.py`

**Why:** PostgreSQL cannot add a NOT NULL column to a table that already has rows without a default. The correct pattern is: (1) add the column as nullable, (2) UPDATE all existing rows, (3) ALTER the column to NOT NULL. This migration implements all three steps in a single `upgrade()` transaction.

- [ ] **Step 1: Write a failing test that asserts the migration revision exists**

Append to `backend/tests/tasks/test_scheduled_scanner_tasks.py`:

```python
# ---------------------------------------------------------------------------
# Task 2 tests: Alembic migration file exists and has correct revision chain
# ---------------------------------------------------------------------------

def test_migration_file_exists():
    """The add_universe_id migration file must exist at the expected path."""
    import os
    path = os.path.join(
        os.path.dirname(__file__),
        "..", "..", "app", "alembic", "versions",
        "c7d8e9f0a1b2_add_universe_id_to_scanner_configs.py",
    )
    assert os.path.isfile(os.path.abspath(path)), (
        "Migration file c7d8e9f0a1b2_add_universe_id_to_scanner_configs.py not found"
    )


def test_migration_revision_chain():
    """Migration must declare correct revision and a non-None down_revision.

    NOTE: The exact down_revision value must match whatever `alembic heads`
    reports at implementation time.  We do NOT hardcode it here to avoid
    creating a false-branch if a later migration is merged before this one.
    The implementer must verify that the value written into the migration file
    matches the output of `alembic heads` at commit time.
    """
    import importlib.util, os
    path = os.path.abspath(os.path.join(
        os.path.dirname(__file__),
        "..", "..", "app", "alembic", "versions",
        "c7d8e9f0a1b2_add_universe_id_to_scanner_configs.py",
    ))
    spec = importlib.util.spec_from_file_location("mig", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.revision == "c7d8e9f0a1b2"
    # down_revision must be set (not None) — the implementer must confirm the
    # specific value matches `alembic heads` output before committing.
    assert mod.down_revision is not None, (
        "down_revision is None — set it to the current alembic HEAD revision "
        "(run `alembic heads` inside the backend container to find it)"
    )
```

- [ ] **Step 2: Verify tests fail**

```bash
cd /workspace/markethawk/backend && python -m pytest tests/tasks/test_scheduled_scanner_tasks.py::test_migration_file_exists tests/tasks/test_scheduled_scanner_tasks.py::test_migration_revision_chain -v
```

Expected: both `FAILED` — file does not exist.

- [ ] **Step 3: Create the migration file**

**IMPORTANT:** Before creating this file, run `alembic heads` inside the backend container to confirm the current HEAD revision:

```bash
docker-compose exec backend python -m alembic heads
```

The output must show `1bf5e10f1111 (head)`. If it shows a different revision, update `down_revision` in the file below to match that revision instead.

Create `backend/app/alembic/versions/c7d8e9f0a1b2_add_universe_id_to_scanner_configs.py`:

```python
"""add universe_id to scanner_configs

Revision ID: c7d8e9f0a1b2
Revises: 1bf5e10f1111
Create Date: 2026-06-03 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
# IMPORTANT: down_revision must equal the output of `alembic heads` at the time
# this migration is created. If the current HEAD is not 1bf5e10f1111, update this
# value — using a stale revision will create an Alembic branch instead of
# advancing the linear chain, and `alembic upgrade head` will pick the wrong tip.
revision: str = "c7d8e9f0a1b2"
down_revision: Union[str, None] = "1bf5e10f1111"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Step 1: Add the column as nullable so existing rows are not rejected.
    op.add_column(
        "scanner_configs",
        sa.Column(
            "universe_id",
            sa.Integer(),
            sa.ForeignKey("stock_universes.id"),
            nullable=True,
        ),
    )

    # Step 2: Backfill all existing rows with universe_id = 1 (the system
    # default universe, confirmed by the scanner.default_universe = 1 seed).
    op.execute(
        sa.text("UPDATE scanner_configs SET universe_id = 1 WHERE universe_id IS NULL")
    )

    # Step 3: Enforce NOT NULL now that all rows have a value.
    op.alter_column("scanner_configs", "universe_id", nullable=False)


def downgrade() -> None:
    op.drop_column("scanner_configs", "universe_id")
```

- [ ] **Step 4: Verify tests pass**

```bash
cd /workspace/markethawk/backend && python -m pytest tests/tasks/test_scheduled_scanner_tasks.py::test_migration_file_exists tests/tasks/test_scheduled_scanner_tasks.py::test_migration_revision_chain -v
```

Expected: both pass.

- [ ] **Step 5: Apply the migration to the running database**

```bash
docker-compose exec backend python -m alembic upgrade head
```

Expected output includes: `Running upgrade 1bf5e10f1111 -> c7d8e9f0a1b2, add universe_id to scanner_configs`

- [ ] **Step 6: Validate the column exists in the live database**

```bash
docker-compose exec backend python -c "
from app.core.database import SessionLocal
from app.models.scanner_config import ScannerConfig
db = SessionLocal()
rows = db.query(ScannerConfig.id, ScannerConfig.scanner_type, ScannerConfig.universe_id).all()
for r in rows:
    print(r)
db.close()
"
```

Expected: all rows print with a non-None `universe_id` (value `1`).

- [ ] **Step 7: Commit**

```bash
cd /workspace/markethawk && git add backend/app/alembic/versions/c7d8e9f0a1b2_add_universe_id_to_scanner_configs.py backend/tests/tasks/test_scheduled_scanner_tasks.py && git commit -m "$(cat <<'EOF'
feat(#156): migration — add universe_id FK to scanner_configs

Three-step upgrade: add nullable column, backfill all existing rows
with universe_id=1 (system default universe), alter to NOT NULL.
Downgrade drops the column. down_revision=1bf5e10f1111.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: Update seed SQL

**Files:**
- Modify: `dark-factory/seed/seed/01_scanner_configs.sql`

**Why:** The seed is applied to a fresh database in preview environments. Without `universe_id` in the INSERT statements the migration backfill covers live databases but seed-only deployments (dark factory previews) will fail the NOT NULL constraint. The `pocket_pivot` scanner config has never been seeded, so new preview environments have no config for it at all.

- [ ] **Step 1: Write a failing test that asserts the seed SQL contains universe_id**

Append to `backend/tests/tasks/test_scheduled_scanner_tasks.py`:

```python
# ---------------------------------------------------------------------------
# Task 3 tests: Seed SQL correctness
# ---------------------------------------------------------------------------

def test_seed_liquidity_hunt_has_universe_id():
    """The liquidity_hunt seed row (id=2) must include universe_id column and value."""
    import os
    seed_path = os.path.abspath(os.path.join(
        os.path.dirname(__file__),
        "..", "..", "..", "..", "dark-factory", "seed", "seed",
        "01_scanner_configs.sql",
    ))
    with open(seed_path) as f:
        content = f.read()
    assert "universe_id" in content, (
        "01_scanner_configs.sql is missing universe_id — update the liquidity_hunt INSERT"
    )


def test_seed_pocket_pivot_row_exists():
    """A pocket_pivot config row must be present in the seed SQL."""
    import os
    seed_path = os.path.abspath(os.path.join(
        os.path.dirname(__file__),
        "..", "..", "..", "..", "dark-factory", "seed", "seed",
        "01_scanner_configs.sql",
    ))
    with open(seed_path) as f:
        content = f.read()
    assert "pocket_pivot" in content, (
        "01_scanner_configs.sql is missing the pocket_pivot config row"
    )
    assert "lookback_days" in content and "volume_floor" in content, (
        "pocket_pivot seed row is missing required parameters (lookback_days, volume_floor)"
    )
```

- [ ] **Step 2: Verify tests fail**

```bash
cd /workspace/markethawk/backend && python -m pytest tests/tasks/test_scheduled_scanner_tasks.py::test_seed_liquidity_hunt_has_universe_id tests/tasks/test_scheduled_scanner_tasks.py::test_seed_pocket_pivot_row_exists -v
```

Expected: `test_seed_liquidity_hunt_has_universe_id` fails (no `universe_id` in file); `test_seed_pocket_pivot_row_exists` fails (no `pocket_pivot` in file).

- [ ] **Step 3: Update the seed SQL**

Replace the entire content of `dark-factory/seed/seed/01_scanner_configs.sql` with:

```sql
-- Module 01: Scanner configurations and system config.
-- Source: curated production export. Idempotent.

BEGIN;

-- Scanner config: Pre-Market Volume Spike
INSERT INTO scanner_configs (id, name, description, scanner_type, parameters, criteria, is_active, universe_id)
VALUES (
  1,
  'Pre-Market Volume Spike',
  'Detects stocks with unusual pre-market volume — 4x average with minimum liquidity',
  'pre_market_volume',
  '{"lookback_days": 20, "min_volume": 50000}',
  '{"relative_volume_threshold": 4.0, "min_price": 5.0, "min_gap_pct": 1.0}',
  true,
  1
)
ON CONFLICT (id) DO UPDATE SET universe_id = EXCLUDED.universe_id;

-- Scanner config: Liquidity Hunt (Evening)
INSERT INTO scanner_configs (id, name, description, scanner_type, parameters, criteria, is_active, universe_id)
VALUES (
  2,
  'Liquidity Hunt (Evening)',
  'Identifies stocks with unusual post-market volume patterns suggesting institutional activity',
  'liquidity_hunt',
  '{"lookback_days": 20, "min_volume": 100000, "scan_window": "evening"}',
  '{"volume_spike_threshold": 3.0, "min_price": 10.0, "min_spread_pct": 0.5}',
  true,
  1
)
ON CONFLICT (id) DO UPDATE SET universe_id = EXCLUDED.universe_id;

-- Scanner config: Oversold Bounce
INSERT INTO scanner_configs (id, name, description, scanner_type, parameters, criteria, is_active, universe_id)
VALUES (
  3,
  'Oversold Bounce',
  'Identifies oversold conditions with early reversal signals',
  'oversold_bounce',
  '{"lookback_days": 14, "rsi_period": 14}',
  '{"rsi_threshold": 30.0, "min_price": 5.0, "min_volume": 50000}',
  true,
  1
)
ON CONFLICT (id) DO UPDATE SET universe_id = EXCLUDED.universe_id;

-- Scanner config: Pocket Pivot (Evening)
-- The migration 1bf5e10f1111 may have already inserted a pocket_pivot row with a
-- system-assigned id (not 4). Patch that existing row first so it gets universe_id=1,
-- then INSERT id=4 only if no row yet exists with scanner_type='pocket_pivot'.
UPDATE scanner_configs
SET universe_id = 1
WHERE scanner_type = 'pocket_pivot'
  AND id != 4;

INSERT INTO scanner_configs (id, name, description, scanner_type, parameters, criteria, is_active, run_frequency, universe_id)
SELECT
  4,
  'Pocket Pivot (Evening)',
  'Detects up-days where session volume exceeds the highest down-day volume in the prior 10 trading days (classic Morales/Kacher pocket pivot).',
  'pocket_pivot',
  '{"lookback_days": 10, "min_lookback_days": 5, "price_floor": 5.0, "volume_floor": 100000}',
  '{}',
  true,
  'evening',
  1
WHERE NOT EXISTS (
  SELECT 1 FROM scanner_configs WHERE scanner_type = 'pocket_pivot'
)
ON CONFLICT (id) DO UPDATE SET universe_id = EXCLUDED.universe_id;

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

- [ ] **Step 4: Verify tests pass**

```bash
cd /workspace/markethawk/backend && python -m pytest tests/tasks/test_scheduled_scanner_tasks.py::test_seed_liquidity_hunt_has_universe_id tests/tasks/test_scheduled_scanner_tasks.py::test_seed_pocket_pivot_row_exists -v
```

Expected: both pass.

- [ ] **Step 5: Validate seed SQL syntax**

```bash
docker-compose exec db psql -U postgres -d markethawk_preview -c "\i /dev/stdin" < /workspace/markethawk/dark-factory/seed/seed/01_scanner_configs.sql 2>&1 | head -20
```

If a preview DB is not available, perform a dry-run parse check:

```bash
docker-compose exec backend python -c "
import re, pathlib
sql = pathlib.Path('/workspace/markethawk/dark-factory/seed/seed/01_scanner_configs.sql').read_text()
assert 'universe_id' in sql
assert 'pocket_pivot' in sql
assert 'lookback_days' in sql
assert 'volume_floor' in sql
print('Seed SQL parse check OK')
"
```

- [ ] **Step 6: Commit**

```bash
cd /workspace/markethawk && git add dark-factory/seed/seed/01_scanner_configs.sql backend/tests/tasks/test_scheduled_scanner_tasks.py && git commit -m "$(cat <<'EOF'
feat(#156): seed universe_id on all scanner_config rows; add pocket_pivot row

Update 01_scanner_configs.sql: add universe_id=1 to all three existing
INSERT statements. Add id=4 pocket_pivot row with universe_id=1 and
parameters {lookback_days:10, min_lookback_days:5, price_floor:5.0,
volume_floor:100000}.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: Fix scheduled task logic

**Files:**
- Modify: `backend/app/tasks/scanning.py`

**Why:** Both `run_liquidity_hunt_scheduled` and `run_pocket_pivot_scheduled` currently call `cfg.parameters.get("universe_id")` and silently skip configs where the key is missing. After the migration, `universe_id` is a first-class column — the tasks must read `cfg.universe_id` directly and raise loudly when it is NULL (which would indicate a data integrity violation post-migration) or when no active configs exist for the scanner type.

- [ ] **Step 1: Write failing tests for the fixed task logic**

Append to `backend/tests/tasks/test_scheduled_scanner_tasks.py`:

```python
# ---------------------------------------------------------------------------
# Task 4 tests: Fixed scheduled task logic
# ---------------------------------------------------------------------------

def _make_cfg(id, universe_id, scanner_type="liquidity_hunt", is_active=True):
    """Return a MagicMock resembling a ScannerConfig ORM row."""
    cfg = MagicMock()
    cfg.id = id
    cfg.scanner_type = scanner_type
    cfg.is_active = is_active
    cfg.universe_id = universe_id
    # parameters.get must NOT be called in the fixed implementation
    cfg.parameters = MagicMock()
    cfg.parameters.get.side_effect = AssertionError(
        "Fixed task must not call cfg.parameters.get('universe_id')"
    )
    return cfg


class TestRunLiquidityHuntScheduledFixed:
    """Tests for the fixed run_liquidity_hunt_scheduled task."""

    def _run_with_configs(self, configs, tickers=None):
        """Invoke the task with a mocked DB returning given configs."""
        from app.models.scanner_config import ScannerConfig
        from app.models.monitored_stock import MonitoredStock

        if tickers is None:
            tickers = [MagicMock(ticker="AAPL"), MagicMock(ticker="MSFT")]

        import app.tasks.scanning as scanning_module

        # Use query side_effect to discriminate ScannerConfig vs MonitoredStock queries.
        # Both use single .filter(A, B).all() in production, so each model gets its own
        # mock query chain.
        def _make_query_mock(return_rows):
            q = MagicMock()
            q.filter.return_value.all.return_value = return_rows
            return q

        mock_db = MagicMock()
        mock_db.query.side_effect = lambda model: (
            _make_query_mock(configs) if model is ScannerConfig
            else _make_query_mock(tickers)
        )

        # Build a mock self with retry configured to re-raise the original exception,
        # matching real Celery behavior and ensuring pytest.raises() sees the exception.
        mock_self = MagicMock()
        mock_self.retry.side_effect = lambda exc, **kw: (_ for _ in ()).throw(exc)

        # PATCH TARGET NOTE: run_liquidity_hunt_scan is imported *inside* the task
        # function body via `from app.services.liquidity_hunt import run_liquidity_hunt_scan`.
        # That local import binds the name inside the function's local scope, NOT in
        # the app.tasks.scanning namespace.  Patching app.tasks.scanning.run_liquidity_hunt_scan
        # would fail because that name does not exist at module level.  The correct
        # target is the service module where the function is defined.
        with (
            patch("app.tasks.scanning.SessionLocal", return_value=mock_db),
            patch("app.tasks.scanning.get_market_today", return_value="2026-06-03"),
            patch("app.tasks.scanning.asyncio.run", return_value=[]),
            patch("app.services.liquidity_hunt.run_liquidity_hunt_scan", return_value=[]),
        ):
            # Use .run(mock_self) rather than .__wrapped__(mock_self).
            # __wrapped__ is not guaranteed to exist on all Celery versions; .run()
            # is the stable public API for invoking a bound task synchronously.
            scanning_module.run_liquidity_hunt_scheduled.run(mock_self)

    def test_does_not_call_parameters_get(self):
        """Fixed task must read cfg.universe_id, never cfg.parameters.get."""
        cfg = _make_cfg(id=2, universe_id=1)
        # If parameters.get is called, the mock raises AssertionError.
        # The test passes only if no AssertionError is raised.
        self._run_with_configs([cfg])

    def test_logs_error_and_raises_when_zero_configs(self, caplog):
        """Task must log an error when no active ScannerConfig rows are found."""
        import logging
        with caplog.at_level(logging.ERROR, logger="app.tasks.scanning"):
            with pytest.raises(Exception):
                self._run_with_configs([])
        assert any("liquidity_hunt" in r.message.lower() for r in caplog.records), (
            "Expected an error log mentioning 'liquidity_hunt' when zero configs found"
        )

    def test_logs_error_when_universe_id_is_null(self, caplog):
        """Task must log a loud error when cfg.universe_id is None."""
        import logging
        cfg = _make_cfg(id=2, universe_id=None)
        with caplog.at_level(logging.ERROR, logger="app.tasks.scanning"):
            with pytest.raises(Exception):
                self._run_with_configs([cfg])
        assert any("universe_id" in r.message.lower() for r in caplog.records)


class TestRunPocketPivotScheduledFixed:
    """Tests for the fixed run_pocket_pivot_scheduled task."""

    def _run_with_configs(self, configs, tickers=None):
        from app.models.scanner_config import ScannerConfig
        from app.models.monitored_stock import MonitoredStock

        if tickers is None:
            tickers = [MagicMock(ticker="AAPL")]

        import app.tasks.scanning as scanning_module

        # Use query side_effect to discriminate ScannerConfig vs MonitoredStock queries.
        # Both use single .filter(A, B).all() in production.
        def _make_query_mock(return_rows):
            q = MagicMock()
            q.filter.return_value.all.return_value = return_rows
            return q

        mock_db = MagicMock()
        mock_db.query.side_effect = lambda model: (
            _make_query_mock(configs) if model is ScannerConfig
            else _make_query_mock(tickers)
        )

        # mock_self.retry re-raises so pytest.raises(Exception) sees the exception.
        mock_self = MagicMock()
        mock_self.retry.side_effect = lambda exc, **kw: (_ for _ in ()).throw(exc)

        # PATCH TARGET NOTE: run_pocket_pivot_scan is imported *inside* the task
        # function body via `from app.services.pocket_pivot import run_pocket_pivot_scan`.
        # Patch the service module where the function is defined, not the scanning
        # module namespace (where the name does not exist at module level).
        with (
            patch("app.tasks.scanning.SessionLocal", return_value=mock_db),
            patch("app.tasks.scanning.get_market_today", return_value="2026-06-03"),
            patch("app.tasks.scanning.asyncio.run", return_value=[]),
            patch("app.services.pocket_pivot.run_pocket_pivot_scan", return_value=[]),
        ):
            # Use .run(mock_self) — the stable Celery API for synchronous invocation.
            # __wrapped__ is not guaranteed to exist on all Celery versions.
            scanning_module.run_pocket_pivot_scheduled.run(mock_self)

    def test_does_not_call_parameters_get(self):
        """Fixed task must read cfg.universe_id, never cfg.parameters.get."""
        cfg = _make_cfg(id=4, universe_id=1, scanner_type="pocket_pivot")
        self._run_with_configs([cfg])

    def test_logs_error_and_raises_when_zero_configs(self, caplog):
        """Task must log an error when no active pocket_pivot configs are found."""
        import logging
        with caplog.at_level(logging.ERROR, logger="app.tasks.scanning"):
            with pytest.raises(Exception):
                self._run_with_configs([])
        assert any("pocket_pivot" in r.message.lower() for r in caplog.records)

    def test_logs_error_when_universe_id_is_null(self, caplog):
        """Task must log a loud error when cfg.universe_id is None."""
        import logging
        cfg = _make_cfg(id=4, universe_id=None, scanner_type="pocket_pivot")
        with caplog.at_level(logging.ERROR, logger="app.tasks.scanning"):
            with pytest.raises(Exception):
                self._run_with_configs([cfg])
        assert any("universe_id" in r.message.lower() for r in caplog.records)
```

- [ ] **Step 2: Verify tests fail**

```bash
cd /workspace/markethawk/backend && python -m pytest tests/tasks/test_scheduled_scanner_tasks.py -k "TestRunLiquidityHuntScheduledFixed or TestRunPocketPivotScheduledFixed" -v
```

Expected: tests fail because the tasks still call `cfg.parameters.get("universe_id")`.

- [ ] **Step 3: Fix `run_liquidity_hunt_scheduled`**

In `backend/app/tasks/scanning.py`, replace the body of `run_liquidity_hunt_scheduled` from after the `db: Session = SessionLocal()` line through the end of the for-loop:

Replace:

```python
        event_date = get_market_today()
        configs = (
            db.query(ScannerConfig)
            .filter(
                ScannerConfig.scanner_type == "liquidity_hunt",
                ScannerConfig.is_active.is_(True),
            )
            .all()
        )

        for cfg in configs:
            universe_id = cfg.parameters.get("universe_id")
            if not universe_id:
                logger.warning(
                    "liquidity_hunt ScannerConfig %s has no universe_id", cfg.id
                )
                continue

            tickers = [
                ms.ticker
                for ms in db.query(MonitoredStock)
                .filter(
                    MonitoredStock.universe_id == universe_id,
                    MonitoredStock.is_active.is_(True),
                )
                .all()
            ]
            if not tickers:
                continue

            results = asyncio.run(
                run_liquidity_hunt_scan(
                    tickers, db, start_date=event_date, end_date=event_date
                )
            )
            logger.info(
                "liquidity_hunt scheduled scan for universe %s on %s: %d events",
                universe_id,
                event_date,
                len(results),
            )
```

With:

```python
        event_date = get_market_today()
        configs = (
            db.query(ScannerConfig)
            .filter(
                ScannerConfig.scanner_type == "liquidity_hunt",
                ScannerConfig.is_active.is_(True),
            )
            .all()
        )

        if not configs:
            logger.error(
                "run_liquidity_hunt_scheduled: no active liquidity_hunt ScannerConfig "
                "rows found — add a row to scanner_configs with scanner_type='liquidity_hunt', "
                "is_active=true, and a valid universe_id FK."
            )
            raise RuntimeError("no active liquidity_hunt scanner configs")

        for cfg in configs:
            if cfg.universe_id is None:
                logger.error(
                    "run_liquidity_hunt_scheduled: ScannerConfig id=%s has universe_id=NULL "
                    "— this is a data integrity violation; run the migration "
                    "c7d8e9f0a1b2_add_universe_id_to_scanner_configs to backfill.",
                    cfg.id,
                )
                raise RuntimeError(
                    f"ScannerConfig id={cfg.id} has universe_id=NULL"
                )

            tickers = [
                ms.ticker
                for ms in db.query(MonitoredStock)
                .filter(
                    MonitoredStock.universe_id == cfg.universe_id,
                    MonitoredStock.is_active.is_(True),
                )
                .all()
            ]
            if not tickers:
                logger.warning(
                    "run_liquidity_hunt_scheduled: universe_id=%s has no active tickers, "
                    "skipping ScannerConfig id=%s",
                    cfg.universe_id,
                    cfg.id,
                )
                continue

            results = asyncio.run(
                run_liquidity_hunt_scan(
                    tickers, db, start_date=event_date, end_date=event_date
                )
            )
            logger.info(
                "liquidity_hunt scheduled scan for universe %s on %s: %d events",
                cfg.universe_id,
                event_date,
                len(results),
            )
```

- [ ] **Step 4: Fix `run_pocket_pivot_scheduled`**

In `backend/app/tasks/scanning.py`, replace the equivalent block in `run_pocket_pivot_scheduled`:

Replace:

```python
        event_date = get_market_today()
        configs = (
            db.query(ScannerConfig)
            .filter(
                ScannerConfig.scanner_type == "pocket_pivot",
                ScannerConfig.is_active.is_(True),
            )
            .all()
        )

        for cfg in configs:
            universe_id = cfg.parameters.get("universe_id")
            if not universe_id:
                logger.warning(
                    "pocket_pivot ScannerConfig %s has no universe_id", cfg.id
                )
                continue

            tickers = [
                ms.ticker
                for ms in db.query(MonitoredStock)
                .filter(
                    MonitoredStock.universe_id == universe_id,
                    MonitoredStock.is_active.is_(True),
                )
                .all()
            ]
            if not tickers:
                continue

            results = asyncio.run(
                run_pocket_pivot_scan(
                    tickers, db, start_date=event_date, end_date=event_date
                )
            )
            logger.info(
                "pocket_pivot scheduled scan for universe %s on %s: %d events",
                universe_id,
                event_date,
                len(results),
            )
```

With:

```python
        event_date = get_market_today()
        configs = (
            db.query(ScannerConfig)
            .filter(
                ScannerConfig.scanner_type == "pocket_pivot",
                ScannerConfig.is_active.is_(True),
            )
            .all()
        )

        if not configs:
            logger.error(
                "run_pocket_pivot_scheduled: no active pocket_pivot ScannerConfig "
                "rows found — add a row to scanner_configs with scanner_type='pocket_pivot', "
                "is_active=true, and a valid universe_id FK."
            )
            raise RuntimeError("no active pocket_pivot scanner configs")

        for cfg in configs:
            if cfg.universe_id is None:
                logger.error(
                    "run_pocket_pivot_scheduled: ScannerConfig id=%s has universe_id=NULL "
                    "— this is a data integrity violation; run the migration "
                    "c7d8e9f0a1b2_add_universe_id_to_scanner_configs to backfill.",
                    cfg.id,
                )
                raise RuntimeError(
                    f"ScannerConfig id={cfg.id} has universe_id=NULL"
                )

            tickers = [
                ms.ticker
                for ms in db.query(MonitoredStock)
                .filter(
                    MonitoredStock.universe_id == cfg.universe_id,
                    MonitoredStock.is_active.is_(True),
                )
                .all()
            ]
            if not tickers:
                logger.warning(
                    "run_pocket_pivot_scheduled: universe_id=%s has no active tickers, "
                    "skipping ScannerConfig id=%s",
                    cfg.universe_id,
                    cfg.id,
                )
                continue

            results = asyncio.run(
                run_pocket_pivot_scan(
                    tickers, db, start_date=event_date, end_date=event_date
                )
            )
            logger.info(
                "pocket_pivot scheduled scan for universe %s on %s: %d events",
                cfg.universe_id,
                event_date,
                len(results),
            )
```

- [ ] **Step 5: Verify tests pass**

```bash
cd /workspace/markethawk/backend && python -m pytest tests/tasks/test_scheduled_scanner_tasks.py -k "TestRunLiquidityHuntScheduledFixed or TestRunPocketPivotScheduledFixed" -v
```

Expected: all tests pass.

- [ ] **Step 6: Run full task test suite to confirm no regressions**

```bash
cd /workspace/markethawk/backend && python -m pytest tests/tasks/ -v
```

Expected: all pass.

- [ ] **Step 7: Validate the backend reloaded cleanly**

```bash
docker-compose logs backend --tail=15
```

Expected: no `ImportError` or `AttributeError` lines. The backend should show the FastAPI startup sequence.

- [ ] **Step 8: Commit**

```bash
cd /workspace/markethawk && git add backend/app/tasks/scanning.py backend/tests/tasks/test_scheduled_scanner_tasks.py && git commit -m "$(cat <<'EOF'
fix(#156): read cfg.universe_id directly in scheduled scanner tasks

Replace cfg.parameters.get("universe_id") with cfg.universe_id in both
run_liquidity_hunt_scheduled and run_pocket_pivot_scheduled. Remove the
warning-and-continue branch. Add loud error logging + RuntimeError when
zero active configs are found or when universe_id is NULL post-migration.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: Add startup validation and wire to worker_ready signal

**Files:**
- Modify: `backend/app/tasks/scanning.py` (add `validate_scheduled_scanner_configs`)
- Modify: `backend/app/core/celery_app.py` (wire `worker_ready` signal)

**Why:** The beat tasks now fail loudly at 02:00 UTC when misconfigured, but that is 24+ hours after a broken deployment. A startup validation that runs when the Celery worker boots surfaces the misconfiguration immediately, in the deployment logs, before any beat tick fires.

- [ ] **Step 1: Write failing tests for the validation function**

Append to `backend/tests/tasks/test_scheduled_scanner_tasks.py`:

```python
# ---------------------------------------------------------------------------
# Task 5 tests: validate_scheduled_scanner_configs startup validation
# ---------------------------------------------------------------------------

class TestValidateScheduledScannerConfigs:
    """Tests for the validate_scheduled_scanner_configs() startup check."""

    def _run_validation(self, liquidity_hunt_configs, pocket_pivot_configs):
        """Invoke validate_scheduled_scanner_configs with mocked DB results."""
        import app.tasks.scanning as scanning_module

        mock_db = MagicMock()

        def _query_side_effect(model):
            q = MagicMock()
            def _filter(*args, **kwargs):
                f = MagicMock()
                # Return different configs depending on which scanner_type is filtered.
                # We inspect the filter args to detect the scanner_type value.
                filter_str = str(args)
                if "liquidity_hunt" in filter_str:
                    f.all.return_value = liquidity_hunt_configs
                else:
                    f.all.return_value = pocket_pivot_configs
                return f
            q.filter.side_effect = _filter
            return q

        mock_db.query.side_effect = _query_side_effect

        with patch("app.tasks.scanning.SessionLocal", return_value=mock_db):
            scanning_module.validate_scheduled_scanner_configs()

    def test_validate_passes_when_both_types_configured(self, caplog):
        """No error logged when both scanner types have a valid config."""
        import logging
        lh = _make_cfg(id=2, universe_id=1, scanner_type="liquidity_hunt")
        pp = _make_cfg(id=4, universe_id=1, scanner_type="pocket_pivot")
        # Keep the AssertionError side-effect on parameters.get intact (do NOT
        # override lh.parameters or pp.parameters here).  validate_scheduled_scanner_configs
        # must never call cfg.parameters.get — if it does, the AssertionError will
        # propagate through the test, making the regression immediately visible.
        with caplog.at_level(logging.ERROR, logger="app.tasks.scanning"):
            self._run_validation([lh], [pp])
        assert not any(r.levelno >= logging.ERROR for r in caplog.records), (
            "validate_scheduled_scanner_configs logged ERROR when it should not have"
        )

    def test_validate_logs_error_for_missing_liquidity_hunt(self, caplog):
        """Error logged when no active liquidity_hunt config exists."""
        import logging
        pp = _make_cfg(id=4, universe_id=1, scanner_type="pocket_pivot")
        # Keep AssertionError guard on parameters.get intact.
        with caplog.at_level(logging.ERROR, logger="app.tasks.scanning"):
            self._run_validation([], [pp])
        assert any("liquidity_hunt" in r.message.lower() for r in caplog.records)

    def test_validate_logs_error_for_missing_pocket_pivot(self, caplog):
        """Error logged when no active pocket_pivot config exists."""
        import logging
        lh = _make_cfg(id=2, universe_id=1, scanner_type="liquidity_hunt")
        # Keep AssertionError guard on parameters.get intact.
        with caplog.at_level(logging.ERROR, logger="app.tasks.scanning"):
            self._run_validation([lh], [])
        assert any("pocket_pivot" in r.message.lower() for r in caplog.records)

    def test_validate_logs_error_when_universe_id_null(self, caplog):
        """Error logged when a config has universe_id=NULL."""
        import logging
        lh = _make_cfg(id=2, universe_id=None, scanner_type="liquidity_hunt")
        pp = _make_cfg(id=4, universe_id=1, scanner_type="pocket_pivot")
        # Keep AssertionError guard on parameters.get intact on both configs.
        with caplog.at_level(logging.ERROR, logger="app.tasks.scanning"):
            self._run_validation([lh], [pp])
        assert any("universe_id" in r.message.lower() for r in caplog.records)

    def test_validate_does_not_raise(self):
        """validate_scheduled_scanner_configs must never raise, even on DB error."""
        import app.tasks.scanning as scanning_module

        with patch(
            "app.tasks.scanning.SessionLocal",
            side_effect=Exception("DB unavailable"),
        ):
            # Should not raise
            scanning_module.validate_scheduled_scanner_configs()


def test_worker_ready_signal_wired_in_celery_app():
    """celery_app.py must import and wire validate_scheduled_scanner_configs."""
    import app.core.celery_app as celery_module
    # Step 1: The handler function must exist at module level (proves the
    # @worker_ready.connect decorator was applied and the name is importable).
    assert hasattr(celery_module, "_on_worker_ready"), (
        "celery_app.py is missing _on_worker_ready — add @worker_ready.connect decorator"
    )
    # Step 2: The signal must have at least one receiver registered.
    # We do NOT inspect receiver string representations — Celery stores receivers as
    # (lookup_key, weakref) tuples; stringifying a weakref does not reliably include
    # the function name and produces false negatives.  A length check is sufficient:
    # importing celery_app registers the handler, so receivers must be non-empty.
    from celery.signals import worker_ready
    assert len(worker_ready.receivers) > 0, (
        "worker_ready signal has no receivers — "
        "wire _on_worker_ready in celery_app.py with @worker_ready.connect"
    )
```

- [ ] **Step 2: Verify tests fail**

```bash
cd /workspace/markethawk/backend && python -m pytest tests/tasks/test_scheduled_scanner_tasks.py -k "TestValidateScheduledScannerConfigs or test_worker_ready_signal_wired" -v
```

Expected: all fail — `validate_scheduled_scanner_configs` does not exist yet.

- [ ] **Step 3: Add `validate_scheduled_scanner_configs` to `scanning.py`**

At the bottom of `backend/app/tasks/scanning.py`, add:

```python
# ---------------------------------------------------------------------------
# Startup validation — wired to worker_ready signal in celery_app.py
# ---------------------------------------------------------------------------

_BEAT_SCHEDULED_SCANNER_TYPES = ["liquidity_hunt", "pocket_pivot"]


def validate_scheduled_scanner_configs() -> None:
    """Check that every beat-scheduled scanner type has at least one active
    ScannerConfig with a non-null universe_id. Logs errors but never raises —
    a crash here would kill the entire worker process rather than surfacing a
    clear, actionable message.

    Called once at Celery worker/beat startup via the worker_ready signal.
    """
    from app.models.scanner_config import ScannerConfig

    db = SessionLocal()
    try:
        for scanner_type in _BEAT_SCHEDULED_SCANNER_TYPES:
            configs = (
                db.query(ScannerConfig)
                .filter(
                    ScannerConfig.scanner_type == scanner_type,
                    ScannerConfig.is_active.is_(True),
                )
                .all()
            )

            if not configs:
                logger.error(
                    "STARTUP VALIDATION FAILED: no active ScannerConfig rows for "
                    "scanner_type='%s'. The '%s' beat task will fail at 02:00 UTC. "
                    "Add a row to scanner_configs with scanner_type='%s', is_active=true, "
                    "and a valid universe_id FK referencing stock_universes(id).",
                    scanner_type,
                    scanner_type,
                    scanner_type,
                )
                continue

            for cfg in configs:
                if cfg.universe_id is None:
                    logger.error(
                        "STARTUP VALIDATION FAILED: ScannerConfig id=%s "
                        "(scanner_type='%s') has universe_id=NULL. "
                        "Run migration c7d8e9f0a1b2_add_universe_id_to_scanner_configs "
                        "to backfill existing rows.",
                        cfg.id,
                        scanner_type,
                    )

    except Exception as exc:
        logger.error(
            "validate_scheduled_scanner_configs: unexpected error during startup "
            "validation — %s. Beat tasks may still fail at runtime.",
            exc,
        )
    finally:
        db.close()
```

- [ ] **Step 4: Wire the validation to `worker_ready` in `celery_app.py`**

In `backend/app/core/celery_app.py`, add the signal handler after the existing imports and before the `beat_schedule` definition:

```python
from celery import Celery
from celery.schedules import crontab
from celery.signals import worker_ready

from app.core.config import settings

celery_app = Celery(
    "stockscanner",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
    include=["app.tasks"],
)


@worker_ready.connect
def _on_worker_ready(sender, **kwargs):
    """Run startup validation when the Celery worker finishes booting."""
    from app.tasks.scanning import validate_scheduled_scanner_configs

    validate_scheduled_scanner_configs()


# News polling runs weekdays only (Mon-Fri).
# ...rest of beat_schedule unchanged...
```

The full file after the edit:

```python
from celery import Celery
from celery.schedules import crontab
from celery.signals import worker_ready

from app.core.config import settings

celery_app = Celery(
    "stockscanner",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
    include=["app.tasks"],
)


@worker_ready.connect
def _on_worker_ready(sender, **kwargs):
    """Run startup validation when the Celery worker finishes booting."""
    from app.tasks.scanning import validate_scheduled_scanner_configs

    validate_scheduled_scanner_configs()


# News polling runs weekdays only (Mon-Fri).
# The task itself enforces the precise 2 AM – 8 PM ET window.
celery_app.conf.beat_schedule = {
    "poll-news-weekdays": {
        "task": "app.tasks.poll_massive_news",
        "schedule": crontab(minute="*", hour="*", day_of_week="1-5"),
    },
    "sync-stock-splits-nightly": {
        "task": "app.tasks.sync_stock_splits",
        "schedule": crontab(minute="0", hour="1"),
    },
    # Auto-trade fill polling — every minute on weekdays during extended market hours
    # (4 AM – 8 PM ET = 9 AM – 1 AM UTC+1, simpler to just run 8-23 UTC Mon-Fri)
    # The task itself is a no-op when there are no submitted/open orders.
    "poll-auto-trade-fills": {
        "task": "app.tasks.poll_auto_trade_fills",
        "schedule": crontab(minute="*", hour="9-23", day_of_week="1-5"),
    },
    # Liquidity hunt scan: runs at 02:00 UTC Mon–Fri
    # After-market closes 20:00 ET; 02:00 UTC = 21:00 EST (winter) / 22:00 EDT (summer) — always post-close.
    "run-liquidity-hunt-scan-evening": {
        "task": "app.tasks.run_liquidity_hunt_scheduled",
        "schedule": crontab(minute="0", hour="2", day_of_week="1-5"),
    },
    # Pocket pivot scan: runs at 02:00 UTC Mon–Fri (same post-close slot as liquidity hunt)
    "run-pocket-pivot-scan-evening": {
        "task": "app.tasks.run_pocket_pivot_scheduled",
        "schedule": crontab(minute="0", hour="2", day_of_week="1-5"),
    },
    "analyze-signal-features-nightly": {
        "task": "app.tasks.analyze_signal_features",
        "schedule": crontab(minute="0", hour="11", day_of_week="1-5"),
    },
    # Tweet monitor: trigger every 45 seconds (expires in 40s to prevent pile-up)
    "trigger-tweet-monitor": {
        "task": "app.tasks.trigger_tweet_monitor",
        "schedule": 45.0,
        "options": {"expires": 40},
    },
}
```

- [ ] **Step 5: Verify all Task 5 tests pass**

```bash
cd /workspace/markethawk/backend && python -m pytest tests/tasks/test_scheduled_scanner_tasks.py -k "TestValidateScheduledScannerConfigs or test_worker_ready_signal_wired" -v
```

Expected: all pass.

- [ ] **Step 6: Run the full test file to confirm no regressions**

```bash
cd /workspace/markethawk/backend && python -m pytest tests/tasks/ -v
```

Expected: all pass.

- [ ] **Step 7: Validate the backend reloaded cleanly after the celery_app.py change**

```bash
docker-compose logs backend --tail=15
```

Expected: no `ImportError` or `AttributeError` lines.

- [ ] **Step 8: Confirm validation runs at worker startup**

```bash
docker-compose restart celery-worker 2>/dev/null || docker-compose restart backend
docker-compose logs celery-worker --tail=30 2>/dev/null || docker-compose logs backend --tail=30
```

Expected: logs contain a line from `validate_scheduled_scanner_configs`. If scanner configs are in place with `universe_id=1`, no ERROR lines appear. If configs are missing, ERROR lines appear immediately at startup (the intended behavior).

- [ ] **Step 9: Commit**

```bash
cd /workspace/markethawk && git add backend/app/tasks/scanning.py backend/app/core/celery_app.py backend/tests/tasks/test_scheduled_scanner_tasks.py && git commit -m "$(cat <<'EOF'
feat(#156): add startup validation for beat-scheduled scanner configs

Add validate_scheduled_scanner_configs() to scanning.py — checks that
every beat-scheduled scanner type (liquidity_hunt, pocket_pivot) has at
least one active ScannerConfig with a non-null universe_id. Logs loud
errors on misconfiguration but never raises (worker stays up). Wire via
@worker_ready.connect signal in celery_app.py so validation runs on
every worker/beat boot.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```
