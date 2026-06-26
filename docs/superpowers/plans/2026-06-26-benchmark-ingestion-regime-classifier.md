# Implementation Plan — Benchmark Ingestion + Regime Classifier

**Goal:** Create the `services/replay/` sub-package with `BenchmarkIngestor` (gap-fill daily bars into
`StockAggregate`) and `RegimeClassifier` (deterministic SMA200 + realized-vol labeler), plus the
`get_benchmark_regime` lookup helper. No new DB tables — benchmark bars reuse `stock_aggregates`.

**Issue:** #486 (sub-issue 3 of the Canonical Signal Replay Engine epic)  
**Spec:** `docs/superpowers/specs/2026-06-21-benchmark-ingestion-regime-classifier-design.md`  
**Date:** 2026-06-26

---

## Architecture

New `services/replay/` sub-package alongside existing services. No migration, no new Docker container,
no new model. Benchmark bars reuse the existing `stock_aggregates` table and schema.

`RegimeClassifier` is fully separate from `RegimeService` — the HMM service is nondeterministic
(rolling retrain) and incompatible with replay reproducibility.

---

## Tech Stack

- **Language/runtime:** Python 3.11, FastAPI app context
- **Data:** SQLAlchemy `Session` (sync), `StockAggregate` model, `MassiveDataProvider.get_bars()`
- **Computation:** `pandas` (rolling SMA, rolling std), `math.sqrt(252)` for annualization
- **Tests:** `pytest` with `MagicMock` for DB and provider (unit tests of isolated service logic —
  not full-pipeline regression tests, which require the transaction-rollback fixture)

---

## File Structure

| File | Status | Purpose |
|------|--------|---------|
| `backend/app/services/replay/__init__.py` | New | Package marker + public re-exports |
| `backend/app/services/replay/benchmark.py` | New | `BenchmarkIngestionError`, `BenchmarkIngestor` |
| `backend/app/services/replay/classifier.py` | New | `ReplayRegime`, `RegimeClassifier`, `get_benchmark_regime` |
| `backend/tests/services/test_benchmark_ingestor.py` | New | Unit tests for `BenchmarkIngestor` |
| `backend/tests/services/test_regime_classifier.py` | New | Unit tests for `RegimeClassifier` and helper |

---

## Task 1 — `services/replay/` package skeleton + `BenchmarkIngestor` (TDD)

**Files:** `backend/app/services/replay/__init__.py`, `backend/app/services/replay/benchmark.py`,
`backend/tests/services/test_benchmark_ingestor.py`

### 1.1 — Write failing tests

Create `backend/tests/services/test_benchmark_ingestor.py`:

```python
"""Unit tests for BenchmarkIngestor — gap-fill daily bars into StockAggregate."""
from collections import namedtuple
from datetime import date, datetime, timezone
from unittest.mock import MagicMock, call

import pytest

from app.exceptions import ProviderError


def _make_provider(bars=None):
    p = MagicMock()
    p.get_bars.return_value = bars if bars is not None else []
    return p


def _make_db(existing_timestamps=None):
    """Mock DB session. existing_timestamps is a list of naive UTC datetimes."""
    db = MagicMock()
    existing = existing_timestamps or []
    db.query.return_value.filter.return_value.all.return_value = [
        (ts,) for ts in existing
    ]
    return db


def _daily_bar(d: date, close: float = 593.0):
    return {
        "timestamp": datetime(d.year, d.month, d.day, tzinfo=timezone.utc),
        "open": close - 1.0,
        "high": close + 2.0,
        "low": close - 2.0,
        "close": close,
        "volume": 50_000_000,
        "vwap": close,
        "transactions": 500_000,
    }


class TestBenchmarkIngestorHappyPath:
    def test_inserts_bars_when_db_empty(self):
        from app.services.replay.benchmark import BenchmarkIngestor

        start = date(2026, 1, 5)  # Monday
        end = date(2026, 1, 7)    # Wednesday
        bars = [_daily_bar(date(2026, 1, d)) for d in (5, 6, 7)]

        ingestor = BenchmarkIngestor(_make_provider(bars))
        count = ingestor.ingest("SPY", start, end, _make_db())

        assert count == 3

    def test_commit_called_after_bulk_save(self):
        from app.services.replay.benchmark import BenchmarkIngestor

        bars = [_daily_bar(date(2026, 1, 5))]
        db = _make_db()
        ingestor = BenchmarkIngestor(_make_provider(bars))
        ingestor.ingest("SPY", date(2026, 1, 5), date(2026, 1, 5), db)

        db.bulk_save_objects.assert_called_once()
        db.commit.assert_called_once()

    def test_symbol_is_parameter_not_hardcoded(self):
        from app.services.replay.benchmark import BenchmarkIngestor

        bars = [_daily_bar(date(2026, 1, 5))]
        provider = _make_provider(bars)
        db = _make_db()
        ingestor = BenchmarkIngestor(provider)
        ingestor.ingest("QQQ", date(2026, 1, 5), date(2026, 1, 5), db)

        call_kwargs = provider.get_bars.call_args
        assert call_kwargs.kwargs.get("symbol") == "QQQ" or call_kwargs.args[0] == "QQQ"


class TestBenchmarkIngestorIdempotency:
    def test_returns_zero_when_all_bars_present(self):
        from app.services.replay.benchmark import BenchmarkIngestor

        # All 3 weekdays already in DB
        existing = [
            datetime(2026, 1, 5, 0, 0, 0),
            datetime(2026, 1, 6, 0, 0, 0),
            datetime(2026, 1, 7, 0, 0, 0),
        ]
        db = _make_db(existing)
        provider = _make_provider()
        ingestor = BenchmarkIngestor(provider)
        count = ingestor.ingest("SPY", date(2026, 1, 5), date(2026, 1, 7), db)

        assert count == 0
        provider.get_bars.assert_not_called()

    def test_no_polygon_call_when_fully_covered(self):
        from app.services.replay.benchmark import BenchmarkIngestor

        existing = [datetime(2026, 1, 5, 0, 0, 0)]
        provider = _make_provider()
        db = _make_db(existing)
        ingestor = BenchmarkIngestor(provider)
        ingestor.ingest("SPY", date(2026, 1, 5), date(2026, 1, 5), db)

        provider.get_bars.assert_not_called()


class TestBenchmarkIngestorInteriorGap:
    def test_detects_interior_missing_days(self):
        """Mon+Fri in DB, fetch Tue–Thu (interior gap), insert only Tue/Wed/Thu."""
        from app.services.replay.benchmark import BenchmarkIngestor

        # Mon=Jan5, Fri=Jan9 are present; Tue=Jan6, Wed=Jan7, Thu=Jan8 are missing
        existing = [datetime(2026, 1, 5, 0, 0, 0), datetime(2026, 1, 9, 0, 0, 0)]
        new_bars = [_daily_bar(date(2026, 1, d)) for d in (6, 7, 8)]
        provider = _make_provider(new_bars)
        db = _make_db(existing)

        ingestor = BenchmarkIngestor(provider)
        count = ingestor.ingest("SPY", date(2026, 1, 5), date(2026, 1, 9), db)

        assert count == 3

    def test_skips_already_present_bars_from_polygon_response(self):
        """If Polygon returns bars that already exist in DB, they are not re-inserted."""
        from app.services.replay.benchmark import BenchmarkIngestor

        existing = [datetime(2026, 1, 5, 0, 0, 0)]  # Mon already present
        # Provider returns Mon (already exists) + Tue (new)
        bars = [_daily_bar(date(2026, 1, d)) for d in (5, 6)]
        db = _make_db(existing)

        ingestor = BenchmarkIngestor(_make_provider(bars))
        count = ingestor.ingest("SPY", date(2026, 1, 5), date(2026, 1, 6), db)

        assert count == 1  # Only Tue inserted


class TestBenchmarkIngestorErrorHandling:
    def test_provider_error_raises_ingestion_error(self):
        from app.services.replay.benchmark import BenchmarkIngestor, BenchmarkIngestionError

        provider = MagicMock()
        provider.get_bars.side_effect = ProviderError(
            "Polygon down", provider="massive", endpoint="get_aggs", is_retryable=True
        )
        db = _make_db()

        ingestor = BenchmarkIngestor(provider)
        with pytest.raises(BenchmarkIngestionError) as exc_info:
            ingestor.ingest("SPY", date(2026, 1, 5), date(2026, 1, 7), db)

        assert "SPY" in str(exc_info.value)
        assert exc_info.value.symbol == "SPY"

    def test_generic_exception_wrapped_in_ingestion_error(self):
        from app.services.replay.benchmark import BenchmarkIngestor, BenchmarkIngestionError

        provider = MagicMock()
        provider.get_bars.side_effect = RuntimeError("network timeout")
        db = _make_db()

        ingestor = BenchmarkIngestor(provider)
        with pytest.raises(BenchmarkIngestionError):
            ingestor.ingest("SPY", date(2026, 1, 5), date(2026, 1, 7), db)
```

