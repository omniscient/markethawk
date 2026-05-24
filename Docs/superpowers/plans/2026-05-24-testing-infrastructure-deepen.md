# Implementation Plan: Testing Infrastructure — Coverage, CI, and Service Test Gaps

**Date:** 2026-05-24  
**Issue:** #72 — Testing Architecture Review: deepen test coverage and infrastructure  
**Spec:** `Docs/superpowers/specs/2026-05-24-testing-infrastructure-deepen-design.md`  
**Branch:** `refine/issue-72-testing-architecture-review--deepen-test`

---

## Goal

Bring backend line coverage from ~40% to ≥60% by: (1) adding `pytest-cov` and a 60% CI gate, (2) collapsing per-test DI-override boilerplate into a single autouse fixture, and (3) shipping test files for six untested services and three untested routers.

---

## Architecture

- **`backend/tests/api/conftest.py`** (new) — function-scoped `autouse=True` fixture that wires and clears `app.dependency_overrides[get_db]` for every test in the `tests/api/` subtree. Composes on the existing root `db` fixture; no changes to root `conftest.py`.
- **`backend/pyproject.toml`** (new) — pytest `addopts` installs coverage measurement and the `--cov-fail-under=60` gate on every `python -m pytest` run.
- **`.github/workflows/ci.yml`** (new) — GitHub Actions pipeline: postgres service container, `TEST_DATABASE_URL` env var, `python -m pytest`, coverage XML upload.
- **6 service test files** in `backend/tests/services/` — one per untested module.
- **3 router test files** in `backend/tests/api/` — `test_auto_trading.py`, `test_watchlist.py` (full tests) and `test_live_data.py` (placeholder with `pytest.skip`).

---

## Tech Stack

| Package | Purpose |
|---------|---------|
| `pytest-cov==6.1.0` | Coverage measurement, XML/terminal reports, fail-under gate |
| `fakeredis==2.28.1` | In-memory Redis for `auto_trade_service` distributed-lock tests |
| `unittest.mock.patch` | IBKR (`IBKROrderManager`) and Polygon (`RESTClient`) isolation — no new deps |

---

## File Structure

| File | Action |
|------|--------|
| `backend/requirements.txt` | Add `pytest-cov`, `fakeredis` |
| `backend/pyproject.toml` | New — pytest + coverage config |
| `.github/workflows/ci.yml` | New — CI pipeline |
| `backend/tests/api/conftest.py` | New — autouse DI fixture |
| `backend/tests/api/test_*.py` (15 files) | Edit — remove 3-line DI boilerplate per test |
| `backend/tests/services/test_chart_indicators.py` | New |
| `backend/tests/services/test_journal_service.py` | New |
| `backend/tests/services/test_outcome_service.py` | New |
| `backend/tests/services/test_alert_service.py` | New |
| `backend/tests/services/test_discovery_service.py` | New |
| `backend/tests/services/test_auto_trade_service.py` | New |
| `backend/tests/api/test_watchlist.py` | New |
| `backend/tests/api/test_auto_trading.py` | New |
| `backend/tests/api/test_live_data.py` | New (placeholder) |

---

## Tasks

---

### Task 1 — Add test dependencies to requirements.txt

**Files:** `backend/requirements.txt`

#### TDD Steps

1. **Confirm current state** — verify `pytest-cov` and `fakeredis` are absent:
   ```bash
   grep -E "pytest-cov|fakeredis" backend/requirements.txt
   # Expected: no output (neither package exists)
   ```

2. **Verify fail** — running with `--cov` errors without the package:
   ```bash
   cd backend && python -m pytest --cov=app --co -q 2>&1 | head -5
   # Expected: ERROR or ModuleNotFoundError: No module named 'pytest_cov'
   ```

3. **Implement** — add the two packages to `backend/requirements.txt` under the `# Testing` section:
   ```
   # Testing
   pytest==9.0.3
   pytest-asyncio==1.3.0
   pytest-cov==6.1.0
   fakeredis==2.28.1
   testcontainers[postgres]==4.10.0
   ```
   Then install into the active environment:
   ```bash
   pip install pytest-cov==6.1.0 fakeredis==2.28.1
   ```

4. **Verify pass**:
   ```bash
   python -c "import pytest_cov, fakeredis; print('OK')"
   # Expected: OK
   ```

5. **Commit**:
   ```bash
   git add backend/requirements.txt
   git commit -m "chore(deps): add pytest-cov and fakeredis to test requirements"
   ```

---

### Task 2 — Create backend/pyproject.toml with coverage configuration

**Files:** `backend/pyproject.toml` (new)

#### TDD Steps

1. **Confirm current state**:
   ```bash
   ls backend/pyproject.toml 2>&1
   # Expected: ls: cannot access 'backend/pyproject.toml': No such file or directory
   ```

2. **Verify fail** — no coverage gate currently enforced:
   ```bash
   cd backend && python -m pytest --co -q 2>&1 | grep "fail-under"
   # Expected: no output (gate not configured)
   ```

3. **Implement** — create `backend/pyproject.toml`:
   ```toml
   [tool.pytest.ini_options]
   testpaths = ["tests"]
   addopts = "--cov=app --cov-report=xml --cov-report=term-missing --cov-fail-under=60"

   [tool.coverage.run]
   source = ["app"]
   omit = ["app/main.py", "app/migrations/*"]

   [tool.coverage.report]
   exclude_lines = [
       "pragma: no cover",
       "if TYPE_CHECKING:",
   ]
   ```

4. **Verify pass** — pytest now picks up addopts:
   ```bash
   cd backend && python -m pytest --co -q 2>&1 | head -15
   # Expected: test collection output (coverage args active, no error)
   ```

5. **Commit**:
   ```bash
   git add backend/pyproject.toml
   git commit -m "chore(test): add pyproject.toml with pytest-cov and 60% line coverage gate"
   ```

---

### Task 3 — Create GitHub Actions CI workflow

**Files:** `.github/workflows/ci.yml` (new)

#### TDD Steps

1. **Confirm current state**:
   ```bash
   ls .github/ 2>&1
   # Expected: No such file or directory
   ```

2. **Implement** — create `.github/workflows/ci.yml`:
   ```yaml
   name: Backend CI

   on:
     pull_request:
       branches: [main]

   jobs:
     test:
       runs-on: ubuntu-latest
       services:
         postgres:
           image: postgres:15-alpine
           env:
             POSTGRES_USER: test
             POSTGRES_PASSWORD: test
             POSTGRES_DB: markethawk_test
           options: >-
             --health-cmd pg_isready
             --health-interval 10s
             --health-timeout 5s
             --health-retries 5
           ports:
             - 5432:5432

       steps:
         - uses: actions/checkout@v4

         - name: Set up Python
           uses: actions/setup-python@v5
           with:
             python-version: "3.12"
             cache: pip
             cache-dependency-path: backend/requirements.txt

         - name: Install dependencies
           run: pip install -r backend/requirements.txt

         - name: Run tests
           working-directory: backend
           env:
             TEST_DATABASE_URL: postgresql://test:test@localhost:5432/markethawk_test
           run: python -m pytest

         - name: Upload coverage report
           uses: actions/upload-artifact@v4
           with:
             name: coverage-xml
             path: backend/coverage.xml
   ```

