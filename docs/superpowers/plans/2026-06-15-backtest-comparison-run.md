---
title: "Backtest Comparison Run: 5 Scanners × Representative Strategies"
date: 2026-06-15
issue: 302
spec: docs/superpowers/specs/2026-06-13-backtest-comparison-run-design.md
author: dark-factory
---

# Goal

Implement `backend/scripts/run_backtest_comparison.py` — a backend management script
that fans out 15 backtest runs (5 scanners × 3 strategy profiles) via the #301 harness,
polls for completion, renders a committed Markdown comparison table, and commits it.

The committed table at `backend/docs/backtest/comparison-{end_date}.md` is the
primary deliverable (spec acceptance criterion). No new DB models, no API endpoints,
no Celery tasks, no migrations.

---

# Architecture

```
backend/scripts/run_backtest_comparison.py
  ├── _default_date_range()        → (start, end) trailing 12 months
  ├── _parse_args()                → argparse.Namespace
  ├── _seed_strategies(db)         → list[int]  (get-or-create 3 TradingStrategy rows)
  ├── _parse_run_uuids(run_uuids)  → list[uuid.UUID]  (str → UUID for Postgres compat.)
  ├── _enqueue_runs(...)           → list[BacktestRun]  (15 runs, BacktestRun + Celery)
  ├── _poll_until_done(...)        → list[BacktestRun]  (poll 5s interval, 30-min timeout)
  ├── _render_markdown(...)        → str  (YAML frontmatter + 5 metric tables + Findings)
  ├── _resolve_universe(db, id)    → (name, ticker_count)
  └── main()                      → orchestrates all above; writes output file
```

The script runs inside the backend container (`docker-compose exec backend python
scripts/run_backtest_comparison.py`) where `app.*` imports resolve directly.
`python -m pytest` adds the CWD (`/app`) to `sys.path`, so
`from scripts.run_backtest_comparison import ...` resolves automatically.

**Output path:** `backend/docs/backtest/comparison-{end_date}.md`
(= `/app/docs/backtest/` inside the container = `backend/docs/backtest/` in the host repo).
The spec's `docs/backtest/` refers to this path — the comparison doc lives inside `backend/`
because the script runs in the backend container and that is the only writable location.

**Dev note:** The override mounts `./backend:/app:ro` (read-only). Run without the
override to write output: `docker-compose -f docker-compose.yml exec backend
python scripts/run_backtest_comparison.py`.

---

# Tech Stack