### 1.2 — Verify tests fail

```bash
docker-compose exec backend python -m pytest tests/services/test_benchmark_ingestor.py -v 2>&1 | tail -20
# Expected: ModuleNotFoundError: No module named 'app.services.replay'
```

### 1.3 — Create package skeleton

```bash
mkdir -p backend/app/services/replay
touch backend/app/services/replay/__init__.py
```

### 1.4 — Implement `benchmark.py`

Create `backend/app/services/replay/benchmark.py`:

```python
import logging
import math
from datetime import date, datetime, timedelta
from typing import List

from sqlalchemy.orm import Session

from app.exceptions import ProviderError
from app.models.stock_aggregate import StockAggregate
from app.providers.massive import MassiveDataProvider

logger = logging.getLogger(__name__)


class BenchmarkIngestionError(Exception):
    def __init__(self, symbol: str, start: date, end: date, cause: Exception):
        super().__init__(
            f"Benchmark ingestion failed for {symbol} [{start}, {end}]: {cause}"
        )
        self.symbol = symbol
        self.cause = cause


def _weekdays_in_range(start_date: date, end_date: date) -> set:
    """Return all Mon–Fri in [start_date, end_date] as naive UTC datetimes at 00:00."""
    days: set = set()
    current = start_date
    while current <= end_date:
        if current.weekday() < 5:
            days.add(datetime(current.year, current.month, current.day, 0, 0, 0))
        current += timedelta(days=1)
    return days


class BenchmarkIngestor:
    def __init__(self, provider: MassiveDataProvider):
        self._provider = provider

    def ingest(
        self,
        symbol: str,
        start_date: date,
        end_date: date,
        db: Session,
    ) -> int:
        """
        Ensures daily bars for `symbol` over [start_date, end_date] exist in
        stock_aggregates. Returns the count of newly inserted rows.
        Raises BenchmarkIngestionError on provider failure.
        """
        # 1. Query existing naive-UTC timestamps for this symbol in the range
        start_dt = datetime(start_date.year, start_date.month, start_date.day, 0, 0, 0)
        end_dt = datetime(end_date.year, end_date.month, end_date.day, 23, 59, 59)

        existing_ts: set = set(
            r[0]
            for r in db.query(StockAggregate.timestamp)
            .filter(
                StockAggregate.ticker == symbol,
                StockAggregate.timespan == "day",
                StockAggregate.multiplier == 1,
                StockAggregate.timestamp >= start_dt,
                StockAggregate.timestamp <= end_dt,
            )
            .all()
        )

        # 2. Compute expected weekdays in the range
        expected = _weekdays_in_range(start_date, end_date)

        # 3. Early exit if DB already covers all expected weekdays
        missing = expected - existing_ts
        if not missing:
            return 0

        # 4. Fetch [min(missing), max(missing)] from Polygon in a single call
        min_date = min(missing).date()
        max_date = max(missing).date()

        try:
            bars = self._provider.get_bars(
                symbol=symbol,
                timespan="day",
                multiplier=1,
                from_date=str(min_date),
                to_date=str(max_date),
            )
        except ProviderError as e:
            raise BenchmarkIngestionError(symbol, start_date, end_date, cause=e) from e
        except Exception as e:
            raise BenchmarkIngestionError(symbol, start_date, end_date, cause=e) from e

        if not bars:
            # Provider returned no bars (e.g., all missing days are holidays) — idempotent 0
            return 0

        # 5. Build StockAggregate rows for timestamps not already in DB
        #    Polygon timestamps are timezone-aware; store as naive UTC (existing pattern)
        new_rows: List[StockAggregate] = []
        for bar in bars:
            ts_utc = bar["timestamp"]
            ts_naive = ts_utc.replace(tzinfo=None)
            # Normalize to day boundary (discard sub-day precision for daily bars)
            ts_day = datetime(ts_naive.year, ts_naive.month, ts_naive.day, 0, 0, 0)
            if ts_day in existing_ts:
                continue
            new_rows.append(
                StockAggregate(
                    ticker=symbol,
                    timestamp=ts_day,
                    multiplier=1,
                    timespan="day",
                    open=bar["open"],
                    high=bar["high"],
                    low=bar["low"],
                    close=bar["close"],
                    volume=bar["volume"],
                    vwap=bar["vwap"],
                    transactions=bar["transactions"],
                    is_pre_market=False,
                    is_after_market=False,
                    provider="polygon",
                )
            )

        if not new_rows:
            return 0

        db.bulk_save_objects(new_rows)
        db.commit()
        logger.info(
            "BenchmarkIngestor: %s inserted %d daily bars (%s → %s)",
            symbol,
            len(new_rows),
            min_date,
            max_date,
        )
        return len(new_rows)
```

