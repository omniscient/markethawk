# ADR-0013: Polygon↔IBKR Hybrid Failover — Alert-and-Degrade for Scans

**Date**: 2026-09-26  
**Status**: Accepted  
**Issue**: [#388 — providers: define Polygon↔IBKR degraded-feed failover for pre-market scans](https://github.com/omniscient/markethawk/issues/388)

## Context

Polygon.io is the primary market-data source and IBKR the secondary. Until now, nothing defined what
happens when Polygon degrades mid-pre-market (04:00–09:30 ET). `run_pre_market_scan()` reads
`StockAggregate` rows persisted by a separate sync pipeline; it does not call Polygon live. An
outage therefore starved ingestion without raising anything: tickers silently failed
`minimum_volume`, and runs completed "empty-but-green".

Three postures were considered: (1) alert-and-degrade everywhere; (2) auto-failover of bars/quotes
to `IBKRDataProvider`; (3) hybrid. Option 2 is not viable. `IBKRDataProvider.get_bars()` and
`get_snapshots()` are stubs that return `[]` for stocks, and even with real support, IBKR pacing
(60 historical requests / 10 min, no duplicates within 15 s) makes scanning thousands of tickers
inside the pre-market window arithmetically impossible.

## Decision

**Hybrid (option 3):**

- **Full-universe scans — alert-and-degrade, never switch providers.** For live session days
  (today's ET date, at or after 04:00 ET):

  | Failure class | Severity | Action |
  |---|---|---|
  | Circuit breaker open in any process | blocker | Stop the scan (`status=failed`), mark degraded, page |
  | Error rate ≥ `POLYGON_HEALTH_ERROR_RATE_THRESHOLD` (5 min, ≥ `PROVIDER_HEALTH_MIN_CALLS`) | blocker | Stop, mark, page |
  | p95 latency > `POLYGON_HEALTH_LATENCY_P95_THRESHOLD_SECONDS` (15 min) | warning | Continue, mark, warning alert only |
  | No pre-market minute bars, or freshest bar older than `PREMARKET_BAR_STALENESS_MINUTES` before 09:30 ET | blocker | Complete, mark, page |
  | Pre-market coverage below `PREMARKET_MIN_COVERAGE_RATIO` | warning | Complete, mark, record `coverage_ratio` |

  These checks apply to every scanner type run through `_run_universe_scan_logic` on a live session
  day, because any universe scan of today's data depends on the same ingestion. The pre-market
  ingestion checks (no/stale bars, coverage) apply only to scanners that report diagnostics, which
  today means `pre_market_volume_spike`.

  Degradation is recorded on the existing `ScannerRun.data_degraded` and as
  `quality_gate.issues[]` entries with `code=provider_gap`, `detail.subtype="live_degradation"`,
  `detail.worker`, and a `detail.reason` from the table. No parallel "data_quality" field is added.
- **Active Watchlist — already resilient, no new failover.** `live_scanner/` streams watchlist
  symbols straight from IB Gateway (`reqMktData`/`reqRealTimeBars`). It reaches clients over Redis
  pub/sub (`watchlist:live_data`, `watchlist:alerts`) with no Polygon coupling.
- **Per-ticker chart stream (`/api/v1/live/ws/{ticker}/{resolution}`) — detection only, explicitly no
  fallback.** IBKR can only stream the curated watchlist and cannot serve arbitrary tickers on
  demand. The stream reports `feed_status` frames. The UI shows "Live feed unavailable — showing
  last known data". `polygon_ws_connected` means "the Polygon client thread is running". It is
  set before the socket authenticates and cleared when the client exits, so it detects a dead
  stream but not an authenticated-yet-silent one.

Provider health is a cross-process Redis rolling window (`app/core/provider_health.py`), written at
the `MassiveDataProvider` chokepoint and by a pybreaker listener. Breaker state is in-process per
worker, so the record is keyed by `hostname:pid`, and the local breaker is OR'd in as a fast path.

## Consequences

- A live Polygon outage produces a visibly degraded or failed run with a reason: in the UI, via
  `GET /api/v1/scanner/history?data_degraded=true`, and in Grafana (`polygon-provider-degraded`,
  `pre-market-scan-provider-gap`, `polygon-latency-elevated`).
- Every Polygon REST call now costs one pipelined Redis round trip. On Redis errors, writes back off
  for 30 s, so they never slow provider calls.
- Thresholds are env-tunable first cuts that have not been validated against production pre-market
  bar cadence. Revisit after a few weeks of `provider_*` gauge history. In particular the
  10-minute `PREMARKET_BAR_STALENESS_MINUTES` default is the value spec §5 asked to confirm during
  planning; it could not be checked against production bar cadence pre-merge and remains a
  first cut.
- `breaker_open` is only reliable while calls keep flowing. `_merge_breaker_states` ignores entries
  older than `PROVIDER_HEALTH_ERROR_WINDOW_SECONDS` (5 min) and downgrades `open` entries older
  than `POLYGON_CB_RESET_TIMEOUT` to `half-open`, so a process that trips its breaker and then
  stops calling Polygon reads `closed` again after five minutes (verified: age 10 s -> open,
  120 s -> half-open, 400 s -> closed). During a sustained outage with idle workers the
  `no_fresh_premarket_bars` / `stale_premarket_bars` ingestion checks are the backstop, not the
  breaker gauge.
- `provider_request_latency_p95_seconds` is bucket-quantised, not interpolated: it reports the upper
  bound of the `LATENCY_BUCKETS` bucket the p95 falls in. Both the finding check and the
  `polygon-latency-elevated` rule therefore compare with `>`, so the effective meaning is "p95
  landed in a bucket above the threshold". Set thresholds to bucket bounds.
- The live-session-day holiday guard depends on `market_holidays` having NYSE `full_close` rows for
  the date in question. The seed migration (`c5d6e7f8a9b0`) covers 2024–2026 only; without a row for
  a weekday full close the guard is inert and that day pages with `no_fresh_premarket_bars`. The
  table must be extended each year (it is the same dependency `services/data_quality.py` already
  has).
- Historical-range scans are unaffected. Their data quality remains the domain of
  `UniverseQualityReport` and the existing `quality_gate` evidence.
- Real IBKR stock market-data support would be a separate ADR. It would not change the scan posture,
  because of pacing limits.
