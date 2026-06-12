# Pre-Market Scan Pipeline Staging — Implementation Plan

**Date:** 2026-06-12  
**Issue:** #288 — [arch-v3][MED] Stage run_pre_market_scan into detect/enrich/persist pipeline  
**Spec:** `docs/superpowers/specs/2026-06-11-pre-market-scan-pipeline-staging-design.md`  
**Status:** Draft

---

## Goal

Stage the 346-line `run_pre_market_scan` monolith in `backend/app/services/pre_market_scan.py` into three composable private functions — `_detect`, `_enrich`, `_persist` — with `@dataclass` intermediate types, so detection is unit-testable without the DB and no function exceeds ~80 lines.

## Architecture

Three private stages + one slim orchestrator, all in the existing `pre_market_scan.py` module (no new files):

```
run_pre_market_scan (orchestrator ~55 lines)
├── per-ticker loop:
│   ├── fetch daily_bars (DB)
│   ├── fetch pre_market_volume (DB SUM)
│   └── _detect(ticker, daily_bars, pre_market_volume, ranker_config, timesfm_config) -> RawSignal | None
├── _enrich(raw_signals, enrichment_batch, market_context_dict, sector_etf_pct_dict, db, event_date) -> list[EnrichedSignal]
└── _persist(enriched_signals, db, event_date, scanner_run, ranker_config, failed) -> list[dict]
```

Stage boundaries:
- `RawSignal` (frozen=True) — output of `_detect`, input to `_enrich`
- `EnrichedSignal` — output of `_enrich`, input to `_persist`

## Tech Stack

FastAPI + SQLAlchemy 2.0 (sync) + pytest + `@dataclass` (consistent with `ScannerDescriptor`, `TimespanCoverage` precedents)

## File Structure

| File | Change |
|------|--------|
| `backend/app/services/pre_market_scan.py` | Add dataclasses; add `_detect`, `_compute_volatility_regime`, `_enrich`, `_persist`; slim `run_pre_market_scan` |
| `backend/tests/services/test_pre_market_scan_module.py` | Add unit tests for `_detect` (no DB) + full-pipeline regression test (real DB fixture) |

---

## Tasks

### Task 1 — Add `RawSignal` and `EnrichedSignal` dataclasses

**Files:** `backend/app/services/pre_market_scan.py`, `backend/tests/services/test_pre_market_scan_module.py`

#### Step 1: Write failing tests

Add to `backend/tests/services/test_pre_market_scan_module.py`:

```python
def test_run_pre_market_scan_importable_from_module():
    from app.services.pre_market_scan import run_pre_market_scan
    assert callable(run_pre_market_scan)


def test_raw_signal_is_frozen_dataclass():
    from dataclasses import fields, is_dataclass
    from app.services.pre_market_scan import RawSignal
    assert is_dataclass(RawSignal)
    field_names = {f.name for f in fields(RawSignal)}
    for required in ("ticker", "daily_bars", "volumes", "closes", "avg_volume_20d",
                     "avg_volume_50d", "previous_close", "pre_market_volume",
                     "relative_volume", "anomaly_score", "forecast",
                     "threshold_method", "criteria_met"):
        assert required in field_names, f"missing field: {required}"
    import pytest
    raw = RawSignal(
        ticker="AAPL", daily_bars=[], volumes=[], closes=[],
        avg_volume_20d=1.0, avg_volume_50d=None, previous_close=100.0,
        pre_market_volume=5_000_000.0, relative_volume=5.0,
        anomaly_score=None, forecast=None, threshold_method="static_4x",
        criteria_met={"volume_spike": True},
    )
    with pytest.raises(Exception):  # FrozenInstanceError
        raw.ticker = "MSFT"  # type: ignore[misc]


def test_enriched_signal_is_dataclass():
    from dataclasses import fields, is_dataclass
    from app.services.pre_market_scan import EnrichedSignal
    assert is_dataclass(EnrichedSignal)
    field_names = {f.name for f in fields(EnrichedSignal)}
    for required in ("raw", "day_metrics", "indicators", "enrichment"):
        assert required in field_names, f"missing field: {required}"
```

#### Step 2: Verify failure

```bash
docker-compose exec backend python -m pytest backend/tests/services/test_pre_market_scan_module.py -x 2>&1 | tail -10
# Expected: ImportError: cannot import name 'RawSignal' from 'app.services.pre_market_scan'
```

#### Step 3: Implement — add to `backend/app/services/pre_market_scan.py`

After the existing imports and before `async def run_pre_market_scan`, add:

```python
from dataclasses import dataclass

_TIMESFM_CONFIG_KEYS = [
    "timesfm_enabled",
    "timesfm_anomaly_threshold",
    "timesfm_min_history_bars",
    "timesfm_fallback_multiplier",
]


@dataclass(frozen=True)
class RawSignal:
    ticker: str
    daily_bars: list          # StockAggregate rows, 20–90 day window
    volumes: list
    closes: list
    avg_volume_20d: float
    avg_volume_50d: float | None
    previous_close: float
    pre_market_volume: float
    relative_volume: float
    anomaly_score: float | None
    forecast: dict | None
    threshold_method: str
    criteria_met: dict


@dataclass
class EnrichedSignal:
    raw: "RawSignal"
    day_metrics: dict
    indicators: dict
    enrichment: dict
```

Also remove the local `_timesfm_config_keys = [...]` list from inside `run_pre_market_scan` (lines 54-59) and replace the `SystemConfig.key.in_(_timesfm_config_keys)` reference with `SystemConfig.key.in_(_TIMESFM_CONFIG_KEYS)`.

#### Step 4: Verify pass

```bash
docker-compose exec backend python -m pytest backend/tests/services/test_pre_market_scan_module.py -x -v 2>&1 | tail -15
# Expected: 3 tests pass
```

#### Step 5: Commit

```bash
git add backend/app/services/pre_market_scan.py backend/tests/services/test_pre_market_scan_module.py
git commit -m "feat(#288): add RawSignal/EnrichedSignal dataclasses and module-level config key constant"
```

---

### Task 2 — Extract `_detect()` + pure unit tests

**Files:** `backend/app/services/pre_market_scan.py`, `backend/tests/services/test_pre_market_scan_module.py`

#### Step 1: Write failing unit tests

Add to `backend/tests/services/test_pre_market_scan_module.py`:

```python
from unittest.mock import MagicMock
import pytest


def _make_daily_bars(n: int, volume: float = 600_000.0, close: float = 100.0) -> list:
    bars = []
    for _ in range(n):
        b = MagicMock()
        b.volume = volume
        b.close = close
        bars.append(b)
    return bars


_DEFAULT_TIMESFM_CFG = {
    "timesfm_enabled": False,
    "anomaly_threshold": 2.0,
    "min_history_bars": 30,
    "fallback_multiplier": 4.0,
}


def test_detect_returns_raw_signal_on_passing_ticker():
    from app.services.pre_market_scan import RawSignal, _detect
    # avg_volume_20d = 600_000; pre_market_volume = 3_000_000 (5× — passes all criteria)
    bars = _make_daily_bars(25)
    result = _detect("TSST", bars, 3_000_000.0, ranker_config=None, timesfm_config=_DEFAULT_TIMESFM_CFG)
    assert isinstance(result, RawSignal)
    assert result.ticker == "TSST"
    assert result.criteria_met["volume_spike"] is True
    assert result.criteria_met["minimum_volume"] is True
    assert result.criteria_met["liquidity"] is True
    assert result.avg_volume_20d == pytest.approx(600_000.0)
    assert result.pre_market_volume == 3_000_000.0
    assert result.threshold_method == "static_4x"


def test_detect_returns_none_for_insufficient_bars():
    from app.services.pre_market_scan import _detect
    result = _detect("TSST", _make_daily_bars(15), 5_000_000.0, None, _DEFAULT_TIMESFM_CFG)
    assert result is None


def test_detect_returns_none_when_liquidity_fails():
    from app.services.pre_market_scan import _detect
    # avg_volume_20d = 200_000 < 500_000 liquidity floor
    result = _detect("TSST", _make_daily_bars(25, volume=200_000.0), 1_000_000.0, None, _DEFAULT_TIMESFM_CFG)
    assert result is None


def test_detect_returns_none_when_volume_spike_fails():
    from app.services.pre_market_scan import _detect
    # pre_market_volume = 1_000_000 < 4.0 × 600_000 = 2_400_000
    result = _detect("TSST", _make_daily_bars(25), 1_000_000.0, None, _DEFAULT_TIMESFM_CFG)
    assert result is None
```

#### Step 2: Verify failure

```bash
docker-compose exec backend python -m pytest backend/tests/services/test_pre_market_scan_module.py::test_detect_returns_raw_signal_on_passing_ticker -x 2>&1 | tail -5
# Expected: ImportError: cannot import name '_detect'
```

#### Step 3: Implement `_detect()` — add before `run_pre_market_scan`

