# Explanation Trait Performance Aggregation — Design (issue #465)

**Date**: 2026-06-19
**Issue**: [#465](https://github.com/omniscient/markethawk/issues/465) — Add explanation trait performance aggregation
**Parent**: [#449](https://github.com/omniscient/markethawk/issues/449) — Epic: Explanation-Aware Edge Intelligence
**Blocked by**: [#463](https://github.com/omniscient/markethawk/issues/463) — Extract analysis-ready features from scanner explanations

---

## Overview

Scanner explanations (added in Epic 1) record *why* each signal fired: which criteria passed, which failed, what data-quality warnings were present, and which confidence inputs drove the score. This issue adds the backend aggregation layer that answers: **which traits correlate with good or bad outcomes?**

The consumer is Scorecard and EdgeExplorer, which need a ranked view of traits (e.g., "signals with criterion `premarket.relative_volume` passed have 62% win rate vs. 44% for those where it failed").

---

## Requirements

1. A `GET /scanner/trait-performance` endpoint returns aggregated outcome metrics grouped by explanation trait.
2. Each trait row includes: `trait_type`, `trait_id`, `label`, `sample_size`, `win_rate_pct`, `follow_through_rate_pct`, `avg_mfe_pct`, `avg_mae_pct`, `sample_warning`.
3. `sample_warning` follows the same three-tier vocabulary as `get_scorecard()`: `"trusted"` (≥30), `"warning"` (10–29), `"blocked"` (<10).
4. Filters: `scanner_type` (optional), `date_from` (optional), `date_to` (optional), `trait_type` (optional — filters to one type).
5. All four trait types are covered:
   - `criteria_passed` — from `explanation.criteria_passed.{criterion_id}`
   - `criteria_failed` — from `explanation.criteria_failed.{criterion_id}`
   - `warning` — from `explanation.data_quality_warnings[].code`
   - `confidence_input` — from `explanation.confidence_inputs.{positive|negative|missing}.{input_id}`, with polarity (`positive`/`negative`/`missing`) embedded in `trait_id`
6. Only events with a complete `ScannerOutcomeSummary` (`is_complete = true`) contribute to outcome metrics. Events without outcomes are counted in `sample_size` but excluded from rate/avg fields.
7. Tests must cover all four trait types: passed criteria, failed criteria, warning traits, and confidence input traits (with polarity variants).

---

## Architecture / Approach

### Dependency on #463

Issue #463 extracts analysis-ready feature rows from `ScannerEvent.explanation`. The trait performance service consumes these rows (or performs equivalent logic inline) to avoid parsing raw JSONB repeatedly.

**Assumption**: #463 produces a queryable representation — either a materialized table (e.g. `explanation_features`) or a shared Python helper function that expands explanation JSONB into `(event_id, trait_type, trait_id, trait_value, passed)` tuples. The spec is written against both; the implementation should defer to whatever #463 ships.

### Service Method

Add `get_trait_performance()` as a static method on the existing `StatsService` in `backend/app/services/stats.py`, following the same pattern as `get_scorecard()` and `get_edge_stats()`:

```python
@staticmethod
def get_trait_performance(
    db: Session,
    scanner_type: Optional[str] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    trait_type: Optional[str] = None,  # criteria_passed | criteria_failed | warning | confidence_input
) -> list[dict]:
    ...
```

The method:
1. Queries `ScannerEvent` (filtered by `scanner_type`, date range) joined to `ScannerOutcomeSummary` on `is_complete = true`.
2. Expands each event's `explanation` into per-trait rows via the #463 extraction helper.
3. Groups by `(trait_type, trait_id)`, computing `COUNT(*)`, `AVG(mfe_pct)`, `AVG(mae_pct)`, win rate (`eod_pct_change > 0`), and follow-through rate (`follow_through = true`).
4. Applies `sample_warning` tier to each group using a shared helper (factored from the existing gate-status logic — not duplicated magic numbers):

```python
def _sample_warning(n: int) -> str:
    if n >= 30:
        return "trusted"
    if n >= 10:
        return "warning"
    return "blocked"
```

5. Returns a list of trait dicts sorted by `sample_size` descending (most evidence first).

### API Endpoint

Add to `backend/app/routers/scanner.py`:

```
GET /api/scanner/trait-performance
```

Query parameters:
| Param | Type | Required | Description |
|---|---|---|---|
| `scanner_type` | string | No | Filter to one scanner type |
| `date_from` | date | No | Inclusive start date |
| `date_to` | date | No | Inclusive end date |
| `trait_type` | string | No | One of `criteria_passed`, `criteria_failed`, `warning`, `confidence_input` |

Response (200):
```json
{
  "traits": [
    {
      "trait_type": "criteria_passed",
      "trait_id": "premarket.relative_volume",
      "label": "Relative volume",
      "sample_size": 47,
      "complete_count": 41,
      "win_rate_pct": 61.0,
      "follow_through_rate_pct": 53.7,
      "avg_mfe_pct": 3.21,
      "avg_mae_pct": -1.05,
      "sample_warning": "trusted"
    },
    {
      "trait_type": "confidence_input",
      "trait_id": "positive:relative_volume",
      "label": "relative_volume (positive)",
      "sample_size": 12,
      "complete_count": 9,
      "win_rate_pct": 55.6,
      "follow_through_rate_pct": 44.4,
      "avg_mfe_pct": 2.10,
      "avg_mae_pct": -1.50,
      "sample_warning": "warning"
    }
  ],
  "filters_applied": {
    "scanner_type": "pre_market_volume_spike",
    "date_from": "2026-01-01",
    "date_to": "2026-06-19",
    "trait_type": null
  }
}
```

### Trait ID Conventions

- `criteria_passed` / `criteria_failed`: `trait_id = criterion_id` (e.g., `"premarket.relative_volume"`), `label` from `explanation.criteria_passed.{id}.label`.
- `warning`: `trait_id = warning_code` (e.g., `"missing_intraday_bars"`), `label` from `explanation.data_quality_warnings[].message` (first occurrence).
- `confidence_input`: `trait_id = "{polarity}:{input_id}"` (e.g., `"positive:relative_volume"`, `"missing:vwap"`), `label = "{input_id} ({polarity})"`. Polarity distinguishes signals where an input was a positive driver vs. missing entirely — they have different outcome implications.

### Schema

Add Pydantic schemas in `backend/app/schemas/`:

```python
class TraitPerformanceRow(BaseModel):
    trait_type: str
    trait_id: str
    label: str
    sample_size: int
    complete_count: int
    win_rate_pct: Optional[float]
    follow_through_rate_pct: Optional[float]
    avg_mfe_pct: Optional[float]
    avg_mae_pct: Optional[float]
    sample_warning: str  # trusted | warning | blocked

class TraitPerformanceResponse(BaseModel):
    traits: list[TraitPerformanceRow]
    filters_applied: dict
```

`win_rate_pct`, `follow_through_rate_pct`, `avg_mfe_pct`, `avg_mae_pct` are `None` when `complete_count == 0`.

---

## Alternatives Considered

### Alternative 1: Pre-computed Celery Task / Materialized View

Write aggregations nightly to a `trait_performance_cache` table (or a PostgreSQL materialized view).

**Rejected**: No pre-computation or caching infrastructure exists anywhere in the analytics path. `get_scorecard()`, `get_edge_stats()`, and `get_edge_decay()` all use query-time aggregation. The added operational complexity (new model, migration, Celery schedule, matview lifecycle) is not justified for a first implementation. Trait performance queries are bounded by the same `scanner_events` table that existing scorecard queries already handle at query time.

### Alternative 2: Separate Per-Trait-Type Endpoints

Separate routes: `GET /scanner/trait-performance/criteria`, `GET /scanner/trait-performance/warnings`, `GET /scanner/trait-performance/confidence`.

**Rejected**: EdgeExplorer needs to build a single ranked view across all trait types. Multiple calls with no guaranteed ordering creates client-side merge complexity. A unified endpoint with optional `trait_type` filter serves both the "give me everything" and "give me one type" use cases without route duplication.

### Alternative 3: Fold Into Scorecard Response

Add a `traits` array to the existing `GET /scanner/scorecard` response.

**Rejected**: Scorecard requires `scanner_type` (singular, required) and returns one scanner's headline metrics. Trait performance is multi-scanner (no required filter) and has a different response cardinality. Coupling them breaks the scorecard's clean semantics and bloats its payload.

### Alternative 4: Wilson Score Confidence Intervals

Return `win_rate_ci_low` / `win_rate_ci_high` (binomial 95% CI) instead of a tier warning.

**Rejected**: The acceptance criteria says "confidence bounds **or** warnings for small samples" — the disjunction permits warnings alone. The existing trusted/warning/blocked vocabulary is already understood by Scorecard consumers. No statistical library exists in the backend today. Tier labels communicate "don't over-read this" more legibly for traders than wide CI bounds. Can be layered on additively later as new fields without breaking changes.

---

## Open Questions (non-blocking)

1. **Pagination**: If there are many distinct traits (e.g., 50+ unique criterion IDs across all scanner types), the response may be long. For V1, return all traits sorted by `sample_size` descending. Pagination can be added if profiling shows response size is a problem.

2. **`complete_count` threshold for rate computation**: Should `win_rate_pct` be suppressed when `complete_count < 5` (even if `sample_warning = "warning"`)? For V1, return `None` only when `complete_count == 0`; the `sample_warning` field handles low-confidence communication.

3. **#463 extraction shape**: If #463 ships a materialized `explanation_features` table (rather than a Python helper), `get_trait_performance()` should query that table directly via a JOIN rather than parsing JSONB in Python. This is an implementation detail to be resolved when #463 is complete.

---

## Assumptions

- **[A1]** Issue #463 will be implemented before this issue is picked up. The trait extraction logic (expanding `explanation` JSONB into per-trait tuples) lives in or is imported from #463's output. This issue does not re-implement that extraction.
- **[A2]** `ScannerEvent.explanation` is populated by the time trait performance is queried. Events without an `explanation` field produce zero trait rows for that event (not an error).
- **[A3]** The `_sample_warning()` helper is factored into a shared utility in `stats.py` rather than duplicated. The thresholds (30/10) are defined once.
- **[A4]** The endpoint is authenticated (behind `AuthMiddleware`) — no public access needed.
- **[A5]** Only events with `ScannerOutcomeSummary.is_complete = true` contribute to outcome metrics (win rate, MFE, MAE, follow-through). Incomplete outcomes are not partial-counted.
