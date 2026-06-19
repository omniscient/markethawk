# Oversold Bounce & Pocket Pivot — Explanation Contract Migration Design

**Date:** 2026-06-19
**Status:** Draft — pending approval
**Issue:** #460
**Parent epic:** #448 (Explainability Foundation for scanner events)
**Blocked by:** #455 (pre-market reference scanner), #458 (backfill path)

---

## Overview

This spec covers migrating `oversold_bounce` and `pocket_pivot` to the shared `scanner_explanation.v1` contract established by the pre-market reference scanner (#455). After this migration every new hit from both scanners will persist a structured explanation payload, and historical events can be backfilled via the `BackfillExplanationService` added in #458.

Both scanners detect daily-chart setups and are the next natural candidates after the pre-market reference path is proven. The migration is primarily a question of defining per-scanner criterion IDs, `why`-bullet templates, confidence wiring, and data-quality warning conditions — the underlying machinery (column, schema validation, `ExplanationBuilder`, `DataReadinessService`, `BackfillExplanationService`) all land in the blocking issues.

---

## Requirements

From the acceptance criteria in issue #460:

1. Oversold bounce events persist v1 explanations with RSI/reversal/risk criteria.
2. Pocket pivot events persist v1 explanations with volume/price/structure criteria.
3. Both scanners include applicable confidence inputs and data-quality warnings.
4. Backfill support and tests cover representative historical rows for both scanner types.

---

## Architecture / Approach

### Chosen approach: extend each scanner's fire path with ExplanationBuilder

Both scanners already compute all the values needed to build an explanation at fire time. The implementation adds:

1. An `ExplanationBuilder` call (from #453) in each scanner's persist step, producing a `scanner_explanation.v1` payload.
2. The payload is passed to `_save_event()` which stores it in `scanner_events.explanation` (from #451).
3. Both scanners register a per-scanner reconstruction mapping with `BackfillExplanationService` (from #458) so historical rows can be backfilled.

#### pocket_pivot: migrate to `ScannerService._save_event()`

`pocket_pivot` currently calls `alert_service.save_event()` directly and does not load `ranker_config`. As part of this issue, migrate it to `ScannerService._save_event()` with `ranker_config` — mirroring `oversold_bounce_scan.py`. This gives pocket_pivot a non-null `signal_quality_score` and allows `confidence_inputs` to be populated from real ranker weights. This is a prerequisite for the full explanation payload.

```python
# Before (pocket_pivot.py)
from app.services.alert_service import save_event as _save_event
# No ranker_config

# After
import app.services.scanner as _scanner_mod
ranker_config = _scanner_mod.load_ranker_config(db)  # once, before ticker loop
# ...
event_dict = ScannerService._save_event(
    db=db, ticker=ticker, event_date=event_date,
    scanner_type="pocket_pivot",
    indicators=indicators, criteria_met=criteria_met, enrichment=enrichment,
    previous_close=prior_close, closing_price=today["close"],
    ranker_config=ranker_config,
    explanation=explanation_payload,   # new
)
```

---

## Criterion IDs and `why` Bullets

Criterion IDs use `<scanner_short_name>.<criterion_key>` dot-notation, matching the reference scanner's `premarket.relative_volume` pattern. Short names are `oversold` and `pocket`.

### oversold_bounce

At fire time all criteria are `True` (scanner only fires when all pass), so `criteria_failed` is always `{}`.

| Criterion ID | Internal key | Observed | Threshold | Operator | Unit | Source | Lookback | `why` template |
|---|---|---|---|---|---|---|---|---|
| `oversold.rsi_2_cross` | `rsi_2_crossed` | `today["rsi_2"]` | 15 | `>=` | — | `stock_aggregates.day.close` | `90d` | `"RSI(2) crossed above 15 (now {rsi_2:.1f}, was {prev_rsi_2:.1f})"` |
| `oversold.rsi_5_cross` | `rsi_5_crossed` | `today["rsi_5"]` | 27 | `>=` | — | `stock_aggregates.day.close` | `90d` | `"RSI(5) crossed above 27 (now {rsi_5:.1f}, was {prev_rsi_5:.1f})"` |
| `oversold.no_gap_down` | `no_gap_down` | `today["Open"]` | `today["prev_low"]` | `>=` | `$` | `stock_aggregates.day.low` | `1d` | `"Opened above prior-day low (open {open:.2f} >= prior low {prev_low:.2f}), no gap-down"` |
| `oversold.volume_ma_3` | `volume_ma_3_ok` | `today["vol_ma_3"]` | 500000 | `>=` | shares | `stock_aggregates.day.volume` | `3d` | `"3-day average volume {vol_ma_3:,.0f} meets 500,000 liquidity floor"` |
| `oversold.price_floor` | `price_ge_5` | `today["prev_close"]` | 5.00 | `>=` | `$` | `stock_aggregates.day.close` | `1d` | `"Prior close ${prev_close:.2f} meets $5.00 price floor"` |

**`why` ordering:** RSI crossovers first (primary reversal signal), then `no_gap_down`, then materiality floors.

**Importance:** RSI criteria carry higher `importance` (e.g. 0.30 each), `no_gap_down` moderate (0.20), floors lower (0.10 each). Actual weights come from the ranker config if populated.

**Indicator addition required:** `yesterday["rsi_2"]` and `yesterday["rsi_5"]` must be added to the `indicators` dict as `prev_rsi_2` and `prev_rsi_5` so the `why` templates can render the "was X" value. The scanner already has these values in scope at fire time (line 122–123 in `oversold_bounce_scan.py`).

### pocket_pivot

| Criterion ID | Internal key | Observed | Threshold | Operator | Unit | Source | Lookback | `why` template |
|---|---|---|---|---|---|---|---|---|
| `pocket.volume_over_max_down` | `volume_over_max_down` | `today["volume"]` | `max_down_day_vol` | `>` | shares | `stock_aggregates.day.volume` | `{lookback_days_available}d` | `"Volume {today_volume:,.0f} exceeded highest down-day volume {max_down_day_vol:,.0f} ({volume_over_max_down_pct:+.0%}) over prior {lookback_days_available}d"` |
| `pocket.up_day` | `up_day` | `today["close"]` | `prior_close` | `>` | `$` | `stock_aggregates.day.close` | `1d` | `"Up day: closed ${today_close:.2f} above prior close ${prior_close:.2f} ({up_day_pct:+.1%})"` |
| `pocket.price_floor` | `price_floor` | `today["close"]` | 5.00 | `>=` | `$` | `stock_aggregates.day.close` | `1d` | `"Close ${today_close:.2f} meets $5.00 price floor"` |
| `pocket.volume_floor` | `volume_floor` | `today["volume"]` | 100000 | `>=` | shares | `stock_aggregates.day.volume` | `1d` | `"Volume {today_volume:,.0f} meets 100,000 liquidity floor"` |

**`why` ordering:** `pocket.volume_over_max_down` first (the defining pocket-pivot criterion, highest importance), then `pocket.up_day`, then floors.

All referenced indicator values (`today_volume`, `max_down_day_vol`, `volume_over_max_down_pct`, `today_close`, `prior_close`, `up_day_pct`, `lookback_days_available`) already exist in the `indicators` dict at lines 293–305 of `pocket_pivot.py` — no additional plumbing needed.

---

## Confidence Inputs

Both scanners populate `confidence_inputs` from `signal_quality_score` via `_save_event`:

```json
{
  "score": 0.68,
  "score_source": "signal_quality_score",
  "positive": { "relative_volume": 0.18, ... },
  "negative": {},
  "missing": {}
}
```

The ranker re-normalizes over whatever features are present for each scanner's reduced feature set, so a valid score is always produced. pocket_pivot's migration to `_save_event` with `ranker_config` is required for this to work.

---

## Data-Quality Warnings

Both scanners call the event-scoped `DataReadinessService.check_for_event()` + `DataQualityService.check_event_window()` from #454, merged with the scanner-specific conditions below.

### oversold_bounce

| Condition | code | severity | affected_inputs |
|---|---|---|---|
| 10 ≤ `len(daily_bars)` < 20 (RSI EWM not fully stabilized) | `insufficient_lookback` | `medium` | `["oversold.rsi_2_cross", "oversold.rsi_5_cross"]` |
| `len(daily_bars)` < 5 (5-day avg liquidity incomplete) | `insufficient_lookback` | `low` | `["oversold.volume_ma_3"]` |

`len(daily_bars)` is available from the query that the scanner already runs (line 71–72); no extra query needed. The scanner skips below 10 bars so the `< 10` case never produces a warning.

### pocket_pivot

| Condition | code | severity | affected_inputs |
|---|---|---|---|
| `split_in_lookback == True` (volume scale changed across split) | `integrity_violation` | `high` | `["pocket.volume_over_max_down"]` |
| `lookback_days_available < lookback_days` (10) — i.e. baseline from fewer bars | `insufficient_lookback` | `medium` | `["pocket.volume_over_max_down"]` |

Both values (`split_in_lookback`, `lookback_days_available`) are already computed and stored in `indicators` at lines 276 and 304 of `pocket_pivot.py`.

**Input registry coordination:** the `SCANNER_INPUT_REGISTRY` entries for both scanners in the #454 service should be updated to use the `oversold.*`/`pocket.*` criterion IDs so the generic warning outputs share the same vocabulary as the scanner-specific ones.

---

## Backfill Support

#458 provides `BackfillExplanationService` with a per-scanner registration point. #460's job is to supply the two reconstruction mappings:

```python
# In a new module: app/services/explanation_reconstructors.py (or within each scanner file)

class OversoldBounceReconstructor:
    scanner_type = "oversold_bounce"

    def reconstruct(self, event: ScannerEvent) -> dict:
        """Map stored indicators/criteria_met to v1 explanation."""
        ind = event.indicators or {}
        return ExplanationBuilder.build(
            schema_version="scanner_explanation.v1",
            criteria_passed={
                "oversold.rsi_2_cross": {..., "observed": ind.get("rsi_2"), "threshold": 15, ...},
                "oversold.rsi_5_cross": {..., "observed": ind.get("rsi_5"), "threshold": 27, ...},
                "oversold.no_gap_down": {...},
                "oversold.volume_ma_3": {..., "observed": ind.get("vol_ma_3"), "threshold": 500000, ...},
                "oversold.price_floor": {...},
            },
            criteria_failed={},
            confidence_inputs={"score": event.signal_quality_score, "score_source": "signal_quality_score", ...},
            data_quality_warnings=[],  # cannot reconstruct per-event DQ warnings from stored fields
            evidence={
                "reconstructed": True,
                "reconstruction_quality": "partial",  # prev_rsi_2/prev_rsi_5 may not be stored
                ...
            },
        )
```

**Idempotency:** inherited from #458 — never overwrites a `reconstructed=False` explanation; re-runs on the same row with `force=False` are no-ops.

**Reconstruction limits:** `prev_rsi_2` and `prev_rsi_5` are new additions to `indicators` (not present in historical rows). Reconstructed explanations for oversold_bounce set `evidence.reconstruction_quality = "partial"` and omit "was X" from the crossover bullets.

---

## Alternatives Considered

### 1. Extend alert_service.save_event instead of migrating pocket_pivot

Keep pocket_pivot on `alert_service.save_event` and add explanation support there. Rejected: all other migrated scanners go through `ScannerService._save_event`; diverging paths means two places to update when the explanation contract evolves. The one-time migration cost is small.

### 2. Defer ranker wiring for pocket_pivot

Populate `confidence_inputs` with `score=null` for pocket_pivot and populate it later. Rejected: the acceptance criterion says "Both scanners include applicable confidence inputs." A null score produces an unusable confidence block that breaks the analogs and trait-performance work in Epic 2.

### 3. Inline the backfill reconstruction in each scanner module

Define the `OversoldBounceReconstructor` and `PocketPivotReconstructor` inside the scanner files themselves. This is valid and reduces indirection; the spec is neutral on whether reconstruction logic lives in the scanner modules or a dedicated `explanation_reconstructors.py`. Follow whatever pattern #458 establishes for registration.

---

## Open Questions (non-blocking)

1. **Prefix length:** the Q&A session notes that `oversold`/`pocket` are judgment calls for brevity (matching `premarket`). Once #455 merges and the actual prefix pattern is visible in the codebase, confirm the short names are consistent.
2. **`importance` values:** the spec uses illustrative weights. Actual weights should come from the ranker config or a hardcoded default table — follow the pattern #455 establishes.
3. **`SCANNER_INPUT_REGISTRY` update scope:** #454's registry entries for `oversold_bounce` and `pocket_pivot` use plain input names (e.g. `"rsi"`, `"avg_daily_volume"`). Whether to update those to dot-notation in this ticket or in a follow-up depends on #454's extension API. Flag to the #454 implementer.

---

## Assumptions

- `scanner_events.explanation` JSONB column exists (from #451).
- `ExplanationBuilder` is importable and stable from #453.
- `DataReadinessService.check_for_event()` and `DataQualityService.check_event_window()` exist and accept the event-scoped signature (from #454).
- `BackfillExplanationService` registration API exists and is importable (from #458).
- The `alert_service.save_event` and `ScannerService._save_event` both accept an `explanation` keyword argument after #455 lands (or `_save_event` calls the builder internally).
- No migration is needed to add `prev_rsi_2`/`prev_rsi_5` to historical `indicators` rows — those fields are only present in rows created after this ticket lands, and the reconstruction mapping handles their absence with `reconstruction_quality: "partial"`.

---

## Test Plan

### Unit tests — live explanation shape

**oversold_bounce** (`tests/services/test_oversold_bounce_scan_module.py`):
1. Firing event produces non-null `explanation` with `schema_version: "scanner_explanation.v1"`, five criterion IDs (`oversold.rsi_2_cross` … `oversold.price_floor`) in `criteria_passed`, `criteria_failed == {}`, and two RSI crossover bullets first in `why`.
2. `signal_quality_score` is non-null when `ranker_config` is passed (already tested via `_save_event`; extend to confirm score flows into `confidence_inputs.score`).
3. `insufficient_lookback` (medium) warning appears in `data_quality_warnings` when `len(daily_bars)` is between 10 and 19.
4. `integrity_violation` warning absent when no split present; `prev_rsi_2`/`prev_rsi_5` appear in `indicators` dict at fire time.
5. Idempotency: calling the backfill reconstructor on a row that already has `evidence.reconstructed=false` leaves the row unchanged.

**pocket_pivot** (`tests/services/test_pocket_pivot.py`):
1. Firing event produces `explanation` with `pocket.*` criterion IDs; `pocket.volume_over_max_down` is first in `criteria_passed` with correct `observed`/`threshold` populated from `today_volume`/`max_down_day_vol`.
2. `ScannerService._save_event()` is called (not `alert_service.save_event`); `signal_quality_score` is non-null with a live `ranker_config`.
3. `integrity_violation` (high) warning in `data_quality_warnings` when `split_in_lookback=True`.
4. `insufficient_lookback` (medium) warning when `lookback_days_available < 10`.
5. Idempotency: backfill reconstructor does not overwrite a row with `evidence.reconstructed=false`.

### Unit tests — backfill reconstruction

New module `tests/services/test_explanation_reconstructors.py` (or similar):
- Feed a representative historical `oversold_bounce` row (realistic `indicators`, `criteria_met`, no `prev_rsi_2`/`prev_rsi_5`) → verify `reconstructed=true`, `reconstruction_quality="partial"`, all five criteria appear, `why` bullets omit "was X" for RSI.
- Feed a `pocket_pivot` historical row → verify `reconstructed=true`, `pocket.*` criterion IDs, `max_down_day_vol` populated in the criterion object.
- Re-run backfill on same row: no mutation (idempotency).
- Run on a row where `explanation` already has `reconstructed=false`: row unchanged.