```python
def _detect(
    ticker: str,
    daily_bars: list,
    pre_market_volume: float,
    ranker_config: "dict | None",
    timesfm_config: dict,
) -> "RawSignal | None":
    import app.services.scanner as _scanner_mod

    if len(daily_bars) < 20:
        return None

    volumes = [float(b.volume) for b in daily_bars]
    closes = [float(b.close) for b in daily_bars]
    avg_volume_20d = sum(volumes[-20:]) / 20
    avg_volume_50d = sum(volumes[-50:]) / 50 if len(volumes) >= 50 else None
    previous_close = closes[-1]
    relative_volume = pre_market_volume / avg_volume_20d if avg_volume_20d > 0 else 0

    min_history_bars = timesfm_config["min_history_bars"]
    forecast = (
        _scanner_mod.get_volume_forecast(ticker, volumes[-60:])
        if len(volumes) >= min_history_bars
        else None
    )
    anomaly_score = compute_anomaly_score(pre_market_volume, forecast)

    if timesfm_config["timesfm_enabled"] and anomaly_score is not None:
        volume_spike_ok = anomaly_score >= timesfm_config["anomaly_threshold"]
        threshold_method = "timesfm"
    else:
        volume_spike_ok = pre_market_volume > avg_volume_20d * timesfm_config["fallback_multiplier"]
        threshold_method = "static_4x"

    criteria_met = {
        "volume_spike": volume_spike_ok,
        "minimum_volume": pre_market_volume > 100000,
        "liquidity": avg_volume_20d > 500000,
    }
    if not all(criteria_met.values()):
        return None

    return RawSignal(
        ticker=ticker,
        daily_bars=daily_bars,
        volumes=volumes,
        closes=closes,
        avg_volume_20d=avg_volume_20d,
        avg_volume_50d=avg_volume_50d,
        previous_close=previous_close,
        pre_market_volume=pre_market_volume,
        relative_volume=relative_volume,
        anomaly_score=anomaly_score,
        forecast=forecast,
        threshold_method=threshold_method,
        criteria_met=criteria_met,
    )
```

#### Step 4: Update `run_pre_market_scan` — pack `timesfm_config` dict and call `_detect` in loop

In `run_pre_market_scan`, replace the four loose `timesfm_*` local variables (lines 64–67) with a single dict, and replace lines 108–155 (detect logic + criteria check) with a `_detect` call.

The per-ticker try-block becomes:

```python
    raw_signals: list = []
    failed: list = []

    for ticker in tickers:
        _ticker_span = _tracer.start_span("scanner.evaluate_ticker")
        _ticker_token = _otel_context.attach(
            _otel_trace.set_span_in_context(_ticker_span)
        )
        try:
            _ticker_span.set_attribute("ticker", ticker)
            _ticker_span.set_attribute("scanner_type", "pre_market_volume_spike")
            daily_bars = (
                db.query(StockAggregate)
                .filter(
                    StockAggregate.ticker == ticker,
                    StockAggregate.timespan == "day",
                    StockAggregate.timestamp >= hist_start_utc,
                    StockAggregate.timestamp < day_start_utc,
                )
                .order_by(StockAggregate.timestamp.asc())
                .all()
            )
            pre_market_volume = float(
                db.query(func.sum(StockAggregate.volume))
                .filter(
                    StockAggregate.ticker == ticker,
                    StockAggregate.timespan == "minute",
                    StockAggregate.is_pre_market == True,
                    StockAggregate.timestamp >= day_start_utc,
                    StockAggregate.timestamp < day_end_utc,
                )
                .scalar()
                or 0
            )
            raw = _detect(ticker, daily_bars, pre_market_volume, ranker_config, timesfm_config)
            if raw is not None:
                raw_signals.append(raw)
        except (ScanError, DataFetchError, ProviderError) as e:
            logging.error(
                "pre_market_scan: domain error for %s: %s",
                ticker,
                e,
                extra={"ticker": ticker, "error_type": type(e).__name__},
            )
            failed.append(
                {
                    "ticker": ticker,
                    "error_type": type(e).__name__,
                    "message": str(e),
                    "retryable": e.is_retryable,
                }
            )
        finally:
            _ticker_span.end()
            _otel_context.detach(_ticker_token)
```

And the `timesfm_config` dict replaces the four loose variables just before the loop:

```python
    _cfg_rows = (
        db.query(SystemConfig).filter(SystemConfig.key.in_(_TIMESFM_CONFIG_KEYS)).all()
    )
    _cfg = {r.key: r.value for r in _cfg_rows}
    timesfm_config = {
        "timesfm_enabled": _cfg.get("timesfm_enabled", "false").lower() == "true",
        "anomaly_threshold": float(_cfg.get("timesfm_anomaly_threshold", "2.0")),
        "min_history_bars": int(_cfg.get("timesfm_min_history_bars", "30")),
        "fallback_multiplier": float(_cfg.get("timesfm_fallback_multiplier", "4.0")),
    }
    ranker_config = _scanner_mod.load_ranker_config(db)
```

At this point, the enrichment block is temporarily inlined after the loop (before extracting `_enrich` in Task 4):

```python
    results = []
    for raw in raw_signals:
        day_metrics = ScannerService.calculate_day_metrics(raw.ticker, event_date, db)
        # ... (full enrichment block using raw.X instead of local vars) ...
        event_dict = ScannerService._save_event(...)
        results.append(event_dict)
        scanner_events_total.labels(scanner_type="pre_market_volume_spike").inc()

    if failed and scanner_run is not None:
        scanner_run.failed_tickers = failed
        db.add(scanner_run)
    db.commit()
    scan_duration_seconds.labels(...).observe(...)
    return results
```

