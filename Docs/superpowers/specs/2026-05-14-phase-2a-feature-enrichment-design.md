# Phase 2a — Feature Enrichment at Signal Time

**Date**: 2026-05-14  
**Status**: Pending Review  
**Issue**: #21

## Problem

MarketHawk signals fire when volume and gap criteria pass, but every passing signal is treated equally. The system has no record of the macro environment, sector momentum, timing, or volatility regime at the moment a signal fired. Without this context, the statistical discovery planned for Phase 2b has nothing meaningful to correlate with outcomes — it can only analyse the signal criteria themselves, which are already known.

## Solution

Enrich every `ScannerEvent.indicators` with a feature vector captured at signal creation time. No model, no training — pure data collection. The existing `indicators` JSONB field is schemaless, so all new features are additive and no migration is required.

Five feature categories are added:

1. **Market context** — ES/NQ futures movement at signal time (macro risk environment)
2. **Sector** — ticker's sector and its ETF's pre-market change (sector momentum)
3. **Timing** — minutes into pre-market session, day of week (edge patterns)
4. **Volatility regime** — ATR percentile rank within own 60-day history (contextual vol)
5. **Catalyst enrichment** — structured form of existing catalyst data (queryable)

A sixth category (TimesFM price forecast) is specified but deferred pending Phase 1 (#20).

## Feature Vector

All values are additive to the existing `indicators` dict. Every feature degrades to `null` when its data source is unavailable — no exception is raised, no scan result is affected.

### Market context

| Key | Type | Description |
|-----|------|-------------|
| `es_pct_from_prev_close` | `float \| null` | ES daily close % change from prior session close |
| `nq_pct_from_prev_close` | `float \| null` | NQ daily close % change from prior session close |
| `market_context` | `"risk_on" \| "risk_off" \| "neutral" \| null` | Categorical derived from combined ES+NQ direction |

**Risk-on/off classification**: if both ES and NQ are up (both > +0.1%), market context is `risk_on`; if both down (both < -0.1%), `risk_off`; otherwise `neutral`.

### Sector

| Key | Type | Description |
|-----|------|-------------|
| `sector` | `str \| null` | GICS sector from `TickerReference.sector` |
| `sector_etf` | `str \| null` | Corresponding SPDR ETF symbol (e.g. `"XLK"`) |
| `sector_etf_pct_change` | `float \| null` | Pre-market % change of the sector ETF at signal time |

**Sector → ETF mapping** (hardcoded):

| Sector | ETF |
|--------|-----|
| Technology | XLK |
| Financials | XLF |
| Health Care | XLV |
| Consumer Discretionary | XLY |
| Consumer Staples | XLP |
| Energy | XLE |
| Industrials | XLI |
| Materials | XLB |
| Real Estate | XLRE |
| Utilities | XLU |
| Communication Services | XLC |

### Timing

| Key | Type | Description |
|-----|------|-------------|
| `minutes_since_premarket_open` | `float \| null` | Minutes from 4:00 AM ET to last pre-market bar |
| `day_of_week` | `int \| null` | 0 = Monday, 4 = Friday |
| `is_monday` | `bool` | True when signal fires on Monday |
| `is_friday` | `bool` | True when signal fires on Friday |

### Volatility regime

| Key | Type | Description |
|-----|------|-------------|
| `atr_percentile_rank` | `float \| null` | ATR_10 percentile rank within own 60-day distribution (0–100) |
| `volatility_regime` | `"compressed" \| "normal" \| "expanded" \| null` | Derived from percentile rank |

**Regime thresholds**: compressed < 25th pct, expanded > 75th pct, normal otherwise.

### Catalyst enrichment

| Key | Type | Description |
|-----|------|-------------|
| `has_news_catalyst` | `bool` | True if any catalyst tag matched |
| `catalyst_tag_count` | `int` | Number of distinct catalyst tags |
| `catalyst_recency_hours` | `float \| null` | Hours since most recent news article |

### TimesFM price forecast *(deferred — Phase 1 dependency)*

These keys are reserved. All default to `null` in Phase 2a. Phase 1 (#20) will populate them once its forecast worker is operational.

| Key | Type | Description |
|-----|------|-------------|
| `price_direction` | `"up" \| "flat" \| "down" \| null` | Forecast trend vs. current price |
| `price_confidence` | `float \| null` | Normalised confidence band width |
| `price_forecast_4h` | `float \| null` | Expected price 4 hours ahead |
| `price_forecast_1d` | `float \| null` | Expected price 1 day ahead |

## Architecture

### Selected approach: Hybrid batch + inline

Batch data shared across all tickers in a scan run is fetched once in `_get_batch_enrichment_data()`. Per-ticker data that depends on each ticker's own daily bar series is computed inline in the scanner loop.

**`_get_batch_enrichment_data()` additions** (one call per scan run):

1. **ES/NQ futures context**: Query `futures_aggregates` for the two most recent daily bars (per symbol) where `symbol IN ('ES', 'NQ')` and `timestamp <= event_date`. Compute `(close_today - close_yesterday) / close_yesterday * 100` for each. Build a single shared `market_context_dict` passed alongside the per-ticker batch data.

2. **Sector ETF bars**: Query `stock_aggregates` for all 11 sector ETF tickers where `is_pre_market = true` and `date(timestamp) = event_date`. Compute pre-market % change per ETF. Build a `sector_etf_pct_dict` keyed by ETF symbol.

Both queries degrade gracefully: if no rows are returned (fresh environment, no IBKR/Polygon data), the dict is empty and all related features become `null` without raising an exception.

**Per-ticker loop additions** in `run_pre_market_scan()` (for each ticker, using the 90-day daily bars already fetched by `calculate_day_metrics()`):

3. **Timing features**: Derive from `pre_aggs[-1].timestamp` (last pre-market bar for the ticker). Compute minutes elapsed since `datetime.combine(event_date, time(4, 0), tzinfo=ZoneInfo("America/New_York"))`. Never use `datetime.now()` — this ensures backtest reproducibility when scans are re-run against historical dates.

4. **Volatility regime**: Build a `pd.DataFrame` from the 90-day daily bars (same bars used by the existing scanners). Compute True Range (TR) and ATR_10 rolling average. Rank the final ATR_10 value within the 60-day window using `pd.Series.rank(pct=True)`. Derive the categorical label. Follow the ATR pattern already implemented in `run_oversold_bounce_scan()` (lines 448–454 in `scanner.py`).

5. **Sector features**: Look up the ticker's sector from the batch `ref_map` (already fetched by `_get_batch_enrichment_data()` step 2). Map sector → ETF symbol using the hardcoded dict. Look up the ETF's pre-market % change from `sector_etf_pct_dict`.

6. **Catalyst features**: Derive from existing `enrichment[ticker]` data. Extend `CatalystParser.batch_analyze()` to return `latest_article_utc` (add `"latest_article_utc": recent_news[0].published_utc if recent_news else None` to the per-ticker result dict — `recent_news` is already fetched and sorted most-recent-first at line 74 of `catalyst_parser.py`). Compute `catalyst_recency_hours` from `(pre_aggs[-1].timestamp - latest_article_utc).total_seconds() / 3600`.

All six feature groups are merged into the `indicators` dict before the call to `_save_event()`. No changes to `_save_event()` itself, no changes to scanner pass/fail criteria evaluation.

### Sector ETFs universe seeding

A new Alembic data migration creates:

1. A row in `stock_universes`: `name = "Sector ETFs"`, `is_active = true`, `description = "11 SPDR sector ETFs for pre-market momentum context"`
2. Eleven rows in `stock_universe_tickers`: one per ETF, `asset_class = 'stocks'`, `data_source = 'massive'`

Use `ON CONFLICT DO NOTHING` so the migration is idempotent. No fixed ID — use name-based conflict resolution.

The same rows are added to `dark-factory/seed_preview.sql` (raw SQL, not Alembic) following the existing `INSERT INTO stock_universes ... ON CONFLICT` pattern used for universe id=1.

Once the universe exists, the standard Catch Up / Sync mechanism in the Universes UI populates `stock_aggregates` with Polygon bars for these tickers automatically.

## Alternatives Considered

### A — All features in `_get_batch_enrichment_data()`

Move ATR and timing computation into the batch enrichment method, requiring either pre-fetching all tickers' daily bars up front or a separate bulk query. Rejected: the per-ticker daily bars are already fetched in the scanner loop; duplicating or pre-fetching them adds cost and complexity without benefit.

### B — New `FeatureEnricher` service

Create `backend/app/services/feature_enricher.py` as a dedicated class. Rejected: premature abstraction at this stage. The feature logic is 5–6 short computations; a dedicated service class would add indirection without justification. Phase 2b may warrant extraction once the feature set stabilises.

### C — Hybrid (selected)

Batch-level data (ES/NQ, sector ETFs) fetched once in `_get_batch_enrichment_data()`. Per-ticker data (ATR, timing, catalyst) computed inline in the scan loop using already-available bars. Matches existing codebase patterns exactly. Zero new abstractions.

## Open Questions

- **Sector ETF data recency**: The sector ETF pre-market % change depends on bars being populated via the Polygon pipeline before the scan runs. If the "Sector ETFs" universe hasn't been synced recently, pre-market bars may be stale or absent. This is expected graceful-degradation behaviour (`null` feature value), but users should be aware. A future operational note or dashboard warning may be warranted.

- **ES/NQ contract month**: `futures_aggregates` stores bars by contract month. The market context query should use the front-month contract. The query should filter by the front-month symbol (e.g. `ESM26`) or use the rollover mapping. The exact query pattern should follow `FuturesDataService.get_continuous_series()` conventions to avoid stale back-month data.

## Assumptions

- **`TickerReference.sector`** contains GICS sector names matching the hardcoded mapping table. If a ticker's sector field uses a different naming convention (e.g. "Info Tech" vs "Technology"), the ETF lookup will miss and `sector_etf` will be `null`.
- **`futures_aggregates`** is populated with daily ES/NQ bars by the existing IBKR data pipeline. In CI/test environments without IBKR, market context features will always be `null`.
- **ATR computation** assumes at least 10 days of daily bars exist for the ticker. If fewer bars are available, ATR_10 is `null` and the volatility regime features are `null`.
- The `run_oversold_bounce_scan()` method is not modified; only `run_pre_market_scan()` gains the new feature enrichment in Phase 2a. The oversold bounce scanner already computes ATR for its own criteria; both can coexist independently.
- Phase 1 (#20) TimesFM price forecast integration is explicitly out of scope — `price_direction` and related keys are `null` throughout Phase 2a.

## Definition of Done

- [ ] All feature categories populated in `indicators` on new `ScannerEvent` records produced by `run_pre_market_scan()`
- [ ] Every feature degrades to `null` without error when its data source is unavailable
- [ ] Timing features derived from `event_date` + last pre-market bar timestamp (not `datetime.now()`)
- [ ] Existing scanner pass/fail criteria evaluation is unchanged
- [ ] `CatalystParser.batch_analyze()` returns `latest_article_utc` per ticker
- [ ] "Sector ETFs" universe seeded via Alembic data migration (11 ETF tickers)
- [ ] `dark-factory/seed_preview.sql` updated with Sector ETFs universe rows
- [ ] TimesFM price forecast keys (`price_direction`, `price_confidence`, `price_forecast_4h`, `price_forecast_1d`) documented and defaulting to `null`

## Out of Scope

- Statistical analysis of features → Phase 2b (#22)
- Signal quality score → Phase 2c (#23)
- Schema migrations (JSONB is schemaless; no new columns added)
- TimesFM price forecast feature implementation → Phase 1 (#20)
- `run_oversold_bounce_scan()` enrichment (only pre-market volume spike scanner is enriched in Phase 2a)