3. **Verify syntax**:
   ```bash
   python -c "import yaml; yaml.safe_load(open('.github/workflows/ci.yml'))" && echo "YAML valid"
   # Expected: YAML valid
   ```

4. **Commit**:
   ```bash
   mkdir -p .github/workflows && git add .github/workflows/ci.yml
   git commit -m "feat(ci): add GitHub Actions backend CI with postgres service and 60% coverage gate"
   ```

---

### Task 4 — Create backend/tests/api/conftest.py with autouse DI fixture

**Files:** `backend/tests/api/conftest.py` (new)

#### TDD Steps

1. **Confirm boilerplate is in every test** — verify the manual pattern exists widely:
   ```bash
   grep -c "dependency_overrides\[get_db\]" backend/tests/api/test_alerts.py
   # Expected: 16 (one per test function)
   ```

2. **Verify fail** — strip boilerplate from one test and run without conftest:
   The `test_health_returns_ok` in `test_health.py` uses the override; removing it breaks the DB lookup.
   *(This step is observational — do not edit yet.)*

3. **Implement** — create `backend/tests/api/conftest.py`:
   ```python
   import pytest
   from app.main import app
   from app.core.database import get_db


   @pytest.fixture(autouse=True)
   def override_get_db(db):
       app.dependency_overrides[get_db] = lambda: db
       yield
       app.dependency_overrides.clear()
   ```

4. **Verify pass** — run one API test file end-to-end to confirm the fixture is picked up:
   ```bash
   cd backend && python -m pytest tests/api/test_health.py -v --no-cov 2>&1 | tail -10
   # Expected: all tests PASSED
   ```

5. **Commit**:
   ```bash
   git add backend/tests/api/conftest.py
   git commit -m "test(api): add autouse DI override fixture to tests/api/conftest.py"
   ```

---

### Task 5 — Refactor existing API tests: remove manual DI override boilerplate

**Files:** All 15 existing files in `backend/tests/api/test_*.py`

#### TDD Steps

1. **Capture baseline** — record current pass count:
   ```bash
   cd backend && python -m pytest tests/api/ -q --no-cov 2>&1 | tail -3
   # Note the N passed count — must match after refactor
   ```

2. **Pre-check** — confirm `get_db` is only used for DI overrides in the test files (not in assertions or fixtures):
   ```bash
   grep -rn "get_db" backend/tests/api/ | grep -v "dependency_overrides" | grep -v "^.*import"
   # Expected: no output — if any line appears, investigate before removing the import
   ```

3. **Implement** — for each of the 15 test files, remove:
   - Every `app.dependency_overrides[get_db] = lambda: db` line
   - Every `app.dependency_overrides.clear()` line
   - The `from app.core.database import get_db` import (only used for the override)
   - Keep `from app.main import app` (still needed for the module-level `client = TestClient(app)`)

   Remove the two boilerplate lines from every test function. Pattern to find and eliminate:
   ```python
   # Remove this (appears before each request):
   app.dependency_overrides[get_db] = lambda: db

   # Remove this (appears after each request):
   app.dependency_overrides.clear()
   ```

   Example transformation — `test_alerts.py::test_stats_returns_correct_shape`:

   **Before:**
   ```python
   def test_stats_returns_correct_shape(db: Session):
       app.dependency_overrides[get_db] = lambda: db
       response = client.get("/api/alerts/stats")
       app.dependency_overrides.clear()

       assert response.status_code == 200
   ```

   **After:**
   ```python
   def test_stats_returns_correct_shape(db: Session):
       response = client.get("/api/alerts/stats")

       assert response.status_code == 200
   ```

   Files to edit (all 15):
   - `test_alerts.py`, `test_analysis.py`, `test_futures.py`, `test_health.py`
   - `test_journal.py`, `test_news.py`, `test_outcomes.py`, `test_scanner.py`
   - `test_scanner_clear.py`, `test_scanner_range.py`, `test_signal_reviews.py`
   - `test_stocks.py`, `test_system.py`, `test_universe.py`, `test_universe_by_ticker.py`

4. **Verify pass** — baseline pass count must be preserved:
   ```bash
   cd backend && python -m pytest tests/api/ -q --no-cov 2>&1 | tail -3
   # Expected: same N passed as step 1
   ```

5. **Commit**:
   ```bash
   git add backend/tests/api/
   git commit -m "refactor(test): remove manual DI override boilerplate from all 15 API test files"
   ```

---

### Task 6 — Create test_chart_indicators.py (pure-function tests)

**Files:** `backend/tests/services/test_chart_indicators.py` (new)

#### TDD Steps

1. **Write the test file**:
   ```python
   """
   Tests for ChartIndicatorsService.add_indicators — pure DataFrame transformation,
   no DB or external calls required.
   """
   import pandas as pd
   import numpy as np
   import pytest
   from datetime import datetime, timezone
   from app.services.chart_indicators import ChartIndicatorsService


   def _make_df(n=30, start="2024-01-15 09:30", freq="1min"):
       """Synthetic OHLCV DataFrame with UTC DatetimeIndex."""
       idx = pd.date_range(start=start, periods=n, freq=freq, tz="UTC")
       rng = np.random.default_rng(42)
       close = 100.0 + rng.normal(0, 0.5, n).cumsum()
       high = close + rng.uniform(0.1, 0.5, n)
       low = close - rng.uniform(0.1, 0.5, n)
       volume = rng.integers(10_000, 50_000, n).astype(float)
       return pd.DataFrame(
           {"Open": close, "High": high, "Low": low, "Close": close, "Volume": volume},
           index=idx,
       )


   def test_returns_dataframe_with_same_length():
       df = _make_df(30)
       result = ChartIndicatorsService.add_indicators(df)
       assert len(result) == len(df)


   def test_empty_dataframe_returned_unchanged():
       empty = pd.DataFrame(columns=["Open", "High", "Low", "Close", "Volume"])
       result = ChartIndicatorsService.add_indicators(empty)
       assert result.empty


   def test_vwap_intraday_column_present():
       df = _make_df(30)
       result = ChartIndicatorsService.add_indicators(df)
       assert "vwap_intraday" in result.columns


   def test_vwap_first_bar_equals_close_times_volume_over_volume():
       df = _make_df(30)
       result = ChartIndicatorsService.add_indicators(df)
       # First bar VWAP = Close[0] * Volume[0] / Volume[0] = Close[0]
       assert pytest.approx(result["vwap_intraday"].iloc[0], rel=1e-4) == df["Close"].iloc[0]


   def test_marker_type_column_present():
       df = _make_df(30)
       result = ChartIndicatorsService.add_indicators(df)
       assert "marker_type" in result.columns


   def test_marker_type_values_are_valid():
       df = _make_df(60)
       result = ChartIndicatorsService.add_indicators(df)
       valid = {None, "swipe", "flush", "high_vol"}
       for val in result["marker_type"]:
           assert val in valid, f"Unexpected marker_type value: {val!r}"


   def test_intermediate_columns_dropped():
       df = _make_df(30)
       result = ChartIndicatorsService.add_indicators(df)
       dropped = [
           "cum_C_V", "TodayVolume", "Vol_MA_5", "fastVolumeAverage",
           "ATR_1", "swipe", "flush",
       ]
       for col in dropped:
           assert col not in result.columns, f"Column {col!r} should have been dropped"


   def test_index_converted_back_to_utc():
       df = _make_df(30)
       result = ChartIndicatorsService.add_indicators(df)
       assert str(result.index.tz) == "UTC"


   def test_does_not_mutate_input():
       df = _make_df(30)
       original_cols = set(df.columns)
       ChartIndicatorsService.add_indicators(df)
       assert set(df.columns) == original_cols
   ```