#### Step 5: Verify pass

```bash
docker-compose exec backend python -m pytest backend/tests/services/test_pre_market_scan_module.py -v 2>&1 | tail -15
# Expected: 7 tests pass (3 dataclass + 4 detect)
```

Verify existing scanner tests still pass:
```bash
docker-compose exec backend python -m pytest backend/tests/services/test_scanner_refactor.py -v 2>&1 | tail -10
# Expected: all pass
```

#### Step 6: Commit

```bash
git add backend/app/services/pre_market_scan.py backend/tests/services/test_pre_market_scan_module.py
git commit -m "feat(#288): extract _detect() pure stage + unit tests; pack timesfm_config dict"
```

---

### Task 3 — Extract `_compute_volatility_regime()` ATR helper

**Files:** `backend/app/services/pre_market_scan.py`

No new tests — the ATR extraction is covered by the full-pipeline test in Task 5.

#### Step 1: Add helper before `_detect`

```python
def _compute_volatility_regime(daily_bars: list) -> "tuple[float | None, str | None]":
    if len(daily_bars) < 11:
        return None, None
    _df = pd.DataFrame(
        [{"H": float(b.high), "L": float(b.low), "C": float(b.close)} for b in daily_bars]
    )
    _df["tr"] = pd.DataFrame(
        {
            "a": _df["H"] - _df["L"],
            "b": (_df["H"] - _df["C"].shift(1)).abs(),
            "c": (_df["L"] - _df["C"].shift(1)).abs(),
        }
    ).max(axis=1)
    _df["atr10"] = _df["tr"].rolling(window=10).mean()
    _window = _df["atr10"].dropna().tail(60)
    if len(_window) < 10:
        return None, None
    _rank_pct = _window.rank(pct=True).iloc[-1]
    atr_rank = round(float(_rank_pct) * 100, 2)
    if _rank_pct < 0.25:
        vol_regime: str | None = "compressed"
    elif _rank_pct > 0.75:
        vol_regime = "expanded"
    else:
        vol_regime = "normal"
    return atr_rank, vol_regime
```

#### Step 2: Remove ATR block from the post-loop enrichment section

Remove lines 267–298 (the ATR pandas block) from the inline enrichment area and replace with:

```python
                _atr_rank, _vol_regime = _compute_volatility_regime(raw.daily_bars)
                indicators["atr_percentile_rank"] = _atr_rank
                indicators["volatility_regime"] = _vol_regime
```

#### Step 3: Verify

```bash
docker-compose exec backend python -m pytest backend/tests/services/test_pre_market_scan_module.py backend/tests/services/test_scanner_refactor.py -v 2>&1 | tail -10
# Expected: all pass
```

#### Step 4: Commit

```bash
git add backend/app/services/pre_market_scan.py
git commit -m "feat(#288): extract _compute_volatility_regime() ATR helper to keep _enrich under 80 lines"
```

---

### Task 4 — Extract `_enrich()` batch enrichment stage

**Files:** `backend/app/services/pre_market_scan.py`

This is the structural shift: the inline per-ticker enrichment moves out of the orchestrator loop and into a batch function called after the full ticker loop completes.

#### Step 1: Add `_enrich()` function before `run_pre_market_scan`

