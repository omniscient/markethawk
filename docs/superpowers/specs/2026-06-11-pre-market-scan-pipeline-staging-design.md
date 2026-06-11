# Pre-Market Scan Pipeline Staging — Design

**Date:** 2026-06-11  
**Issue:** #288 — [arch-v3][MED] Stage run_pre_market_scan into detect/enrich/persist pipeline  
**Status:** Spec pending review

## Overview

`backend/app/services/pre_market_scan.py` contains a single 346-line function (`run_pre_market_scan`, CC ~37) that fuses detection, enrichment, and persistence in one per-ticker loop with five levels of nesting. This was flagged in the v3 architecture review (R04) as a module-depth candidate. The fix stages the pipeline into three composable functions with explicit boundaries, making detection unit-testable without the DB and reducing per-function size to ~80 lines.

## Requirements

1. Split `run_pre_market_scan` into three named stages: `_detect`, `_enrich`, `_persist`.
2. No function in `pre_market_scan.py` exceeds ~80 lines after the refactor.
3. `_detect` must be unit-testable without any DB access (takes pre-fetched bar data as arguments).
4. Two new tests: (a) a pure unit test for `_detect`, (b) a full-pipeline regression test using the existing transaction-rollback DB fixture, asserting the public output inline.
5. Scope is strictly `pre_market_scan.py`. `oversold_bounce_scan.py` is a follow-on ticket.
6. Public interface of `run_pre_market_scan(...) -> List[Dict[str, Any]]` is unchanged; stage types are module-internal.

## Data Types

Define two `@dataclass` types at the top of `pre_market_scan.py` (consistent with `ScannerDescriptor` in `scan_orchestrator.py` and `TimespanCoverage` in `data_readiness.py` — established pattern, no `TypedDict` exists in the backend):

```python
@dataclass(frozen=True)
class RawSignal:
    ticker: str
    daily_bars: list          # StockAggregate rows, 20–90 day window
    volumes: list[float]      # float(b.volume) for b in daily_bars
    closes: list[float]       # float(b.close) for b in daily_bars
    avg_volume_20d: float
    avg_volume_50d: float | None
    previous_close: float
    pre_market_volume: float
    relative_volume: float
    anomaly_score: float | None
    forecast: dict | None     # {p50, p90} or None
    threshold_method: str     # "timesfm" or "static_4x"
    criteria_met: dict[str, bool]

@dataclass
class EnrichedSignal:
    raw: RawSignal
    day_metrics: dict         # from ScannerService.calculate_day_metrics
    indicators: dict          # full 19-key indicators dict (ready for _save_event)
    enrichment: dict          # from enrichment_batch per ticker
```

`RawSignal` is `frozen=True` because it is the immutable output of detection and must not be mutated by enrichment. `EnrichedSignal` is mutable because `indicators` is built incrementally across enrichment sub-steps.

## Architecture / Approach

### Stage 1 — `_detect(ticker, daily_bars, pre_market_volume, ranker_config, timesfm_config) -> RawSignal | None`

Pure function. No DB access. Receives pre-fetched data:
- `daily_bars`: `list[StockAggregate]` — fetched by the orchestrator per-ticker
- `pre_market_volume`: `float` — computed by the orchestrator (SUM of minute bars)
- `ranker_config`: already loaded once before the loop
- `timesfm_config`: already loaded once before the loop

Responsibilities:
- Early-exit guard (`len(daily_bars) < 20 → return None`)
- Compute `avg_volume_20d`, `avg_volume_50d`, `previous_close`, `relative_volume`
- Compute `forecast` (TimesFM) and `anomaly_score`
- Evaluate `criteria_met` (`volume_spike`, `minimum_volume`, `liquidity`)
- Return `RawSignal` if all criteria pass, `None` otherwise

OTel span management and per-ticker `except (ScanError, DataFetchError, ProviderError)` stay in the orchestrator, not in `_detect`, so the function stays pure.

### Stage 2 — `_enrich(raw_signals, enrichment_batch, market_context_dict, sector_etf_pct_dict, db, event_date) -> list[EnrichedSignal]`

Batch operation over all `RawSignal`s that passed detection. Receives the already-computed batch enrichment data (fetched once before the ticker loop via `_get_batch_enrichment_data`). Accesses the DB only for:
- `ScannerService.calculate_day_metrics(ticker, event_date, db)` — day price metrics (gap %, fade, day range)
- One per-ticker query for the last pre-market bar (timing features: `minutes_since_premarket_open`, `day_of_week`)

Responsibilities per signal:
- Build base price indicators (gap %, fade, day range — from `day_metrics`)
- Build Phase 2a features: market context (ES/NQ), sector/ETF, timing, volatility regime (ATR percentile), catalyst enrichment, TimesFM price forecast stubs
- Compute float rotation if outstanding shares available
- Return `EnrichedSignal` list

If the volatility regime block (ATR pandas computation) pushes `_enrich` past ~80 lines, extract it to a private helper `_compute_volatility_regime(daily_bars) -> tuple[float | None, str | None]`.

### Stage 3 — `_persist(enriched_signals, db, event_date, scanner_run, ranker_config) -> list[dict]`

Handles all DB writes and Prometheus metrics. No business logic.

