# Pre-Market Scan Latency SLO — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add three Prometheus metrics (`scan_last_success_timestamp`, `scan_data_to_detection_seconds`, `scan_failed_tickers_ratio`), three Grafana alert rules (missed-slot, p95 SLO breach, failed-ticker ratio), and three new Grafana panels to `scanner-performance.json` so pre-market scan health is fully observable and alertable without any schema migration.

**Architecture:** All metrics go in `backend/app/core/metrics.py` and are observed at the tail of each scanner service's run entry-point (after `_persist` returns). Alert rules extend the existing `markethawk-infrastructure` group in `grafana/provisioning/alerting/rules.yaml` (the existing two-refId pattern). Three new panels are appended to `grafana/provisioning/dashboards/scanner-performance.json`. SLO thresholds are env vars (`SCAN_DURATION_SLO_SECONDS`, `SCAN_STALENESS_SLO_SECONDS`) in `Settings`. No Alembic migration. No `prometheus.yml` changes.

**Tech Stack:** Python / prometheus_client, FastAPI / pydantic-settings, Grafana YAML/JSON provisioning.

**Spec:** `docs/superpowers/specs/2026-06-13-scan-latency-slo-design.md` · **Ticket:** #391

---

### Task 1: Add three new Prometheus metrics to metrics.py (TDD)

**Files:**
- Modify: `backend/app/core/metrics.py`
- Modify (test): `backend/tests/core/test_metrics_module.py`

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/core/test_metrics_module.py`:

```python
def test_slo_metrics_registered():
    """New SLO metrics must be importable and of the correct prometheus_client type."""
    from prometheus_client import Gauge, Histogram

    from app.core.metrics import (
        scan_data_to_detection_seconds,
        scan_failed_tickers_ratio,
        scan_last_success_timestamp,
    )

    assert isinstance(scan_last_success_timestamp, Gauge)
    assert scan_last_success_timestamp._name == "scan_last_success_timestamp"
    # multiprocess_mode="livemax" ensures the most-recent write survives across
    # Celery worker processes — verify the kwarg was not omitted.
    assert scan_last_success_timestamp._multiprocess_mode == "livemax"

    assert isinstance(scan_data_to_detection_seconds, Histogram)
    assert scan_data_to_detection_seconds._name == "scan_data_to_detection_seconds"

    assert isinstance(scan_failed_tickers_ratio, Gauge)
    assert scan_failed_tickers_ratio._name == "scan_failed_tickers_ratio"
    assert scan_failed_tickers_ratio._multiprocess_mode == "livemax"


def test_slo_gauge_settable():
    """scan_last_success_timestamp and scan_failed_tickers_ratio must accept .labels().set()."""
    from prometheus_client import REGISTRY

    from app.core.metrics import scan_failed_tickers_ratio, scan_last_success_timestamp

    scan_last_success_timestamp.labels(scanner_type="pre_market_volume_spike").set(
        1234567890.0
    )
    assert (
        REGISTRY.get_sample_value(
            "scan_last_success_timestamp",
            {"scanner_type": "pre_market_volume_spike"},
        )
        == 1234567890.0
    )

    scan_failed_tickers_ratio.labels(scanner_type="pre_market_volume_spike").set(0.05)
    assert (
        REGISTRY.get_sample_value(
            "scan_failed_tickers_ratio",
            {"scanner_type": "pre_market_volume_spike"},
        )
        == 0.05
    )
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
docker-compose exec backend python -m pytest \
  backend/tests/core/test_metrics_module.py::test_slo_metrics_registered \
  backend/tests/core/test_metrics_module.py::test_slo_gauge_settable \
  -x -q 2>&1 | tail -20
```

Expected: `ImportError: cannot import name 'scan_last_success_timestamp'` (or `ModuleNotFoundError`).

- [ ] **Step 3: Add the three metrics to `backend/app/core/metrics.py`**

After the existing `scan_duration_seconds = Histogram(...)` block, add:

```python
scan_last_success_timestamp = Gauge(
    "scan_last_success_timestamp",
    "Unix timestamp of the last successful scan completion",
    ["scanner_type"],
    multiprocess_mode="livemax",
)

scan_data_to_detection_seconds = Histogram(
    "scan_data_to_detection_seconds",
    "Seconds between the freshest bar used and ScannerEvent creation time",
    ["scanner_type"],
    buckets=[30, 60, 120, 300, 600, 900, 1800, 3600],
)

