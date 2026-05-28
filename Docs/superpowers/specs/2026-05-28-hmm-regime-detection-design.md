# HMM Market Regime Detection Design

**Date:** 2026-05-28  
**Issue:** [#106 — Integrate HMM regime detection to enhance and validate scanner signals](https://github.com/omniscient/markethawk/issues/106)

## Overview

Integrate a Hidden Markov Model (HMM) into MarketHawk's scanning pipeline to classify broad market conditions (e.g., risk-on, risk-off, high-volatility) and annotate each `ScannerEvent` with the prevailing regime at the time it fired. A second deliverable in this PR uses those labels to produce per-regime win-rate breakdowns via the existing outcomes framework, answering the question: "Do our scans perform differently across market regimes?"

## Requirements

1. A `RegimeService` in `backend/app/services/` that:
   - Trains a `GaussianHMM` (hmmlearn) on SPY daily OHLCV bars from `stock_aggregates` using three features: daily return, rolling 20-day volatility, rolling 20-day skewness.
   - Selects the optimal number of hidden states (2–5) using BIC model selection.
   - Post-maps hidden state indices to human-readable labels (`risk_on`, `risk_off`, `high_volatility`, etc.) based on mean return and volatility of each state.
   - Exposes `get_current_regime() → str` (reads from Redis cache) and `get_regime_at_date(date) → str` (queries PostgreSQL).

2. A `regime_models` PostgreSQL table that stores serialized fitted models (following the `SignalAnalysisRun` precedent) with version tracking and a JSONB `state_label_mapping`.

3. A new `ScannerEvent.regime` column (`String(30), nullable=True`) populated at event creation time via `event_helpers.save_event()`.

4. A one-time Celery backfill task that back-labels all existing `ScannerEvent` rows using `get_regime_at_date()`.

5. A daily Celery beat task (`update_regime_model`) scheduled post-market-close (21:00 UTC weekdays) that re-trains the HMM on a rolling 2-year SPY window and writes the new model to PostgreSQL + Redis.

6. A `?regime=` query parameter on the existing `GET /api/outcomes/scorecard/{scanner_type}` endpoint.

7. A new `GET /api/outcomes/regime-breakdown/{scanner_type}` endpoint returning win-rate, avg MFE, avg MAE, and sample size per regime.

8. A regime badge on scanner result cards (frontend `ScannerResults.tsx`) displayed beside the existing severity pill, using color coding (green=risk_on, red=risk_off, amber=high_volatility, gray=null/unknown).

9. **Out of scope for this PR**: regime-specific `ScannerConfig` thresholds (App 2), regime-transition scan type (App 3), per-sector regime models (App 4), VIX as a feature, intraday regime switching.

## Architecture

### New files

| Path | Purpose |
|------|---------|
| `backend/app/services/regime_service.py` | RegimeService — train, persist, query, cache |
| `backend/app/models/regime_model.py` | `RegimeModel` ORM — serialized HMM + metadata |
| `backend/app/tasks/regime.py` | `update_regime_model` (daily beat) + `backfill_regime_labels` (one-time) |

### Changed files

| Path | Change |
|------|--------|
| `backend/app/models/scanner_event.py` | Add `regime = Column(String(30), nullable=True)` |
| `backend/app/services/event_helpers.py` | Call `RegimeService.get_regime_at_date(event_date)` when saving event |
| `backend/app/routers/outcomes.py` | Add `?regime=` param to scorecard; add `/regime-breakdown/{scanner_type}` endpoint |
| `backend/app/services/stats.py` | Add `regime` filter to `get_scorecard()`; add `get_regime_breakdown()` method |
| `backend/app/core/celery_app.py` | Register `update_regime_model` in beat schedule |
| `backend/app/models/__init__.py` | Import `RegimeModel` |
| `backend/requirements.txt` | Add `hmmlearn>=0.3` |
| `frontend/src/api/scanner.ts` | Add `regime?: string` to `ScannerEventResponse` type |
| `frontend/src/components/ScannerResults.tsx` | Render regime badge |

### Data flow

```
Daily Celery beat (21:00 UTC weekdays)
  └── update_regime_model task
        ├── Query stock_aggregates WHERE ticker='SPY' AND timespan='day' (rolling 2y)
        ├── Compute features: daily_return, rolling_vol_20d, skewness_20d
        ├── Fit GaussianHMM for N in {2..5}, select min BIC
        ├── Map state indices → labels via return/vol characteristics
        ├── Serialize model (pickle → base64)
        ├── INSERT regime_models (version=latest, status='active')
        ├── Archive previous (status='archived')
        └── SET Redis "regime:current" → {regime_label, as_of_date, model_version}

Scanner event creation (real-time / batch)
  └── event_helpers.save_event()
        ├── RegimeService.get_regime_at_date(event_date)
        │     ├── If event_date == today → read Redis "regime:current"
        │     └── Else → load model from regime_models, predict state for that date
        └── ScannerEvent.regime = label

One-time backfill task
  └── backfill_regime_labels()
        ├── Load latest regime_models row
        ├── For each unique event_date in scanner_events WHERE regime IS NULL
        │     └── predict_regime(event_date) → UPDATE scanner_events SET regime=...
        └── LOG: N rows labeled, regime distribution
```

### `RegimeModel` schema

```python
class RegimeModel(Base):
    __tablename__ = "regime_models"
    id          = Column(Integer, primary_key=True)
    version     = Column(Integer, nullable=False, index=True)
    status      = Column(String(20), nullable=False, default="active")  # active | archived
    n_states    = Column(Integer, nullable=False)
    model_b64   = Column(Text, nullable=False)          # base64-encoded pickle
    feature_set = Column(JSONB, nullable=False)         # ["daily_return", "rolling_vol_20d", "skewness_20d"]
    state_label_mapping = Column(JSONB, nullable=False) # {"0": "risk_on", "1": "risk_off", ...}
    data_start_date = Column(Date, nullable=False)
    data_end_date   = Column(Date, nullable=False)
    bic_score       = Column(Float, nullable=True)
    trained_at  = Column(DateTime, nullable=False)
    created_at  = Column(DateTime, default=now_utc)
```

### Regime label mapping algorithm

After fitting, sort hidden states by their mean daily return (ascending). Map:
- State with **lowest mean return AND highest volatility** → `"risk_off"`
- State with **highest mean return AND moderate/low volatility** → `"risk_on"`
- State with **highest volatility** (regardless of return sign) → `"high_volatility"`
- Additional states (if N=4 or 5) → `"low_vol_drift"` or `"transition"`

Store the final mapping in `state_label_mapping` JSONB so it is queryable and human-auditable.

### Backtesting endpoint response

```json
GET /api/outcomes/regime-breakdown/pre_market_volume_spike

{
  "scanner_type": "pre_market_volume_spike",
  "total_events": 312,
  "breakdown": {
    "risk_on": {
      "sample_size": 148,
      "win_rate_pct": 62.2,
      "avg_mfe_pct": 3.1,
      "avg_mae_pct": 1.2
    },
    "risk_off": {
      "sample_size": 91,
      "win_rate_pct": 41.8,
      "avg_mfe_pct": 1.9,
      "avg_mae_pct": 2.4
    },
    "high_volatility": {
      "sample_size": 73,
      "win_rate_pct": 35.6,
      "avg_mfe_pct": 2.7,
      "avg_mae_pct": 3.1
    }
  }
}
```

## Alternatives Considered

### A: Store the HMM model in Redis only

Fast lookups, but Redis can evict under memory pressure. The current Redis config is also the Celery broker — a model eviction during a scan run would silently degrade signal quality with no alerting path. Rejected in favor of PostgreSQL as the durable store with Redis as a read cache.

### B: Use VIX as a feature

VIX is not available in the existing data pipeline (it is not a tradeable equity; Polygon does not expose it as a standard ticker). Adding a VIX sync path increases scope and introduces a new data-source dependency. Rolling SPY volatility (std of daily returns over 20 days) has ~0.85 correlation with VIX and is computable from data already in `stock_aggregates`. Deferred to a follow-up if regime differentiation proves insufficient.

### C: Fixed 3-state HMM (risk_on / risk_off / high_volatility)

Simpler to implement and label. Rejected because financial regime data often supports 4 states (e.g., a distinct "low-vol drift upward" state separate from a high-momentum "risk_on" state). BIC-based selection costs minimal extra work and produces a more honest model fit.

### D: Intraday regime switching

The issue explicitly defers this; daily regimes are the first step. Intraday would require streaming feature computation and a separate model with much higher operational complexity. Not in scope.

## Open Questions

- **SPY data depth**: If `stock_aggregates` has fewer than 252 trading days of SPY daily bars, the HMM may underfit. The backfill task should log a warning if fewer than 500 bars are available and proceed with what's there. If SPY daily data is absent entirely, the task exits cleanly without labeling.
- **State stability**: HMM states are not deterministic across re-trains (state numbering can flip). The `state_label_mapping` re-sort algorithm (lowest-mean-return → risk_off, etc.) anchors labels to economic characteristics, but a sudden shift in regime structure could produce a one-day mislabeling. Future work: add a regime consistency check (e.g., regime today should match regime from yesterday unless a significant feature shift occurs).

## Assumptions

- **SPY daily bars exist** in `stock_aggregates` going back at least 1 year. If not, the first training run will use whatever is available and emit a warning.
- **hmmlearn 0.3+** is compatible with the existing Python version in the Docker image. No other ML library dependencies are introduced in this PR.
- **Regime null is valid**: Existing `ScannerEvent` rows created before this feature ships will have `regime=NULL` until the backfill task completes. NULL events are excluded from regime-stratified scorecard queries.
- **Backfill is non-blocking**: The back-labeling Celery task runs as a low-priority background job and does not block scanner runs or the daily Celery beat.
- **Redis TTL**: The `regime:current` Redis key has a 25-hour TTL so a failed daily update does not leave a stale regime in use indefinitely — the service falls back to the last row in `regime_models`.