### 1.5 — Update `__init__.py` with initial re-exports

```python
# backend/app/services/replay/__init__.py
from app.services.replay.benchmark import BenchmarkIngestionError, BenchmarkIngestor

__all__ = ["BenchmarkIngestor", "BenchmarkIngestionError"]
```

### 1.6 — Verify tests pass

```bash
docker-compose exec backend python -m pytest tests/services/test_benchmark_ingestor.py -v 2>&1 | tail -20
# Expected: all tests green
```

### 1.7 — Commit

```bash
git add backend/app/services/replay/__init__.py \
        backend/app/services/replay/benchmark.py \
        backend/tests/services/test_benchmark_ingestor.py
git commit -m "feat(replay): BenchmarkIngestor with gap-fill idempotent ingestion (#486)"
```

---

## Task 2 — `RegimeClassifier` and `get_benchmark_regime` (TDD)

**Files:** `backend/app/services/replay/classifier.py`,
`backend/tests/services/test_regime_classifier.py`

### 2.1 — Write failing tests

Create `backend/tests/services/test_regime_classifier.py`:

```python
"""Unit tests for RegimeClassifier and get_benchmark_regime."""
import math
from collections import namedtuple
from datetime import date, datetime
from decimal import Decimal
from unittest.mock import MagicMock

import pytest


Row = namedtuple("Row", ["timestamp", "close"])


def _make_db_with_rows(rows):
    db = MagicMock()
    db.query.return_value.filter.return_value.order_by.return_value.all.return_value = rows
    return db


def _make_rows(closes: list, start_date: date = date(2023, 1, 2)):
    """Build Row objects for consecutive weekdays starting at start_date."""
    from datetime import timedelta

    rows = []
    d = start_date
    for c in closes:
        while d.weekday() >= 5:
            d += timedelta(days=1)
        rows.append(Row(timestamp=datetime(d.year, d.month, d.day), close=Decimal(str(c))))
        d += timedelta(days=1)
    return rows


class TestRegimeClassifierTrend:
    def test_bull_when_close_above_sma200(self):
        from app.services.replay.classifier import RegimeClassifier, ReplayRegime

        # 200 bars at close=100, then day 201 at close=100.01 → bull
        closes = [100.0] * 200 + [100.01]
        rows = _make_rows(closes)
        last_date = rows[-1].timestamp.date()

        classifier = RegimeClassifier("SPY")
        classifier.classify(last_date, last_date, _make_db_with_rows(rows))

        regime = classifier._regime_map[last_date]
        assert regime.trend == "bull"

    def test_bear_when_close_equals_sma200(self):
        from app.services.replay.classifier import RegimeClassifier

        # 200 bars at close=100, then day 201 at close=100 → bear (close ≤ SMA200)
        closes = [100.0] * 201
        rows = _make_rows(closes)
        last_date = rows[-1].timestamp.date()

        classifier = RegimeClassifier("SPY")
        classifier.classify(last_date, last_date, _make_db_with_rows(rows))

        assert classifier._regime_map[last_date].trend == "bear"

    def test_bear_when_close_below_sma200(self):
        from app.services.replay.classifier import RegimeClassifier

        closes = [100.0] * 200 + [99.0]
        rows = _make_rows(closes)
        last_date = rows[-1].timestamp.date()

        classifier = RegimeClassifier("SPY")
        classifier.classify(last_date, last_date, _make_db_with_rows(rows))

        assert classifier._regime_map[last_date].trend == "bear"

    def test_unknown_when_fewer_than_200_prior_bars(self):
        from app.services.replay.classifier import RegimeClassifier

        # Only 199 bars total — first (and only) classifiable day has <200 prior bars
        closes = [100.0] * 199
        rows = _make_rows(closes)
        last_date = rows[-1].timestamp.date()

        classifier = RegimeClassifier("SPY")
        classifier.classify(last_date, last_date, _make_db_with_rows(rows))

        assert classifier._regime_map[last_date].trend == "unknown"


class TestRegimeClassifierVol:
    def _build_rows_with_vol(self, target_annualized_vol: float, n_warmup: int = 230):
        """
        Build rows whose trailing-20d realized vol approximates target_annualized_vol.
        First n_warmup rows are flat (vol=0 baseline); last 20 vary by a fixed daily return
        that produces the desired annualized vol.
        """
        # daily return that gives target annualized vol:
        # std(log_returns) * sqrt(252) = target_annualized_vol
        # → daily_std = target_annualized_vol / sqrt(252)
        daily_std = target_annualized_vol / math.sqrt(252)
        # Alternate +daily_std and -daily_std over 21 bars to produce that std
        closes = [100.0] * n_warmup
        price = 100.0
        for i in range(21):
            direction = 1 if i % 2 == 0 else -1
            price *= math.exp(direction * daily_std)
            closes.append(price)
        return _make_rows(closes)

    def test_calm_bucket(self):
        from app.services.replay.classifier import RegimeClassifier

        rows = self._build_rows_with_vol(0.05)  # 5% annualized → calm
        last_date = rows[-1].timestamp.date()
        # Need enough bars for SMA200 too
        classifier = RegimeClassifier("SPY")
        classifier.classify(last_date, last_date, _make_db_with_rows(rows))
        assert classifier._regime_map[last_date].vol == "calm"

    def test_turbulent_bucket(self):
        from app.services.replay.classifier import RegimeClassifier

        rows = self._build_rows_with_vol(0.35)  # 35% annualized → turbulent
        last_date = rows[-1].timestamp.date()
        classifier = RegimeClassifier("SPY")
        classifier.classify(last_date, last_date, _make_db_with_rows(rows))
        assert classifier._regime_map[last_date].vol == "turbulent"

    def test_normal_bucket(self):
        from app.services.replay.classifier import RegimeClassifier

        rows = self._build_rows_with_vol(0.15)  # 15% annualized → normal
        last_date = rows[-1].timestamp.date()
        classifier = RegimeClassifier("SPY")
        classifier.classify(last_date, last_date, _make_db_with_rows(rows))
        assert classifier._regime_map[last_date].vol == "normal"

    def test_vol_normal_when_fewer_than_20_prior_bars(self):
        from app.services.replay.classifier import RegimeClassifier

        # Only 10 bars — not enough for 20d vol window
        closes = [100.0] * 10
        rows = _make_rows(closes)
        last_date = rows[-1].timestamp.date()
        classifier = RegimeClassifier("SPY")
        classifier.classify(last_date, last_date, _make_db_with_rows(rows))
        # trend="unknown" (< 200 bars), vol="normal" (< 20 bars)
        assert classifier._regime_map[last_date].vol == "normal"


class TestRegimeClassifierThresholds:
    def test_custom_thresholds_override_defaults(self):
        from app.services.replay.classifier import RegimeClassifier

        # With calm_below=0.30, turbulent_above=0.50, 15% vol → calm
        thresholds = {"calm_below": 0.30, "turbulent_above": 0.50}
        rows = TestRegimeClassifierVol()._build_rows_with_vol(0.15, n_warmup=230)
        last_date = rows[-1].timestamp.date()
        classifier = RegimeClassifier("SPY", vol_thresholds=thresholds)
        classifier.classify(last_date, last_date, _make_db_with_rows(rows))
        assert classifier._regime_map[last_date].vol == "calm"

    def test_invalid_thresholds_raise_value_error(self):
        from app.services.replay.classifier import RegimeClassifier

        with pytest.raises(ValueError, match="calm_below"):
            RegimeClassifier("SPY", vol_thresholds={"calm_below": 0.25, "turbulent_above": 0.20})

    def test_negative_threshold_raises_value_error(self):
        from app.services.replay.classifier import RegimeClassifier

        with pytest.raises(ValueError):
            RegimeClassifier("SPY", vol_thresholds={"calm_below": -0.05, "turbulent_above": 0.20})

    def test_missing_threshold_key_raises_value_error(self):
        from app.services.replay.classifier import RegimeClassifier

        with pytest.raises(ValueError):
            RegimeClassifier("SPY", vol_thresholds={"calm_below": 0.10})


class TestGetBenchmarkRegime:
    def _classifier_with_map(self, regime_map: dict):
        from app.services.replay.classifier import RegimeClassifier

        c = RegimeClassifier.__new__(RegimeClassifier)
        c._regime_map = regime_map
        c._symbol = "SPY"
        c._thresholds = RegimeClassifier.DEFAULT_VOL_THRESHOLDS
        return c

    def test_exact_match(self):
        from app.services.replay.classifier import RegimeClassifier, ReplayRegime, get_benchmark_regime

        regime = ReplayRegime("bull", "calm")
        c = self._classifier_with_map({date(2026, 1, 5): regime})
        assert get_benchmark_regime(c, date(2026, 1, 5)) == regime

    def test_nontrading_day_carryforward(self):
        """Saturday carries forward Friday's regime."""
        from app.services.replay.classifier import ReplayRegime, get_benchmark_regime

        fri_regime = ReplayRegime("bull", "normal")
        c = self._classifier_with_map({date(2026, 1, 2): fri_regime})  # Jan 2, 2026 = Friday
        result = get_benchmark_regime(c, date(2026, 1, 3))  # Saturday
        assert result == fri_regime

    def test_date_after_last_carries_forward_last(self):
        from app.services.replay.classifier import ReplayRegime, get_benchmark_regime

        last = ReplayRegime("bear", "turbulent")
        c = self._classifier_with_map({date(2026, 1, 5): last})
        result = get_benchmark_regime(c, date(2026, 12, 31))
        assert result == last

    def test_date_before_first_returns_unknown(self):
        from app.services.replay.classifier import ReplayRegime, get_benchmark_regime

        c = self._classifier_with_map({date(2026, 6, 1): ReplayRegime("bull", "calm")})
        result = get_benchmark_regime(c, date(2026, 1, 1))
        assert result == ReplayRegime("unknown", "normal")

    def test_empty_map_returns_unknown(self):
        from app.services.replay.classifier import ReplayRegime, get_benchmark_regime

        c = self._classifier_with_map({})
        result = get_benchmark_regime(c, date(2026, 1, 5))
        assert result == ReplayRegime("unknown", "normal")
```

