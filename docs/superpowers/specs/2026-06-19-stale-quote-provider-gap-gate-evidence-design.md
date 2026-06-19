# Stale Quote and Provider Gap Gate Evidence Design

**Date:** 2026-06-19  
**Issue:** #499 — Generate stale quote and provider gap gate issues  
**Parent Epic:** #491 — Data Quality Trust Gate  
**Depends on:** #492 — Add reusable data quality gate contract and service  
**Status:** Spec

---

## Overview

Issue #499 is sub-issue #8 in the Data Quality Trust Gate epic. It adds the evidence-detection logic for two gate issue codes that were declared but not emitted by #492:

- **`stale_quote`** — fired when the latest available data per ticker is older than acceptable for the requesting consumer.
- **`provider_gap`** — fired when provider coverage evidence shows data is absent, partial, or structurally gapped. Extended from the rough proxy in #492 with three subtypes and a richer context payload.

> **Naming note:** The issue body uses `stale_quote_risk` as prose, matching the epic's human-readable label vocabulary. The emitted issue code is `QualityIssueCode.stale_quote` per the #492 contract. No enum rename is performed.

---

## Requirements

1. `_build_assessment()` emits `stale_quote` issues for tickers whose `last_bar` timestamp is older than the acceptable age threshold for the given policy and timespan.
2. The report-freshness guard: if the `UniverseQualityReport` is itself stale (strict: >4h, advisory: any age that makes per-ticker staleness unassessable), a scope-level `stale_quote` issue fires.
3. Staleness thresholds are trading-day based (weekday-only), not calendar days. They respect the existing `MarketHoliday` table.
4. An optional `as_of_date` in `data_requirements` shifts the staleness reference for historical/backtest consumers so a ticker whose `last_bar` covers the `as_of_date` is never stale.
5. `provider_gap` extends the #492 proxy (`gap_count`/`continuity_score`) with two new sub-types: `absent` (`actual_bars == 0`) and `partial` (low relative or absolute coverage).
6. Transient provider errors (rate-limiting, connection failures) are **out of scope** — they are not recorded in any stored table. The spec notes them as a known limitation and recommends a follow-up issue for provider request telemetry.
7. Issue payloads carry a structured `context` dict with subtype, ticker-level metrics, and optional `source` field (populated as `None` today — no per-ticker provider attribution exists in stored data).
8. `policy="off"` suppresses all stale_quote and provider_gap detection.
9. Tests cover: strict vs advisory severity difference; report-freshness guard; `as_of_date` override; absent/partial/structural provider_gap subtypes; and `policy="off"` passthrough.

---

## Architecture

### What #492 established

```
QualityGateService.assess(db, universe_id, policy, scope)  ← DB wrapper
    └── _build_assessment(report_data, data_requirements, scope, policy)  ← pure function
           ├── _check_missing_bars()      ← already wired
           ├── _check_provider_gap()      ← #492 proxy (gap_count/continuity_score)
           └── _check_insufficient_lookback()  ← already wired
```

### What #499 adds

Two private pure functions are added and called from `_build_assessment`. The existing `_check_provider_gap()` body is extended in-place (not replaced) by adding the `absent` and `partial` sub-type checks ahead of the existing `structural` check.

```
_build_assessment(report_data, data_requirements, scope, policy)
    ├── [existing] _check_missing_bars()
    ├── _check_stale_quote(tickers, generated_at, policy, scope, data_requirements)   ← NEW
    ├── _check_provider_gap(tickers, policy, scope)                                   ← EXTENDED
    └── [existing] _check_insufficient_lookback()
```

`assess()` passes `report_data["generated_at"]` and `report_data["tickers"]` into `_build_assessment`. No additional DB queries are added.

---

## Stale Quote Detection

### Data source

- Per-ticker `last_bar` from `report_data["tickers"]` (ISO string, set by `_analyze_ticker_timespan`).
- Report-level `generated_at` from `report_data["generated_at"]` (already present in the report dict).
- Staleness is measured against `utc_now()` or the optional `as_of_date` from `data_requirements`.

### Thresholds

Thresholds are computed in trading days (using `MarketHoliday` table for accuracy, weekday-filter as fallback):

| Policy | Intraday timespans (minute / hour) | Daily+ timespans (day / week / month) | Severity |
|---|---|---|---|
| `strict` | `last_bar` > T-1 trading day old | `last_bar` > T-1 trading day old | **blocker** |
| `advisory` | `last_bar` > T-5 trading days old | `last_bar` > T-7 trading days old | **warning** |
| `off` | no check | no check | none |

T = `utc_now()` (or `as_of_date` if provided). The T-1 boundary aligns with the existing normalizer convention: `(today - last_date).days > 1` in `normalization.py:356`.

### Report freshness guard

If `generated_at` is older than 4 hours (reusing the threshold from `system_service.py:289`), the gate cannot certify freshness from stale snapshot data:

- `strict` → scope-level `stale_quote` **blocker** with message "quality report stale, generated {generated_at}".
- `advisory` → scope-level `stale_quote` **warning**.

This check runs before the per-ticker loop; if the report is stale, per-ticker staleness checks are skipped (the report-level issue covers the whole scope).

### `as_of_date` override

`data_requirements` dict may carry an optional `"as_of_date": "YYYY-MM-DD"` key. When present, staleness is measured against that date instead of `utc_now()`. A ticker whose `last_bar` >= `as_of_date` is considered fresh regardless of calendar age. This enables historical and backtesting consumers to not drown in false blockers on month-old data scopes.

`as_of_date` lives in `data_requirements` (not `QualityGateScope`) because it is a consumer requirement ("I need data covering this date") rather than a filtering dimension.

