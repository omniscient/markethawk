# Pre-Market Volume Spike: Explanation Integration Design

**Date:** 2026-06-19
**Issue:** #455
**Parent Epic:** #448 (Explainability Foundation for scanner events)
**Status:** Spec generated, pending review
**Blocked by:** #451 (explanation column), #453 (ExplanationBuilder), #454 (event-scoped data quality warnings)

---

## Overview

Issue #455 is the fifth sub-issue of the Explainability Foundation epic. It integrates the
scanner-neutral `ExplanationBuilder` (issue #453) and event-scoped data quality warnings (issue
#454) into `pre_market_scan.py`, so that every new `pre_market_volume_spike` hit persists a
populated `scanner_explanation.v1` JSONB alongside the existing event envelope.

The change is purely additive — it does not touch `indicators`, `criteria_met`, `metadata_`,
`signal_quality_score`, outcome snapshots, or alert evaluation logic.

---

## Requirements

From the issue acceptance criteria:

1. New `pre_market_volume_spike` events persist a populated `scanner_explanation.v1` explanation.
2. Explanation includes volume, liquidity, threshold method, catalyst, market/sector context,
   confidence score source, and data-quality warnings where available.
3. Existing pre-market scanner tests are updated without weakening behavioral assertions.
4. Created events remain compatible with outcome snapshot creation and alert evaluation.

Additional inferred requirements:

5. If explanation generation fails (ExplanationBuilder raises, or DataReadinessService raises),
   the event is still persisted with `explanation=None` — failure must not block detection or
   alerting.
6. The spec does **not** re-define the ExplanationBuilder call signature (owned by #453) or the
   DataReadinessService event-scoped method (owned by #454). It defines the data contract —
   which `EnrichedSignal` fields map to which scanner criterion IDs.

---

## Architecture

### Chosen Approach: New `_explain` Stage

Insert a new `_explain(enriched, db, event_date, ranker_config)` stage between `_enrich` and
`_persist` in `pre_market_scan.py`. This matches the existing pipeline structure:

```
_detect  →  _enrich  →  _explain  →  _persist
(pure)      (reads)     (reads)      (writes)
```

`_enrich` already reads the DB (`calculate_day_metrics`, `_build_timing_features`). A separate
`_explain` stage keeps the read-only data-quality check and explanation-building alongside
`_enrich`, not inside the single-commit write stage (`_persist`).

#### New `ExplainedSignal` Dataclass

```python
@dataclass
class ExplainedSignal:
    enriched: EnrichedSignal
    explanation: Optional[dict]  # scanner_explanation.v1 or None on builder failure
```

#### `_explain` Function Signature

```python
def _explain(
    enriched: list[EnrichedSignal],
    db: Session,
    event_date: date,
    ranker_config: Optional[dict],
) -> tuple[list[ExplainedSignal], list[dict]]:
    ...
```

Returns `(explained_signals, failed_list)` using the same error-isolation pattern as `_enrich`.
Per-signal failures log a warning and add an entry to `failed_list`; the signal still becomes
an `ExplainedSignal` with `explanation=None` so it can be persisted normally.

#### `_explain_one` Per-Signal Logic

```python
def _explain_one(
    signal: EnrichedSignal,
    db: Session,
    event_date: date,
    ranker_config: Optional[dict],
) -> Optional[dict]:
    # Step 1: fetch event-scoped data quality warnings (best-effort)
    try:
        from app.services.data_readiness import DataReadinessService
        warnings = DataReadinessService.check_for_event(
            db, signal.raw.ticker, "pre_market_volume_spike", event_date
        )
    except Exception as e:
        logging.warning("pre_market_scan: data readiness check failed for %s: %s", signal.raw.ticker, e)
        warnings = []

    # Step 2: assemble criterion inputs (see mapping table below)
    # Step 3: build confidence inputs from ranker_config + signal_quality_score
    # Step 4: call ExplanationBuilder (from #453)
    from app.services.explanation_builder import ExplanationBuilder
    return ExplanationBuilder.build(
        scanner_type="pre_market_volume_spike",
        criteria=...,         # assembled from EnrichedSignal per mapping table
        confidence_inputs=..., # from ranker_config and indicators
        warnings=warnings,
        evidence={...},
    )
```

The entire body of `_explain_one` is wrapped in try/except at the `_explain` level — if it
raises, `explanation=None` is used and the signal is still passed to `_persist`.

### Scanner-Specific Criterion ID Mapping

This is the data contract issue #455 owns. The ExplanationBuilder receives these criterion IDs
with their observed values and metadata sourced from `EnrichedSignal`:

| Criterion ID | Passes when | Observed value | Source field | Threshold | Unit | Lookback |
|---|---|---|---|---|---|---|
| `premarket.volume_spike` | `raw.criteria_met["volume_spike"]` | `raw.relative_volume` (for static_4x) or `raw.anomaly_score` (for timesfm) | `raw.relative_volume`, `raw.anomaly_score` | 4.0 (static) or `anomaly_threshold` (timesfm) | "x" | "20d" |
| `premarket.minimum_volume` | `raw.criteria_met["minimum_volume"]` | `raw.pre_market_volume` | `raw.pre_market_volume` | 100_000 | "shares" | "current_session" |
| `premarket.liquidity` | `raw.criteria_met["liquidity"]` | `raw.avg_volume_20d` | `raw.avg_volume_20d` | 500_000 | "shares/day" | "20d" |
| `premarket.threshold_method` | always informational | `raw.threshold_method` ("static_4x" or "timesfm") | `raw.threshold_method` | — | — | — |
| `premarket.catalyst` | informational | `indicators["has_news_catalyst"]`, `indicators["catalyst_tag_count"]`, `indicators["catalyst_recency_hours"]` | `indicators` | — | various | "72h" |
| `premarket.market_context` | informational | `indicators["es_pct_from_prev_close"]`, `indicators["nq_pct_from_prev_close"]`, `indicators["market_context"]` | `indicators` | — | "%" | "current_session" |
| `premarket.sector_context` | informational | `indicators["sector"]`, `indicators["sector_etf"]`, `indicators["sector_etf_pct_change"]` | `indicators` | — | "%" | "current_session" |

**Criteria classification**: `volume_spike`, `minimum_volume`, and `liquidity` are gating
criteria (go in `criteria_passed` / `criteria_failed` depending on `raw.criteria_met`). The
remaining four are informational context criteria and go in `criteria_passed` only when their
values are non-null.

**Note on `criteria_failed`**: Because `_detect` returns `None` when any gating criterion fails
(see `if not all(criteria_met.values()): return None`), all `EnrichedSignal` objects that reach
`_explain` have all three gating criteria as `True`. In practice, `criteria_failed` will always
be empty for this scanner. The ExplanationBuilder should still accept the field — it must be
passed an empty dict, not omitted — so that the schema contract is satisfied and future scanners
that can partially fire can populate it correctly.

**Confidence inputs** assembly:

```python
confidence_inputs = {
    "score": signal_quality_score,        # from indicators or computed during _explain
    "score_source": "signal_quality_score",
    "positive": {},  # populated from ranker weights if ranker_config is available
    "negative": {},
    "missing": {},   # keys for indicators not present or None
}
```

The `signal_quality_score` is not computed in `_explain` — it is already computed in `_persist`
via `compute_signal_quality_score(indicators, ranker_config["weights"])`. To avoid double
computation, `_explain` should compute it once and carry it forward, OR `_persist` should
receive it pre-computed. See Open Questions #1.

### Threading Explanation Through to `_save_event`

Three related changes required (coordinated with issues #451 and #453):

1. `ScannerService._save_event` (in `scanner.py`) gains `explanation: Optional[dict] = None`.
2. `alert_service.save_event` gains `explanation: Optional[dict] = None`, stores to
   `event.explanation` (the JSONB column added by issue #451).
3. `_persist` receives `list[ExplainedSignal]` instead of `list[EnrichedSignal]` and accesses
   `signal.enriched.*` for all existing fields, passing `explanation=signal.explanation`.

### Updated Run Orchestration

```python
enriched, enrich_failed = _enrich(raw_signals, ...)
failed.extend(enrich_failed)

explained, explain_failed = _explain(enriched, db, event_date, ranker_config)
failed.extend(explain_failed)

results = _persist(explained, failed, db, event_date, ranker_config, scanner_run)
```

`ranker_config` is already loaded before `_enrich` and passed to `_persist`. Reusing it in
`_explain` for confidence_inputs avoids a second DB query.

---

## Alternatives Considered

### Alt 1: Inline ExplanationBuilder call in `_persist`

Put the builder call inside `_persist` before `_save_event`.

**Rejected**: `_persist` owns the single `db.commit()` and all writes. Adding read-only
DataReadinessService DB queries inside the write stage erodes the established
read-in-enrich/write-in-persist boundary. Also complicates error isolation — explanation failure
would be tangled with commit failure.

### Alt 2: Build explanation inside `_enrich_one`

Add `explanation: Optional[dict]` to `EnrichedSignal`.

**Rejected**: `_enrich_one` builds the indicator/enrichment inputs that the ExplanationBuilder
will consume. Generating the explanation there couples construction to enrichment, violates
single-responsibility, and makes the `EnrichedSignal` contract do double duty.

### Alt 3: Explanation failure drops the event

If `ExplanationBuilder.build()` raises, add ticker to `failed` instead of persisting
with `explanation=None`.

**Rejected**: The issue explicitly requires "preserving current event summaries, indicators,
criteria_met, metadata, outcomes, and alerts." A transient ExplanationBuilder bug would silently
lose all events for a scan run. The established codebase pattern — `regime` lookup fallback in
`alert_service.save_event()` — confirms optional enrichment must not gate event persistence.

---

## Test Updates

### Existing tests — behavioral assertions must not be weakened

`test_run_pre_market_scan_golden_day` currently patches `ScannerService._save_event` and
asserts the criteria_met, indicators, and ticker arguments. These assertions must be preserved.

**Update**: additionally assert that `_save_event` was called with `explanation=` key present
(may be `None` if ExplanationBuilder is not mocked, or a dict if it is mocked).

### New tests to add

| Test | What it covers |
|---|---|
| `test_explain_failure_falls_back_to_none` | When `ExplanationBuilder.build` raises, `_explain_one` returns `None`; `_save_event` is called with `explanation=None`; event still persists. |
| `test_explain_data_readiness_failure_continues` | When `DataReadinessService.check_for_event` raises, warnings are set to `[]` and ExplanationBuilder is still called. |
| `test_explain_one_golden_day` | With a fully populated `EnrichedSignal`, `ExplanationBuilder.build` is called with the correct criterion IDs and field values per the mapping table. Uses `MagicMock` for the builder to capture call args. |
| `test_explain_produces_explainedSignal_dataclass` | `ExplainedSignal.__dataclass_fields__` contains `enriched` and `explanation`. |

---

## Open Questions (Non-Blocking)

1. **Signal quality score computation in `_explain`**: The ranker score is currently computed in
   `_persist` for the first time. Options: compute it earlier in `_explain` (single source of
   truth for confidence_inputs), or leave it in `_persist` and pass a placeholder in
   confidence_inputs. Recommendation: compute in `_explain`, pass pre-computed score to
   `_persist` via `ExplainedSignal`. Revisit when implementing.

2. **ExplanationBuilder import path**: Assumed `app.services.explanation_builder.ExplanationBuilder`.
   Coordinate with issue #453 author on final module location before merging.

3. **DataReadinessService event-scoped method name**: Assumed
   `DataReadinessService.check_for_event(db, ticker, scanner_type, event_date)`. Coordinate
   with issue #454 author on final signature.

4. **`evidence` metadata fields**: The `evidence` dict passed to `ExplanationBuilder.build`
   needs `generated_at`, `generator_version`, `market_data_asof`, `provider`. The
   `generated_at` is `datetime.now(timezone.utc)`. `market_data_asof` is the timestamp of the
   last pre-market bar consumed (already tracked for the SLO metric). `provider` = "polygon".
   `generator_version` = "explanation_builder.v1". Confirm these fields match #453's spec.

---

## Assumptions

1. Issue #451 (add `explanation` JSONB column to `scanner_events`) lands before or alongside
   this issue. `ScannerEvent.explanation` is a nullable JSONB column.
2. Issue #453 (ExplanationBuilder) lands before this issue; it exposes `ExplanationBuilder.build()`
   accepting the criterion dict structure described in this spec.
3. Issue #454 (enhanced data quality/readiness) lands before this issue; it exposes an
   event-scoped check method returning a list of warning dicts.
4. `_save_event` / `alert_service.save_event` are extended to accept and store `explanation=`
   as part of the #451 + #455 work.
5. The `ExplainedSignal` struct is backward-compatible: all existing `_persist` field accesses
   move from `signal.*` to `signal.enriched.*`.
6. The live scanner (`live_scanner/conditions.py`) is out of scope for this issue — it is
   covered by a later migration ticket in the epic.
