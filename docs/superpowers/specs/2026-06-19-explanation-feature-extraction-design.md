# Explanation Feature Extraction Design

**Date:** 2026-06-19
**Status:** Spec — pending review
**Issue:** #463 — Extract analysis-ready features from scanner explanations
**Parent:** #449 — Epic: Explanation-Aware Edge Intelligence
**Blocked by:** #459, #460, #461, #462 (Epic 1 scanner migrations)

---

## Overview

Scanner events now carry (or will carry, after Epic 1) a structured `explanation` JSONB column with a stable `scanner_explanation.v1` schema. That schema captures why a signal fired: which criteria passed and failed, observed values with thresholds and units, per-criterion importance weights, confidence inputs, and data-quality warnings.

Epic 2 begins here: before trait performance, historical analogs, or signal archetypes can be built, the explanation data must be flattened into a numeric/categorical feature row that the existing statistical discovery pipeline can consume. The existing `analyze_signal_features` Celery task already builds a feature matrix from the raw `indicators` JSONB — this work replaces that ad-hoc flattening with a principled, explanation-aware extraction path.

---

## Requirements

1. **Explained events → feature rows.** Each `ScannerEvent` with a populated `explanation` JSONB can be transformed into a flat feature row suitable for ML analysis (correlations, SHAP, K-means).

2. **Reconstructed explanations for legacy events.** When `explanation` is NULL, synthesize an approximate `scanner_explanation.v1` object from the existing `indicators` + `criteria_met` + `signal_quality_score` columns. Process it through the same extraction pipeline as native explanations. Mark the resulting row `is_reconstructed = 1`.

3. **Missing explanation handling.** When `explanation` is NULL *and* reconstruction inputs (`indicators`, `criteria_met`) are also absent, skip the event and log a warning — do not silently emit a zero-filled row.

4. **Warning-bearing explanations.** When an explanation carries `data_quality_warnings`, emit `has_warnings = 1` and `warning_count = N` in the feature row. Encode the highest warning severity as an ordinal int (`warning_max_severity`: 0=none, 1=low, 2=medium, 3=high).

5. **Outcome join key.** Every feature row must include `event_id` so the row can be joined to `ScannerOutcomeSummary` and `ScannerOutcomeSnapshot` downstream. The extraction function does not accept or output snapshot data — joining happens in `analyze_signal_features`.

6. **Criterion-level columns.** Per criterion present in `criteria_passed` or `criteria_failed`:
   - `crit_<criterion_id>_observed` (float) — the observed value
   - `crit_<criterion_id>_met` (0/1 int) — 1 if in `criteria_passed`, 0 if in `criteria_failed`
   - `crit_<criterion_id>_importance` (float) — from `importance` field; null when absent

7. **Confidence inputs.** `confidence_score` (float) from `confidence_inputs.score`, `confidence_positive_count` (int), `confidence_negative_count` (int), `confidence_missing_count` (int).

8. **Identity columns.** `event_id` (int), `scanner_type` (string — preserved for task-level splitting; dropped as non-numeric by `build_feature_matrix`), `is_reconstructed` (0/1 int).

9. **Existing indicator columns.** Flatten `indicators` JSONB keys unchanged, as before. Numeric values pass through; non-numeric are dropped by the downstream `build_feature_matrix` cleaner. This preserves backward compatibility with analysis runs that predate Epic 2.

10. **All boolean/flag values as 0/1 ints** — not Python `bool` — so they survive `pd.to_numeric` coercion in `build_feature_matrix`.

11. **Tests cover ≥ 2 scanner types and the reconstructed path.** Concrete cases: `pre_market_volume_spike` and `oversold_bounce`, plus a legacy event with `explanation = NULL`.

---

## Architecture

### New module: `backend/app/services/explanation_features.py`

Business logic lives in `app/services/`. The extraction is non-trivial domain computation (explanation parsing, reconstruction, per-criterion column emission) — it belongs in a service, not inline in a Celery task.

**Public API:**

```python
def extract_features(events: list[ScannerEvent]) -> pd.DataFrame:
    """Flatten scanner explanations into an analysis-ready feature DataFrame.

    Returns one row per event. Reserved columns: event_id, scanner_type,
    is_reconstructed. Criterion columns: crit_<id>_observed/met/importance.
    Indicator columns from existing indicators JSONB.
    Callers should join on event_id to add outcome columns before calling
    build_feature_matrix().
    """
```

**Internal helpers (private):**

```python
def _reconstruct_explanation(event: ScannerEvent) -> dict | None:
    """Synthesize a scanner_explanation.v1-shaped dict from legacy fields.

    Returns None if reconstruction inputs are absent (both indicators and
    criteria_met are empty). Sets evidence.reconstructed = True.
    """

def _flatten_explanation(event_id: int, scanner_type: str,
                         explanation: dict, is_reconstructed: bool) -> dict:
    """Flatten one explanation object into a flat feature dict."""
```