2. **Run and verify pass**:
   ```bash
   cd backend && python -m pytest tests/services/test_chart_indicators.py -v --no-cov 2>&1
   # Expected: 9 tests PASSED
   ```

3. **Commit**:
   ```bash
   git add backend/tests/services/test_chart_indicators.py
   git commit -m "test(services): add ChartIndicatorsService pure-function test suite"
   ```

---

### Task 7 — Create test_journal_service.py

**Files:** `backend/tests/services/test_journal_service.py` (new)

#### TDD Steps

1. **Write the test file**:
   ```python
   """
   Tests for journal_service CRUD functions against the testcontainers DB.
   """
   from decimal import Decimal
   import pytest
   from sqlalchemy.orm import Session

   from app.services.journal_service import (
       create_trade, get_trade, get_trades, update_trade,
       create_journal_entry, get_journal_entries,
       create_tag, get_tags, get_trade_stats,
   )
   from app.schemas.journal import TradeCreate, TradeUpdate, JournalEntryCreate, TagCreate


   # ── helpers ──────────────────────────────────────────────────────────────

   def _trade(symbol="AAPL", status="open"):
       return TradeCreate(symbol=symbol, status=status)


   # ── create_trade / get_trade ─────────────────────────────────────────────

   def test_create_trade_returns_persisted_object(db: Session):
       trade = create_trade(db, _trade())
       assert trade.id is not None
       assert trade.symbol == "AAPL"
       assert trade.status == "open"


   def test_get_trade_returns_correct_record(db: Session):
       created = create_trade(db, _trade("TSLA"))
       fetched = get_trade(db, created.id)
       assert fetched is not None
       assert fetched.symbol == "TSLA"


   def test_get_trade_returns_none_for_missing_id(db: Session):
       assert get_trade(db, 999999) is None


   # ── get_trades ───────────────────────────────────────────────────────────

   def test_get_trades_returns_all(db: Session):
       create_trade(db, _trade("AAPL"))
       create_trade(db, _trade("MSFT"))
       trades = get_trades(db)
       symbols = [t.symbol for t in trades]
       assert "AAPL" in symbols
       assert "MSFT" in symbols


   def test_get_trades_filters_by_symbol(db: Session):
       create_trade(db, _trade("AAPL"))
       create_trade(db, _trade("MSFT"))
       trades = get_trades(db, symbol="AAPL")
       assert all(t.symbol == "AAPL" for t in trades)


   def test_get_trades_filters_by_status(db: Session):
       create_trade(db, TradeCreate(symbol="AAPL", status="open"))
       create_trade(db, TradeCreate(symbol="MSFT", status="closed"))
       open_trades = get_trades(db, status="open")
       assert all(t.status == "open" for t in open_trades)


   # ── update_trade ─────────────────────────────────────────────────────────

   def test_update_trade_status(db: Session):
       trade = create_trade(db, _trade())
       updated = update_trade(db, trade.id, TradeUpdate(status="closed"))
       assert updated.status == "closed"


   def test_update_trade_notes(db: Session):
       trade = create_trade(db, _trade())
       updated = update_trade(db, trade.id, TradeUpdate(notes="Good entry"))
       assert updated.notes == "Good entry"


   def test_update_trade_returns_none_for_missing(db: Session):
       result = update_trade(db, 999999, TradeUpdate(status="closed"))
       assert result is None


   # ── trade stats ───────────────────────────────────────────────────────────

   def test_trade_stats_empty_db(db: Session):
       stats = get_trade_stats(db)
       assert stats.total_trades == 0
       assert stats.win_rate == 0


   def test_trade_stats_win_rate(db: Session):
       from app.models.trade import Trade
       winner = Trade(symbol="AAPL", status="closed", net_pnl=Decimal("100"))
       loser = Trade(symbol="MSFT", status="closed", net_pnl=Decimal("-50"))
       db.add_all([winner, loser])
       db.flush()
       stats = get_trade_stats(db)
       assert stats.total_trades == 2
       assert stats.winning_trades == 1
       assert stats.losing_trades == 1
       assert pytest.approx(stats.win_rate, rel=1e-3) == 0.5


   # ── journal entries ────────────────────────────────────────────────────────

   def test_create_and_get_journal_entry(db: Session):
       from datetime import date
       entry = create_journal_entry(db, JournalEntryCreate(
           entry_date=date.today(), title="Test Entry", content="Notes here"
       ))
       entries = get_journal_entries(db)
       ids = [e.id for e in entries]
       assert entry.id in ids


   # ── tags ──────────────────────────────────────────────────────────────────

   def test_create_and_get_tag(db: Session):
       tag = create_tag(db, TagCreate(name="momentum"))
       tags = get_tags(db)
       names = [t.name for t in tags]
       assert "momentum" in names
   ```

2. **Run and verify pass**:
   ```bash
   cd backend && python -m pytest tests/services/test_journal_service.py -v --no-cov 2>&1
   # Expected: all tests PASSED
   ```

3. **Commit**:
   ```bash
   git add backend/tests/services/test_journal_service.py
   git commit -m "test(services): add journal_service CRUD test suite"
   ```

---

### Task 8 — Create test_outcome_service.py

**Files:** `backend/tests/services/test_outcome_service.py` (new)

#### TDD Steps