scan_failed_tickers_ratio = Gauge(
    "scan_failed_tickers_ratio",
    "Fraction of tickers that failed in the most recent scan run (0.0–1.0)",
    ["scanner_type"],
    multiprocess_mode="livemax",
)
```

`multiprocess_mode="livemax"` ensures that when multiple Celery worker processes write the same gauge label, Prometheus multiprocess mode returns the maximum value (i.e. the most recent timestamp / most recent failure ratio) rather than summing across all processes.

- [ ] **Step 4: Run tests to verify they pass**

```bash
docker-compose exec backend python -m pytest backend/tests/core/test_metrics_module.py -q 2>&1 | tail -10
```

Expected: All tests in `test_metrics_module.py` pass.

- [ ] **Step 5: Commit**

```bash
git add backend/app/core/metrics.py backend/tests/core/test_metrics_module.py
git commit -m "feat: add scan_last_success_timestamp, scan_data_to_detection_seconds, scan_failed_tickers_ratio metrics (#391)"
```

---

### Task 2: Add SLO env vars to config.py + document in ENV_VARIABLES.md (TDD)

**Files:**
- Modify: `backend/app/core/config.py`
- Modify: `ENV_VARIABLES.md`
- Modify (test): `backend/tests/test_settings.py`

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_settings.py` (outside the existing test classes, at the module level):

```python
def test_scan_slo_defaults():
    """SCAN_DURATION_SLO_SECONDS and SCAN_STALENESS_SLO_SECONDS default to spec values."""
    from app.core.config import Settings

    s = Settings(
        DATABASE_URL="postgresql://test:test@localhost/test",
        POLYGON_API_KEY="test-key",
    )
    assert s.SCAN_DURATION_SLO_SECONDS == 120
    assert s.SCAN_STALENESS_SLO_SECONDS == 900


def test_scan_slo_overridable():
    """SLO fields must accept int overrides from init kwargs."""
    from app.core.config import Settings

    s = Settings(
        DATABASE_URL="postgresql://test:test@localhost/test",
        POLYGON_API_KEY="test-key",
        SCAN_DURATION_SLO_SECONDS=60,
        SCAN_STALENESS_SLO_SECONDS=600,
    )
    assert s.SCAN_DURATION_SLO_SECONDS == 60
    assert s.SCAN_STALENESS_SLO_SECONDS == 600
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
docker-compose exec backend python -m pytest \
  backend/tests/test_settings.py::test_scan_slo_defaults \
  backend/tests/test_settings.py::test_scan_slo_overridable \
  -x -q 2>&1 | tail -10
```

Expected: `AttributeError: 'Settings' object has no attribute 'SCAN_DURATION_SLO_SECONDS'` (or `ValidationError`).

- [ ] **Step 3: Add fields to `backend/app/core/config.py`**

In the `Settings` class, after the last existing field (`VAPID_CLAIMS_EMAIL`, line 114) and before the first `@field_validator`, add:

```python
    # Scanner SLO thresholds — documented in ENV_VARIABLES.md
    SCAN_DURATION_SLO_SECONDS: int = 120
    SCAN_STALENESS_SLO_SECONDS: int = 900
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
docker-compose exec backend python -m pytest backend/tests/test_settings.py -q 2>&1 | tail -10
```

Expected: All tests in `test_settings.py` pass.

- [ ] **Step 5: Document in `ENV_VARIABLES.md`**

Find the section immediately before `## Adding a New Variable` and insert:

```markdown
---

## Scanner SLO

| Variable | Default | Description |
|---|---|---|
| `SCAN_DURATION_SLO_SECONDS` | `120` | p95 scan duration threshold in seconds above which the SLO-breach alert fires (Grafana alert `scan-duration-slo-breach`). |
| `SCAN_STALENESS_SLO_SECONDS` | `900` | Seconds since last successful scan completion before the missed-slot alert fires, when within the 08:00–15:00 UTC pre-market window (Grafana alert `scan-missed-slot-pre-market`). |
```

- [ ] **Step 6: Commit**

```bash
git add backend/app/core/config.py ENV_VARIABLES.md backend/tests/test_settings.py
git commit -m "feat: add SCAN_DURATION_SLO_SECONDS and SCAN_STALENESS_SLO_SECONDS env vars (#391)"
```

---

### Task 3: Instrument pre_market_scan.py with all three metrics (TDD)