- Python 3.11, SQLAlchemy sync `Session` (`SessionLocal`)
- Celery (`run_backtest.delay(...)` from `app.tasks.backtest`)
- `BacktestRun` model, `TradingStrategy` model (both from #301)
- pytest unit tests (MagicMock db; no testcontainers)

---

# File Structure

| File | Action | Description |
|------|--------|-------------|
| `backend/scripts/run_backtest_comparison.py` | **Create** | Main comparison script |
| `backend/tests/scripts/__init__.py` | **Create** | Package marker for new test sub-package |
| `backend/tests/scripts/test_run_backtest_comparison.py` | **Create** | Unit tests |
| `backend/docs/backtest/comparison-{end_date}.md` | **Create (Task 6)** | Live comparison output |

`backend/scripts/__init__.py` already exists — no change needed.

**Path convention:** Pytest commands run from inside the container (WORKDIR `/app`).
Use `tests/scripts/...` for pytest paths; `backend/tests/scripts/...` for `git add`.

---

# Task 1 — Scaffold: CLI args + date-range helper

**Files:** `backend/scripts/run_backtest_comparison.py` (create),
`backend/tests/scripts/__init__.py` (create),
`backend/tests/scripts/test_run_backtest_comparison.py` (create)

## Step 1.1 — Create `backend/tests/scripts/__init__.py` and write failing tests

Create `backend/tests/scripts/__init__.py` — empty file (package marker):

```python
```

Create `backend/tests/scripts/test_run_backtest_comparison.py`:

```python
"""Unit tests for run_backtest_comparison.py helpers."""
import uuid as _uuid_mod
from datetime import date
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Date-range helpers
# ---------------------------------------------------------------------------

def test_default_date_range_mid_year():
    # Today=2026-06-15 → start=2025-06-01, end=2026-05-31
    with patch("scripts.run_backtest_comparison._today", return_value=date(2026, 6, 15)):
        from scripts.run_backtest_comparison import _default_date_range
        start, end = _default_date_range()
    assert start == date(2025, 6, 1)
    assert end == date(2026, 5, 31)


def test_default_date_range_january_wraps_year():
    # Today=2026-01-10 → start=2025-01-01, end=2025-12-31
    with patch("scripts.run_backtest_comparison._today", return_value=date(2026, 1, 10)):
        from scripts.run_backtest_comparison import _default_date_range
        start, end = _default_date_range()
    assert start == date(2025, 1, 1)
    assert end == date(2025, 12, 31)


# ---------------------------------------------------------------------------
# CLI arg parsing
# ---------------------------------------------------------------------------

def test_parse_args_defaults():
    from scripts.run_backtest_comparison import _parse_args
    args = _parse_args([])
    assert args.universe_id == 1
    assert args.max_hold == 10
    assert args.start is None
    assert args.end is None


def test_parse_args_overrides():
    from scripts.run_backtest_comparison import _parse_args
    args = _parse_args([
        "--start", "2025-01-01",
        "--end", "2025-12-31",
        "--universe-id", "3",
        "--max-hold", "20",
    ])
    assert args.start == date(2025, 1, 1)
    assert args.end == date(2025, 12, 31)
    assert args.universe_id == 3
    assert args.max_hold == 20
```

## Step 1.2 — Verify tests fail

```bash
docker-compose exec backend python -m pytest tests/scripts/test_run_backtest_comparison.py -v --no-cov 2>&1 | tail -8
# Expected: ERROR — ModuleNotFoundError: No module named 'scripts.run_backtest_comparison'
```

## Step 1.3 — Implement the scaffold

Create `backend/scripts/run_backtest_comparison.py`:

```python
#!/usr/bin/env python3
"""
Backtest comparison run: 5 scanners × 3 strategy profiles.

Usage (inside the backend container):
  python scripts/run_backtest_comparison.py [--start YYYY-MM-DD] [--end YYYY-MM-DD]
                                             [--universe-id N] [--max-hold N]

Output:
  backend/docs/backtest/comparison-{end_date}.md
  (mounted read-only in dev; run without override: docker-compose -f docker-compose.yml exec backend ...)
"""
import argparse
import calendar
import sys
import time
import uuid as _uuid
from datetime import date
from pathlib import Path

SCANNERS = [
    "trend_pullback",
    "oversold_bounce",
    "pocket_pivot",
    "pre_market_volume_spike",
    "liquidity_hunt",
]

STRATEGY_DEFINITIONS = [
    {
        "name": "backtest-tight-2pct-2to1",
        "entry_type": "market",
        "stop_pct": 2.0,
        "risk_reward_ratio": 2.0,
        "limit_offset_pct": 0.0,
        "allowed_sessions": ["regular"],
    },
    {
        "name": "backtest-loose-4pct-1.5to1",
        "entry_type": "market",
        "stop_pct": 4.0,
        "risk_reward_ratio": 1.5,
        "limit_offset_pct": 0.0,
        "allowed_sessions": ["regular"],
    },
    {
        "name": "backtest-pullback-limit-2pct-2to1",
        "entry_type": "limit",
        "stop_pct": 2.0,
        "risk_reward_ratio": 2.0,
        "limit_offset_pct": -0.5,
        "allowed_sessions": ["regular", "pre"],
    },
]

POLL_INTERVAL_SECONDS = 5
TIMEOUT_SECONDS = 30 * 60  # 30 minutes
LOW_SAMPLE_THRESHOLD = 20


def _today() -> date:
    return date.today()


def _default_date_range() -> tuple[date, date]:
    """Return (start, end) for trailing 12 months ending at last completed month."""
    today = _today()
    first_this_month = today.replace(day=1)
    if first_this_month.month == 1:
        prior_month = first_this_month.replace(year=first_this_month.year - 1, month=12)
    else:
        prior_month = first_this_month.replace(month=first_this_month.month - 1)
    end = prior_month.replace(
        day=calendar.monthrange(prior_month.year, prior_month.month)[1]
    )
    start = today.replace(year=today.year - 1, day=1)
    return start, end


def _parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Run 5×3 backtest comparison and write a Markdown report."
    )
    parser.add_argument("--start", type=date.fromisoformat, default=None,
                        help="Start date YYYY-MM-DD (default: 12 months ago, first of month)")
    parser.add_argument("--end", type=date.fromisoformat, default=None,
                        help="End date YYYY-MM-DD (default: last day of prior month)")
    parser.add_argument("--universe-id", type=int, default=1, dest="universe_id",
                        help="StockUniverse id (default: 1)")
    parser.add_argument("--max-hold", type=int, default=10, dest="max_hold",
                        help="Max hold sessions per trade (default: 10)")
    return parser.parse_args(argv)
```

## Step 1.4 — Verify tests pass

```bash
docker-compose exec backend python -m pytest \
  tests/scripts/test_run_backtest_comparison.py::test_default_date_range_mid_year \
  tests/scripts/test_run_backtest_comparison.py::test_default_date_range_january_wraps_year \
  tests/scripts/test_run_backtest_comparison.py::test_parse_args_defaults \
  tests/scripts/test_run_backtest_comparison.py::test_parse_args_overrides \
  -v --no-cov
# Expected: 4 passed
```

## Step 1.5 — Commit

```bash
git add backend/scripts/run_backtest_comparison.py \
        backend/tests/scripts/__init__.py \
        backend/tests/scripts/test_run_backtest_comparison.py
git commit -m "feat(scripts): scaffold run_backtest_comparison CLI + date-range helper (#302)"
```

---

# Task 2 — Strategy seed (get-or-create)

**Files:** `backend/scripts/run_backtest_comparison.py` (append),
`backend/tests/scripts/test_run_backtest_comparison.py` (append)

## Step 2.1 — Write failing tests

Append to `backend/tests/scripts/test_run_backtest_comparison.py`:

```python
# ---------------------------------------------------------------------------
# Strategy seed
# ---------------------------------------------------------------------------

def _make_db_not_found():
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = None
    return db


def _stub_strategy(name: str, id_: int):
    s = MagicMock()
    s.id = id_
    s.name = name
    return s


def test_seed_strategies_creates_all_three_when_absent():
    from scripts.run_backtest_comparison import _seed_strategies
    db = _make_db_not_found()
    ids = _seed_strategies(db)
    assert len(ids) == 3
    assert db.add.call_count == 3
    assert db.flush.call_count == 3


def test_seed_strategies_idempotent_when_rows_exist():
    from scripts.run_backtest_comparison import STRATEGY_DEFINITIONS, _seed_strategies
    db = MagicMock()
    stubs = [_stub_strategy(d["name"], i + 10) for i, d in enumerate(STRATEGY_DEFINITIONS)]
    db.query.return_value.filter.return_value.first.side_effect = stubs
    ids = _seed_strategies(db)
    assert ids == [10, 11, 12]
    db.add.assert_not_called()


def test_seed_strategies_returns_three_ids():
    from scripts.run_backtest_comparison import _seed_strategies
    db = _make_db_not_found()
    ids = _seed_strategies(db)
    assert len(ids) == 3
    assert all(isinstance(i, int) for i in ids)
```

## Step 2.2 — Verify tests fail

```bash
docker-compose exec backend python -m pytest tests/scripts/test_run_backtest_comparison.py -k "seed" -v --no-cov 2>&1 | tail -5
# Expected: AttributeError: module 'scripts.run_backtest_comparison' has no attribute '_seed_strategies'
```

## Step 2.3 — Implement `_seed_strategies`

Append to `backend/scripts/run_backtest_comparison.py`:

```python
def _seed_strategies(db) -> list[int]:
    """Get-or-create the 3 backtest TradingStrategy rows. Returns list of IDs in definition order."""
    from app.models.trading_strategy import TradingStrategy

    ids = []
    for defn in STRATEGY_DEFINITIONS:
        row = (
            db.query(TradingStrategy)
            .filter(TradingStrategy.name == defn["name"])
            .first()
        )
        if row is None:
            row = TradingStrategy(
                name=defn["name"],
                entry_type=defn["entry_type"],
                stop_pct=defn["stop_pct"],
                risk_reward_ratio=defn["risk_reward_ratio"],
                limit_offset_pct=defn["limit_offset_pct"],
                allowed_sessions=defn["allowed_sessions"],
                paper_mode=True,
                requires_approval=False,
                risk_per_trade_pct=1.0,
                direction="long_only",
                max_trades_per_day=99,
                max_concurrent_positions=99,
            )
            db.add(row)
            db.flush()  # populate row.id before moving to next strategy
        ids.append(row.id)
    return ids
```

## Step 2.4 — Verify tests pass

```bash
docker-compose exec backend python -m pytest tests/scripts/test_run_backtest_comparison.py -k "seed" -v --no-cov
# Expected: 3 passed
```

## Step 2.5 — Commit

```bash
git add backend/scripts/run_backtest_comparison.py backend/tests/scripts/test_run_backtest_comparison.py
git commit -m "feat(scripts): add strategy get-or-create seed with idempotency (#302)"
```

---

# Task 3 — UUID helper, enqueue 15 runs, poll for completion

**Files:** `backend/scripts/run_backtest_comparison.py` (append),
`backend/tests/scripts/test_run_backtest_comparison.py` (append)

## Step 3.1 — Write failing tests

Append to `backend/tests/scripts/test_run_backtest_comparison.py`:

```python
# ---------------------------------------------------------------------------
# UUID conversion (Postgres UUID(as_uuid=True) requires UUID objects, not strings)
# ---------------------------------------------------------------------------

def test_parse_run_uuids_converts_strings():
    from scripts.run_backtest_comparison import _parse_run_uuids
    uuid_str = "12345678-1234-5678-1234-567812345678"
    result = _parse_run_uuids([uuid_str])
    assert result == [_uuid_mod.UUID(uuid_str)]
    assert all(isinstance(u, _uuid_mod.UUID) for u in result)


def test_parse_run_uuids_accepts_uuid_objects():
    from scripts.run_backtest_comparison import _parse_run_uuids
    uid = _uuid_mod.uuid4()
    result = _parse_run_uuids([uid])
    assert result == [uid]


# ---------------------------------------------------------------------------
# Enqueue + poll
# ---------------------------------------------------------------------------

def test_enqueue_runs_creates_15_rows():
    from scripts.run_backtest_comparison import SCANNERS, _enqueue_runs

    db = MagicMock()
    created_runs = []

    def capturing_add(obj):
        obj.id = None
        created_runs.append(obj)

    def fake_flush():
        for run in created_runs:
            if run.id is None:
                run.id = len(created_runs)

    db.add.side_effect = capturing_add
    db.flush.side_effect = fake_flush
    db.refresh.side_effect = lambda obj: None

    with patch("scripts.run_backtest_comparison.run_backtest") as mock_task:
        mock_task.delay.return_value.id = "celery-id"
        runs = _enqueue_runs(
            db=db,
            strategy_ids=[1, 2, 3],
            universe_id=1,
            start_date=date(2025, 6, 1),
            end_date=date(2026, 5, 31),
            max_hold_sessions=10,
        )

    assert len(runs) == 15  # 5 scanners × 3 strategies
    dispatched_scanners = [c.kwargs["scanner_type"] for c in mock_task.delay.call_args_list]
    for scanner in SCANNERS:
        assert dispatched_scanners.count(scanner) == 3


def test_poll_returns_when_all_completed():
    from scripts.run_backtest_comparison import _poll_until_done

    db = MagicMock()
    runs = [MagicMock(uuid=_uuid_mod.uuid4(), status="completed") for _ in range(15)]
    db.query.return_value.filter.return_value.all.return_value = runs

    run_uuids = [str(r.uuid) for r in runs]
    result = _poll_until_done(db=db, run_uuids=run_uuids, timeout=30)
    assert len(result) == 15


def test_poll_exits_on_failed_run():
    from scripts.run_backtest_comparison import _poll_until_done

    db = MagicMock()
    runs = [MagicMock(uuid=_uuid_mod.uuid4(), status="completed") for _ in range(14)]
    failed = MagicMock(uuid=_uuid_mod.uuid4(), status="failed",
                       scanner_type="trend_pullback", error_message="crash")
    runs.append(failed)
    db.query.return_value.filter.return_value.all.return_value = runs

    with pytest.raises(SystemExit):
        _poll_until_done(db=db, run_uuids=[str(r.uuid) for r in runs], timeout=30)


def test_poll_exits_on_timeout():
    from scripts.run_backtest_comparison import _poll_until_done

    db = MagicMock()
    stuck = [MagicMock(uuid=_uuid_mod.uuid4(), status="running")]
    db.query.return_value.filter.return_value.all.return_value = stuck

    # First monotonic() call sets the deadline; second is the in-loop comparison
    with patch("time.sleep"), \
         patch("time.monotonic", side_effect=[0.0, 3601.0]):
        with pytest.raises(SystemExit):
            _poll_until_done(db=db, run_uuids=[str(stuck[0].uuid)], timeout=1)
```

## Step 3.2 — Verify tests fail

```bash
docker-compose exec backend python -m pytest tests/scripts/test_run_backtest_comparison.py -k "uuid or enqueue or poll" -v --no-cov 2>&1 | tail -5
# Expected: AttributeError — _parse_run_uuids / _enqueue_runs / _poll_until_done not found
```

## Step 3.3 — Implement `_parse_run_uuids`, `_enqueue_runs`, and `_poll_until_done`

Append to `backend/scripts/run_backtest_comparison.py`:

```python
def _parse_run_uuids(run_uuids: list) -> list:
    """Convert any mix of str/UUID to UUID objects.

    BacktestRun.uuid is UUID(as_uuid=True); Postgres requires uuid.UUID objects
    (not strings) in .in_() queries, matching the convention in routers/backtest.py.
    """
    return [_uuid.UUID(str(u)) for u in run_uuids]


def _enqueue_runs(
    db,
    strategy_ids: list[int],
    universe_id: int,
    start_date: date,
    end_date: date,
    max_hold_sessions: int,
) -> list:
    """Create 15 BacktestRun rows (5 scanners × 3 strategies) and dispatch Celery tasks."""
    from app.models.backtest_run import BacktestRun
    from app.tasks.backtest import run_backtest
    from app.utils.time import utc_now

    runs = []
    for scanner_type in SCANNERS:
        for strategy_id in strategy_ids:
            run = BacktestRun(
                uuid=_uuid.uuid4(),
                scanner_type=scanner_type,
                strategy_id=strategy_id,
                universe_id=universe_id,
                start_date=start_date,
                end_date=end_date,
                max_hold_sessions=max_hold_sessions,
                status="queued",
                created_at=utc_now(),
            )
            db.add(run)
            db.flush()    # obtain run.id before dispatching
            db.refresh(run)

            async_result = run_backtest.delay(
                run_id=run.id,
                scanner_type=scanner_type,
                strategy_id=strategy_id,
                universe_id=universe_id,
                start_date_iso=start_date.isoformat(),
                end_date_iso=end_date.isoformat(),
                max_hold_sessions=max_hold_sessions,
            )
            run.celery_task_id = async_result.id
            runs.append(run)

    db.commit()
    return runs


def _poll_until_done(db, run_uuids: list, timeout: int = TIMEOUT_SECONDS) -> list:
    """Poll BacktestRun.status until all reach 'completed'.

    Calls sys.exit(1) if any run fails or the timeout is exceeded.
    """
    from app.models.backtest_run import BacktestRun

    uuid_objs = _parse_run_uuids(run_uuids)  # str → UUID for Postgres UUID(as_uuid=True)
    deadline = time.monotonic() + timeout
    total = len(run_uuids)

    while True:
        db.expire_all()
        runs = (
            db.query(BacktestRun)
            .filter(BacktestRun.uuid.in_(uuid_objs))
            .all()
        )
        failed = [r for r in runs if r.status == "failed"]
        if failed:
            for r in failed:
                print(
                    f"FAILED: {r.scanner_type} — {r.error_message}",
                    file=sys.stderr,
                )
            sys.exit(1)

        done = [r for r in runs if r.status == "completed"]
        print(f"Progress: {len(done)}/{total} completed", flush=True)
        if len(done) == total:
            return runs

        if time.monotonic() > deadline:
            print(
                f"TIMEOUT: {len(done)}/{total} completed after {timeout}s",
                file=sys.stderr,
            )
            sys.exit(1)

        time.sleep(POLL_INTERVAL_SECONDS)
```

## Step 3.4 — Verify tests pass

```bash
docker-compose exec backend python -m pytest tests/scripts/test_run_backtest_comparison.py -k "uuid or enqueue or poll" -v --no-cov
# Expected: 7 passed (2 uuid + 1 enqueue + 4 poll)
```

## Step 3.5 — Commit

```bash
git add backend/scripts/run_backtest_comparison.py backend/tests/scripts/test_run_backtest_comparison.py
git commit -m "feat(scripts): add UUID helper, run enqueue, and completion poll (#302)"
```

---

# Task 4 — Stats collection + Markdown rendering + `main()`

**Files:** `backend/scripts/run_backtest_comparison.py` (append),
`backend/tests/scripts/test_run_backtest_comparison.py` (append)

## Step 4.1 — Write failing tests

Append to `backend/tests/scripts/test_run_backtest_comparison.py`:

```python
# ---------------------------------------------------------------------------
# Markdown rendering
# ---------------------------------------------------------------------------

def _full_stats(expectancy_r=0.3, total_trades=30):
    from scripts.run_backtest_comparison import SCANNERS, STRATEGY_DEFINITIONS
    stats = {}
    for scanner in SCANNERS:
        for defn in STRATEGY_DEFINITIONS:
            stats[(scanner, defn["name"])] = {
                "total_trades": total_trades,
                "win_rate": 0.55,
                "profit_factor": 1.8,
                "expectancy_r": expectancy_r,
                "max_drawdown_r": -2.5,
            }
    return stats


def test_render_markdown_contains_all_section_headers():
    from scripts.run_backtest_comparison import _render_markdown
    md = _render_markdown(
        stats=_full_stats(),
        universe_id=1,
        universe_name="Main Liquid Universe",
        ticker_count=50,
        start_date=date(2025, 6, 1),
        end_date=date(2026, 5, 31),
        max_hold_sessions=10,
    )
    assert "## Expectancy (R)" in md
    assert "## Profit Factor" in md
    assert "## Win Rate (%)" in md
    assert "## Max Drawdown (%)" in md
    assert "## Trade Count" in md
    assert "## Findings" in md
    assert "universe_id:" in md        # YAML frontmatter present
    assert "generated_at:" in md


def test_render_markdown_low_sample_flag():
    from scripts.run_backtest_comparison import _render_markdown
    md = _render_markdown(
        stats=_full_stats(total_trades=5),  # below LOW_SAMPLE_THRESHOLD (20)
        universe_id=1,
        universe_name="Test",
        ticker_count=10,
        start_date=date(2025, 6, 1),
        end_date=date(2026, 5, 31),
        max_hold_sessions=10,
    )
    assert "⚠*" in md


def test_render_markdown_no_low_sample_flag_above_threshold():
    from scripts.run_backtest_comparison import _render_markdown
    md = _render_markdown(
        stats=_full_stats(total_trades=25),  # above threshold
        universe_id=1,
        universe_name="Test",
        ticker_count=10,
        start_date=date(2025, 6, 1),
        end_date=date(2026, 5, 31),
        max_hold_sessions=10,
    )
    assert "⚠*" not in md


def test_render_markdown_findings_positive_expectancy():
    from scripts.run_backtest_comparison import SCANNERS, STRATEGY_DEFINITIONS, _render_markdown
    # Only trend_pullback × tight-2pct-2to1 has positive expectancy with enough trades
    stats = {}
    for scanner in SCANNERS:
        for defn in STRATEGY_DEFINITIONS:
            if scanner == "trend_pullback" and defn["name"] == "backtest-tight-2pct-2to1":
                stats[(scanner, defn["name"])] = {
                    "total_trades": 30, "win_rate": 0.6, "profit_factor": 2.0,
                    "expectancy_r": 0.5, "max_drawdown_r": -1.0,
                }
            else:
                stats[(scanner, defn["name"])] = {
                    "total_trades": 30, "win_rate": 0.4, "profit_factor": 0.8,
                    "expectancy_r": -0.2, "max_drawdown_r": -3.0,
                }
    md = _render_markdown(
        stats=stats,
        universe_id=1, universe_name="Test", ticker_count=50,
        start_date=date(2025, 6, 1), end_date=date(2026, 5, 31), max_hold_sessions=10,
    )
    findings_section = md.split("## Findings")[1]
    assert "trend_pullback" in findings_section
    assert "backtest-tight-2pct-2to1" in findings_section


def test_render_markdown_findings_none_positive():
    from scripts.run_backtest_comparison import _render_markdown
    md = _render_markdown(
        stats=_full_stats(expectancy_r=-0.1),
        universe_id=1, universe_name="Test", ticker_count=10,
        start_date=date(2025, 6, 1), end_date=date(2026, 5, 31), max_hold_sessions=10,
    )
    assert "No combos with positive expectancy" in md


def test_render_markdown_pre_market_note_present():
    from scripts.run_backtest_comparison import _render_markdown
    md = _render_markdown(
        stats=_full_stats(),
        universe_id=1, universe_name="Test", ticker_count=10,
        start_date=date(2025, 6, 1), end_date=date(2026, 5, 31), max_hold_sessions=10,
    )
    assert "pre_market_volume_spike" in md.split("## Expectancy")[0]  # note in preamble
```

## Step 4.2 — Verify tests fail

```bash
docker-compose exec backend python -m pytest tests/scripts/test_run_backtest_comparison.py -k "render" -v --no-cov 2>&1 | tail -5
# Expected: AttributeError — _render_markdown not found
```

## Step 4.3 — Implement `_resolve_universe`, `_render_markdown`, and `main`

Append to `backend/scripts/run_backtest_comparison.py`:

```python
def _resolve_universe(db, universe_id: int) -> tuple[str, int]:
    """Return (name, ticker_count) for the given universe. Exits on not found."""
    from app.models.stock_universe import StockUniverse
    from app.models.stock_universe_ticker import StockUniverseTicker

    universe = db.query(StockUniverse).filter(StockUniverse.id == universe_id).first()
    if universe is None:
        print(f"ERROR: StockUniverse id={universe_id} not found", file=sys.stderr)
        sys.exit(1)
    count = (
        db.query(StockUniverseTicker)
        .filter(StockUniverseTicker.universe_id == universe_id)
        .count()
    )
    return universe.name, count


def _render_markdown(
    stats: dict,
    universe_id: int,
    universe_name: str,
    ticker_count: int,
    start_date: date,
    end_date: date,
    max_hold_sessions: int,
) -> str:
    """Render the full comparison Markdown document."""
    from datetime import datetime, timezone

    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    strategy_slugs = [d["name"] for d in STRATEGY_DEFINITIONS]
    short_slugs = ["tight-2pct-2to1", "loose-4pct-1.5to1", "pullback-limit"]

    lines: list[str] = []

    # YAML frontmatter
    lines += [
        "---",
        f"universe_id: {universe_id}",
        f"universe_name: {universe_name}",
        f"ticker_count: {ticker_count}",
        f"start_date: {start_date}",
        f"end_date: {end_date}",
        f"max_hold_sessions: {max_hold_sessions}",
        "strategies:",
        f"  {strategy_slugs[0]}: {{entry: market, stop_pct: 2.0, rr: 2.0, sessions: [regular]}}",
        f"  {strategy_slugs[1]}: {{entry: market, stop_pct: 4.0, rr: 1.5, sessions: [regular]}}",
        (
            f"  {strategy_slugs[2]}: {{entry: limit, limit_offset_pct: -0.5,"
            " stop_pct: 2.0, rr: 2.0, sessions: [regular, pre]}}"
        ),
        f"generated_at: {generated_at}",
        'harness_issue: "301"',
        "---",
        "",
        (
            "> **Note — `pre_market_volume_spike`**: this scanner fires on intraday"
            " pre-market minute bars."
        ),
        (
            "> Where those are absent in the replay window the harness uses stored"
            " `ScannerEvent` rows only."
        ),
        "> Interpret its row against `trade_count`; a low count indicates limited"
        " historical data coverage.",
        "",
    ]

    header_row = "| Scanner | " + " | ".join(short_slugs) + " |"
    sep_row = "|---------|" + "|".join(["---"] * len(short_slugs)) + "|"

    def _cell(metric_key: str, fmt_str: str, scanner: str, slug: str) -> str:
        s = stats.get((scanner, slug), {})
        v = s.get(metric_key)
        if v is None:
            cell = "N/A"
        else:
            cell = format(v, fmt_str)
        trades = s.get("total_trades") or 0
        if trades < LOW_SAMPLE_THRESHOLD:
            cell += " ⚠*"
        return cell

    def _metric_table(metric_key: str, fmt_str: str, heading: str) -> list[str]:
        rows = [f"## {heading}", "", header_row, sep_row]
        for scanner in SCANNERS:
            cells = [_cell(metric_key, fmt_str, scanner, slug) for slug in strategy_slugs]
            rows.append(f"| {scanner} | " + " | ".join(cells) + " |")
        rows.append("")
        return rows

    lines += _metric_table("expectancy_r", ".3f", "Expectancy (R)")
    lines += _metric_table("profit_factor", ".2f", "Profit Factor")
    lines += _metric_table("win_rate", ".1%", "Win Rate (%)")
    lines += _metric_table("max_drawdown_r", ".2f", "Max Drawdown (%)")

    # Trade count table — flag low-sample cells; count displayed raw
    lines += ["## Trade Count", "", header_row, sep_row]
    for scanner in SCANNERS:
        cells = []
        for slug in strategy_slugs:
            s = stats.get((scanner, slug), {})
            trades = s.get("total_trades")
            if trades is None:
                cells.append("N/A")
            elif trades < LOW_SAMPLE_THRESHOLD:
                cells.append(f"{trades} ⚠*")
            else:
                cells.append(str(trades))
        lines.append(f"| {scanner} | " + " | ".join(cells) + " |")
    lines += ["", "⚠ Cells with fewer than 20 trades are marked with *.", ""]

    # Findings
    lines += ["## Findings", ""]
    positives = []
    best: tuple | None = None
    best_exp: float | None = None

    for scanner in SCANNERS:
        for slug in strategy_slugs:
            s = stats.get((scanner, slug), {})
            exp = s.get("expectancy_r")
            trades = s.get("total_trades") or 0
            if exp is not None and exp > 0 and trades >= LOW_SAMPLE_THRESHOLD:
                positives.append(
                    f"- **{scanner}** / `{slug}` —"
                    f" expectancy_r={exp:.3f} R ({trades} trades)"
                )
                if best_exp is None or exp > best_exp:
                    best_exp = exp
                    best = (scanner, slug, exp, trades)

    if positives:
        lines.append("Combos with positive expectancy (expectancy_r > 0, trade_count ≥ 20):")
        lines += positives
    else:
        lines.append("No combos with positive expectancy and ≥ 20 trades.")

    lines.append("")
    if best:
        s, slug, exp, trades = best
        lines.append(
            f"Best combo: **{s}** / `{slug}`"
            f" (expectancy_r = {exp:.2f} R, {trades} trades)"
        )
    else:
        lines.append("Best combo: N/A")

    all_negative = [
        scanner for scanner in SCANNERS
        if all(
            (stats.get((scanner, slug), {}).get("expectancy_r") or 0) <= 0
            for slug in strategy_slugs
        )
    ]
    lines.append("")
    if all_negative:
        lines.append(
            f"Scanners negative across all strategies: {', '.join(all_negative)}"
        )
    else:
        lines.append("Scanners negative across all strategies: none")

    return "\n".join(lines) + "\n"


def main():
    args = _parse_args()

    if args.start and args.end:
        start_date, end_date = args.start, args.end
    else:
        start_date, end_date = _default_date_range()

    from app.core.database import SessionLocal

    db = SessionLocal()
    try:
        print("Seeding strategies...")
        strategy_ids = _seed_strategies(db)
        print(f"  Strategy IDs: {strategy_ids}")

        universe_name, ticker_count = _resolve_universe(db, args.universe_id)
        print(f"Universe: {universe_name} ({ticker_count} tickers)")
        print(f"Date range: {start_date} → {end_date}")
        print("Enqueueing 15 backtest runs (5 scanners × 3 strategies)...")

        runs = _enqueue_runs(
            db=db,
            strategy_ids=strategy_ids,
            universe_id=args.universe_id,
            start_date=start_date,
            end_date=end_date,
            max_hold_sessions=args.max_hold,
        )
        run_uuids = [str(r.uuid) for r in runs]
        print(f"Enqueued {len(run_uuids)} runs. Polling (timeout=30 min)...")

        completed_runs = _poll_until_done(db=db, run_uuids=run_uuids)

        id_to_slug = {
            sid: defn["name"]
            for sid, defn in zip(strategy_ids, STRATEGY_DEFINITIONS)
        }
        stats: dict = {}
        for run in completed_runs:
            slug = id_to_slug.get(run.strategy_id)
            if slug:
                stats[(run.scanner_type, slug)] = {
                    "total_trades": run.total_trades,
                    "win_rate": run.win_rate,
                    "profit_factor": run.profit_factor,
                    "expectancy_r": run.expectancy_r,
                    "max_drawdown_r": run.max_drawdown_r,
                }

        md = _render_markdown(
            stats=stats,
            universe_id=args.universe_id,
            universe_name=universe_name,
            ticker_count=ticker_count,
            start_date=start_date,
            end_date=end_date,
            max_hold_sessions=args.max_hold,
        )

        # Output at backend/docs/backtest/ (= /app/docs/backtest/ in container)
        out_dir = Path(__file__).parent.parent / "docs" / "backtest"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"comparison-{end_date}.md"
        out_path.write_text(md, encoding="utf-8")
        print(f"\nWritten: {out_path}")

    finally:
        db.close()


if __name__ == "__main__":
    main()
```

## Step 4.4 — Verify rendering tests pass

```bash
docker-compose exec backend python -m pytest tests/scripts/test_run_backtest_comparison.py -k "render" -v --no-cov
# Expected: 6 passed
```

## Step 4.5 — Run the full script test suite

```bash
docker-compose exec backend python -m pytest tests/scripts/test_run_backtest_comparison.py -v --no-cov
# Expected: all 15 tests pass
```

## Step 4.6 — Commit

```bash
git add backend/scripts/run_backtest_comparison.py backend/tests/scripts/test_run_backtest_comparison.py
git commit -m "feat(scripts): add Markdown renderer, stats collection, and main() (#302)"
```

---

# Task 5 — Smoke test (container validation)

**Files:** none (validation only)

## Step 5.1 — Confirm the script is importable without errors

```bash
docker-compose exec backend python -c "import scripts.run_backtest_comparison; print('OK')"
# Expected: OK
```

## Step 5.2 — Confirm CLI help renders

```bash
docker-compose exec backend python scripts/run_backtest_comparison.py --help
# Expected output: --start, --end, --universe-id, --max-hold flags visible
```

## Step 5.3 — Run the full script test suite and confirm no regressions

```bash
# Scripts-only suite (--no-cov; coverage of app/ is near-zero for this subset)
docker-compose exec backend python -m pytest tests/scripts/ -v --no-cov
# Expected: 15 tests pass

# Full suite to confirm coverage gate still passes
docker-compose exec backend python -m pytest tests/ -q --tb=no 2>&1 | tail -5
# Expected: all pass, coverage >= 60%
```

---

# Task 6 — Live comparison run (primary deliverable)

This task produces `backend/docs/backtest/comparison-{end_date}.md`, the
committed table required by the spec's acceptance criteria.

**Prerequisite:** All services running (`docker-compose up -d`), universe id=1 populated
with tickers and daily `StockAggregate` bars for the trailing 12-month window,
Celery workers healthy (`docker-compose ps celery-worker`).

## Step 6.1 — Run the comparison script

```bash
# Without the :ro override so the container can write files
docker-compose -f docker-compose.yml exec backend \
  python scripts/run_backtest_comparison.py
# Expected output (may take 10–30 min depending on history coverage):
#   Seeding strategies...
#   Universe: <name> (<N> tickers)
#   Date range: <start> → <end>
#   Enqueueing 15 backtest runs (5 scanners × 3 strategies)...
#   Enqueued 15 runs. Polling (timeout=30 min)...
#   Progress: 0/15 completed
#   ...
#   Progress: 15/15 completed
#   Written: /app/docs/backtest/comparison-<end_date>.md
```

## Step 6.2 — Verify the output file was created

```bash
ls backend/docs/backtest/
# Expected: comparison-<end_date>.md present

head -20 backend/docs/backtest/comparison-*.md
# Expected: YAML frontmatter with universe_id, start_date, end_date, strategies block
```

## Step 6.3 — Commit the comparison report

```bash
END_DATE=$(ls backend/docs/backtest/comparison-*.md | sed 's/.*comparison-//' | sed 's/\.md//')
git add backend/docs/backtest/comparison-*.md
git commit -m "feat(backtest): 5x3 comparison run ${END_DATE} (#302)"
# Expected: 1 file changed
```