1. **Write the test file**:
   ```python
   """
   Tests for OutcomeService — snapshot creation, capture, and summary recompute.
   """
   from datetime import date, datetime, timezone
   from decimal import Decimal
   import pytest
   from sqlalchemy.orm import Session

   from app.models.scanner_config import ScannerConfig
   from app.models.scanner_event import ScannerEvent
   from app.models.stock_aggregate import StockAggregate
   from app.services.outcome_service import OutcomeService


   # ── helpers ────────────────────────────────────────────────────────────────

   def _config(db, scanner_type="pre_market_volume_spike"):
       cfg = ScannerConfig(
           name="Test Config",
           scanner_type=scanner_type,
           parameters={},
           criteria={},
           outcome_config={
               "intervals": ["1h", "eod"],
               "reference_price_source": "opening_price",
               "follow_through_threshold_pct": 2.0,
           },
       )
       db.add(cfg)
       db.flush()
       return cfg


   def _event(db, scanner_type="pre_market_volume_spike", opening_price=10.0):
       ev = ScannerEvent(
           ticker="AAPL",
           event_date=date.today(),
           scanner_type=scanner_type,
           indicators={},
           criteria_met={},
           metadata_={},
           opening_price=Decimal(str(opening_price)),
       )
       db.add(ev)
       db.flush()
       return ev


   # ── create_pending_snapshots ──────────────────────────────────────────────

   def test_create_pending_snapshots_returns_correct_count(db: Session):
       _config(db)
       event = _event(db)
       snapshots = OutcomeService.create_pending_snapshots(db, event)
       assert len(snapshots) == 2  # "1h" and "eod"


   def test_create_pending_snapshots_sets_status_pending(db: Session):
       _config(db)
       event = _event(db)
       snapshots = OutcomeService.create_pending_snapshots(db, event)
       assert all(s.status == "pending" for s in snapshots)


   def test_create_pending_snapshots_no_config_returns_empty(db: Session):
       event = _event(db, scanner_type="unknown_type")
       snapshots = OutcomeService.create_pending_snapshots(db, event)
       assert snapshots == []


   def test_create_pending_snapshots_no_opening_price_returns_empty(db: Session):
       _config(db)
       event = _event(db, opening_price=0)
       event.opening_price = None
       db.flush()
       snapshots = OutcomeService.create_pending_snapshots(db, event)
       assert snapshots == []


   # ── capture_snapshot ──────────────────────────────────────────────────────

   def test_capture_snapshot_sets_status_captured(db: Session):
       from datetime import timedelta
       from zoneinfo import ZoneInfo
       _config(db)
       event = _event(db, opening_price=10.0)
       snapshots = OutcomeService.create_pending_snapshots(db, event)

       _ET = ZoneInfo("America/New_York")
       open_et = datetime.combine(event.event_date, __import__("datetime").time(9, 30), tzinfo=_ET)
       open_utc = open_et.astimezone(timezone.utc).replace(tzinfo=None)

       bar = StockAggregate(
           ticker="AAPL",
           timespan="minute",
           timestamp=open_utc + timedelta(minutes=5),
           open=Decimal("10.1"),
           high=Decimal("10.5"),
           low=Decimal("9.9"),
           close=Decimal("10.3"),
           volume=5000,
           multiplier=1,
       )
       db.add(bar)
       db.flush()

       snap_1h = next(s for s in snapshots if s.interval_key == "1h")
       OutcomeService.capture_snapshot(db, snap_1h)
       assert snap_1h.status == "captured"
       assert snap_1h.snapshot_price == pytest.approx(Decimal("10.3"), rel=Decimal("1e-4"))


   def test_capture_snapshot_no_bars_sets_failed(db: Session):
       _config(db)
       event = _event(db)
       snapshots = OutcomeService.create_pending_snapshots(db, event)
       snap = snapshots[0]
       OutcomeService.capture_snapshot(db, snap)
       assert snap.status == "failed"


   # ── recompute_summary ─────────────────────────────────────────────────────

   def test_recompute_summary_returns_none_without_captured_snapshots(db: Session):
       _config(db)
       event = _event(db)
       OutcomeService.create_pending_snapshots(db, event)
       result = OutcomeService.recompute_summary(db, event.id)
       assert result is None


   def test_recompute_summary_returns_none_for_missing_event(db: Session):
       result = OutcomeService.recompute_summary(db, 999999)
       assert result is None
   ```

2. **Run and verify pass**:
   ```bash
   cd backend && python -m pytest tests/services/test_outcome_service.py -v --no-cov 2>&1
   # Expected: all tests PASSED
   ```

3. **Commit**:
   ```bash
   git add backend/tests/services/test_outcome_service.py
   git commit -m "test(services): add OutcomeService snapshot and summary test suite"
   ```

---

### Task 9 — Create test_alert_service.py

**Files:** `backend/tests/services/test_alert_service.py` (new)

#### TDD Steps

1. **Write the test file**:
   ```python
   """
   Tests for AlertRuleService — rule matching, cooldown logic, and delivery dispatch.
   """
   from datetime import date, datetime, timezone, timedelta
   from unittest.mock import patch, MagicMock
   import pytest
   from sqlalchemy.orm import Session

   from app.models.alert_rule import AlertRule
   from app.models.alert_delivery_log import AlertDeliveryLog
   from app.models.scanner_event import ScannerEvent
   from app.services.alert_service import AlertRuleService


   # ── helpers ────────────────────────────────────────────────────────────────

   def _rule(db, scanner_types=None, severity_filter="any", cooldown_minutes=0,
             is_active=True, channels=None):
       r = AlertRule(
           name="Test Rule",
           is_active=is_active,
           scanner_types=scanner_types or [],
           severity_filter=severity_filter,
           cooldown_minutes=cooldown_minutes,
           channels=channels or [],
           channel_config={},
       )
       db.add(r)
       db.flush()
       return r


   def _event(scanner_type="pre_market_volume_spike", severity="high"):
       ev = ScannerEvent.__new__(ScannerEvent)
       ev.id = None
       ev.ticker = "AAPL"
       ev.event_date = date.today()
       ev.scanner_type = scanner_type
       ev.severity = severity
       ev.indicators = {}
       ev.criteria_met = {}
       ev.metadata_ = {}
       ev.opening_price = None
       return ev


   # ── get_matching_rules ────────────────────────────────────────────────────

   def test_matches_rule_with_empty_scanner_types_filter(db: Session):
       rule = _rule(db, scanner_types=[])
       event = _event()
       matched = AlertRuleService.get_matching_rules(event, db)
       assert rule in matched


   def test_matches_rule_when_scanner_type_in_filter(db: Session):
       rule = _rule(db, scanner_types=["pre_market_volume_spike"])
       event = _event(scanner_type="pre_market_volume_spike")
       matched = AlertRuleService.get_matching_rules(event, db)
       assert rule in matched


   def test_excludes_rule_when_scanner_type_not_in_filter(db: Session):
       rule = _rule(db, scanner_types=["oversold_bounce"])
       event = _event(scanner_type="pre_market_volume_spike")
       matched = AlertRuleService.get_matching_rules(event, db)
       assert rule not in matched


   def test_excludes_inactive_rule(db: Session):
       rule = _rule(db, is_active=False)
       event = _event()
       matched = AlertRuleService.get_matching_rules(event, db)
       assert rule not in matched


   def test_severity_filter_match(db: Session):
       rule = _rule(db, severity_filter="high")
       event = _event(severity="high")
       matched = AlertRuleService.get_matching_rules(event, db)
       assert rule in matched


   def test_severity_filter_no_match(db: Session):
       rule = _rule(db, severity_filter="high")
       event = _event(severity="low")
       matched = AlertRuleService.get_matching_rules(event, db)
       assert rule not in matched


   # ── is_on_cooldown ────────────────────────────────────────────────────────

   def test_no_cooldown_returns_false(db: Session):
       rule = _rule(db, cooldown_minutes=0)
       assert AlertRuleService.is_on_cooldown(rule, "AAPL", db) is False


   def test_cooldown_active_when_recent_delivery_exists(db: Session):
       rule = _rule(db, cooldown_minutes=60)
       log = AlertDeliveryLog(
           rule_id=rule.id,
           ticker="AAPL",
           scanner_type="pre_market_volume_spike",
           channel="browser_push",
           status="sent",
           delivered_at=datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=5),
       )
       db.add(log)
       db.flush()
       assert AlertRuleService.is_on_cooldown(rule, "AAPL", db) is True


   def test_cooldown_expired_returns_false(db: Session):
       rule = _rule(db, cooldown_minutes=30)
       log = AlertDeliveryLog(
           rule_id=rule.id,
           ticker="AAPL",
           scanner_type="pre_market_volume_spike",
           channel="browser_push",
           status="sent",
           delivered_at=datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=2),
       )
       db.add(log)
       db.flush()
       assert AlertRuleService.is_on_cooldown(rule, "AAPL", db) is False
   ```

