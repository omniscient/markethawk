# Deterministic AI Signal Brief Endpoint Design

**Date:** 2026-06-19
**Issue:** #467
**Parent Epic:** #449 (Explanation-Aware Edge Intelligence)
**Status:** Spec — pending review
**Blocked by:** #464 (deterministic historical analog service), #466 (generate signal archetypes)

---

## Overview

Scanner events need a model-ready payload that packages everything an LLM (or alert engine, or analyst tool) needs to reason about a signal — without generating prose itself. This endpoint assembles `ai_signal_brief.v1`: facts, why bullets, risks, data-quality warnings, historical analogs, outcome context, archetype context, and forbidden claims, all derived deterministically from existing DB rows. No LLM call is involved. The brief is the "safe substrate" for Epic 3 narratives, alert copy, and analyst Q&A.

---

## Requirements

- `GET /api/v1/scanner/events/{event_uuid}/brief` returns an `ai_signal_brief.v1` payload for a scanner event.
- Brief includes: `facts`, `why`, `risks`, `data_quality_warnings`, `historical_analogs`, `outcome_context`, `archetype`, `forbidden_claims`, and a `meta` provenance block.
- Brief is deterministic — same inputs produce the same output; no sampling, no LLM generation.
- Brief is usable without an LLM provider being configured.
- Endpoint degrades gracefully when upstream data is incomplete (no explanation, no outcome, no analogs, no archetype).
- 404 when the `event_uuid` does not match any `ScannerEvent`.
- Tests cover four fixture states: complete, partial (no explanation), warning-heavy, and no-analog.

---

## Architecture

### Route

```
GET /api/v1/scanner/events/{event_uuid}/brief
```

- **Path param**: `event_uuid` (UUID string), matching the existing `POST /api/v1/scanner/events/{event_uuid}/review` pattern (scanner.py:621–637).
- **Router**: `backend/app/routers/scanner.py`, appended to the existing scanner router.
- **Auth**: same `current_user: User = Depends(get_current_user)` guard as sibling endpoints.
- **Rate limit**: use the existing `SCANNER_LIMIT` limiter.

### New Files

| File | Purpose |
|---|---|
| `backend/app/services/signal_brief.py` | `SignalBriefService` — assembles the `ai_signal_brief.v1` dict from DB state |
| `backend/app/schemas/signal_brief.py` | Pydantic response model for `ai_signal_brief.v1` |
| `backend/tests/services/test_signal_brief.py` | Service-layer tests (4 fixture states) |

### Storage / Caching