**Files:**
- Modify: `backend/app/services/pre_market_scan.py`
- Modify (test): `backend/tests/services/test_pre_market_scan_module.py`

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/services/test_pre_market_scan_module.py`:

```python
def test_pre_market_scan_observes_slo_metrics(db):
    """After a successful run, scan_last_success_timestamp, scan_failed_tickers_ratio,
    and scan_data_to_detection_seconds must all be observed."""
    import asyncio
    import time
    from datetime import date, datetime, timedelta, timezone
    from unittest.mock import MagicMock, patch
    from zoneinfo import ZoneInfo

    from app.models.stock_aggregate import StockAggregate
    from app.services.scanner import ScannerService

    ticker = "SLOM"
    event_date = date(2025, 3, 10)
    _ET = ZoneInfo("America/New_York")
    base_et = datetime.combine(event_date, datetime.min.time(), tzinfo=_ET)

    # Seed 25 daily bars so _detect's 20-bar history check passes
    for i in range(25):
        bar = StockAggregate()
        bar.ticker = ticker
        bar.timestamp = (
            (base_et - timedelta(days=25 - i)).astimezone(timezone.utc).replace(tzinfo=None)
        )
        bar.timespan = "day"
        bar.multiplier = 1
        bar.open = bar.high = bar.low = bar.close = 100.0
        bar.volume = 1_000_000
        bar.is_pre_market = False
        bar.is_after_market = False
        db.add(bar)

    # Seed one pre-market minute bar (5× avg → spike passes, also provides max_bar_ts)
    import datetime as _dt
    pm_ts = datetime.combine(event_date, _dt.time(7, 0), tzinfo=_ET)
    pm_bar = StockAggregate()
    pm_bar.ticker = ticker
    pm_bar.timestamp = pm_ts.astimezone(timezone.utc).replace(tzinfo=None)
    pm_bar.timespan = "minute"
    pm_bar.multiplier = 1
    pm_bar.open = pm_bar.high = pm_bar.low = pm_bar.close = 100.5
    pm_bar.volume = 5_000_000
    pm_bar.is_pre_market = True
    pm_bar.is_after_market = False
    db.add(pm_bar)
    db.flush()

    with (
        patch.object(
            ScannerService,
            "_get_batch_enrichment_data",
            return_value=({"SLOM": {}}, {}, {}),
        ),
        patch.object(
            ScannerService,
            "_save_event",
            return_value={"id": 1, "ticker": ticker, "scanner_type": "pre_market_volume_spike"},
        ),
        patch("app.services.pre_market_scan.scan_last_success_timestamp") as mock_ts,
        patch("app.services.pre_market_scan.scan_failed_tickers_ratio") as mock_ratio,
        patch("app.services.pre_market_scan.scan_data_to_detection_seconds") as mock_dtd,
    ):
        mock_ts_lbl = MagicMock()
        mock_ts.labels.return_value = mock_ts_lbl
        mock_ratio_lbl = MagicMock()
        mock_ratio.labels.return_value = mock_ratio_lbl
        mock_dtd_lbl = MagicMock()
        mock_dtd.labels.return_value = mock_dtd_lbl

        from app.services.pre_market_scan import run_pre_market_scan

        asyncio.run(run_pre_market_scan([ticker], db, event_date=event_date))

    # scan_last_success_timestamp.labels(scanner_type=...).set(<unix ts>)
    mock_ts.labels.assert_called_with(scanner_type="pre_market_volume_spike")
    mock_ts_lbl.set.assert_called_once()
    ts_arg = mock_ts_lbl.set.call_args[0][0]
    assert abs(ts_arg - time.time()) < 30  # within 30s

    # scan_failed_tickers_ratio.labels(scanner_type=...).set(<0.0–1.0>)
    mock_ratio.labels.assert_called_with(scanner_type="pre_market_volume_spike")
    mock_ratio_lbl.set.assert_called_once()
    ratio_arg = mock_ratio_lbl.set.call_args[0][0]
    assert 0.0 <= ratio_arg <= 1.0

    # scan_data_to_detection_seconds: the seeded pm_bar guarantees max_bar_ts is non-null
    mock_dtd.labels.assert_called_with(scanner_type="pre_market_volume_spike")
    mock_dtd_lbl.observe.assert_called_once()
    dtd_arg = mock_dtd_lbl.observe.call_args[0][0]
    assert dtd_arg >= 0  # latency is non-negative seconds
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
docker-compose exec backend python -m pytest \
  "backend/tests/services/test_pre_market_scan_module.py::test_pre_market_scan_observes_slo_metrics" \
  -x -q 2>&1 | tail -20
```

Expected: `AssertionError` or `AttributeError` — the metrics aren't imported or called in `pre_market_scan.py` yet.

- [ ] **Step 3: Implement — update `backend/app/services/pre_market_scan.py`**

**3a.** Update the import at line 13 from:
```python
from app.core.metrics import scan_duration_seconds, scanner_events_total
```
to:
```python
from app.core.metrics import (
    scan_data_to_detection_seconds,
    scan_duration_seconds,
    scan_failed_tickers_ratio,
    scan_last_success_timestamp,
    scanner_events_total,
)
```

**3b.** Replace the existing `scan_duration_seconds.labels(scanner_type="pre_market_volume_spike").observe(...)` block (two lines at the end of `run_pre_market_scan`, after `results = _persist(...)`) with:

```python
    # --- SLO metrics -------------------------------------------------------
    scan_last_success_timestamp.labels(scanner_type="pre_market_volume_spike").set(
        _time.time()
    )
    scan_failed_tickers_ratio.labels(scanner_type="pre_market_volume_spike").set(
        len(failed) / len(tickers) if tickers else 0.0
    )
    # data-to-detection: freshest pre-market minute bar consumed vs. wall-clock now
    _max_bar_ts = (
        db.query(func.max(StockAggregate.timestamp))
        .filter(
            StockAggregate.ticker.in_(tickers),
            StockAggregate.timespan == "minute",
            StockAggregate.is_pre_market == True,
            StockAggregate.timestamp >= day_start_utc,
            StockAggregate.timestamp < day_end_utc,
        )
        .scalar()
    )
    if _max_bar_ts is not None:
        _bar_utc = (
            _max_bar_ts
            if _max_bar_ts.tzinfo
            else _max_bar_ts.replace(tzinfo=timezone.utc)
        )
        scan_data_to_detection_seconds.labels(
            scanner_type="pre_market_volume_spike"
        ).observe((datetime.now(timezone.utc) - _bar_utc).total_seconds())
    scan_duration_seconds.labels(scanner_type="pre_market_volume_spike").observe(
        _time.monotonic() - _start
    )