2. **Run and verify pass**:
   ```bash
   cd backend && python -m pytest tests/services/test_alert_service.py -v --no-cov 2>&1
   # Expected: all tests PASSED
   ```

3. **Commit**:
   ```bash
   git add backend/tests/services/test_alert_service.py
   git commit -m "test(services): add AlertRuleService matching and cooldown test suite"
   ```

---

### Task 10 — Create test_discovery_service.py

**Files:** `backend/tests/services/test_discovery_service.py` (new)

#### TDD Steps

1. **Write the test file**:
   ```python
   """
   Tests for DiscoveryService — Polygon client interactions mocked via unittest.mock.

   Patch target: app.services.discovery_service.RESTClient
   (DiscoveryService imports `from polygon import RESTClient` so the module-local
   name must be patched, not `polygon.RESTClient` directly.)
   """
   from unittest.mock import MagicMock, patch
   import pytest
   from sqlalchemy.orm import Session

   from app.services.discovery_service import DiscoveryService


   # ── sync_fundamental_data ──────────────────────────────────────────────────

   def test_sync_fundamental_data_starts_celery_task(db: Session):
       """sync_fundamental_data delegates to Celery — verify it returns 'started'."""
       with patch("app.services.discovery_service.RESTClient"), \
            patch("app.tasks.sync_tickers_batch") as mock_task:
           mock_task.delay = MagicMock()
           service = DiscoveryService(db)
           result = service.sync_fundamental_data()

       assert result["status"] == "started"
       mock_task.delay.assert_called_once()


   # ── update_daily_metrics_snapshot ─────────────────────────────────────────

   def test_update_daily_metrics_no_aggs_returns_early(db: Session):
       """When Polygon returns no aggregates, method returns without error."""
       with patch("app.services.discovery_service.RESTClient") as MockRESTClient:
           mock_client = MockRESTClient.return_value
           mock_client.get_grouped_daily_aggs.return_value = []
           service = DiscoveryService(db)
           result = service.update_daily_metrics_snapshot()
           assert result is None


   def test_update_daily_metrics_skips_unknown_tickers(db: Session):
       """Tickers not in ticker_reference table are skipped silently."""
       mock_agg = MagicMock()
       mock_agg.ticker = "UNKNWN"
       mock_agg.open = 10.0
       mock_agg.high = 11.0
       mock_agg.low = 9.5
       mock_agg.close = 10.5
       mock_agg.volume = 100000
       mock_agg.vwap = 10.2
       mock_agg.transactions = 500

       with patch("app.services.discovery_service.RESTClient") as MockRESTClient:
           mock_client = MockRESTClient.return_value
           mock_client.get_grouped_daily_aggs.return_value = [mock_agg]
           service = DiscoveryService(db)
           # Should not raise even though ticker is not in DB
           service.update_daily_metrics_snapshot()
   ```

2. **Run and verify pass**:
   ```bash
   cd backend && python -m pytest tests/services/test_discovery_service.py -v --no-cov 2>&1
   # Expected: all tests PASSED
   ```

3. **Commit**:
   ```bash
   git add backend/tests/services/test_discovery_service.py
   git commit -m "test(services): add DiscoveryService Celery delegation and Polygon mock tests"
   ```

---

### Task 11 — Create test_auto_trade_service.py

**Files:** `backend/tests/services/test_auto_trade_service.py` (new)

#### TDD Steps

