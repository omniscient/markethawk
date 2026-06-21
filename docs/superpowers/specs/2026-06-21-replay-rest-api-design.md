# Replay Engine: REST API — Design Spec

**Date:** 2026-06-21
**Status:** Design (brainstorm complete)
**Issue:** #488 — Replay engine: REST API (`/api/v1/replay`)
**Epic:** #483 — Canonical Signal Replay Engine
**Depends on:** #484 (data model + manifest resolver + data hash), #487 (execution task + metrics computer)

---

## 1. Problem

The replay engine (sub-issues #484–#487) needs a REST surface so users can create, list, inspect, and compare replay runs. Without an API layer there is no way to trigger a replay or retrieve its results. This issue builds the thin router + Pydantic schemas that sit above the services; it does **not** implement execution logic or UI.

## 2. Requirements

Distilled from the issue body and Q&A:

- **R1** — `POST /api/v1/replay/runs` creates a `replay_run` record, enqueues `run_signal_replay`, and returns HTTP 202 with the run object (status=`queued`).
- **R2** — `GET /api/v1/replay/runs` lists runs with optional filters (`scanner_type`, `trading_strategy_id`, `status`), paginated (default 50, max 200).
- **R3** — `GET /api/v1/replay/runs/{run_uuid}` returns the full manifest + cached `metrics` JSONB. Accepts a UUID string in the path (not the integer PK).
- **R4** — `GET /api/v1/replay/runs/{run_uuid}/trades` returns the `replay_trade` ledger for one run, paginated and sortable.
- **R5** — `GET /api/v1/replay/runs/{run_uuid}/analytics` returns structured analytics (calendar decay, holding-period decay, regime breakdown). Returns 200 with `status` + empty sections while the run is `queued`/`running`; once `complete`, serves cached `replay_run.metrics` with a fallback to compute from `replay_trade` rows if the JSONB is absent.
- **R6** — `GET /api/v1/replay/runs/compare?ids=a,b[,c,d,e]` compares headline metrics side-by-side. Min 2, max 5 UUIDs. Response includes each run's headline metrics + `data_hash`, a pairwise `comparisons` array (`[{a, b, data_hash_match: bool}, …]`), and a convenience `all_hashes_match: bool`.
- **R7** — Register the router in `backend/app/routers/__init__.py` and `backend/app/main.py`.
- **R8** — 404 on unknown `run_uuid`; 422 on malformed UUID format; 400/422 on invalid manifest inputs; 422 when `compare` receives fewer than 2 or more than 5 IDs.
- **R9** — `POST /runs` inputs include: `scanner_type` (str), `trading_strategy_id` (int), `universe_id` (int), `start_date`/`end_date` (BatchDateRange mixin — max 1830-day range), `max_hold_days` (int, 1–252), `exit_fidelity` (optional str enum: `"intraday"` | `"daily"`, default `"intraday"`), `benchmark_symbol` (optional Ticker-validated str, e.g. `"SPY"`).

## 3. Architecture / Approach

### Files

| File | Role |
|------|------|
| `backend/app/routers/replay.py` | FastAPI `APIRouter(prefix="/api/v1/replay", tags=["replay"])` |
| `backend/app/schemas/replay.py` | Pydantic request/response schemas |
| `backend/app/routers/__init__.py` | Add `replay_router` import + `__all__` entry |
| `backend/app/main.py` | Add `replay_router` to `include_router` block |

### Router pattern

Follow `backend/app/routers/backtest.py` as the canonical template:
- All endpoints use `db: Session = Depends(get_db)` (sync session).
- UUID path params parsed with `uuid.UUID(run_uuid)`; invalid format → 422.
- 404 lookups via `get_or_404(db, ReplayRun, ...)` from `app.utils.db`.
- Lazy imports of models inside handlers (avoids circular imports at module load).
- No `joinedload()` on paginated one-to-many queries — use `selectinload()` or separate queries.

### Endpoint details

#### `POST /runs` (HTTP 202)
1. Validate `TradingStrategy` and `StockUniverse` exist (404 if not).
2. Create `ReplayRun(uuid=uuid4(), status="queued", created_at=utc_now(), …)`, commit.
3. Dispatch `run_signal_replay.delay(run_id=run.id, …)`, store `celery_task_id`, commit.
4. Return `ReplayRunResponse`.

#### `GET /runs`
Filters: `scanner_type`, `trading_strategy_id`, `status`. Order: `created_at DESC`. Pagination: `limit` (1–200, default 50), `offset`.

#### `GET /runs/{run_uuid}`
Lookup by `ReplayRun.uuid`. Return `ReplayRunResponse` (includes `metrics` JSONB as-is).

#### `GET /runs/{run_uuid}/trades`
Separate query on `ReplayTrade.run_id == run.id`. Sortable by `signal_date` (default asc), `return_r`, `ticker`. Pagination: `limit` (1–500, default 100), `offset`.

#### `GET /runs/{run_uuid}/analytics`
- If `run.status` in (`queued`, `running`, `failed`): return 200 with `{"status": run.status, "calendar_decay": [], "holding_period_decay": [], "regime_breakdown": []}`.
- If `run.status == "complete"` and `run.metrics` is not null: deserialize and return.
- If `run.status == "complete"` and `run.metrics` is null (legacy/recompute): compute from `replay_trade` rows and return (mirrors how `/api/v1/outcomes/` endpoints compute from DB).

#### `GET /runs/compare`
- Query param `ids`: comma-separated list of UUID strings (min 2, max 5). Validate format, return 422 on count violation.
- Fetch each run; 404 if any is not found (include which UUID was missing in the detail).
- Return `ReplayCompareResponse`:
  ```json
  {
    "runs": [
      {"uuid": "...", "headline_metrics": {...}, "data_hash": "..."},
      ...
    ],
    "comparisons": [
      {"a": "uuid-a", "b": "uuid-b", "data_hash_match": true},
      ...
    ],
    "all_hashes_match": true
  }
  ```
  The `comparisons` array enumerates all N×(N-1)/2 pairs; each pair has both run UUIDs and the boolean equality check.

### Pydantic schemas (`schemas/replay.py`)

```python
class ReplayRunRequest(BatchDateRange):          # start_date / end_date + 1830-day cap
    model_config = ConfigDict(extra="forbid")
    scanner_type: str
    trading_strategy_id: int
    universe_id: int
    max_hold_days: int = Field(default=10, ge=1, le=252)
    exit_fidelity: Optional[Literal["intraday", "daily"]] = "intraday"
    benchmark_symbol: Optional[Ticker] = None    # Ticker from app.schemas.common

class ReplayTradeResponse(BaseModel):
    id: int
    run_id: int
    scanner_event_id: Optional[int]
    ticker: str
    signal_date: date
    entry_date: Optional[date]
    entry_price: Optional[float]
    exit_date: Optional[date]
    exit_price: Optional[float]
    exit_reason: Optional[str]
    return_pct: Optional[float]
    return_r: Optional[float]
    mfe_pct: Optional[float]
    mae_pct: Optional[float]
    bars_held: Optional[int]
    regime_trend: Optional[str]
    regime_vol: Optional[str]
    fill_source: Optional[str]
    model_config = {"from_attributes": True}

class ReplayRunResponse(BaseModel):
    id: int
    uuid: UUID
    status: str
    scanner_type: str
    trading_strategy_id: int
    universe_id: int
    start_date: date
    end_date: date
    max_hold_days: int
    exit_fidelity: Optional[str]
    benchmark_symbol: Optional[str]
    data_hash: Optional[str]
    metrics: Optional[Dict[str, Any]]           # raw JSONB blob
    skipped_count: Optional[int]
    error_message: Optional[str]
    celery_task_id: Optional[str]
    created_at: Optional[datetime]
    completed_at: Optional[datetime]
    model_config = {"from_attributes": True}

class ReplayRunDetailResponse(ReplayRunResponse):
    trades: List[ReplayTradeResponse] = []

class ReplayAnalyticsResponse(BaseModel):
    status: str
    calendar_decay: List[Dict[str, Any]] = []
    holding_period_decay: List[Dict[str, Any]] = []
    regime_breakdown: List[Dict[str, Any]] = []

class RunCompareEntry(BaseModel):
    uuid: UUID
    headline_metrics: Optional[Dict[str, Any]]
    data_hash: Optional[str]

class RunPairComparison(BaseModel):
    a: UUID
    b: UUID
    data_hash_match: bool

class ReplayCompareResponse(BaseModel):
    runs: List[RunCompareEntry]
    comparisons: List[RunPairComparison]
    all_hashes_match: bool
```

### Router registration

`routers/__init__.py`:
```python
from app.routers.replay import router as replay_router
```
Add `"replay_router"` to `__all__`.

`main.py` — import `replay_router` from `app.routers` and include in the import block alongside the other routers.

## 4. Alternatives Considered

### A: Integer IDs in URL paths
Rejected. The integer PK is an internal join key; exposing it leaks sequential implementation details and breaks consistency with `BacktestRun` and `ScannerRun` which expose UUIDs externally. The dual `id`/`uuid` on `replay_run` follows the same convention.

### B: 425 Too Early on `analytics` when run not complete
Rejected. `425` is non-idiomatic in this codebase (no endpoint uses it). It forces clients to handle a different error-code polling loop compared to the well-established `status`-polling pattern used by `/backtest/runs/{uuid}`. Returning 200 + empty sections + `status` lets a single poll loop handle both runs and analytics consistently.

### C: Compute analytics on-the-fly from partial trade rows
Rejected. Serving partial decay/regime numbers that change on every poll produces misleading results (a run 10% through will show a very different win-rate than at 100%). Analytics are only meaningful over the full trade set; serve them only when `status == "complete"`.

## 5. Open Questions (non-blocking)

- **Trade sort fields**: sortable by `signal_date`, `return_r`, `ticker` is proposed. If the UI sub-issues (489/490) need additional sort columns (e.g. `mfe_pct`, `bars_held`), they can be added to the schema without a model change.
- **Analytics response shape**: the `calendar_decay`, `holding_period_decay`, and `regime_breakdown` shapes depend on what `MetricsComputer` (sub-issue #487) produces and stores in the `metrics` JSONB. This spec defines them as `List[Dict[str, Any]]` to avoid premature coupling; the implementing agent should align with the actual `MetricsComputer` output schema.
- **Rate limiting**: no per-endpoint rate limit is specified. The global 100 req/min limit from `core/rate_limits.py` applies. If `POST /runs` proves expensive to enqueue, a `SCANNER_LIMIT`-style cap can be added later.

## 6. Assumptions

- `ReplayRun` and `ReplayTrade` SQLAlchemy models exist in `backend/app/models/` and are imported in `models/__init__.py` (delivered by sub-issue #484).
- The Celery task `run_signal_replay` exists in `backend/app/tasks/replay.py` and accepts `run_id` as its first positional argument (delivered by sub-issue #487).
- `ManifestResolver` validation (freezing config/strategy/universe snapshots) is done inside the Celery task, not in the router — the router only validates FK existence (strategy, universe).
- `exit_fidelity` is an optional string enum (`"intraday"` | `"daily"`). If sub-issue #484 implements it as a Python `Enum` column, the schema validator may need adjustment.
- The `compare` endpoint is read-only and does not require any lock or serialization beyond a single DB transaction.

## 7. Validation

Per CLAUDE.md, backend changes must be validated live before committing:

```bash
# Confirm backend reloaded
docker-compose logs backend --tail=5

# Create a replay run
curl -s -X POST http://localhost:8000/api/v1/replay/runs \
  -H "Content-Type: application/json" \
  -d '{"scanner_type":"pre_market_volume_spike","trading_strategy_id":1,"universe_id":1,"start_date":"2026-01-01","end_date":"2026-03-31","max_hold_days":10}' \
  | python -m json.tool

# Poll status
curl -s http://localhost:8000/api/v1/replay/runs/<uuid> | python -m json.tool

# Fetch trades
curl -s "http://localhost:8000/api/v1/replay/runs/<uuid>/trades?limit=10" | python -m json.tool

# Fetch analytics
curl -s http://localhost:8000/api/v1/replay/runs/<uuid>/analytics | python -m json.tool

# Compare two runs
curl -s "http://localhost:8000/api/v1/replay/runs/compare?ids=<uuid1>,<uuid2>" | python -m json.tool
```