```

`func` and `StockAggregate` are already imported in the file. `timezone` is already in the `datetime` import at line 5.

- [ ] **Step 4: Run all tests in the file to verify they pass**

```bash
docker-compose exec backend python -m pytest backend/tests/services/test_pre_market_scan_module.py -q 2>&1 | tail -10
```

Expected: All tests pass.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/pre_market_scan.py backend/tests/services/test_pre_market_scan_module.py
git commit -m "feat: instrument pre_market_scan with SLO metrics (last_success, failed_ratio, data_to_detection) (#391)"
```

---

### Task 4: Instrument four evening scanners with scan_last_success_timestamp + scan_failed_tickers_ratio (TDD)

**Files:**
- Modify: `backend/app/services/pocket_pivot.py`, `backend/app/services/liquidity_hunt.py`, `backend/app/services/trend_pullback_scan.py`, `backend/app/services/oversold_bounce_scan.py`
- Modify (tests): `backend/tests/services/test_pocket_pivot.py`, `backend/tests/services/test_liquidity_hunt.py`, `backend/tests/services/test_trend_pullback_scan.py`, `backend/tests/services/test_oversold_bounce_scan_module.py`

- [ ] **Step 1: Write failing tests for each scanner**

**`backend/tests/services/test_pocket_pivot.py`** — append:

```python
def test_pocket_pivot_observes_slo_metrics():
    """scan_last_success_timestamp and scan_failed_tickers_ratio are set after a run."""
    import asyncio
    import time
    from unittest.mock import MagicMock, patch

    with (
        patch("app.services.pocket_pivot._get_today_bar", return_value=None),
        patch("app.services.pocket_pivot._get_prior_close", return_value=None),
        patch("app.services.pocket_pivot._get_lookback_bars", return_value=[]),
        patch("app.services.pocket_pivot._get_enrichment", return_value={}),
        patch("app.services.pocket_pivot._save_event", return_value={}),
        patch("app.services.pocket_pivot.scanner_events_total"),
        patch("app.services.pocket_pivot.scan_duration_seconds"),
        patch("app.services.pocket_pivot.scan_last_success_timestamp") as mock_ts,
        patch("app.services.pocket_pivot.scan_failed_tickers_ratio") as mock_ratio,
    ):
        mock_ts_lbl = MagicMock()
        mock_ts.labels.return_value = mock_ts_lbl
        mock_ratio_lbl = MagicMock()
        mock_ratio.labels.return_value = mock_ratio_lbl

        from app.services.pocket_pivot import run_pocket_pivot_scan

        asyncio.run(
            run_pocket_pivot_scan(
                [], db=MagicMock(), start_date=_EVENT_DATE, end_date=_EVENT_DATE
            )
        )

    mock_ts.labels.assert_called_with(scanner_type="pocket_pivot")
    mock_ts_lbl.set.assert_called_once()
    assert abs(mock_ts_lbl.set.call_args[0][0] - time.time()) < 30
    mock_ratio.labels.assert_called_with(scanner_type="pocket_pivot")
    mock_ratio_lbl.set.assert_called_once()
    assert 0.0 <= mock_ratio_lbl.set.call_args[0][0] <= 1.0
```

**`backend/tests/services/test_trend_pullback_scan.py`** — append:

```python
def test_trend_pullback_observes_slo_metrics():
    """scan_last_success_timestamp and scan_failed_tickers_ratio are set after a run."""
    import asyncio
    import time
    from datetime import date
    from unittest.mock import MagicMock, patch

    with (
        patch("app.services.trend_pullback_scan.scanner_events_total"),
        patch("app.services.trend_pullback_scan.scan_duration_seconds"),
        patch("app.services.trend_pullback_scan.scan_last_success_timestamp") as mock_ts,
        patch("app.services.trend_pullback_scan.scan_failed_tickers_ratio") as mock_ratio,
        patch("app.services.trend_pullback_scan._get_daily_bars", return_value=[]),
    ):
        mock_ts_lbl = MagicMock()
        mock_ts.labels.return_value = mock_ts_lbl
        mock_ratio_lbl = MagicMock()
        mock_ratio.labels.return_value = mock_ratio_lbl

        from app.services.trend_pullback_scan import run_trend_pullback_scan

        asyncio.run(
            run_trend_pullback_scan(
                [], db=MagicMock(), start_date=_EVENT_DATE, end_date=_EVENT_DATE
            )
        )

    mock_ts.labels.assert_called_with(scanner_type="trend_pullback")
    mock_ts_lbl.set.assert_called_once()
    assert abs(mock_ts_lbl.set.call_args[0][0] - time.time()) < 30
    mock_ratio.labels.assert_called_with(scanner_type="trend_pullback")
    mock_ratio_lbl.set.assert_called_once()
    assert 0.0 <= mock_ratio_lbl.set.call_args[0][0] <= 1.0
```