1. **Write the test file**:
   ```python
   """
   Tests for AutoTradeExecutor — guard checks, position sizing, and paper-mode order path.

   All tests use paper_mode=True strategies. Redis is replaced with fakeredis.
   Live IBKR paths are isolated with unittest.mock.patch.
   """
   from datetime import date
   from decimal import Decimal
   from unittest.mock import patch, MagicMock
   import fakeredis
   import pytest
   from sqlalchemy.orm import Session

   from app.models.alert_rule import AlertRule
   from app.models.scanner_event import ScannerEvent
   from app.models.trading_strategy import TradingStrategy
   from app.services.auto_trade_service import AutoTradeExecutor, PositionCalc


   # ── helpers ────────────────────────────────────────────────────────────────

   def _strategy(db, paper_mode=True, requires_approval=False, direction="long_only",
                 max_trades_per_day=5, max_concurrent_positions=3,
                 stop_pct=Decimal("2.0"), risk_per_trade_pct=Decimal("1.0"),
                 risk_reward_ratio=Decimal("2.0"), max_position_usd=None):
       s = TradingStrategy(
           name=f"Test Strategy {id(db)}",
           paper_mode=paper_mode,
           requires_approval=requires_approval,
           is_active=True,
           direction=direction,
           max_trades_per_day=max_trades_per_day,
           max_concurrent_positions=max_concurrent_positions,
           stop_pct=stop_pct,
           risk_per_trade_pct=risk_per_trade_pct,
           risk_reward_ratio=risk_reward_ratio,
           max_position_usd=max_position_usd,
           allowed_sessions=["regular", "pre_market"],
       )
       db.add(s)
       db.flush()
       return s


   def _rule(db, strategy, auto_trade=True):
       r = AlertRule(
           name="Test Rule",
           is_active=True,
           scanner_types=[],
           severity_filter="any",
           cooldown_minutes=0,
           channels=[],
           channel_config={},
           auto_trade=auto_trade,
           trading_strategy_id=strategy.id,
       )
       db.add(r)
       db.flush()
       return r


   def _event(db, ticker="AAPL", scanner_type="pre_market_volume_spike",
              opening_price=Decimal("50.00"), indicators=None):
       ev = ScannerEvent(
           ticker=ticker,
           event_date=date.today(),
           scanner_type=scanner_type,
           indicators=indicators or {"last_trade_price": 50.0},
           criteria_met={},
           metadata_={"session": "pre_market"},
           opening_price=opening_price,
       )
       db.add(ev)
       db.flush()
       return ev


   def _fake_redis():
       return fakeredis.FakeRedis(decode_responses=True)


   # Patch target for Redis: use the module-local name, not the top-level redis package.
   # auto_trade_service.py does `import redis` then `redis.from_url(...)` at line 148,
   # so the correct target is "app.services.auto_trade_service.redis.from_url".
   REDIS_PATCH = "app.services.auto_trade_service.redis.from_url"


   # ── _calculate_position (pure math, no DB/Redis) ───────────────────────────

   def test_calculate_position_long_basic():
       from app.models.trading_strategy import TradingStrategy as TS
       s = TS.__new__(TS)
       s.risk_per_trade_pct = Decimal("1.0")
       s.stop_pct = Decimal("2.0")
       s.risk_reward_ratio = Decimal("2.0")
       s.limit_offset_pct = Decimal("0.0")
       s.entry_type = "market"
       s.max_position_usd = None
       executor = AutoTradeExecutor()
       calc = executor._calculate_position(s, trigger_price=100.0, side="long",
                                           account_equity=10_000.0)
       assert calc.quantity == 50          # 100 risk / (100*2%) = 50
       assert calc.stop == pytest.approx(98.0, abs=0.01)
       assert calc.target == pytest.approx(104.0, abs=0.01)


   def test_calculate_position_short_flips_stop_and_target():
       from app.models.trading_strategy import TradingStrategy as TS
       s = TS.__new__(TS)
       s.risk_per_trade_pct = Decimal("1.0")
       s.stop_pct = Decimal("2.0")
       s.risk_reward_ratio = Decimal("2.0")
       s.limit_offset_pct = Decimal("0.0")
       s.entry_type = "market"
       s.max_position_usd = None
       executor = AutoTradeExecutor()
       calc = executor._calculate_position(s, trigger_price=100.0, side="short",
                                           account_equity=10_000.0)
       assert calc.stop == pytest.approx(102.0, abs=0.01)
       assert calc.target == pytest.approx(96.0, abs=0.01)


   def test_calculate_position_zero_quantity_when_price_too_high():
       from app.models.trading_strategy import TradingStrategy as TS
       s = TS.__new__(TS)
       s.risk_per_trade_pct = Decimal("0.001")
       s.stop_pct = Decimal("2.0")
       s.risk_reward_ratio = Decimal("2.0")
       s.limit_offset_pct = Decimal("0.0")
       s.entry_type = "market"
       s.max_position_usd = None
       executor = AutoTradeExecutor()
       calc = executor._calculate_position(s, trigger_price=50000.0, side="long",
                                           account_equity=100.0)
       assert calc.quantity == 0


   # ── _determine_side ────────────────────────────────────────────────────────

   def test_determine_side_long_only_with_long_scanner():
       from app.models.trading_strategy import TradingStrategy as TS
       from app.models.scanner_event import ScannerEvent as SE
       s = TS.__new__(TS)
       s.direction = "long_only"
       ev = SE.__new__(SE)
       ev.scanner_type = "pre_market_volume_spike"
       ev.indicators = {}
       side = AutoTradeExecutor()._determine_side(ev, s)
       assert side == "long"


   def test_determine_side_long_only_blocks_short():
       from app.models.trading_strategy import TradingStrategy as TS
       from app.models.scanner_event import ScannerEvent as SE
       s = TS.__new__(TS)
       s.direction = "long_only"
       ev = SE.__new__(SE)
       ev.scanner_type = "live_price_move"
       ev.indicators = {"price_change_pct": -3.0}
       side = AutoTradeExecutor()._determine_side(ev, s)
       assert side is None


   # ── maybe_execute — guard checks ──────────────────────────────────────────

   def test_maybe_execute_skips_when_auto_trade_false(db: Session):
       strategy = _strategy(db)
       rule = _rule(db, strategy, auto_trade=False)
       event = _event(db)
       with patch(REDIS_PATCH, return_value=_fake_redis()):
           result = AutoTradeExecutor().maybe_execute(rule, event, db)
       assert result is None


   def test_maybe_execute_skips_when_strategy_inactive(db: Session):
       strategy = _strategy(db)
       strategy.is_active = False
       db.flush()
       rule = _rule(db, strategy)
       event = _event(db)
       with patch(REDIS_PATCH, return_value=_fake_redis()):
           result = AutoTradeExecutor().maybe_execute(rule, event, db)
       assert result is None


   def test_maybe_execute_paper_mode_creates_submitted_order(db: Session):
       strategy = _strategy(db, paper_mode=True, max_concurrent_positions=10,
                            max_trades_per_day=10)
       rule = _rule(db, strategy)
       event = _event(db)
       with patch(REDIS_PATCH, return_value=_fake_redis()):
           order = AutoTradeExecutor().maybe_execute(rule, event, db)
       assert order is not None
       assert order.status == "submitted"
       assert order.is_paper is True
       assert order.broker_order_id.startswith("PAPER-")


   def test_maybe_execute_requires_approval_creates_pending_approval(db: Session):
       strategy = _strategy(db, paper_mode=True, requires_approval=True,
                            max_concurrent_positions=10, max_trades_per_day=10)
       rule = _rule(db, strategy)
       event = _event(db)
       with patch(REDIS_PATCH, return_value=_fake_redis()):
           order = AutoTradeExecutor().maybe_execute(rule, event, db)
       assert order is not None
       assert order.status == "pending_approval"


   def test_maybe_execute_idempotent_second_call_returns_none(db: Session):
       strategy = _strategy(db, paper_mode=True, max_concurrent_positions=10,
                            max_trades_per_day=10)
       rule = _rule(db, strategy)
       event = _event(db)
       fake_r = _fake_redis()
       with patch(REDIS_PATCH, return_value=fake_r):
           AutoTradeExecutor().maybe_execute(rule, event, db)
       with patch(REDIS_PATCH, return_value=fake_r):
           second = AutoTradeExecutor().maybe_execute(rule, event, db)
       assert second is None


   def test_maybe_execute_live_mode_isolates_ibkr(db: Session):
       """Live (paper_mode=False) path: IBKROrderManager is patched per spec Req 7."""
       from app.models.system_config import SystemConfig
       db.add(SystemConfig(key="AUTO_TRADING_ENABLED", value="true"))
       db.flush()
       strategy = _strategy(db, paper_mode=False, requires_approval=False,
                            max_concurrent_positions=10, max_trades_per_day=10)
       rule = _rule(db, strategy)
       event = _event(db)

       mock_result = MagicMock()
       mock_result.parent_order_id = "IB-PARENT-1"
       mock_result.stop_order_id = "IB-STOP-1"
       mock_result.target_order_id = "IB-TGT-1"

       async def _fake_bracket(**kwargs):
           return mock_result

       with patch(REDIS_PATCH, return_value=_fake_redis()), \
            patch("app.providers.ibkr_orders.IBKROrderManager") as MockIBKR:
           mock_mgr = MagicMock()
           mock_mgr.place_bracket_order = _fake_bracket
           MockIBKR.return_value = mock_mgr
           order = AutoTradeExecutor().maybe_execute(rule, event, db)

       assert order is not None
       assert order.status == "submitted"
       assert order.broker_order_id == "IB-PARENT-1"
   ```

2. **Run and verify pass**:
   ```bash
   cd backend && python -m pytest tests/services/test_auto_trade_service.py -v --no-cov 2>&1
   # Expected: all tests PASSED
   ```