### 2.2 — Verify tests fail

```bash
docker-compose exec backend python -m pytest tests/services/test_regime_classifier.py -v 2>&1 | tail -20
# Expected: ModuleNotFoundError: No module named 'app.services.replay.classifier'
```

### 2.3 — Implement `classifier.py`

Create `backend/app/services/replay/classifier.py`:

```python
import math
import logging
from dataclasses import dataclass
from datetime import date, datetime
from typing import Dict, Optional

import pandas as pd
from sqlalchemy.orm import Session

from app.models.stock_aggregate import StockAggregate

logger = logging.getLogger(__name__)

_SQRT_252 = math.sqrt(252)


@dataclass(frozen=True)
class ReplayRegime:
    trend: str  # "bull" | "bear" | "unknown"
    vol: str    # "calm" | "normal" | "turbulent"


class RegimeClassifier:
    DEFAULT_VOL_THRESHOLDS = {
        "calm_below": 0.10,
        "turbulent_above": 0.20,
    }

    def __init__(
        self,
        symbol: str,
        vol_thresholds: Optional[Dict[str, float]] = None,
    ):
        self._symbol = symbol
        self._thresholds = self._validate_thresholds(
            vol_thresholds if vol_thresholds is not None else self.DEFAULT_VOL_THRESHOLDS
        )
        self._regime_map: Dict[date, ReplayRegime] = {}

    @staticmethod
    def _validate_thresholds(t: Dict[str, float]) -> Dict[str, float]:
        required = {"calm_below", "turbulent_above"}
        missing = required - t.keys()
        if missing:
            raise ValueError(f"vol_thresholds missing required keys: {missing}")
        if t["calm_below"] <= 0 or t["turbulent_above"] <= 0:
            raise ValueError("vol_thresholds values must be positive")
        if t["calm_below"] >= t["turbulent_above"]:
            raise ValueError(
                f"calm_below ({t['calm_below']}) must be < turbulent_above ({t['turbulent_above']})"
            )
        return t

    def classify(self, start_date: date, end_date: date, db: Session) -> None:
        """
        Loads all daily bars for self._symbol from stock_aggregates (full history for SMA200
        warm-up), computes per-day (trend, vol) labels, and populates self._regime_map for
        [start_date, end_date]. Call once; use get_benchmark_regime() for lookups thereafter.
        """
        rows = (
            db.query(StockAggregate.timestamp, StockAggregate.close)
            .filter(
                StockAggregate.ticker == self._symbol,
                StockAggregate.timespan == "day",
                StockAggregate.multiplier == 1,
            )
            .order_by(StockAggregate.timestamp.asc())
            .all()
        )

        if not rows:
            logger.warning(
                "RegimeClassifier: no daily bars found for %s — run BenchmarkIngestor first",
                self._symbol,
            )
            return

        df = pd.DataFrame(
            [
                {
                    "date": r.timestamp.date() if isinstance(r.timestamp, datetime) else r.timestamp,
                    "close": float(r.close),
                }
                for r in rows
            ]
        ).sort_values("date").reset_index(drop=True)

        # SMA200: trailing 200 trading days (min_periods=200 → NaN until warm-up)
        df["sma200"] = df["close"].rolling(200, min_periods=200).mean()

        # Annualized realized vol: std of log-returns × √252 (20-day window)
        df["log_return"] = pd.Series(df["close"]).transform(
            lambda s: s.apply(math.log).diff()
        )
        df["realized_vol"] = df["log_return"].rolling(20, min_periods=20).std() * _SQRT_252

        thresholds = self._thresholds
        self._regime_map.clear()

        for _, row in df.iterrows():
            d = row["date"]
            if not (start_date <= d <= end_date):
                continue

            # Trend
            if pd.isna(row["sma200"]):
                trend = "unknown"
            elif row["close"] > row["sma200"]:
                trend = "bull"
            else:
                trend = "bear"

            # Vol
            if pd.isna(row["realized_vol"]):
                vol = "normal"
            elif row["realized_vol"] < thresholds["calm_below"]:
                vol = "calm"
            elif row["realized_vol"] > thresholds["turbulent_above"]:
                vol = "turbulent"
            else:
                vol = "normal"

            self._regime_map[d] = ReplayRegime(trend=trend, vol=vol)

        logger.info(
            "RegimeClassifier: classified %d days for %s (%s → %s)",
            len(self._regime_map),
            self._symbol,
            start_date,
            end_date,
        )


_UNKNOWN_REGIME = ReplayRegime("unknown", "normal")


def get_benchmark_regime(
    classifier: RegimeClassifier,
    lookup_date: date,
) -> ReplayRegime:
    """
    Pure dict lookup into classifier._regime_map.
    - Exact match: returns the stored ReplayRegime.
    - Non-trading day or weekend: carries forward the last available trading day.
    - Date before first available entry: returns ReplayRegime("unknown", "normal").
    - Date after last available entry: carries forward the last entry.
    """
    regime_map = classifier._regime_map
    if not regime_map:
        return _UNKNOWN_REGIME

    sorted_dates = sorted(regime_map.keys())

    if lookup_date < sorted_dates[0]:
        return _UNKNOWN_REGIME

    if lookup_date in regime_map:
        return regime_map[lookup_date]

    # Carry forward: last known trading day ≤ lookup_date
    for d in reversed(sorted_dates):
        if d <= lookup_date:
            return regime_map[d]

    return _UNKNOWN_REGIME  # unreachable, but satisfies type checker
```