**`backend/tests/services/test_liquidity_hunt.py`** — append:

```python
def test_liquidity_hunt_observes_slo_metrics():
    """scan_last_success_timestamp and scan_failed_tickers_ratio are set after a run."""
    import asyncio
    import time
    from datetime import date
    from unittest.mock import MagicMock, patch

    with (
        patch("app.services.liquidity_hunt.scanner_events_total"),
        patch("app.services.liquidity_hunt.scan_duration_seconds"),
        patch("app.services.liquidity_hunt.scan_last_success_timestamp") as mock_ts,
        patch("app.services.liquidity_hunt.scan_failed_tickers_ratio") as mock_ratio,
    ):
        mock_ts_lbl = MagicMock()
        mock_ts.labels.return_value = mock_ts_lbl
        mock_ratio_lbl = MagicMock()
        mock_ratio.labels.return_value = mock_ratio_lbl

        from app.services.liquidity_hunt import run_liquidity_hunt_scan

        # tickers=[] skips the inner loop; explicit dates avoid get_market_today() call
        asyncio.run(
            run_liquidity_hunt_scan(
                [], db=MagicMock(), start_date=date(2026, 1, 15), end_date=date(2026, 1, 15)
            )
        )

    mock_ts.labels.assert_called_with(scanner_type="liquidity_hunt")
    mock_ts_lbl.set.assert_called_once()
    assert abs(mock_ts_lbl.set.call_args[0][0] - time.time()) < 30
    mock_ratio.labels.assert_called_with(scanner_type="liquidity_hunt")
    mock_ratio_lbl.set.assert_called_once()
    assert 0.0 <= mock_ratio_lbl.set.call_args[0][0] <= 1.0
```

**`backend/tests/services/test_oversold_bounce_scan_module.py`** — append:

```python
def test_oversold_bounce_observes_slo_metrics():
    """scan_last_success_timestamp and scan_failed_tickers_ratio are set after a run."""
    import asyncio
    import time
    from datetime import date
    from unittest.mock import AsyncMock, MagicMock, patch

    with (
        patch("app.services.oversold_bounce_scan.scanner_events_total"),
        patch("app.services.oversold_bounce_scan.scan_duration_seconds"),
        patch("app.services.oversold_bounce_scan.scan_last_success_timestamp") as mock_ts,
        patch("app.services.oversold_bounce_scan.scan_failed_tickers_ratio") as mock_ratio,
        # Patch _get_batch_enrichment_data so the asyncio.to_thread call returns cleanly
        patch(
            "app.services.scanner.ScannerService._get_batch_enrichment_data",
            return_value=({}, {}, {}),
        ),
        # Patch load_ranker_config (called via _scanner_mod inside the function body)
        patch("app.services.scanner.load_ranker_config", return_value={}),
        # Replace asyncio.to_thread with a coroutine that returns the mocked value
        patch("asyncio.to_thread", new=AsyncMock(return_value=({}, {}, {}))),
    ):
        mock_ts_lbl = MagicMock()
        mock_ts.labels.return_value = mock_ts_lbl
        mock_ratio_lbl = MagicMock()
        mock_ratio.labels.return_value = mock_ratio_lbl

        from app.services.oversold_bounce_scan import run_oversold_bounce_scan

        # tickers=[] skips the inner for-ticker loop; all metric observations still execute
        asyncio.run(
            run_oversold_bounce_scan([], db=MagicMock(), event_date=date(2026, 1, 15))
        )

    mock_ts.labels.assert_called_with(scanner_type="oversold_bounce")
    mock_ts_lbl.set.assert_called_once()
    assert abs(mock_ts_lbl.set.call_args[0][0] - time.time()) < 30
    mock_ratio.labels.assert_called_with(scanner_type="oversold_bounce")
    mock_ratio_lbl.set.assert_called_once()
    assert 0.0 <= mock_ratio_lbl.set.call_args[0][0] <= 1.0
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
docker-compose exec backend python -m pytest \
  backend/tests/services/test_pocket_pivot.py::test_pocket_pivot_observes_slo_metrics \
  backend/tests/services/test_trend_pullback_scan.py::test_trend_pullback_observes_slo_metrics \
  backend/tests/services/test_liquidity_hunt.py::test_liquidity_hunt_observes_slo_metrics \
  backend/tests/services/test_oversold_bounce_scan_module.py::test_oversold_bounce_observes_slo_metrics \
  -x -q 2>&1 | tail -20
```

Expected: All four fail — `scan_last_success_timestamp` is not imported or called yet.

- [ ] **Step 3: Implement — update each scanner service file**

**3a. `backend/app/services/pocket_pivot.py`** (line 22)