```python
def _enrich(
    raw_signals: list,
    enrichment_batch: dict,
    market_context_dict: dict,
    sector_etf_pct_dict: dict,
    db: Session,
    event_date: date,
) -> list:
    from sqlalchemy import desc

    from app.services.scanner import ScannerService
    from app.services.scan_enrichment import _SECTOR_ETF_MAP

    _ET = ZoneInfo("America/New_York")
    day_start_et = datetime.combine(event_date, datetime.min.time(), tzinfo=_ET)
    day_start_utc = day_start_et.astimezone(timezone.utc).replace(tzinfo=None)
    day_end_utc = (
        (day_start_et + timedelta(days=1)).astimezone(timezone.utc).replace(tzinfo=None)
    )

    enriched = []
    for raw in raw_signals:
        ticker = raw.ticker
        day_metrics = ScannerService.calculate_day_metrics(ticker, event_date, db)
        current_price = (
            day_metrics["closing_price"] or day_metrics["pre_market_close"] or raw.previous_close
        )
        gap_pct = (
            (day_metrics["opening_price"] - raw.previous_close) / raw.previous_close * 100
            if day_metrics["opening_price"] > 0
            else 0
        )
        fade_from_high_pct = (
            (day_metrics["regular_high"] - current_price) / day_metrics["regular_high"] * 100
            if day_metrics["regular_high"] > 0
            else 0
        )
        day_range_pct = (
            (day_metrics["regular_high"] - day_metrics["regular_low"])
            / day_metrics["regular_low"]
            * 100
            if day_metrics["regular_low"] > 0
            else 0
        )
        indicators: dict = {
            "pre_market_volume": raw.pre_market_volume,
            "avg_volume_20d": int(raw.avg_volume_20d),
            "avg_volume_50d": int(raw.avg_volume_50d) if raw.avg_volume_50d else None,
            "relative_volume": round(raw.relative_volume, 2),
            "volume_spike_ratio": round(raw.pre_market_volume / raw.avg_volume_20d, 2),
            "gap_pct": round(gap_pct, 4),
            "fade_from_high_pct": round(fade_from_high_pct, 4),
            "day_range_pct": round(day_range_pct, 4),
            "volume_anomaly_score": round(raw.anomaly_score, 4) if raw.anomaly_score is not None else None,
            "predicted_volume_p50": round(raw.forecast["p50"]) if raw.forecast else None,
            "predicted_volume_p90": round(raw.forecast["p90"]) if raw.forecast else None,
            "volume_threshold_method": raw.threshold_method,
        }
        enrichment = enrichment_batch.get(ticker.upper(), {})
        if enrichment.get("outstanding_shares"):
            indicators["float_rotation_pct"] = round(
                raw.pre_market_volume / enrichment["outstanding_shares"] * 100, 4
            )
        indicators["es_pct_from_prev_close"] = market_context_dict.get("es_pct_from_prev_close")
        indicators["nq_pct_from_prev_close"] = market_context_dict.get("nq_pct_from_prev_close")
        indicators["market_context"] = market_context_dict.get("market_context")
        _sector = enrichment.get("sector")
        _sector_etf = _SECTOR_ETF_MAP.get(_sector) if _sector else None
        indicators["sector"] = _sector
        indicators["sector_etf"] = _sector_etf
        indicators["sector_etf_pct_change"] = (
            sector_etf_pct_dict.get(_sector_etf) if _sector_etf else None
        )
        _last_pre = (
            db.query(StockAggregate)
            .filter(
                StockAggregate.ticker == ticker,
                StockAggregate.timespan == "minute",
                StockAggregate.is_pre_market == True,
                StockAggregate.timestamp >= day_start_utc,
                StockAggregate.timestamp < day_end_utc,
            )
            .order_by(desc(StockAggregate.timestamp))
            .first()
        )
        if _last_pre:
            _bar_ts = _last_pre.timestamp
            if _bar_ts.tzinfo is None:
                _bar_ts = _bar_ts.replace(tzinfo=timezone.utc)
            _bar_ts_et = _bar_ts.astimezone(_ET)
            _pm_open_et = datetime.combine(event_date, time(4, 0), tzinfo=_ET)
            indicators["minutes_since_premarket_open"] = round(
                (_bar_ts_et - _pm_open_et).total_seconds() / 60, 2
            )
            indicators["day_of_week"] = _bar_ts_et.weekday()
            indicators["is_monday"] = _bar_ts_et.weekday() == 0
            indicators["is_friday"] = _bar_ts_et.weekday() == 4
        else:
            indicators["minutes_since_premarket_open"] = None
            indicators["day_of_week"] = None
            indicators["is_monday"] = False
            indicators["is_friday"] = False
        atr_rank, vol_regime = _compute_volatility_regime(raw.daily_bars)
        indicators["atr_percentile_rank"] = atr_rank
        indicators["volatility_regime"] = vol_regime
        _cat_tags = enrichment.get("catalyst_tags", [])
        _cat_latest = enrichment.get("catalyst_latest_utc")
        indicators["has_news_catalyst"] = bool(_cat_tags)
        indicators["catalyst_tag_count"] = len(_cat_tags)
        if _cat_latest is not None and _last_pre is not None:
            _ref_ts = _last_pre.timestamp
            if _ref_ts.tzinfo is None:
                _ref_ts = _ref_ts.replace(tzinfo=timezone.utc)
            if _cat_latest.tzinfo is None:
                _cat_latest = _cat_latest.replace(tzinfo=timezone.utc)
            indicators["catalyst_recency_hours"] = round(
                (_ref_ts - _cat_latest).total_seconds() / 3600, 2
            )
        else:
            indicators["catalyst_recency_hours"] = None
        indicators["price_direction"] = None
        indicators["price_confidence"] = None
        indicators["price_forecast_4h"] = None
        indicators["price_forecast_1d"] = None
        enriched.append(
            EnrichedSignal(raw=raw, day_metrics=day_metrics, indicators=indicators, enrichment=enrichment)
        )
    return enriched
```

#### Step 2: Update `run_pre_market_scan` to call `_enrich` batch-style

Replace the post-loop inline enrichment section. After the per-ticker loop, the orchestrator becomes:

```python
    enriched = _enrich(
        raw_signals, enrichment_batch, market_context_dict, sector_etf_pct_dict, db, event_date
    )

    results = []
    for sig in enriched:
        event_dict = ScannerService._save_event(
            db=db,
            ticker=sig.raw.ticker,
            event_date=event_date,
            scanner_type="pre_market_volume_spike",
            indicators=sig.indicators,
            criteria_met=sig.raw.criteria_met,
            enrichment=sig.enrichment,
            previous_close=sig.raw.previous_close,
            opening_price=sig.day_metrics["opening_price"],
            closing_price=sig.day_metrics["closing_price"],
            ranker_config=ranker_config,
        )
        results.append(event_dict)
        scanner_events_total.labels(scanner_type="pre_market_volume_spike").inc()

    if failed and scanner_run is not None:
        scanner_run.failed_tickers = failed
        db.add(scanner_run)
    db.commit()
    scan_duration_seconds.labels(scanner_type="pre_market_volume_spike").observe(
        _time.monotonic() - _start
    )
    return results
```

Also remove the now-unused `import ScannerService` deferred import inside the function body (it moves to `_enrich`). Keep the `_scanner_mod` lazy import at the start of `run_pre_market_scan` for `load_ranker_config`.

#### Step 3: Verify

```bash
docker-compose exec backend python -m pytest backend/tests/services/test_pre_market_scan_module.py backend/tests/services/test_scanner_refactor.py -v 2>&1 | tail -10
# Expected: all pass
```

#### Step 4: Commit

```bash
git add backend/app/services/pre_market_scan.py
git commit -m "feat(#288): extract _enrich() batch stage; orchestrator now collects raw_signals then enriches in batch"
```

---

### Task 5 — Extract `_persist()`, slim orchestrator, add golden-day pipeline test

**Files:** `backend/app/services/pre_market_scan.py`, `backend/tests/services/test_pre_market_scan_module.py`

#### Step 1: Write full-pipeline regression test (regression anchor — passes before and after slim)

The test uses the real transaction-rollback DB fixture from `conftest.py`. Pre-market volume = 3,000,000 (5× avg_volume_20d of 600,000), satisfying all three criteria.

Add to `backend/tests/services/test_pre_market_scan_module.py`:

```python
import asyncio
from datetime import date, datetime, timedelta, timezone

import pytest
from app.models.stock_aggregate import StockAggregate
from app.services.scanner import ScannerService
from unittest.mock import patch


_FIXTURE_DATE = date(2024, 1, 15)  # Monday


def _et_utc(event_date: date):
    from zoneinfo import ZoneInfo
    _ET = ZoneInfo("America/New_York")
    day_start_et = datetime.combine(event_date, datetime.min.time(), tzinfo=_ET)
    day_start_utc = day_start_et.astimezone(timezone.utc).replace(tzinfo=None)
    day_end_utc = ((day_start_et + timedelta(days=1)).astimezone(timezone.utc).replace(tzinfo=None))
    hist_start_utc = ((day_start_et - timedelta(days=90)).astimezone(timezone.utc).replace(tzinfo=None))
    return hist_start_utc, day_start_utc, day_end_utc


def test_run_pre_market_scan_golden_day(db):
    """Full pipeline: seeded DB + mocked enrichment → asserts output fields."""
    hist_start_utc, day_start_utc, day_end_utc = _et_utc(_FIXTURE_DATE)

    # Insert 25 daily bars for "TSST" (avg_volume_20d = 600_000)
    for i in range(25):
        bar = StockAggregate(
            ticker="TSST",
            timestamp=hist_start_utc + timedelta(days=i + 1),
            timespan="day",
            multiplier=1,
            open=100.0, high=101.0, low=99.0, close=100.0,
            volume=600_000,
            is_pre_market=False,
            is_after_market=False,
        )
        db.add(bar)

    # Insert 3 pre-market minute bars (total pre_market_volume = 3_000_000 → 5× 600k)
    for i in range(3):
        pm_bar = StockAggregate(
            ticker="TSST",
            timestamp=day_start_utc + timedelta(hours=4, minutes=i),
            timespan="minute",
            multiplier=1,
            open=100.0, high=100.5, low=99.5, close=100.0,
            volume=1_000_000,
            is_pre_market=True,
            is_after_market=False,
        )
        db.add(pm_bar)
    db.flush()

    with (
        patch.object(
            ScannerService,
            "_get_batch_enrichment_data",
            return_value=({"TSST": {}}, {}, {}),
        ),
        patch("app.services.alert_service.trigger_scanner_alert"),  # suppress Celery
    ):
        results = asyncio.run(
            __import__("app.services.pre_market_scan", fromlist=["run_pre_market_scan"])
            .run_pre_market_scan(["TSST"], db, event_date=_FIXTURE_DATE)
        )

    assert len(results) == 1
    assert results[0]["ticker"] == "TSST"
    assert results[0]["indicators"]["relative_volume"] == pytest.approx(5.0, abs=0.01)
    assert results[0]["criteria_met"]["volume_spike"] is True
    assert results[0]["indicators"]["volume_threshold_method"] == "static_4x"
    assert results[0]["indicators"]["pre_market_volume"] == pytest.approx(3_000_000.0)
```