**No new DB table.** The brief is a pure projection of durable rows already in PostgreSQL (`scanner_events`, `scanner_outcome_summaries`, `signal_clusters`, and the analog service results from #464). A stored brief would denormalize data that has independent update schedules (outcome backfill, archetype clustering) and require multi-source invalidation hooks.

Instead, wrap the assembly in Redis read-through caching:
```python
def build_brief(event_uuid: str, db: Session) -> dict:
    def _fetch():
        event = _lookup_event(event_uuid, db)  # raises 404 if absent
        return SignalBriefService(db).assemble(event)
    return get_cached(f"mh:scanner:brief:{event_uuid}", ttl=120, fn=_fetch)
```

TTL of 120 seconds balances freshness (outcome summaries fill in over hours; a 2-minute window is safe) and avoids redundant assembly on burst calls. Redis is best-effort (volatile) here, consistent with the existing `get_cached` pattern — a cold cache falls through to direct DB computation.

### Service: `SignalBriefService.assemble(event)`

Assembles each section in order. All sections tolerate missing upstream data.

```python
class SignalBriefService:
    def __init__(self, db: Session): ...

    def assemble(self, event: ScannerEvent) -> dict:
        explanation = event.explanation or {}   # JSONB, may be None if Epic 1 not run
        outcome = self._load_outcome(event.id)  # ScannerOutcomeSummary or None
        analogs = self._load_analogs(event)     # from #464 service; list, may be []
        archetype = self._load_archetype(event) # from #466 / SignalCluster; may be None

        return {
            "schema_version": "ai_signal_brief.v1",
            "facts":                self._build_facts(event),
            "why":                  self._build_why(event, explanation),
            "risks":                self._build_risks(event, explanation, outcome),
            "data_quality_warnings": self._build_dq_warnings(event, explanation),
            "historical_analogs":   analogs,
            "outcome_context":      self._build_outcome_context(outcome),
            "archetype":            archetype,
            "forbidden_claims":     self._build_forbidden_claims(event, explanation, outcome, analogs, archetype),
            "meta":                 self._build_meta(event, explanation, outcome, analogs, archetype),
        }
```

#### `facts` — flat dict of scalar values

```json
{
  "ticker": "AAPL",
  "scanner_type": "pre_market_volume",
  "event_date": "2026-06-19",
  "severity": "high",
  "regime": "bull",
  "signal_quality_score": 0.82,
  "previous_close": 180.50,
  "opening_price": 188.00,
  "closing_price": null,
  "relative_volume": 6.3,
  "gap_pct": 4.1
}
```

Core scalar columns first (`ticker`, `scanner_type`, `event_date`, `severity`, `regime`, `signal_quality_score`, price fields), then all keys from `event.indicators` merged in. Do not hardcode a universal indicator list — `pre_market_volume` and `oversold_bounce` carry different indicator keys; just pass through whatever is in `indicators`.

#### `why` — list of bullet strings

1. If `explanation` is present and non-empty: use `explanation["why"]` list directly.
2. Fallback (explanation absent): synthesise from `criteria_met` — for each truthy key in `criteria_met`, emit `"{key.replace('_', ' ').title()} criterion met"`. Simple but accurate.

#### `risks` — list of bullet strings

Compose from three sources, deduplicated:
1. **Failed criteria**: keys in `explanation.get("criteria_failed", {})` → `"{criterion} threshold not met"`.
2. **High-severity data quality warnings**: `DataQualityService` grades A–F; emit a risk bullet for any warning with `severity == "high"` or grade C/D/F, phrased as a consequence (`"Coverage gaps may understate true relative volume"`).
3. **Outcome state**: if `outcome` exists and `is_complete=True` with `follow_through=False`, emit `"Historical follow-through was negative"`. If `outcome is None`, emit `"Outcome not yet available"`.

#### `data_quality_warnings` — raw warning objects

Copy `explanation.get("data_quality_warnings", [])` verbatim. If explanation is absent, return `[]` (do not re-invoke `DataQualityService` at request time — that would introduce latency and non-determinism).

#### `historical_analogs` — list from #464

Call the analog service built in #464. Return its list; may be `[]`. Shape delegated to #464 but must include at minimum: `event_id`, `ticker`, `event_date`, `similarity_score`, `outcome_summary`.

#### `outcome_context` — from `ScannerOutcomeSummary`

```json
{
  "is_complete": true,
  "mfe_pct": 4.2,
  "mae_pct": -1.1,
  "mfe_mae_ratio": 3.8,
  "r_multiple": 2.1,
  "eod_pct_change": 3.5,
  "follow_through": true,
  "gap_filled": false
}
```

Returns `null` when no `ScannerOutcomeSummary` row exists for this event.

#### `archetype` — from #466

Call the archetype lookup from #466. Returns the assigned cluster/archetype object or `null` when not yet assigned. Shape delegated to #466 but must include at minimum: `label`, `sample_size`, `return_profile`, `confidence`.

#### `forbidden_claims` — computed list

Static base (always present, per scanner type):
- `"Do not claim a directional price outcome (up or down)."`
- `"Do not state or imply a price target."`
- `"Do not present this as investment advice."`

Conditionally appended:
- `outcome is None or not is_complete` → `"Do not claim a known outcome; outcome tracking is not yet complete."`
- `len(analogs) == 0` → `"Do not assert historical precedent; no sufficiently similar prior events were found."`
- Any `data_quality_warnings` with high severity → `"Do not present indicator values as exact; data coverage is degraded."`
- `archetype is None` → `"Do not assert an archetype label; no archetype has been assigned to this event."`

#### `meta` — provenance block

```json
{
  "generated_at": "2026-06-19T14:05:00Z",
  "brief_version": "ai_signal_brief.v1",
  "explanation_source": "enriched",
  "analog_count": 3,
  "analog_reason": null,
  "archetype_reason": null,
  "outcome_available": true
}
```

- `explanation_source`: `"enriched"` when `event.explanation` is present; `"derived"` when synthesised from raw `indicators`/`criteria_met`.
- `analog_reason`: `"no_similar_events_found"` | `"service_unavailable"` | `null` (success).
- `archetype_reason`: `"not_yet_assigned"` | `"clustering_not_run"` | `null` (success).

---

## Pydantic Schema (`signal_brief.py`)

```python
class AISignalBriefMeta(BaseModel):
    generated_at: datetime
    brief_version: str
    explanation_source: Literal["enriched", "derived"]
    analog_count: int
    analog_reason: Optional[str] = None
    archetype_reason: Optional[str] = None
    outcome_available: bool

class AISignalBriefResponse(BaseModel):
    schema_version: str
    facts: Dict[str, Any]
    why: List[str]
    risks: List[str]
    data_quality_warnings: List[Dict[str, Any]]
    historical_analogs: List[Dict[str, Any]]
    outcome_context: Optional[Dict[str, Any]] = None
    archetype: Optional[Dict[str, Any]] = None
    forbidden_claims: List[str]
    meta: AISignalBriefMeta

    model_config = ConfigDict(from_attributes=True)
```

---

## Router Handler

```python
@router.get("/events/{event_uuid}/brief", response_model=AISignalBriefResponse)
@limiter.limit(SCANNER_LIMIT)
def get_event_brief(
    request: Request,
    event_uuid: str,
    db: Session = Depends(get_db),
    _current_user: User = Depends(get_current_user),
):
    try:
        parsed_uuid = uuid.UUID(event_uuid)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid event UUID format")

    def _fetch():
        event = db.query(ScannerEvent).filter(
            ScannerEvent.uuid == parsed_uuid
        ).first()
        if not event:
            raise HTTPException(status_code=404, detail="Scanner event not found")
        return SignalBriefService(db).assemble(event)

    return get_cached(f"mh:scanner:brief:{event_uuid}", ttl=120, fn=_fetch)
```

---

## Alternatives Considered

### A. Store the brief as a JSONB column on `scanner_events`

**Rejected.** The brief depends on four upstream sources that update on independent schedules (outcome backfill tasks, archetype clustering, analog recomputation). Invalidation would need hooks in all four, and a stale cached brief is harder to debug than a fresh assembly. The `ai_signal_brief.v1` adds no durable state of its own.

### B. Separate `signal_briefs` table with a FK to `scanner_events`

**Rejected.** Same invalidation problem as A, plus schema overhead and a migration. The brief is a pure read projection, not a new entity.

### C. Integer `event_id` path parameter

**Rejected.** UUID is more stable for external/LLM use cases (the parent epic explicitly anticipates this brief being consumed by external LLM systems). The existing `POST /events/{event_uuid}/review` establishes this pattern. Integer IDs are an internal implementation detail and should not leak into LLM-facing contracts.

---

## Open Questions (non-blocking)

1. **Analog service interface** (#464): the spec assumes the analog service is callable as a synchronous function returning a list of analog dicts. The exact call signature and output shape are delegated to #464.
2. **Archetype lookup interface** (#466): same delegation — assumes a function that accepts a `ScannerEvent` and returns an archetype dict or `None`.
3. **`explanation` column name**: the spec assumes `ScannerEvent.explanation` as the JSONB attribute added by Epic 1. If the column name differs, update the service accordingly.
4. **Cache TTL tuning**: 120 s is a reasonable starting point; revisit based on observed outcome-update frequency once #464/#466 are live.

---

## Assumptions

- `[ASSUMPTION]` The `ScannerEvent.explanation` JSONB column is added by the Epic 1 blocking chain before this issue is implemented. If not yet present, the service falls back to `derived` mode using `indicators`/`criteria_met`.
- `[ASSUMPTION]` The analog service from #464 exposes a synchronous function callable from within a sync FastAPI handler (same pattern as all existing scanner services).
- `[ASSUMPTION]` The archetype lookup from #466 is available as a service function that accepts a `ScannerEvent` and returns the assigned cluster/archetype or `None`.
- `[ASSUMPTION]` `DataQualityService` severity grading (A–F, C+ = caution threshold) is unchanged from current `services/data_quality.py` when this issue is implemented.

---

## Test Coverage

Four test fixture states (`backend/tests/services/test_signal_brief.py`):

| Fixture | Description | Assertions |
|---|---|---|
| `complete` | Event with explanation, outcome, 3 analogs, archetype | All sections populated; `forbidden_claims` minimal; `meta.explanation_source == "enriched"` |
| `partial` | Event with no `explanation` (Epic 1 not run) | `meta.explanation_source == "derived"`; `why` synthesised from `criteria_met`; `data_quality_warnings == []` |
| `warning_heavy` | Event with high-severity DQ warnings, no outcome | Risk bullets include consequence text; `forbidden_claims` includes outcome and DQ clauses |
| `no_analog` | Event where analog service returns `[]` | `historical_analogs == []`; `forbidden_claims` includes no-precedent clause; `meta.analog_reason == "no_similar_events_found"` |

Tests mock the analog service (#464) and archetype lookup (#466) since those services are not yet built.
