# Data Quality Gate Preflight API — Design

**Date:** 2026-06-19  
**Issue:** #493  
**Parent:** #491 (Epic: Data Quality Trust Gate)  
**Blocked by:** #492 (Gate contract and service)  
**Status:** Spec

---

## Overview

Product surfaces (scanner UI, backtest harness, auto-trading paths) need a way to request a trust assessment before executing workflows, without each consumer re-implementing quality policy logic. Issue #492 adds the `QualityGateService` and `QualityGateAssessment` contract; this issue exposes that service through a single HTTP endpoint so any caller — frontend, Celery task, or external tooling — can invoke it over the API.

## Requirements

Derived from issue acceptance criteria and Q&A brainstorming:

1. `POST /api/v1/data-quality/gate` endpoint exists and is reachable under standard JWT auth.
2. Request body accepts:
   - `universe_id: int` (required) — the universe whose quality report to evaluate.
   - `policy: Literal["strict", "advisory", "off"]` (required) — gate strictness. Invalid values return HTTP 422.
   - `consumer: Literal["scanner", "auto_trading", "backtesting", "scorecard", "ui"]` (required) — identifies which product surface is requesting. Invalid values return HTTP 422.
   - `scanner_type: Optional[str]` — scope the assessment to a specific scanner.
   - `ticker: Optional[str]` — further scope to a single ticker within the universe.
   - `start_date: Optional[date]` / `end_date: Optional[date]` — date range for the assessment window.
   - `requirements: Optional[DataRequirements]` — explicit data requirements the consumer needs covered. Invalid structure returns HTTP 422.
     - `timespans: Optional[List[TimespanRequirement]]` — list of bar resolutions required.
       - `timespan: Literal["minute", "hour", "day", "week", "month"]` (required per entry).
       - `multiplier: int = 1` (optional, defaults to 1).