#### Step 2: Verify test passes against current code (regression anchor)

```bash
docker-compose exec backend python -m pytest backend/tests/services/test_pre_market_scan_module.py::test_run_pre_market_scan_golden_day -v 2>&1 | tail -15
# Expected: PASSED (verifies existing code produces correct output before slim)
```

#### Step 3: Implement `_persist()` — add before `run_pre_market_scan`

```python
def _persist(
    enriched_signals: list,
    db: Session,
    event_date: date,
    scanner_run: "Optional[Any]",
    ranker_config: "dict | None",
    failed: list,
) -> "list[dict]":
    from app.services.scanner import ScannerService

    results = []
    for sig in enriched_signals:
        event_dict = ScannerService._save_event(
            db=db,
            ticker=sig.raw.ticker,
            event_date=event_date,
            scanner_type="pre_market_volume_spike",
            indicators=sig.indicators,
            criteria_met=sig.raw.criteria_met,
            enrichment=sig.enrichment,
            previous_close=sig.raw.previous_close,
            opening_price=sig.day_metrics["opening_price"],
            closing_price=sig.day_metrics["closing_price"],
            ranker_config=ranker_config,
        )
        results.append(event_dict)
        scanner_events_total.labels(scanner_type="pre_market_volume_spike").inc()

    if failed and scanner_run is not None:
        scanner_run.failed_tickers = failed
        db.add(scanner_run)

    db.commit()
    return results
```

#### Step 4: Slim `run_pre_market_scan` orchestrator (~55 lines)

Replace the full body with the slim coordinator:

```python
async def run_pre_market_scan(
    tickers: List[str],
    db: Session,
    event_date: date = None,
    scanner_run: Optional["ScannerRun"] = None,
) -> List[Dict[str, Any]]:
    """Run extended hours volume spike scanner using DB aggregates."""
    import app.services.scanner as _scanner_mod
    from app.services.scanner import ScannerService
    from opentelemetry import context as _otel_context
    from opentelemetry import trace as _otel_trace

    _start = _time.monotonic()
    if event_date is None:
        event_date = get_market_today()

    _ET = ZoneInfo("America/New_York")
    day_start_et = datetime.combine(event_date, datetime.min.time(), tzinfo=_ET)
    day_start_utc = day_start_et.astimezone(timezone.utc).replace(tzinfo=None)
    day_end_utc = (
        (day_start_et + timedelta(days=1)).astimezone(timezone.utc).replace(tzinfo=None)
    )
    hist_start_utc = (
        (day_start_et - timedelta(days=90)).astimezone(timezone.utc).replace(tzinfo=None)
    )

    _cfg_rows = (
        db.query(SystemConfig).filter(SystemConfig.key.in_(_TIMESFM_CONFIG_KEYS)).all()
    )
    _cfg = {r.key: r.value for r in _cfg_rows}
    timesfm_config = {
        "timesfm_enabled": _cfg.get("timesfm_enabled", "false").lower() == "true",
        "anomaly_threshold": float(_cfg.get("timesfm_anomaly_threshold", "2.0")),
        "min_history_bars": int(_cfg.get("timesfm_min_history_bars", "30")),
        "fallback_multiplier": float(_cfg.get("timesfm_fallback_multiplier", "4.0")),
    }
    ranker_config = _scanner_mod.load_ranker_config(db)

    (
        enrichment_batch,
        market_context_dict,
        sector_etf_pct_dict,
    ) = await asyncio.to_thread(
        ScannerService._get_batch_enrichment_data, tickers, event_date, db
    )

    _tracer = _otel_trace.get_tracer(__name__)
    raw_signals: list = []
    failed: list = []

    for ticker in tickers:
        _ticker_span = _tracer.start_span("scanner.evaluate_ticker")
        _ticker_token = _otel_context.attach(
            _otel_trace.set_span_in_context(_ticker_span)
        )
        try:
            _ticker_span.set_attribute("ticker", ticker)
            _ticker_span.set_attribute("scanner_type", "pre_market_volume_spike")
            daily_bars = (
                db.query(StockAggregate)
                .filter(
                    StockAggregate.ticker == ticker,
                    StockAggregate.timespan == "day",
                    StockAggregate.timestamp >= hist_start_utc,
                    StockAggregate.timestamp < day_start_utc,
                )
                .order_by(StockAggregate.timestamp.asc())
                .all()
            )
            pre_market_volume = float(
                db.query(func.sum(StockAggregate.volume))
                .filter(
                    StockAggregate.ticker == ticker,
                    StockAggregate.timespan == "minute",
                    StockAggregate.is_pre_market == True,
                    StockAggregate.timestamp >= day_start_utc,
                    StockAggregate.timestamp < day_end_utc,
                )
                .scalar()
                or 0
            )
            raw = _detect(ticker, daily_bars, pre_market_volume, ranker_config, timesfm_config)
            if raw is not None:
                raw_signals.append(raw)
        except (ScanError, DataFetchError, ProviderError) as e:
            logging.error(
                "pre_market_scan: domain error for %s: %s",
                ticker,
                e,
                extra={"ticker": ticker, "error_type": type(e).__name__},
            )
            failed.append(
                {
                    "ticker": ticker,
                    "error_type": type(e).__name__,
                    "message": str(e),
                    "retryable": e.is_retryable,
                }
            )
        finally:
            _ticker_span.end()
            _otel_context.detach(_ticker_token)

    enriched = _enrich(
        raw_signals, enrichment_batch, market_context_dict, sector_etf_pct_dict, db, event_date
    )
    results = _persist(enriched, db, event_date, scanner_run, ranker_config, failed)
    scan_duration_seconds.labels(scanner_type="pre_market_volume_spike").observe(
        _time.monotonic() - _start
    )
    return results
```