### stale_quote context payload

```python
{
    "subtype": "report_stale",  # or "ticker_stale"
    "ticker": "AAPL",           # None for report-level scope issues
    "timespan": "minute",
    "multiplier": 1,
    "last_bar": "2026-06-16T20:00:00",
    "generated_at": "2026-06-18T15:00:00",  # report-level issues only
    "trading_days_stale": 2,
    "threshold_trading_days": 1,
    "as_of_date": "2026-06-19",   # None if not provided
    "source": None,               # no per-ticker provider attribution in stored data today
}
```

---

## Provider Gap Detection

### Three subtypes

The existing `_check_provider_gap()` is extended with two new sub-type checks that run before the existing `structural` check:

#### 1. Absent (`actual_bars == 0`)

A ticker with zero bars was asked for but the provider returned nothing. The existing `_analyze_ticker_timespan` returns `gap_count: 0, continuity_score: 100.0` for this case — the #492 proxy is structurally blind to total absence. This check catches it explicitly.

- Trigger: `actual_bars == 0` (and ticker is in scope).
- Severity: **blocker** for both strict and advisory (no data is never acceptable).
- Context: `subtype="absent"`, `ticker`, `timespan`, `multiplier`, `actual_bars=0`, `expected_bars`.

#### 2. Partial (`coverage_pct` low)

Some tickers have significantly less coverage than the universe — consistent with provider pagination cuts, provider-side delistings, or partial data returns.

- Trigger (absolute): `coverage_pct < 50` and `actual_bars > 0`.
- Trigger (relative outlier): `coverage_pct` is more than 30 points below the universe median AND `coverage_pct < 80`.
- Severity: advisory → **warning**; strict → **blocker**.
- Universe median is computed once before the ticker loop from `[t["coverage_pct"] for t in tickers if t.get("actual_bars", 0) > 0]`. Using median (not mean) makes it robust to absent-ticker outliers.
- Context: `subtype="partial"`, `ticker`, `timespan`, `multiplier`, `coverage_pct`, `universe_median_coverage`, `actual_bars`, `expected_bars`.

#### 3. Structural (existing #492 logic — retained unchanged)

Gap-based detection using `gap_count`/`continuity_score`:
- Warning: `gap_count >= 1`.
- Blocker: `continuity_score < 70`.
- Context: `subtype="structural"`, `ticker`, `timespan`, `multiplier`, `gap_count`, `continuity_score`.

### Provider/source attribution

No per-ticker `source`/`provider` column exists in `StockAggregate` or `FuturesAggregate`, and `report_data` does not carry it. The `source` field in all `provider_gap` context payloads is `None` for now. This satisfies the acceptance criterion "when available" — the field is forward-compatible for when a provider column is added.

### Known limitation: transient provider errors

Transient provider errors (HTTP 429 rate-limited, connection timeout, Polygon circuit-open) are not stored in any DB table and cannot be detected from `report_data`. The persistent symptoms of those errors are detected via the `absent` and `partial` subtypes. Live error-class attribution requires a separate provider request telemetry store — **recommended as a follow-up issue**.

---

## Alternatives Considered

### Alt A: Query `StockAggregate.MAX(timestamp)` directly in `assess()`

Adding a live `MAX(timestamp)` per-ticker query in `assess()` would give real-time freshness but breaks the `_build_assessment` pure-function contract from #492, reintroduces N+1 DB access, and duplicates work already done by `DataQualityService.analyze_universe()`. Rejected.

### Alt B: New `QualityGateService.assess_freshness()` method

A separate method for stale/provider checks only would fit narrow call sites that don't need the full assessment but adds API surface that has no current caller. Rejected in favor of extending `_build_assessment`.

### Alt C: Subtype-specific issue codes (e.g., `provider_gap_absent`)

Splitting into multiple enum members would make the switch to stable codes harder for downstream consumers (preflight API, UI in #493/#495) that are already written against `provider_gap`. Context subtypes in the payload provide the same discrimination without breaking the contract. Rejected.

---

## Open Questions

1. Should `DataQualityService.analyze_universe()` be updated to store `provider`/`exchange` in the per-ticker entry so future gate runs can populate the `source` field? (Non-blocking for #499; could be added in a follow-up.)
2. Should the provider request telemetry follow-up issue be filed as part of this epic (#491) or as a standalone improvement?

---

## Assumptions

- `QualityIssueCode`, `QualityGateService`, `_build_assessment`, `QualityGateScope`, `QualityGatePolicy`, `QualityGateVerdict`, and `QualityGateAssessment` all land with #492 before #499 is implemented.
- `UniverseQualityReport.report_data["generated_at"]` is always present when `status == "complete"` (set by `DataQualityService.analyze_universe()` at line 541).
- Trading-day arithmetic uses the `MarketHoliday` table with fallback to `weekday() < 5` if the holiday table is empty — consistent with existing `data_quality.py` usage.
- Per-ticker `last_bar` timestamps from `report_data` are naive UTC (as stored by `_analyze_ticker_timespan`, line 386).
- `policy="advisory"` maps to "historical/exploratory consumers" per #491; `policy="strict"` maps to "live/current consumers."
- `actual_bars == 0` in a per-ticker report entry occurs when `DataQualityService.analyze_universe()` finds no stored `(timespan, multiplier)` combos for that ticker — i.e., the ticker is in the universe but the provider returned no bars in any resolution. Within-combo zero-bar entries cannot appear in practice because combos are discovered by querying distinct `(timespan, multiplier)` pairs from existing rows. The `absent` check is correct to treat a zero-bars ticker entry as a provider-coverage failure.
