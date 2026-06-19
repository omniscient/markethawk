# Deterministic Historical Analog Service — Design

**Date:** 2026-06-19
**Status:** Spec generated — pending review
**Issue:** #464
**Parent epic:** #449 (Explanation-Aware Edge Intelligence)
**Blocked by:** #463 (Extract analysis-ready features from scanner explanations)

## Overview

Scanner events today show *what* fired and *why*, but no comparative context. When a trader looks at a pre-market volume spike, the natural question is: "Have I seen something like this before, and how did it play out?" This feature adds a deterministic historical analog service that answers that question from the existing `ScannerEvent` + `ScannerOutcomeSummary` data, without embeddings or an LLM.

The service finds prior scanner events that closely resemble a target event across scanner type, explanation criterion overlap, normalized indicator values, market regime, and data-quality cleanliness. It aggregates their outcomes (median MFE, follow-through rate, etc.) and returns them alongside the individual analog list, sample size, and confidence warnings. The output feeds the event-level UI sub-issue (#9) and the AI signal brief payload (#5).

## Requirements

1. **Service method** — `HistoricalAnalogService.find_analogs(db, event_id, limit=None)` in `backend/app/services/historical_analog_service.py` returns the full analog result object. Both the REST endpoint and the AI signal brief sub-issue (#5) call this in-process; no HTTP round-trip for internal callers.

2. **REST endpoint** — `GET /api/v1/scanner/events/{event_id}/analogs` on the scanner router (`backend/app/routers/scanner.py`) with an optional `limit` query param (capped at `historical_analog_top_n`). Returns the same object the service method computes. Event not found → 404 via `get_or_404`.

3. **Two-phase algorithm:**
   - *Phase 1 — hard pre-filter*: candidates must share the target's `scanner_type` AND have a completed `ScannerOutcomeSummary` (`is_complete == True`). Exclude the target event itself.
   - *Phase 2 — weighted sum score*: four components, each normalized to [0, 1], combined as a re-normalized weighted sum (same pattern as `signal_ranker.py`). Score must be in [0.0, 1.0].

4. **Similarity components (Phase 2):**

   | Component | How computed | Default weight |
   |---|---|---|
   | `criterion_overlap` | Jaccard similarity on the set of passing criterion IDs from `explanation.criteria_passed` (keys) | 0.40 |
   | `value_distance` | `1 − normalized_L1_distance` across *shared* numeric criterion values (criteria present in both `target.explanation.criteria_passed` AND `candidate.explanation.criteria_passed`); normalize each value via per-criterion caps analogous to `_NORM_CAPS` in `signal_ranker.py`; if no criteria are shared, component is excluded from the weight denominator | 0.30 |
   | `regime_match` | Binary 1.0 if `regime` matches exactly, 0.0 if either is NULL or they differ | 0.20 |
   | `warning_cleanliness` | `1 − min(n_warnings / WARNING_CAP, 1.0)` where `n_warnings` = len of `explanation.data_quality_warnings`; `WARNING_CAP` = 5 | 0.10 |

   Re-normalization: if a component cannot be computed for a candidate (e.g., no explanation on file), exclude its weight from the denominator — same logic as `compute_signal_quality_score` in `signal_ranker.py`.

5. **Config in SystemConfig** — four keys loaded via `_ANALOG_KEYS` (pattern from `_RANKER_KEYS`):
   - `historical_analog_weights` (JSON, default `{"criterion_overlap": 0.40, "value_distance": 0.30, "regime_match": 0.20, "warning_cleanliness": 0.10}`)
   - `historical_analog_version` (string, default `"analog.v1"`)
   - `historical_analog_top_n` (int string, default `"10"`)
   - `historical_analog_min_sample` (int string, default `"5"`)

6. **Response structure:**
   ```python
   {
     "analogs": [                  # top-N candidates, ranked by score desc
       {
         "event_id": int,
         "ticker": str,
         "event_date": date,
         "scanner_type": str,
         "regime": str | None,
         "score": float,           # final weighted similarity [0, 1]
         "component_scores": {
           "criterion_overlap": float,
           "value_distance": float,
           "regime_match": float,
           "warning_cleanliness": float
         },
         # outcome fields from ScannerOutcomeSummary
         "mfe_pct": Decimal | None,
         "mae_pct": Decimal | None,
         "eod_pct_change": Decimal | None,
         "follow_through": bool | None,
         "r_multiple": Decimal | None
       }
     ],
     "outcome_summary": {          # aggregate over returned analogs; null when analogs=[]
       "sample_size": int,
       "median_mfe_pct": float | None,
       "median_mae_pct": float | None,
       "median_eod_pct_change": float | None,
       "follow_through_rate": float | None,  # fraction in [0,1]
       "excluded_incomplete_count": int       # candidates dropped for is_complete=False
     } | None,
     "weights": dict,              # active weight dict echoed for auditability
     "config_version": str,
     "warnings": [str]            # empty list when none
   }
   ```

7. **Warnings:**
   - Low sample: when `len(analogs) < historical_analog_min_sample` — emit `"Only {N} completed analog(s) available; fewer than the minimum {K} for reliable confidence."`
   - Excluded incomplete: when `excluded_incomplete_count > 3 × len(analogs)` — emit `"{M} prior {scanner_type} events excluded for incomplete outcomes."`
   - No-analog: when phase-1 yields zero survivors — emit `"No completed historical analogs found for scanner_type '{scanner_type}'."` and return `analogs: []`, `outcome_summary: null`.

8. **Test coverage** (in `backend/tests/services/test_historical_analog_service.py`):
   - Ranking order: higher criterion overlap and closer values rank first.
   - Pre-filter: candidates with `is_complete=False` are excluded from results and counted in `excluded_incomplete_count`.
   - Low-sample warning fires when fewer than `min_sample` analogs survive.
   - No-analog state: zero survivors returns 200 with correct warnings and null summary.
   - Component re-normalization: candidate missing an explanation still scores on available components without penalizing absence.
   - Event not found: 404 from the endpoint.

## Architecture / Approach

```
backend/app/services/historical_analog_service.py   ← new; HistoricalAnalogService
backend/app/routers/scanner.py                       ← add GET /events/{event_id}/analogs
backend/app/schemas/analog.py                        ← new; AnalogItem, AnalogOutcomeSummary,
                                                         AnalogResponse Pydantic models
backend/tests/services/test_historical_analog_service.py  ← new
```

**Service internal flow:**

```
find_analogs(db, event_id, limit):
  1. get_or_404(db, ScannerEvent, event_id)
  2. load_analog_config(db) → weights, top_n, min_sample, version
  3. phase1_candidates = (
       db.query(ScannerEvent, ScannerOutcomeSummary)
         .join(ScannerOutcomeSummary, ...)
         .filter(scanner_type==target.scanner_type, is_complete==True, id!=event_id)
         .all()
     )
  4. excluded_incomplete_count = (
       db.query(ScannerEvent)
         .outerjoin(ScannerOutcomeSummary, ...)
         .filter(scanner_type==target.scanner_type, id!=event_id,
                 or_(is_complete==False, ScannerOutcomeSummary.id==None))
         .count()
     )
  5. For each candidate: compute component scores → final score
  6. Sort descending, take top min(limit or top_n, top_n)
  7. Build outcome_summary from returned analogs
  8. Build warnings list
  9. Return AnalogResult
```

**Score computation pattern** (mirrors `compute_signal_quality_score`):

```python
def _score_candidate(target, candidate, weights):
    components = {}
    for component, fn in _COMPONENT_FNS.items():
        val = fn(target, candidate)
        if val is not None:
            components[component] = val
    total_weight = sum(weights[c] for c in components)
    if total_weight == 0:
        return 0.0, components
    raw = sum(weights[c] * v for c, v in components.items())
    return round(raw / total_weight, 3), components
```

`_COMPONENT_FNS` is a module-level dict mapping component name → callable(target, candidate) → float | None.

**Router endpoint** (thin wrapper, same pattern as `outcomes.py:get_event_outcome`):

```python
@router.get("/events/{event_id}/analogs", response_model=AnalogResponse)
def get_event_analogs(
    event_id: int,
    limit: Optional[int] = Query(None, ge=1),
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    return HistoricalAnalogService.find_analogs(db, event_id, limit=limit)
```

## Alternatives Considered

**Option A — Multi-phase filter-then-rank without outcome pre-filter:**
Rank all same-type events, then join outcomes for the returned top-N. Rejected because analogs without completed outcomes cannot populate the outcome_summary the acceptance criteria require, and including them would mislead the aggregate stats.

**Option B — Cosine similarity over a concatenated feature vector:**
One-hot encode scanner_type, booleanize criterion flags, append normalized values into a flat vector, compute cosine. Rejected because (1) it mixes cross-type events if scanner_type is just one dimension, and criterion value scales differ meaningfully between scanner types; (2) the resulting scalar is opaque and does not satisfy the "explainable" requirement — per-component scores cannot be derived from a single cosine value.

**Embeddings-based similarity:**
Explicitly excluded by the issue and the parent epic design, which reserves embeddings for free-text/news/catalyst similarity in Epic 3.

## Assumptions

- `assumption` The `explanation` JSONB column (from Epic 1 sub-issues) exists on `ScannerEvent` before this service is implemented. Events without a populated `explanation` are scored on whichever components are available (`regime`, `signal_quality_score`) via re-normalization; missing `criteria_passed` means `criterion_overlap` and `value_distance` contribute nothing and are excluded from the weight denominator.
- `assumption` The feature extraction path from #463 (analysis-ready feature rows) is a dependency for testing purposes but is *not* a runtime dependency of `HistoricalAnalogService`. The service reads `explanation` directly from `ScannerEvent.explanation`, matching the format produced by Epic 1 scanners. #463's extraction path serves trait-performance and archetype analysis (sub-issues #3 and #4) separately.
- `assumption` Sector/market context (mentioned in the parent epic's candidate input list) is deferred. The `metadata_` JSONB may contain sector/catalyst recency but the format is scanner-type-specific and not yet normalized. Add a `sector_match` component (binary, like `regime_match`) in a follow-up once `metadata_` is standardized by Epic 1 migrations.
- `assumption` Per-criterion value normalization caps (`value_distance` component) are defined as a module-level dict in `historical_analog_service.py`, analogous to `_NORM_CAPS` in `signal_ranker.py`. Caps can be refined per scanner type in a follow-up without changing the algorithm shape.

## Open Questions (non-blocking)

- Should the endpoint support a `min_score` query param to filter out low-similarity analogs? Current spec defaults `min_score=0.0` (no floor). A score floor could be surfaced in a follow-up without schema changes.
- When criterion value scales differ significantly across scanner types that share the same `scanner_type` string over time (after parameter tuning), should `value_distance` be computed against a per-scanner-version expected range rather than absolute `_NORM_CAPS`? Deferred — flag for Epic 2 trait performance work.