#### Step 5: Verify all tests pass

```bash
docker-compose exec backend python -m pytest backend/tests/services/test_pre_market_scan_module.py -v 2>&1 | tail -20
# Expected: 8 tests pass

docker-compose exec backend python -m pytest backend/tests/services/test_scanner_refactor.py -v 2>&1 | tail -10
# Expected: all pass
```

#### Step 6: Verify line counts

```bash
docker-compose exec backend python -c "
import ast, inspect
from app.services.pre_market_scan import (
    run_pre_market_scan, _detect, _enrich, _persist, _compute_volatility_regime
)
for fn in [run_pre_market_scan, _detect, _enrich, _persist, _compute_volatility_regime]:
    src = inspect.getsource(fn)
    print(f'{fn.__name__}: {len(src.splitlines())} lines')
"
# Expected: each ≤ ~80 lines
```

#### Step 7: Commit

```bash
git add backend/app/services/pre_market_scan.py backend/tests/services/test_pre_market_scan_module.py
git commit -m "feat(#288): extract _persist(); slim run_pre_market_scan orchestrator to ~55 lines; add golden-day regression test"
```

---

### Task 6 — Final validation

**Files:** none (read-only checks)

#### Step 1: Full test suite for affected modules

```bash
docker-compose exec backend python -m pytest backend/tests/services/ -v 2>&1 | tail -20
# Expected: all pass (no regressions)
```

#### Step 2: Confirm no function in `pre_market_scan.py` exceeds ~80 lines

```bash
docker-compose exec backend python -c "
import inspect
import app.services.pre_market_scan as m
fns = [v for k, v in vars(m).items() if callable(v) and not k.startswith('__')]
for fn in fns:
    try:
        lines = len(inspect.getsource(fn).splitlines())
        marker = ' *** OVER LIMIT' if lines > 85 else ''
        print(f'{fn.__name__}: {lines} lines{marker}')
    except (TypeError, OSError):
        pass
"
# Expected: no line counts exceed 85
```

#### Step 3: Confirm backend reloaded and scanner route works

```bash
docker-compose logs backend --tail=5
# Expected: no errors (app reloaded cleanly)

curl -s http://localhost:8000/api/scanner/recent | python -m json.tool | head -20
# Expected: valid JSON response
```

#### Step 4: Commit if clean

```bash
git status  # no uncommitted changes
```

---

## Summary

| Function | Approx lines | Role |
|----------|-------------|------|
| `_compute_volatility_regime` | ~20 | ATR pandas helper |
| `_detect` | ~48 | Pure stage: no DB, returns RawSignal or None |
| `_enrich` | ~72 | Batch stage: DB reads for day metrics + timing; builds indicators dict |
| `_persist` | ~24 | All DB writes: _save_event, Prometheus, db.commit |
| `run_pre_market_scan` | ~58 | Slim orchestrator: setup, loop, call stages, return |

Total module after refactor: ~270 lines (down from 388). All functions ≤ ~80 lines.

**Tests added:**
- `test_raw_signal_is_frozen_dataclass` — frozen constraint
- `test_enriched_signal_is_dataclass` — field presence
- `test_detect_returns_raw_signal_on_passing_ticker` — happy path (no DB)
- `test_detect_returns_none_for_insufficient_bars` — early-exit guard (no DB)
- `test_detect_returns_none_when_liquidity_fails` — liquidity criterion (no DB)
- `test_detect_returns_none_when_volume_spike_fails` — spike criterion (no DB)
- `test_run_pre_market_scan_golden_day` — full pipeline regression (real DB fixture)