### Reconstruction path

For `explanation = NULL` events, `_reconstruct_explanation` builds:

```python
{
    "schema_version": "scanner_explanation.v1",
    "criteria_passed": {
        k: {"observed": v, "met": True, "importance": None}
        for k, v in (event.criteria_met or {}).items() if v is True
    },
    "criteria_failed": {
        k: {"observed": None, "met": False, "importance": None}
        for k, v in (event.criteria_met or {}).items() if v is False
    },
    "confidence_inputs": {
        "score": float(event.signal_quality_score) if event.signal_quality_score else None,
        "positive": {},
        "negative": {},
        "missing": {},
    },
    "data_quality_warnings": [],
    "evidence": {
        "reconstructed": True,
        "reconstruction_quality": "indicators_only",
    },
}
```

Observed values for reconstructed criteria are sourced from `event.indicators` where key matches criterion name; otherwise NULL. Criterion IDs in `criteria_met` may differ from v1 canonical IDs — this is handled on a per-scanner-type basis by a small mapping table inside `_reconstruct_explanation`.

### Integration with `analyze_signal_features`

The existing inline flattening loop in `tasks/quality.py` (~lines 248–261) is replaced with:

```python
from app.services.explanation_features import extract_features

raw_df = extract_features(events)  # replaces the inline for loop
# existing outcome join (query snapshots, merge on event_id) runs here
# then:
clean_df = build_feature_matrix(raw_df)
```

`build_feature_matrix` is unchanged — it continues to drop sparse columns (>50% NULL) and coerce to float. Cross-scanner sparsity (e.g., `crit_rsi_2_oversold_*` columns are NULL for pre-market events) is handled correctly by the existing >50% NULL drop, especially since `analyze_signal_features` is already typically scoped to a single `scanner_type`.

---

## Approach Comparison

### Approach A — New `explanation_features.py` service (recommended)

One `extract_features()` function, one reconstruction path, one column schema. Native and reconstructed explanations go through the same flattening logic, distinguished only by `is_reconstructed`. Clear module boundary matches `app/services/` convention. Dedicated test file (`tests/services/test_explanation_features.py`) keeps test scope focused.

**Trade-off:** New file. Slightly more import surface.

### Approach B — Inline in `quality.py`

No new file. But domain logic (explanation parsing, reconstruction) sits inside a Celery task module, violating the CLAUDE.md rule that tasks orchestrate and dispatch but don't own logic. Testing is harder — tests must import and run within the task machinery.

**Rejected:** Architecture violation; harder to test in isolation.

### Approach C — Persist features to a new `signal_features` table

Feature rows are written to PostgreSQL per event. Allows ad-hoc querying and replay without re-extraction.

**Rejected:** No stated consumer beyond `analyze_signal_features`. Analysis outputs (`SignalAnalysisRun`, `SignalCluster`) already persist the results. Adds a migration, storage overhead, and an upsert pattern for no current gain. Revisit if a feature-store UI or replay-from-frozen-features requirement emerges.

---

## Open Questions

1. **Criterion ID mapping for reconstruction.** Legacy `criteria_met` keys (e.g., `"volume_spike"`, `"rsi_2_crossed"`) may differ slightly from the canonical v1 criterion IDs defined by each scanner migration (issues #459–462). The mapping can be inlined in `_reconstruct_explanation` — but the final canonical IDs are determined by those issues, which are not yet merged. The mapping should be defined after #459–462 land and treated as a thin config dict inside the reconstruction helper.

2. **`importance` for reconstructed criteria.** When synthesizing from `criteria_met`, we have no per-criterion importance (that comes from the native explanation builder). The `crit_<id>_importance` column will be NULL for all reconstructed rows. `build_feature_matrix` will drop it when the reconstructed fraction of the run exceeds 50%. This is acceptable — the importance signal emerges from natively explained events.

---

## Assumptions

- **[Assumption]** The `scanner_explanation.v1` schema is stable by the time this issue is implemented. If any field names change in #459–462, `_flatten_explanation` must be updated to match.

- **[Assumption]** `analyze_signal_features` is the only consumer of `extract_features()` at this stage. Future consumers (analog service, trait performance) will call it directly and join their own outcome data.

- **[Assumption]** `criteria_met` booleans on legacy events map one-to-one to criterion IDs with a thin name-mapping dict. If the mapping is many-to-many or requires runtime DB lookups, reconstruction complexity increases — flag this during implementation.

- **[Assumption]** Warning severity is a closed set: `low`, `medium`, `high`. If a new severity is added to the v1 schema, the ordinal encoding (`warning_max_severity`) must be updated.