### 2.4 — Verify tests pass

```bash
docker-compose exec backend python -m pytest tests/services/test_regime_classifier.py -v 2>&1 | tail -30
# Expected: all tests green
```

### 2.5 — Commit

```bash
git add backend/app/services/replay/classifier.py \
        backend/tests/services/test_regime_classifier.py
git commit -m "feat(replay): RegimeClassifier with SMA200 + realized-vol bucketing (#486)"
```

---

## Task 3 — Wire `__init__.py` re-exports + full-suite pass

**Files:** `backend/app/services/replay/__init__.py`

### 3.1 — Update `__init__.py` with all public re-exports

```python
# backend/app/services/replay/__init__.py
from app.services.replay.benchmark import BenchmarkIngestionError, BenchmarkIngestor
from app.services.replay.classifier import (
    ReplayRegime,
    RegimeClassifier,
    get_benchmark_regime,
)

__all__ = [
    "BenchmarkIngestor",
    "BenchmarkIngestionError",
    "ReplayRegime",
    "RegimeClassifier",
    "get_benchmark_regime",
]
```

### 3.2 — Smoke-test the re-exports

```bash
docker-compose exec backend python -c "
from app.services.replay import (
    BenchmarkIngestor,
    BenchmarkIngestionError,
    ReplayRegime,
    RegimeClassifier,
    get_benchmark_regime,
)
print('All re-exports OK')
"
# Expected: All re-exports OK
```