Replace:
```python
from app.core.metrics import scan_duration_seconds, scanner_events_total
```
with:
```python
from app.core.metrics import (
    scan_duration_seconds,
    scan_failed_tickers_ratio,
    scan_last_success_timestamp,
    scanner_events_total,
)
```

Immediately before the existing `scan_duration_seconds.labels(scanner_type="pocket_pivot").observe(...)` line (around line 362), insert:

```python
    scan_last_success_timestamp.labels(scanner_type="pocket_pivot").set(_time.time())
    scan_failed_tickers_ratio.labels(scanner_type="pocket_pivot").set(
        counts["errors"] / max(1, len(tickers) * len(trading_days))
    )
```

**3b. `backend/app/services/liquidity_hunt.py`** (line 25)

Replace:
```python
from app.core.metrics import scan_duration_seconds, scanner_events_total
```
with:
```python
from app.core.metrics import (
    scan_duration_seconds,
    scan_failed_tickers_ratio,
    scan_last_success_timestamp,
    scanner_events_total,
)
```

Immediately before the existing `scan_duration_seconds.labels(scanner_type="liquidity_hunt").observe(...)` line (around line 633), insert:

```python
    scan_last_success_timestamp.labels(scanner_type="liquidity_hunt").set(_time.time())
    scan_failed_tickers_ratio.labels(scanner_type="liquidity_hunt").set(
        counts["errors"] / max(1, len(tickers) * len(trading_days))
    )
```

**3c. `backend/app/services/trend_pullback_scan.py`** (line 23)

Replace:
```python
from app.core.metrics import scan_duration_seconds, scanner_events_total
```
with:
```python
from app.core.metrics import (
    scan_duration_seconds,
    scan_failed_tickers_ratio,
    scan_last_success_timestamp,
    scanner_events_total,
)
```

Immediately before the existing `scan_duration_seconds.labels(scanner_type="trend_pullback").observe(...)` line (around line 372), insert:

```python
    scan_last_success_timestamp.labels(scanner_type="trend_pullback").set(_time.time())
    scan_failed_tickers_ratio.labels(scanner_type="trend_pullback").set(
        counts["errors"] / max(1, len(tickers) * len(trading_days))
    )
```

**3d. `backend/app/services/oversold_bounce_scan.py`** (line 11)

Replace:
```python
from app.core.metrics import scan_duration_seconds, scanner_events_total
```
with:
```python
from app.core.metrics import (
    scan_duration_seconds,
    scan_failed_tickers_ratio,
    scan_last_success_timestamp,
    scanner_events_total,
)
```

Immediately before the existing `scan_duration_seconds.labels(scanner_type="oversold_bounce").observe(...)` line (around line 210), insert:

```python
    scan_last_success_timestamp.labels(scanner_type="oversold_bounce").set(_time.time())
    scan_failed_tickers_ratio.labels(scanner_type="oversold_bounce").set(
        len(failed) / max(1, len(tickers))
    )
```

Note: `oversold_bounce` uses a `failed` list (not `counts["errors"]`) and is single-date (no `trading_days` variable) — identical pattern to `pre_market_scan.py`.

- [ ] **Step 4: Run all tests to verify they pass**

```bash
docker-compose exec backend python -m pytest \
  backend/tests/services/test_pocket_pivot.py \
  backend/tests/services/test_trend_pullback_scan.py \
  backend/tests/services/test_liquidity_hunt.py \
  backend/tests/services/test_oversold_bounce_scan_module.py \
  -q 2>&1 | tail -10
```

Expected: All tests in all four files pass.

- [ ] **Step 5: Commit**

```bash
git add \
  backend/app/services/pocket_pivot.py \
  backend/app/services/liquidity_hunt.py \
  backend/app/services/trend_pullback_scan.py \
  backend/app/services/oversold_bounce_scan.py \
  backend/tests/services/test_pocket_pivot.py \
  backend/tests/services/test_liquidity_hunt.py \
  backend/tests/services/test_trend_pullback_scan.py \
  backend/tests/services/test_oversold_bounce_scan_module.py
git commit -m "feat: instrument evening scanners (pocket_pivot, liquidity_hunt, trend_pullback, oversold_bounce) with SLO metrics (#391)"
```

---

### Task 5: Add three alert rules to grafana/provisioning/alerting/rules.yaml

**Files:**
- Modify: `grafana/provisioning/alerting/rules.yaml`

- [ ] **Step 1: Validate current YAML is parseable**

```bash
python3 -c "import yaml; yaml.safe_load(open('grafana/provisioning/alerting/rules.yaml')); print('OK')"
```

Expected: `OK`.

- [ ] **Step 2: Append three rules inside the `markethawk-infrastructure` group's `rules:` list**

After the last existing rule in `grafana/provisioning/alerting/rules.yaml` (currently the `tweet-monitor-auth-expired` rule block, which ends with `expression: $B < 1`), and still inside the `rules:` list of the `markethawk-infrastructure` group, append:

```yaml
      - uid: scan-missed-slot-pre-market
        title: Pre-Market Scan Missed Slot
        condition: C
        for: 0m
        annotations:
          summary: >
            pre_market_volume_spike has not completed successfully for >15 min
            during the pre-market window (04:00–09:30 ET). Check Celery worker health.
        labels:
          severity: critical
        data:
          - refId: B
            relativeTimeRange:
              from: 60
              to: 0
            datasourceUid: prometheus
            model:
              # Time since last successful scan. SCAN_STALENESS_SLO_SECONDS default: 900
              expr: time() - scan_last_success_timestamp{scanner_type="pre_market_volume_spike"}
              refId: B
          - refId: C
            relativeTimeRange:
              from: 60
              to: 0
            datasourceUid: "-- Grafana --"
            model:
              type: math
              # Gate to 08:00–15:00 UTC via Grafana alert rule "Active time range"
              # (weekdays, 08:00–15:00 UTC) in the Grafana UI after provisioning.
              expression: $B > 900

      - uid: scan-duration-slo-breach
        title: Scanner p95 Duration Exceeds SLO
        condition: C
        for: 5m
        annotations:
          summary: >
            {{ $labels.scanner_type }} p95 scan duration exceeds the 120-second SLO.
            Tune threshold via SCAN_DURATION_SLO_SECONDS env var.
        labels:
          severity: warning
        data:
          - refId: B
            relativeTimeRange:
              from: 900
              to: 0
            datasourceUid: prometheus
            model:
              # SCAN_DURATION_SLO_SECONDS default: 120
              expr: >
                histogram_quantile(0.95,
                  sum(rate(scan_duration_seconds_bucket[15m])) by (le, scanner_type)
                )
              refId: B
          - refId: C
            relativeTimeRange:
              from: 900
              to: 0
            datasourceUid: "-- Grafana --"
            model:
              type: math
              expression: $B > 120

      - uid: scan-high-failed-ticker-ratio
        title: Scanner High Failed-Ticker Ratio
        condition: C
        for: 0m
        annotations:
          summary: >
            {{ $labels.scanner_type }} had >10% failed tickers on the last run.
            Check provider connectivity (Polygon/IBKR) or universe health.
        labels:
          severity: warning
        data:
          - refId: B
            relativeTimeRange:
              from: 300
              to: 0
            datasourceUid: prometheus
            model:
              expr: scan_failed_tickers_ratio
              refId: B
          - refId: C
            relativeTimeRange:
              from: 300
              to: 0
            datasourceUid: "-- Grafana --"
            model:
              type: math
              expression: $B > 0.1
```

- [ ] **Step 3: Validate YAML is parseable and contains all three new rule UIDs**

```bash
python3 -c "
import yaml
doc = yaml.safe_load(open('grafana/provisioning/alerting/rules.yaml'))
rules = doc['groups'][0]['rules']
uids = [r['uid'] for r in rules]
print(f'Total rules: {len(rules)}')
assert len(rules) == 8, f'expected 8 (5 existing + 3 new), got {len(rules)}'
assert 'scan-missed-slot-pre-market' in uids, 'missing scan-missed-slot-pre-market'
assert 'scan-duration-slo-breach' in uids, 'missing scan-duration-slo-breach'
assert 'scan-high-failed-ticker-ratio' in uids, 'missing scan-high-failed-ticker-ratio'
print('All three alert rules present — OK')
"
```

Expected: `Total rules: 8`, `All three alert rules present — OK`.

- [ ] **Step 4: Commit**

```bash
git add grafana/provisioning/alerting/rules.yaml
git commit -m "feat: add scan missed-slot, p95 SLO breach, and failed-ticker ratio Grafana alert rules (#391)"
```

---

### Task 6: Add three panels to grafana/provisioning/dashboards/scanner-performance.json

**Files:**
- Modify: `grafana/provisioning/dashboards/scanner-performance.json`

- [ ] **Step 1: Validate current JSON is parseable**

```bash
python3 -c "
import json
d = json.load(open('grafana/provisioning/dashboards/scanner-performance.json'))
print(f'panels: {len(d[\"panels\"])}')
"
```

Expected: `panels: 5`.

- [ ] **Step 2: Add three panels**

Use a parse-modify-dump approach to avoid fragile text-level bracket matching. Run this Python script from the repo root:

```bash
python3 - <<'EOF'
import json

path = "grafana/provisioning/dashboards/scanner-performance.json"
d = json.load(open(path))

d["panels"].extend([
    {
      "id": 6,
      "title": "Scan Duration P95 (s) — SLO 120s",
      "type": "timeseries",
      "gridPos": { "h": 8, "w": 24, "x": 0, "y": 24 },
      "fieldConfig": {
        "defaults": {
          "unit": "s",
          "thresholds": {
            "mode": "absolute",
            "steps": [
              { "color": "green", "value": null },
              { "color": "red", "value": 120 }
            ]
          },
          "custom": {
            "thresholdsStyle": { "mode": "line" }
          }
        }
      },
      "targets": [
        {
          "datasource": { "type": "prometheus", "uid": "$datasource" },
          "expr": "histogram_quantile(0.95, sum(rate(scan_duration_seconds_bucket[5m])) by (le, scanner_type))",
          "legendFormat": "p95 {{scanner_type}}"
        }
      ]
    },
    {
      "id": 7,
      "title": "Last-Success Age (s)",
      "type": "stat",
      "gridPos": { "h": 8, "w": 12, "x": 0, "y": 32 },
      "options": {
        "colorMode": "background"
      },
      "fieldConfig": {
        "defaults": {
          "unit": "s",
          "thresholds": {
            "mode": "absolute",
            "steps": [
              { "color": "green", "value": null },
              { "color": "yellow", "value": 600 },
              { "color": "red", "value": 900 }
            ]
          }
        }
      },
      "targets": [
        {
          "datasource": { "type": "prometheus", "uid": "$datasource" },
          "expr": "time() - scan_last_success_timestamp",
          "legendFormat": "{{scanner_type}}"
        }
      ]
    },
    {
      "id": 8,
      "title": "Bar-to-Signal Latency p50 (s)",
      "type": "stat",
      "gridPos": { "h": 8, "w": 12, "x": 12, "y": 32 },
      "options": {
        "colorMode": "background"
      },
      "fieldConfig": {
        "defaults": {
          "unit": "s",
          "thresholds": {
            "mode": "absolute",
            "steps": [
              { "color": "green", "value": null },
              { "color": "yellow", "value": 300 },
              { "color": "red", "value": 600 }
            ]
          }
        }
      },
      "targets": [
        {
          "datasource": { "type": "prometheus", "uid": "$datasource" },
          "expr": "histogram_quantile(0.50, sum(rate(scan_data_to_detection_seconds_bucket[15m])) by (le, scanner_type))",
          "legendFormat": "{{scanner_type}}"
        }
      ]
    }
])

json.dump(d, open(path, "w"), indent=2)
print(f"panels after: {len(d['panels'])}")
EOF
```

- [ ] **Step 3: Validate JSON is parseable and has 8 panels**

```bash
python3 -c "
import json
d = json.load(open('grafana/provisioning/dashboards/scanner-performance.json'))
assert len(d['panels']) == 8, f'expected 8 panels, got {len(d[\"panels\"])}'
ids = [p['id'] for p in d['panels']]
assert 6 in ids and 7 in ids and 8 in ids, f'missing new panel IDs; got {ids}'
titles = {p['id']: p['title'] for p in d['panels']}
assert 'SLO 120s' in titles[6], f'panel 6 title unexpected: {titles[6]}'
assert 'Last-Success' in titles[7], f'panel 7 title unexpected: {titles[7]}'
assert 'Bar-to-Signal' in titles[8], f'panel 8 title unexpected: {titles[8]}'
print(f'panels: {len(d[\"panels\"])} — OK')
"
```

Expected: `panels: 8 — OK`.

- [ ] **Step 4: Commit**

```bash
git add grafana/provisioning/dashboards/scanner-performance.json
git commit -m "feat: add scan duration P95, last-success age, bar-to-signal latency panels to scanner-performance dashboard (#391)"
```

---

## File Structure

| File | Change |
|---|---|
| `backend/app/core/metrics.py` | + `scan_last_success_timestamp` Gauge, `scan_data_to_detection_seconds` Histogram, `scan_failed_tickers_ratio` Gauge |
| `backend/app/core/config.py` | + `SCAN_DURATION_SLO_SECONDS: int = 120`, `SCAN_STALENESS_SLO_SECONDS: int = 900` |
| `backend/app/services/pre_market_scan.py` | + import 3 new metrics; + 3 observation blocks after `_persist` |
| `backend/app/services/pocket_pivot.py` | + import 2 new metrics; + 2 observation lines before `scan_duration_seconds.observe` |
| `backend/app/services/liquidity_hunt.py` | Same as pocket_pivot |
| `backend/app/services/trend_pullback_scan.py` | Same as pocket_pivot |
| `backend/app/services/oversold_bounce_scan.py` | Same as pocket_pivot (uses `len(failed)` instead of `counts["errors"]`) |
| `grafana/provisioning/alerting/rules.yaml` | + 3 alert rules in `markethawk-infrastructure` group |
| `grafana/provisioning/dashboards/scanner-performance.json` | + 3 panels (id 6, 7, 8; rows y=24 and y=32) |
| `ENV_VARIABLES.md` | + Scanner SLO section |
| `backend/tests/core/test_metrics_module.py` | + 2 new test functions |
| `backend/tests/test_settings.py` | + 2 new test functions |
| `backend/tests/services/test_pre_market_scan_module.py` | + 1 new test function |
| `backend/tests/services/test_pocket_pivot.py` | + 1 new test function |
| `backend/tests/services/test_liquidity_hunt.py` | + 1 new test function |
| `backend/tests/services/test_trend_pullback_scan.py` | + 1 new test function |
| `backend/tests/services/test_oversold_bounce_scan_module.py` | + 1 new test function |

**No migration** — no new SQLAlchemy model fields.
**No `prometheus.yml` changes** — all alerts use Grafana's native alerting engine.