3. **Commit**:
   ```bash
   git add backend/tests/services/test_auto_trade_service.py
   git commit -m "test(services): add AutoTradeExecutor guard checks, sizing math, and paper-mode tests"
   ```

---

### Task 12 — Create test_watchlist.py (router)

**Files:** `backend/tests/api/test_watchlist.py` (new)

#### TDD Steps

1. **Write the test file**:
   ```python
   """
   Integration tests for /api/watchlist endpoints.
   DI override is handled by tests/api/conftest.py autouse fixture.
   """
   import pytest
   from fastapi.testclient import TestClient
   from sqlalchemy.orm import Session

   from app.main import app
   from app.models.active_watchlist import ActiveWatchlist

   client = TestClient(app)


   def _add(symbol="AAPL", security_type="STK"):
       return {"symbol": symbol, "security_type": security_type}


   # ── GET / ─────────────────────────────────────────────────────────────────

   def test_list_watchlist_empty(db: Session):
       response = client.get("/api/watchlist/")
       assert response.status_code == 200
       assert response.json() == []


   def test_list_watchlist_returns_seeded_entries(db: Session):
       entry = ActiveWatchlist(symbol="TSLA", security_type="STK")
       db.add(entry)
       db.flush()
       response = client.get("/api/watchlist/")
       assert response.status_code == 200
       symbols = [e["symbol"] for e in response.json()]
       assert "TSLA" in symbols


   # ── POST / ────────────────────────────────────────────────────────────────

   def test_add_to_watchlist_returns_201(db: Session):
       response = client.post("/api/watchlist/", json=_add("AAPL"))
       assert response.status_code == 201
       data = response.json()
       assert data["symbol"] == "AAPL"
       assert "id" in data
       assert "added_at" in data


   def test_add_duplicate_returns_409(db: Session):
       client.post("/api/watchlist/", json=_add("AAPL"))
       response = client.post("/api/watchlist/", json=_add("AAPL"))
       assert response.status_code == 409


   def test_add_beyond_soft_limit_returns_422(db: Session):
       from app.models.active_watchlist import WATCHLIST_SOFT_LIMIT
       for i in range(WATCHLIST_SOFT_LIMIT):
           db.add(ActiveWatchlist(symbol=f"SYM{i:03d}", security_type="STK"))
       db.flush()
       response = client.post("/api/watchlist/", json=_add("NEWONE"))
       assert response.status_code == 422


   # ── PATCH /{symbol} ───────────────────────────────────────────────────────

   def test_update_watchlist_notes(db: Session):
       db.add(ActiveWatchlist(symbol="MSFT", security_type="STK"))
       db.flush()
       response = client.patch("/api/watchlist/MSFT", json={"notes": "Watching closely"})
       assert response.status_code == 200
       assert response.json()["notes"] == "Watching closely"


   def test_update_watchlist_not_found_returns_404(db: Session):
       response = client.patch("/api/watchlist/GHOST", json={"notes": "nothing"})
       assert response.status_code == 404


   # ── DELETE /{symbol} ──────────────────────────────────────────────────────

   def test_delete_from_watchlist_returns_204(db: Session):
       db.add(ActiveWatchlist(symbol="AMD", security_type="STK"))
       db.flush()
       response = client.delete("/api/watchlist/AMD")
       assert response.status_code == 204


   def test_delete_removes_entry_from_list(db: Session):
       db.add(ActiveWatchlist(symbol="AMD", security_type="STK"))
       db.flush()
       client.delete("/api/watchlist/AMD")
       response = client.get("/api/watchlist/")
       symbols = [e["symbol"] for e in response.json()]
       assert "AMD" not in symbols


   def test_delete_not_found_returns_404(db: Session):
       response = client.delete("/api/watchlist/GHOST")
       assert response.status_code == 404
   ```

2. **Run and verify pass**:
   ```bash
   cd backend && python -m pytest tests/api/test_watchlist.py -v --no-cov 2>&1
   # Expected: all tests PASSED
   ```

3. **Commit**:
   ```bash
   git add backend/tests/api/test_watchlist.py
   git commit -m "test(api): add watchlist router CRUD integration tests"
   ```

---

### Task 13 — Create test_auto_trading.py (router)

**Files:** `backend/tests/api/test_auto_trading.py` (new)

#### TDD Steps