3. Response body is a `QualityGateAssessment` (shape defined in #492): `schema_version`, `policy`, `verdict`, `trusted`, `scope`, `score`, `grade`, `issues`, `warnings`, `generated_at`.
4. The router is **thin** — it validates input, calls `QualityGateService.assess()` from #492, and returns the result. No policy logic lives in the router.
5. API tests cover all four verdict paths: `trusted`, `warning`, `blocked`, `skipped`.
6. Non-existent `universe_id` returns HTTP 404.
7. Endpoint is rate-limited at `SCANNER_LIMIT` (5/min per user), matching the existing `analyze-quality` sibling.
8. No Redis caching in v1 (see §Alternatives).

## Architecture

```
POST /api/v1/data-quality/gate
  └─ backend/app/routers/data_quality.py   ← new router, prefix /api/v1/data-quality
       ├─ validate request (Pydantic, 422 on bad enum/structure)
       ├─ GET stock_universes WHERE id = universe_id → 404 if missing
       └─ QualityGateService.assess(db, request_params)   ← from #492
            ├─ read UniverseQualityReport for universe_id
            ├─ apply policy (strict / advisory / off)
            ├─ evaluate seven issue codes against report_data
            └─ return QualityGateAssessment
```

### New files

| File | Purpose |
|------|---------|
| `backend/app/routers/data_quality.py` | New router, registers `POST /gate` |
| `backend/app/schemas/data_quality.py` | `GateRequest`, `TimespanRequirement`, `DataRequirements` Pydantic schemas; imports `QualityGateAssessment` from `#492`'s schema file |
| `backend/tests/api/test_data_quality.py` | Router integration tests (transaction-rollback fixture) |

### Changes to existing files

| File | Change |
|------|--------|
| `backend/app/main.py` | Import and register `data_quality_router` via `app.include_router(...)` |
| `backend/app/routers/__init__.py` | Add `data_quality` to imports if the package exports routers there |

### `requirements.timespans` format

The format reuses the existing `ScannerConfig.data_requirements["timespans"]` contract already consumed by `DataReadinessService`:

```json
{
  "requirements": {
    "timespans": [
      {"timespan": "minute", "multiplier": 1},
      {"timespan": "day", "multiplier": 1}
    ]
  }
}
```

Each entry maps to the `(timespan, multiplier)` pair that identifies bar resolutions in `StockAggregate` and `FuturesAggregate`. When `requirements` is omitted, the gate evaluates the universe's overall quality without timespan-scoping.

### Pydantic schemas (`schemas/data_quality.py`)

```python
from typing import List, Literal, Optional
from datetime import date
from pydantic import BaseModel, ConfigDict

class TimespanRequirement(BaseModel):
    model_config = ConfigDict(extra="forbid")
    timespan: Literal["minute", "hour", "day", "week", "month"]
    multiplier: int = 1

class DataRequirements(BaseModel):
    model_config = ConfigDict(extra="forbid")
    timespans: Optional[List[TimespanRequirement]] = None

class GateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    universe_id: int
    policy: Literal["strict", "advisory", "off"]
    consumer: Literal["scanner", "auto_trading", "backtesting", "scorecard", "ui"]
    scanner_type: Optional[str] = None
    ticker: Optional[str] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    requirements: Optional[DataRequirements] = None
```

`QualityGateAssessment` is defined in #492 and imported — not redefined here.

### Router (`routers/data_quality.py`)

```python
from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.rate_limits import SCANNER_LIMIT, limiter
from app.schemas.data_quality import GateRequest
from app.services.quality_gate import QualityGateService  # from #492
from app.utils.db import get_or_404
from app.models.stock_universe import StockUniverse

router = APIRouter(prefix="/api/v1/data-quality", tags=["data-quality"])

@router.post("/gate")
@limiter.limit(SCANNER_LIMIT)
def preflight_gate(
    http_request: Request,
    body: GateRequest,
    db: Session = Depends(get_db),
):
    """Return a trust assessment for a universe before running a workflow."""
    get_or_404(db, StockUniverse, body.universe_id, "Universe")
    return QualityGateService.assess(db, body)
```

## Test coverage (`tests/api/test_data_quality.py`)

Tests use the transaction-rollback `db` fixture from `conftest.py` (real PostgreSQL schema, no mocks).

| Test | Setup | Expected |
|------|-------|----------|
| `test_gate_trusted` | Universe with grade A `UniverseQualityReport`, `policy=strict` | `verdict=trusted`, `trusted=True` |
| `test_gate_warning` | Universe with grade C report (significant gaps), `policy=advisory` | `verdict=warning`, `trusted=False` |
| `test_gate_blocked` | Universe with no `UniverseQualityReport` row, `policy=strict` | `verdict=blocked`, `trusted=False` |
| `test_gate_skipped` | Any universe, `policy=off` | `verdict=skipped`, `trusted=True` |
| `test_gate_invalid_policy` | `policy="invalid"` | HTTP 422 |
| `test_gate_invalid_consumer` | `consumer="unknown"` | HTTP 422 |
| `test_gate_invalid_timespan` | `requirements.timespans=[{"timespan":"tick"}]` | HTTP 422 |
| `test_gate_universe_not_found` | `universe_id=999999` | HTTP 404 |

## Alternatives considered

### 1. Extend `universe.py` under `/api/v1/universe/quality-gate`
Rejected. The acceptance criterion specifies `/api/v1/data-quality/gate` explicitly. More importantly, the gate is cross-cutting: its `consumer` field already includes `backtesting`, `auto_trading`, and `scorecard` — none of which are universe-CRUD concerns. Adding it to `universe.py` creates a conceptual mismatch and makes it harder to route later epic tickets (#491 sub-issues 7–11) to the same module.

### 2. Async Celery task (HTTP 202 + polling)
Rejected. The endpoint is a "preflight" — callers need a synchronous decision before proceeding. The gate service reads from the already-computed `UniverseQualityReport` row (a single indexed DB read) and applies in-memory policy logic. There is no heavy computation to offload; a Celery task would add latency and polling complexity for no benefit.

### 3. Redis caching (5-minute TTL)
Deferred to a follow-up. Arguments against caching now:
- **Stale-verdict risk is asymmetric.** A cached "trusted" verdict that survives a quality-report recomputation could greenlight an auto-trading action on data the user just learned was degraded.
- **The underlying operation is cheap.** The gate reads one `UniverseQualityReport` row (indexed on `universe_id`) and applies stateless policy logic — cost is in the microseconds-to-low-milliseconds range.
- **Cache invalidation requires wiring.** A correct cache key is `(universe_id, policy, consumer, serialized_requirements, date_range)`, and invalidation must fire whenever `tasks/quality.py` rewrites the report. That coordination is out of scope for this ticket and a real bug surface. If load profiling later shows this endpoint as a hot path, file a dedicated ticket to cache at the quality-report layer (keyed on `universe_id + report generated_at`, invalidated by the Celery task), not at the assessment layer.

## Assumptions

- **[ASSUMPTION]** `QualityGateService` from #492 will expose a method compatible with `QualityGateService.assess(db: Session, request: GateRequest) -> QualityGateAssessment`. If #492 ships a different signature, the router must adapt at integration time.
- **[ASSUMPTION]** `policy="off"` returns `verdict="skipped"` and `trusted=True` regardless of data state (per #492 AC: "skipped" is a valid verdict, implying the gate was intentionally bypassed).
- **[ASSUMPTION]** The universe 404 check happens in the router before calling the gate service (gate service can assume the universe exists).
- **[ASSUMPTION]** `extra="forbid"` on all request schemas is the right choice — it satisfies "malformed requirements return validation errors" and matches the existing `StockUniverseCreate` pattern.

## Open questions (non-blocking)

- Should `universe_id` move to a path parameter in a future revision (`POST /api/v1/data-quality/gate/{universe_id}`)? The current body-field approach matches the issue AC; revisit if the endpoint evolves toward a GET.
- Should a future `GET /api/v1/data-quality/gate` variant be added for purely idempotent, cacheable assessments (no side effects)? Out of scope for this ticket.