Responsibilities:
- Call `ScannerService._save_event(...)` per enriched signal, appending to `results`
- Increment `scanner_events_total` counter per event
- If `scanner_run` is not None, write `failed_tickers` from the orchestrator's collected failures
- `db.commit()` once at the end
- Return `results` (the public `List[Dict[str, Any]]`)

### Orchestrator — `run_pre_market_scan(tickers, db, event_date, scanner_run) -> List[Dict[str, Any]]`

Slim coordinator (~50 lines):

```python
async def run_pre_market_scan(...):
    # 1. Setup: event_date default, _ET, time window bounds
    # 2. Load timesfm_config and ranker_config once (DB reads, before loop)
    # 3. await _get_batch_enrichment_data (already batch)
    # 4. Per-ticker loop:
    #    a. Fetch daily_bars (DB)
    #    b. Fetch pre_market_volume (DB SUM)
    #    c. OTel span start
    #    d. try: raw = _detect(ticker, daily_bars, pre_market_volume, ...)
    #    e. except: collect failed_tickers
    #    f. OTel span end
    # 5. raw_signals = [r for r in raw_signals if r is not None]
    # 6. enriched = await asyncio.to_thread(_enrich, raw_signals, ...)
    # 7. results = _persist(enriched, db, event_date, scanner_run, ranker_config)
    # 8. Observe scan_duration_seconds, return results
```

Note: `_enrich` may need to be called with `asyncio.to_thread` if the ATR pandas computation is CPU-bound on large universes, consistent with the existing `asyncio.to_thread(ScannerService._get_batch_enrichment_data, ...)` pattern.

## Alternatives Considered

**Alt A — Single-file private functions, no typed intermediates**: Extract `_detect`/`_enrich`/`_persist` as private module functions but pass plain `Dict[str, Any]` between them. Simpler but loses the explicit contract at stage boundaries — the whole point of the refactor is making the seams legible. Rejected.

**Alt B — New `pre_market_pipeline.py` module**: Move the three stages to a separate module, keeping `pre_market_scan.py` as a thin adapter. Adds a new file, a new import, and surface area for the orchestrator pattern; the issue doesn't require this level of isolation. Rejected in favor of keeping all three stages in the existing module, consistent with how `session_metrics.py` and `scan_enrichment.py` were introduced without splitting the scan module.

**Alt C — Batch daily-bar pre-fetch for all tickers before detect**: Issue Q&A ruled this out as out-of-scope (performance ticket, not a structural refactor). Per-ticker fetch stays in the orchestrator, detect stays pure.

## Test Plan

### Test 1 — Pure unit test: `test_detect_returns_raw_signal_on_passing_ticker`

File: `backend/tests/services/test_pre_market_scan_module.py`

Build `StockAggregate` instances in Python (no DB). Pass `daily_bars` list (≥20 items) and `pre_market_volume` float directly to `_detect`. Assert:
- Returned `RawSignal.ticker` matches
- `RawSignal.criteria_met["volume_spike"]` is `True` when volume exceeds threshold
- `RawSignal` is `None` when `len(daily_bars) < 20`
- `RawSignal` is `None` when criteria fail (e.g. avg_volume_20d below liquidity floor)

No DB fixture required.

### Test 2 — Full-pipeline regression: `test_run_pre_market_scan_golden_day`

File: same module

Seed a fixture day (e.g. 2024-01-15) into the test DB using the transaction-rollback `db` fixture (see `backend/tests/conftest.py`). Insert:
- 20 `StockAggregate` daily bars for one ticker with known values
- Sufficient pre-market minute bars (`is_pre_market=True`) with known total volume
- `TickerReference` row for enrichment

Mock `ScannerService._get_batch_enrichment_data` to return deterministic enrichment (no Polygon call). Run `run_pre_market_scan([ticker], db, event_date=date(2024, 1, 15))` end-to-end. Assert the returned event dict's key fields inline (not a JSON file — no golden-file precedent exists in `backend/tests/`):

```python
assert len(results) == 1
assert results[0]["ticker"] == "AAPL"
assert results[0]["indicators"]["relative_volume"] == expected_rvol
assert results[0]["criteria_met"]["volume_spike"] is True
```

## Assumptions

- `_detect` is called **after** the `len(daily_bars) < 20` guard that currently exists on line 105. Since `_detect` itself performs the same guard (and returns `None`), the orchestrator's explicit check before the OTel span can be removed. The spec assumes both guard and span sit in the orchestrator to keep OTel management centralized.
- The `asyncio.to_thread` wrapping for `_enrich` is left to the implementer's judgment based on actual profile data. The spec defines the boundary but doesn't prescribe threading.
- TimesFM price forecast stubs (`price_direction`, `price_confidence`, `price_forecast_4h`, `price_forecast_1d` set to `None`) persist in `_enrich` as-is. They are deferred to a separate issue (referenced as Phase 1 dependency #20 in the current code).

## Open Questions (non-blocking)

1. Should `_enrich` receive the `daily_bars` from `RawSignal` (already available there) or re-query for the ATR computation? `RawSignal.daily_bars` already carries them — `_enrich` should read from `raw.daily_bars` rather than re-fetching, avoiding a DB round-trip per passing signal.
2. Once the canonical three-stage pattern is established by this issue, a follow-on ticket should apply it to `oversold_bounce_scan.py` (same architecture-audit-v3 label).