1. **Write the test file**:
   ```python
   """
   Integration tests for /api/trading endpoints.
   Paper-mode fixture seeds a TradingStrategy with paper_mode=True.
   Broker-touching paths are not exercised here (unit tests in test_auto_trade_service.py cover those).
   DI override is handled by tests/api/conftest.py autouse fixture.
   """
   import pytest
   from fastapi.testclient import TestClient
   from sqlalchemy.orm import Session

   from app.main import app
   from app.models.trading_strategy import TradingStrategy

   client = TestClient(app)


   # ── fixtures ──────────────────────────────────────────────────────────────

   def _paper_strategy(db, name="Paper Strat", is_active=True):
       s = TradingStrategy(
           name=name,
           paper_mode=True,
           is_active=is_active,
           risk_per_trade_pct=1.0,
           stop_pct=2.0,
           risk_reward_ratio=2.0,
           max_trades_per_day=5,
           max_concurrent_positions=3,
           allowed_sessions=["regular"],
           direction="long_only",
       )
       db.add(s)
       db.flush()
       return s


   # ── GET /api/trading/strategies ───────────────────────────────────────────

   def test_list_strategies_empty(db: Session):
       response = client.get("/api/trading/strategies")
       assert response.status_code == 200
       assert response.json() == []


   def test_list_strategies_returns_seeded(db: Session):
       _paper_strategy(db)
       response = client.get("/api/trading/strategies")
       assert response.status_code == 200
       assert len(response.json()) == 1


   def test_list_strategies_response_shape(db: Session):
       _paper_strategy(db, name="Shape Test")
       response = client.get("/api/trading/strategies")
       item = response.json()[0]
       for field in ("id", "name", "paper_mode", "is_active", "risk_per_trade_pct",
                     "stop_pct", "direction", "created_at"):
           assert field in item, f"Missing field: {field}"


   # ── POST /api/trading/strategies ──────────────────────────────────────────

   def test_create_strategy_returns_201(db: Session):
       payload = {
           "name": "New Paper Strat",
           "paper_mode": True,
           "risk_per_trade_pct": 1.0,
           "stop_pct": 2.0,
           "risk_reward_ratio": 2.0,
           "max_trades_per_day": 5,
           "max_concurrent_positions": 3,
           "direction": "long_only",
       }
       response = client.post("/api/trading/strategies", json=payload)
       assert response.status_code == 201
       data = response.json()
       assert data["name"] == "New Paper Strat"
       assert data["paper_mode"] is True


   def test_create_strategy_appears_in_list(db: Session):
       client.post("/api/trading/strategies", json={
           "name": "Discoverable Strat",
           "paper_mode": True,
       })
       response = client.get("/api/trading/strategies")
       names = [s["name"] for s in response.json()]
       assert "Discoverable Strat" in names


   # ── GET /api/trading/strategies/{id} ──────────────────────────────────────

   def test_get_strategy_by_id(db: Session):
       s = _paper_strategy(db, name="Single Fetch")
       response = client.get(f"/api/trading/strategies/{s.id}")
       assert response.status_code == 200
       assert response.json()["name"] == "Single Fetch"


   def test_get_strategy_not_found(db: Session):
       response = client.get("/api/trading/strategies/99999")
       assert response.status_code == 404


   # ── PATCH /api/trading/strategies/{id} ───────────────────────────────────

   def test_update_strategy_name(db: Session):
       s = _paper_strategy(db)
       response = client.patch(f"/api/trading/strategies/{s.id}",
                               json={"name": "Renamed"})
       assert response.status_code == 200
       assert response.json()["name"] == "Renamed"


   def test_update_strategy_toggle_active(db: Session):
       s = _paper_strategy(db)
       response = client.patch(f"/api/trading/strategies/{s.id}",
                               json={"is_active": False})
       assert response.status_code == 200
       assert response.json()["is_active"] is False


   def test_update_strategy_not_found(db: Session):
       response = client.patch("/api/trading/strategies/99999", json={"name": "Ghost"})
       assert response.status_code == 404


   # ── DELETE /api/trading/strategies/{id} ──────────────────────────────────

   def test_delete_strategy_returns_204(db: Session):
       s = _paper_strategy(db)
       response = client.delete(f"/api/trading/strategies/{s.id}")
       assert response.status_code == 204


   def test_delete_strategy_removes_from_list(db: Session):
       s = _paper_strategy(db)
       client.delete(f"/api/trading/strategies/{s.id}")
       response = client.get("/api/trading/strategies")
       ids = [item["id"] for item in response.json()]
       assert s.id not in ids


   def test_delete_strategy_with_open_orders_returns_409(db: Session):
       from datetime import date
       from app.models.auto_trade_order import AutoTradeOrder
       s = _paper_strategy(db)
       order = AutoTradeOrder(
           symbol="AAPL",
           side="long",
           event_date=date.today(),
           trading_strategy_id=s.id,
           status="submitted",
           is_paper=True,
       )
       db.add(order)
       db.flush()
       response = client.delete(f"/api/trading/strategies/{s.id}")
       assert response.status_code == 409


   # ── GET /api/trading/orders ───────────────────────────────────────────────

   def test_list_orders_empty(db: Session):
       response = client.get("/api/trading/orders")
       assert response.status_code == 200
       assert isinstance(response.json(), list)


   # ── GET /api/trading/stats ────────────────────────────────────────────────
   # Fields confirmed from backend/app/routers/auto_trading.py lines 492–500:
   # period_days, total_orders, by_status, closed_count, win_count, win_rate,
   # total_pnl, avg_pnl_per_trade

   def test_stats_returns_expected_shape(db: Session):
       response = client.get("/api/trading/stats")
       assert response.status_code == 200
       data = response.json()
       for field in ("period_days", "total_orders", "by_status", "closed_count",
                     "win_count", "win_rate", "total_pnl", "avg_pnl_per_trade"):
           assert field in data, f"Missing field: {field}"


   def test_stats_empty_db_returns_zero_counts(db: Session):
       response = client.get("/api/trading/stats")
       data = response.json()
       assert data["total_orders"] == 0
       assert data["closed_count"] == 0
       assert data["win_rate"] is None
       assert data["total_pnl"] == 0.0
   ```

2. **Run and verify pass**:
   ```bash
   cd backend && python -m pytest tests/api/test_auto_trading.py -v --no-cov 2>&1
   # Expected: all tests PASSED
   ```

3. **Commit**:
   ```bash
   git add backend/tests/api/test_auto_trading.py
   git commit -m "test(api): add auto-trading router strategy CRUD and order list integration tests"
   ```

---

### Task 14 — Create test_live_data.py (placeholder)

**Files:** `backend/tests/api/test_live_data.py` (new)

#### TDD Steps

1. **Write the placeholder file**:
   ```python
   """
   live_data router — WebSocket-only; HTTP integration tests are deferred.

   The live_data router exposes no HTTP endpoints (100% WebSocket).
   Full test coverage requires async WebSocket test clients and is tracked
   as a separate follow-on work item.

   See: backend/app/routers/live_data.py
   """
   import pytest


   @pytest.mark.skip(reason="live_data router is 100% WebSocket — deferred to async/WebSocket work item")
   def test_placeholder_live_data_websocket():
       pass
   ```

2. **Run and verify skip (not fail)**:
   ```bash
   cd backend && python -m pytest tests/api/test_live_data.py -v --no-cov 2>&1
   # Expected: 1 SKIPPED
   ```

3. **Commit**:
   ```bash
   git add backend/tests/api/test_live_data.py
   git commit -m "test(api): add live_data placeholder — WebSocket testing deferred"
   ```

---

### Task 15 — Run full suite and verify 60% gate

**Files:** (none — verification step)

#### Steps

1. **Run full test suite with coverage**:
   ```bash
   cd backend && python -m pytest --no-header -q 2>&1 | tail -20
   # Expected: all tests pass and "Required test coverage of 60% reached"
   ```

2. **If coverage is below 60%**, check which modules have the lowest coverage:
   ```bash
   cd backend && python -m pytest --cov-report=term-missing -q 2>&1 | grep -E "^app/" | sort -k4 -n | head -20
   ```
   Add targeted tests for the weakest modules until the gate passes.

3. **Commit (if any fixes were needed)**:
   ```bash
   git add backend/tests/
   git commit -m "test: add targeted tests to reach 60% coverage gate"
   ```

---

## Expected Outcome

| Metric | Before | After |
|--------|--------|-------|
| Untested service modules | 6 | 0 |
| Untested router files | 3 | 0 (live_data deferred/documented) |
| Per-test DI boilerplate | 2 lines × N tests | 0 |
| Coverage gate | None | 60% enforced in CI and locally |
| CI pipeline | None | GitHub Actions on every PR to main |

---

## Notes for Implementer

- **Task 5 ordering:** complete Task 4 (conftest.py) before Task 5 (refactor). The autouse fixture must exist before boilerplate is removed or tests will break.
- **Task 13 stats shape:** `GET /api/trading/stats` field names must be verified against the live router before finalising assertions. Run `curl -s http://localhost:8000/api/trading/stats | python -m json.tool` first.
- **Task 8 StockAggregate:** the `StockAggregate` model requires a `multiplier` column — verify by checking `backend/app/models/stock_aggregate.py` if the test fails on model construction.
- **`fakeredis` patch target in Task 11:** always use `"app.services.auto_trade_service.redis.from_url"` (the module-local name). `auto_trade_service.py` does `import redis` then `redis.from_url(...)`, so the correct patch target is the module-local reference, not the global `redis` package. This is already written as `REDIS_PATCH` in the test file.
- **IBKR patch target in Task 11 live-mode test:** `"app.providers.ibkr_orders.IBKROrderManager"` — imported lazily inside `_submit_to_ibkr`. This satisfies spec Requirement 7 explicitly.
- **`TradeCreate.status` field:** confirmed present in `app/schemas/journal.py` as `status: str = "open"` with a default. No verification needed.