### 3.3 — Run the full new test suite

```bash
docker-compose exec backend python -m pytest \
    tests/services/test_benchmark_ingestor.py \
    tests/services/test_regime_classifier.py \
    -v 2>&1 | tail -40
# Expected: all tests green
```

### 3.4 — Run the full backend test suite for regressions

```bash
docker-compose exec backend python -m pytest tests/ -x -q 2>&1 | tail -20
# Expected: no new failures
```

### 3.5 — Commit

```bash
git add backend/app/services/replay/__init__.py
git commit -m "feat(replay): wire services/replay package re-exports (#486)"
```

---

## Validation Checklist

Before marking this complete:

| Check | Command |
|-------|---------|
| Backend reloaded | `docker-compose logs backend --tail=10` |
| All new tests pass | `docker-compose exec backend python -m pytest tests/services/test_benchmark_ingestor.py tests/services/test_regime_classifier.py -v` |
| No regressions | `docker-compose exec backend python -m pytest tests/ -x -q` |
| TypeScript still passes | `npx tsc --noEmit` (no frontend changes) |
| Package importable | `python -c "from app.services.replay import BenchmarkIngestor, RegimeClassifier, get_benchmark_regime"` |

---

## Requirement Traceability

| Spec Req | Covered by |
|----------|-----------|
| R1 — re-run inserts zero rows | `test_returns_zero_when_all_bars_present`, `test_no_polygon_call_when_fully_covered` |
| R2 — interior gap detection | `test_detects_interior_missing_days`, `test_skips_already_present_bars_from_polygon_response` |
| R3 — symbol is a parameter | `test_symbol_is_parameter_not_hardcoded` |
| R4 — ProviderError → BenchmarkIngestionError | `test_provider_error_raises_ingestion_error`, `test_generic_exception_wrapped_in_ingestion_error` |
| R5 — deterministic labels | Rule-based (SMA200 + realized-vol), no ML, same bars → same output |
| R6 — unit tests for SMA200 boundary + vol buckets + zero-duplicate | Tasks 1 + 2 test suites |
| R7 — vol thresholds overridable + validated | `test_custom_thresholds_override_defaults`, `test_invalid_thresholds_raise_value_error`, `test_negative_threshold_raises_value_error`, `test_missing_threshold_key_raises_value_error` |
| R8 — carry-forward on non-trading days + out-of-range | `test_nontrading_day_carryforward`, `test_date_after_last_carries_forward_last`, `test_date_before_first_returns_unknown`, `test_empty_map_returns_unknown` |
