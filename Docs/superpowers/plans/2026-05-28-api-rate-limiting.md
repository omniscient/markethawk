# API Rate Limiting — Implementation Plan (Issue #87)

**Date**: 2026-05-28
**Issue**: #87 — Add API rate limiting (SlowAPI)
**Spec**: `Docs/superpowers/specs/2026-05-27-api-rate-limiting-design.md`

---

## Goal

Add SlowAPI middleware to the FastAPI backend with Redis-backed storage, three rate-limit tiers keyed by client IP, and a 429 JSON response matching the existing error envelope.

## Architecture

**Key decision**: The `limiter` instance lives in `backend/app/core/rate_limits.py`, not `app/main.py`. This avoids circular imports — `main.py` imports all routers, and routers need to import `limiter`. Putting `limiter` in `core/rate_limits.py` breaks the cycle cleanly.

**Redis isolation**: Rate limit counters use Redis db 1 (`REDIS_URL` ending `/0` is swapped to `/1`). Celery broker uses db 0. Keys never collide.

**`request: Request` naming**: SlowAPI requires `request: Request` as a parameter on every `@limiter.limit()`-decorated function. Several existing endpoints use `request` as the name for a Pydantic body model. These must be renamed to `body` to avoid shadowing.

## Tech Stack

- `slowapi==0.1.9` + its `limits` dependency (Redis storage included)
- Existing `redis==7.4.0` container on `redis://redis:6379`

---

## File Structure

| File | Change |
|------|--------|
| `backend/requirements.txt` | Add `slowapi==0.1.9` |
| `backend/app/core/rate_limits.py` | **New** — limit constants + `limiter` instance |
| `backend/app/core/config.py` | Add `RATE_LIMITING_ENABLED` setting |
| `.env.example` | Add `RATE_LIMITING_ENABLED=true` |
| `backend/app/main.py` | Wire `SlowAPIASGIMiddleware` + `RateLimitExceeded` handler |
| `backend/app/routers/health.py` | Exempt `GET /health` |
| `backend/app/routers/scanner.py` | `SCANNER_LIMIT` on `/run`, `/run-range`; exempt WS |
| `backend/app/routers/universe.py` | `SCANNER_LIMIT` on 6 expensive POSTs |
| `backend/app/routers/auto_trading.py` | `TRADING_LIMIT` on 3 order-state-change POSTs |
| `backend/app/routers/live_data.py` | Exempt 3 WebSocket routes |
| `backend/app/routers/system.py` | Exempt 1 WebSocket route |
| `backend/app/routers/tweets.py` | Exempt 1 WebSocket route |
| `backend/app/routers/news.py` | Exempt 1 WebSocket route |
| `backend/tests/api/test_rate_limiting.py` | **New** — 429 format + structural tests |

---

## Tasks

### Task 1 — Core infrastructure: dependency, `rate_limits.py`, config, env

**Files**: `backend/requirements.txt`, `backend/app/core/rate_limits.py` (new), `backend/app/core/config.py`, `.env.example`

#### TDD

**Step 1** — Write failing test. Create `backend/tests/api/test_rate_limiting.py`:

```python
import pytest
from slowapi import Limiter
from app.core.rate_limits import GLOBAL_LIMIT, SCANNER_LIMIT, TRADING_LIMIT, limiter
from app.core.config import settings


def test_rate_limit_constants():
    assert GLOBAL_LIMIT == "100/minute"
    assert SCANNER_LIMIT == "5/minute"
    assert TRADING_LIMIT == "10/minute"


def test_limiter_is_limiter_instance():
    assert isinstance(limiter, Limiter)


def test_rate_limiting_enabled_setting_is_bool():
    assert isinstance(settings.RATE_LIMITING_ENABLED, bool)
```

**Step 2** — Verify tests fail (slowapi not installed yet):

```bash
docker-compose exec backend python -m pytest tests/api/test_rate_limiting.py -v 2>&1 | head -20
# Expected: ModuleNotFoundError: No module named 'slowapi'
```

**Step 3** — Add `slowapi==0.1.9` to `backend/requirements.txt` after the `redis==7.4.0` line:

```
slowapi==0.1.9
```

**Step 4** — Install in the running container:

```bash
docker-compose exec backend pip install slowapi==0.1.9
# Expected: Successfully installed slowapi-0.1.9 limits-...
```

**Step 5** — Create `backend/app/core/rate_limits.py`:

```python
from slowapi import Limiter
from slowapi.util import get_remote_address
from app.core.config import settings

GLOBAL_LIMIT = "100/minute"
SCANNER_LIMIT = "5/minute"
TRADING_LIMIT = "10/minute"


def _build_limiter() -> Limiter:
    # headers_enabled=False: suppresses X-RateLimit-* headers on every response (R4).
    # When RATE_LIMITING_ENABLED=False, main.py does NOT add SlowAPIASGIMiddleware,
    # so this limiter is imported by routers for decorators but never enforced — true no-op.
    # rsplit('/', 1)[0] strips the trailing /0 db segment safely regardless of port digits.
    if not settings.RATE_LIMITING_ENABLED:
        # enabled=False is SlowAPI's purpose-built no-op switch — neither middleware nor
        # decorator auto_check will enforce limits (R6).
        return Limiter(key_func=get_remote_address, headers_enabled=False, enabled=False)
    rate_redis_url = settings.REDIS_URL.rsplit("/", 1)[0] + "/1"
    return Limiter(
        key_func=get_remote_address,
        default_limits=[GLOBAL_LIMIT],
        storage_uri=rate_redis_url,
        headers_enabled=False,
    )


limiter = _build_limiter()
```

**Step 6** — Add `RATE_LIMITING_ENABLED` to `backend/app/core/config.py` in the `Settings` class, after the `REDIS_URL` line:

```python
RATE_LIMITING_ENABLED: bool = os.getenv("RATE_LIMITING_ENABLED", "true").lower() == "true"
```

**Step 7** — Add to `.env.example` after the `REDIS_URL` block:

```
RATE_LIMITING_ENABLED=true
```

**Step 8** — Verify tests pass:

```bash
docker-compose exec backend python -m pytest tests/api/test_rate_limiting.py -v
# Expected: 3 passed
```

**Step 9** — Commit:

```bash
git add backend/requirements.txt backend/app/core/rate_limits.py backend/app/core/config.py .env.example backend/tests/api/test_rate_limiting.py
git commit -m "feat(rate-limiting): add SlowAPI dependency, rate_limits module, and RATE_LIMITING_ENABLED setting"
```

---

### Task 2 — Wire SlowAPI middleware and 429 handler into `main.py`

**Files**: `backend/app/main.py`

#### TDD

**Step 1** — Add failing test to `backend/tests/api/test_rate_limiting.py`:

```python
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIASGIMiddleware
from slowapi.util import get_remote_address
from app.main import app as main_app


def _make_test_app() -> FastAPI:
    """Minimal FastAPI app with rate limiting wired the same way as main.py."""
    test_limiter = Limiter(
        key_func=get_remote_address,
        default_limits=["100/minute"],
        storage_uri="memory://",
        headers_enabled=False,
    )
    test_app = FastAPI()
    test_app.state.limiter = test_limiter
    test_app.add_middleware(SlowAPIASGIMiddleware)

    @test_app.exception_handler(RateLimitExceeded)
    async def rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded):
        retry_after = exc.limit.limit.get_expiry() if exc.limit else 60
        return JSONResponse(
            status_code=429,
            headers={"Retry-After": str(retry_after)},
            content={"message": "Rate limit exceeded", "error_id": None, "retry_after": retry_after},
        )

    @test_app.get("/test-limited")
    @test_limiter.limit("1/minute")
    async def limited_route(request: Request):
        return {"ok": True}

    return test_app


def test_429_response_format():
    test_app = _make_test_app()
    client = TestClient(test_app, raise_server_exceptions=False)
    first = client.get("/test-limited")       # first — 200
    assert first.status_code == 200
    assert "X-RateLimit-Limit" not in first.headers   # R4: no rate limit headers on non-429
    response = client.get("/test-limited")    # second — 429
    assert response.status_code == 429
    body = response.json()
    assert body["message"] == "Rate limit exceeded"
    assert "error_id" in body
    assert body["error_id"] is None
    assert "retry_after" in body
    assert isinstance(body["retry_after"], int)
    assert "Retry-After" in response.headers
    assert "X-RateLimit-Limit" not in response.headers  # R4: no rate limit headers on 429


def test_main_app_has_limiter_state():
    assert hasattr(main_app.state, "limiter")
    assert isinstance(main_app.state.limiter, Limiter)


def test_rate_limiting_disabled_is_noop():
    """When enabled=False, limiter is a true no-op — middleware + decorator both skip enforcement."""
    disabled_limiter = Limiter(
        key_func=get_remote_address,
        headers_enabled=False,
        enabled=False,
    )
    test_app = FastAPI()
    test_app.state.limiter = disabled_limiter
    test_app.add_middleware(SlowAPIASGIMiddleware)

    @test_app.get("/test-disabled-limited")
    @disabled_limiter.limit("1/minute")
    async def limited_route(request: Request):
        return {"ok": True}

    client = TestClient(test_app, raise_server_exceptions=False)
    for _ in range(5):  # would 429 at request 2 without enabled=False
        response = client.get("/test-disabled-limited")
        assert response.status_code == 200
```

**Step 2** — Verify `test_main_app_has_limiter_state` fails (app not wired yet):

```bash
docker-compose exec backend python -m pytest tests/api/test_rate_limiting.py::test_main_app_has_limiter_state -v
# Expected: AssertionError (app.state has no limiter attribute)
```

**Step 3** — Modify `backend/app/main.py`:

Add these imports after the existing import block (after line 24):

```python
from slowapi.middleware import SlowAPIASGIMiddleware
from slowapi.errors import RateLimitExceeded
from app.core.rate_limits import limiter
```

Inside `create_app()`, after the `app.add_middleware(GZipMiddleware, minimum_size=1000)` line (line 170), add:

```python
    # Added last = outermost middleware (LIFO stacking = first to process inbound requests).
    # When RATE_LIMITING_ENABLED=False, limiter.enabled=False — middleware is present but
    # the limiter is a no-op (neither middleware nor decorator auto_check enforces limits, R6).
    app.state.limiter = limiter
    app.add_middleware(SlowAPIASGIMiddleware)

    @app.exception_handler(RateLimitExceeded)
    async def rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded):
        retry_after = exc.limit.limit.get_expiry() if exc.limit else 60
        return JSONResponse(
            status_code=429,
            headers={"Retry-After": str(retry_after)},
            content={"message": "Rate limit exceeded", "error_id": None, "retry_after": retry_after},
        )
```

**Step 4** — Verify tests pass:

```bash
docker-compose exec backend python -m pytest tests/api/test_rate_limiting.py -v
# Expected: all 6 tests pass
```

**Step 5** — Confirm backend starts without errors:

```bash
docker-compose logs backend --tail=15
# Expected: no import errors; normal "Application startup complete" line
```

**Step 6** — Commit:

```bash
git add backend/app/main.py backend/tests/api/test_rate_limiting.py
git commit -m "feat(rate-limiting): wire SlowAPIASGIMiddleware and 429 handler into main.py"
```

---

### Task 3 — Scanner router: `SCANNER_LIMIT` on POSTs, exempt WebSocket

**Files**: `backend/app/routers/scanner.py`

**Naming conflict**: `run_scanner` and `run_scanner_range` both use `request` as the Pydantic body parameter name. SlowAPI needs `request: Request` as the first parameter, so the Pydantic params must be renamed to `body`.

#### TDD

**Step 1** — Add failing test to `backend/tests/api/test_rate_limiting.py`:

```python
from inspect import signature


def test_scanner_run_has_request_param():
    from app.routers.scanner import run_scanner
    assert "request" in signature(run_scanner).parameters


def test_scanner_run_range_has_request_param():
    from app.routers.scanner import run_scanner_range
    assert "request" in signature(run_scanner_range).parameters


def test_scanner_ws_is_exempt():
    from app.core.rate_limits import limiter as app_limiter
    from app.routers.scanner import scan_run_websocket
    fn = scan_run_websocket
    assert f"{fn.__module__}.{fn.__name__}" in app_limiter._exempt_routes
```

**Step 2** — Verify tests fail:

```bash
docker-compose exec backend python -m pytest tests/api/test_rate_limiting.py::test_scanner_run_has_request_param tests/api/test_rate_limiting.py::test_scanner_run_range_has_request_param tests/api/test_rate_limiting.py::test_scanner_ws_is_exempt -v
# Expected: all 3 fail
```

**Step 3** — Modify `backend/app/routers/scanner.py`:

Add imports (after existing imports near the top of the file):

```python
from fastapi import Request
from app.core.rate_limits import limiter, SCANNER_LIMIT
```

Modify `run_scanner` (line 66). Replace:

```python
@router.post("/run", response_model=ScannerRunAsyncResponse, status_code=202)
def run_scanner(
    request: ScannerRunRequest,
    db: Session = Depends(get_db),
):
```

With:

```python
@router.post("/run", response_model=ScannerRunAsyncResponse, status_code=202)
@limiter.limit(SCANNER_LIMIT)
def run_scanner(
    request: Request,
    body: ScannerRunRequest,
    db: Session = Depends(get_db),
):
```

Inside `run_scanner`, rename **every** `request.` reference to `body.` within the function body. Use a scoped find-and-replace within the function's lines — do not count occurrences. Every `request.universe_id`, `request.scanner_type`, `request.start_date`, `request.end_date` must become `body.*`.

Modify `run_scanner_range` (line 681). Replace:

```python
@router.post("/run-range")
def run_scanner_range(
    request: ScannerRangeRequest,
    db: Session = Depends(get_db),
):
```

With:

```python
@router.post("/run-range")
@limiter.limit(SCANNER_LIMIT)
def run_scanner_range(
    request: Request,
    body: ScannerRangeRequest,
    db: Session = Depends(get_db),
):
```

Inside `run_scanner_range`, rename **every** `request.` reference to `body.` within the function body (scoped find-and-replace within the function's lines): `request.ticker`, `request.scanner_types`, `request.start_date`, `request.end_date`, `request.fetch_missing_data` → `body.*`.

Exempt the WebSocket (line ~237). Replace:

```python
@router.websocket("/ws/runs/{task_id}")
async def scan_run_websocket(websocket: WebSocket, task_id: str):
```

With:

```python
@router.websocket("/ws/runs/{task_id}")
@limiter.exempt
async def scan_run_websocket(websocket: WebSocket, task_id: str):
```

**Step 4** — Verify new tests pass:

```bash
docker-compose exec backend python -m pytest tests/api/test_rate_limiting.py::test_scanner_run_has_request_param tests/api/test_rate_limiting.py::test_scanner_run_range_has_request_param tests/api/test_rate_limiting.py::test_scanner_ws_is_exempt -v
# Expected: 3 passed
```

**Step 5** — Verify no regressions in scanner tests:

```bash
docker-compose exec backend python -m pytest tests/api/test_scanner.py tests/api/test_scanner_range.py tests/api/test_scanner_clear.py -v
# Expected: all pass
```

**Step 6** — Smoke test scanner list endpoint:

```bash
curl -s http://localhost:8000/api/scanner/runs | python -m json.tool
# Expected: 200 with scan runs list
```

**Step 7** — Commit:

```bash
git add backend/app/routers/scanner.py
git commit -m "feat(rate-limiting): apply SCANNER_LIMIT to scanner POSTs, exempt WebSocket, rename body param"
```

---

### Task 4 — Universe router: `SCANNER_LIMIT` on 6 expensive POSTs

**Files**: `backend/app/routers/universe.py`

**Endpoints**:

| Handler | Route | Line |
|---------|-------|------|
| `sync_fundamental_data` | `POST /sync/fundamentals` | 182 |
| `sync_ticker_details` | `POST /sync/details` | 194 |
| `sync_missing_aggregates` | `POST /{universe_id}/sync-missing` | 249 |
| `sync_universe_aggregates` | `POST /{universe_id}/sync-aggregates` | 294 |
| `trigger_quality_analysis` | `POST /{universe_id}/analyze-quality` | 312 |
| `trigger_normalization` | `POST /{universe_id}/normalize` | 385 |

**Naming conflict**: `trigger_normalization` uses `request: Optional[NormalizeRequest]`. Rename to `body`.

**Do NOT touch these endpoints** — they carry no `@limiter.limit()` decorator (global 100/min default applies via middleware), but they already use `request` as a Pydantic body parameter name. Adding `request: Request` would break them. Leave them unchanged:
- `export_universe_aggregates` (line 265): `request: ExportAggregatesRequest`
- `delete_ticker_aggregates` (line 327): `request: DeleteAggregatesRequest`

#### TDD

**Step 1** — Add failing test to `backend/tests/api/test_rate_limiting.py`:

```python
def test_universe_expensive_post_functions_take_request_param():
    from inspect import signature
    from app.routers.universe import (
        sync_fundamental_data,
        sync_ticker_details,
        sync_missing_aggregates,
        sync_universe_aggregates,
        trigger_quality_analysis,
        trigger_normalization,
    )
    fns = [
        sync_fundamental_data,
        sync_ticker_details,
        sync_missing_aggregates,
        sync_universe_aggregates,
        trigger_quality_analysis,
        trigger_normalization,
    ]
    for fn in fns:
        assert "request" in signature(fn).parameters, (
            f"{fn.__name__} missing 'request: Request' parameter"
        )
```

**Step 2** — Verify test fails:

```bash
docker-compose exec backend python -m pytest tests/api/test_rate_limiting.py::test_universe_expensive_post_functions_take_request_param -v
# Expected: AssertionError: sync_fundamental_data missing 'request: Request' parameter
```

**Step 3** — Modify `backend/app/routers/universe.py`:

Add imports after the existing import block:

```python
from fastapi import Request
from app.core.rate_limits import limiter, SCANNER_LIMIT
```

Modify `sync_fundamental_data` (line 182). Replace:

```python
@router.post("/sync/fundamentals")
def sync_fundamental_data(
    background_tasks: BackgroundTasks,
    delay: float = 15.0,
    db: Session = Depends(get_db),
):
```

With:

```python
@router.post("/sync/fundamentals")
@limiter.limit(SCANNER_LIMIT)
def sync_fundamental_data(
    request: Request,
    background_tasks: BackgroundTasks,
    delay: float = 15.0,
    db: Session = Depends(get_db),
):
```

Modify `sync_ticker_details` (line 194). Replace:

```python
@router.post("/sync/details")
def sync_ticker_details(
    background_tasks: BackgroundTasks,
    delay: float = 15.0,
    resync: bool = False,
    db: Session = Depends(get_db),
):
```

With:

```python
@router.post("/sync/details")
@limiter.limit(SCANNER_LIMIT)
def sync_ticker_details(
    request: Request,
    background_tasks: BackgroundTasks,
    delay: float = 15.0,
    resync: bool = False,
    db: Session = Depends(get_db),
):
```

Modify `sync_missing_aggregates` (line 249). Replace:

```python
@router.post("/{universe_id}/sync-missing")
def sync_missing_aggregates(
    universe_id: int,
    db: Session = Depends(get_db),
):
```

With:

```python
@router.post("/{universe_id}/sync-missing")
@limiter.limit(SCANNER_LIMIT)
def sync_missing_aggregates(
    request: Request,
    universe_id: int,
    db: Session = Depends(get_db),
):
```

Modify `sync_universe_aggregates` (line 294). Replace:

```python
@router.post("/{universe_id}/sync-aggregates")
def sync_universe_aggregates(
    universe_id: int,
    from_date: str,
    to_date: str,
    multiplier: int = 1,
    timespan: str = "minute",
    adjusted: bool = True,
    sort: str = "asc",
    limit: int = 50000,
    db: Session = Depends(get_db),
):
```

With:

```python
@router.post("/{universe_id}/sync-aggregates")
@limiter.limit(SCANNER_LIMIT)
def sync_universe_aggregates(
    request: Request,
    universe_id: int,
    from_date: str,
    to_date: str,
    multiplier: int = 1,
    timespan: str = "minute",
    adjusted: bool = True,
    sort: str = "asc",
    limit: int = 50000,
    db: Session = Depends(get_db),
):
```

Modify `trigger_quality_analysis` (line 312). Replace:

```python
@router.post("/{universe_id}/analyze-quality")
def trigger_quality_analysis(
    universe_id: int,
    db: Session = Depends(get_db),
):
```

With:

```python
@router.post("/{universe_id}/analyze-quality")
@limiter.limit(SCANNER_LIMIT)
def trigger_quality_analysis(
    request: Request,
    universe_id: int,
    db: Session = Depends(get_db),
):
```

Modify `trigger_normalization` (line 385). Replace:

```python
@router.post("/{universe_id}/normalize")
def trigger_normalization(
    universe_id: int,
    request: Optional[NormalizeRequest] = None,
    db: Session = Depends(get_db),
):
    target_tickers = request.target_tickers if request else None
```

With:

```python
@router.post("/{universe_id}/normalize")
@limiter.limit(SCANNER_LIMIT)
def trigger_normalization(
    request: Request,
    universe_id: int,
    body: Optional[NormalizeRequest] = None,
    db: Session = Depends(get_db),
):
    target_tickers = body.target_tickers if body else None
```

**Step 4** — Verify test passes:

```bash
docker-compose exec backend python -m pytest tests/api/test_rate_limiting.py::test_universe_expensive_post_functions_take_request_param -v
# Expected: 1 passed
```

**Step 5** — Verify no regressions:

```bash
docker-compose exec backend python -m pytest tests/api/test_universe.py -v
# Expected: all pass
```

**Step 6** — Commit:

```bash
git add backend/app/routers/universe.py
git commit -m "feat(rate-limiting): apply SCANNER_LIMIT to 6 expensive universe POSTs"
```

---

### Task 5 — Auto-trading router: `TRADING_LIMIT` on 3 order-state-change POSTs

**Files**: `backend/app/routers/auto_trading.py`

**Endpoints**:

| Handler | Route | Line |
|---------|-------|------|
| `approve_order` | `POST /orders/{order_id}/approve` | 272 |
| `reject_order` | `POST /orders/{order_id}/reject` | 325 |
| `cancel_order` | `POST /orders/{order_id}/cancel` | 350 |

#### TDD

**Step 1** — Add failing test to `backend/tests/api/test_rate_limiting.py`:

```python
def test_auto_trading_order_functions_take_request_param():
    from inspect import signature
    from app.routers.auto_trading import approve_order, reject_order, cancel_order
    for fn in [approve_order, reject_order, cancel_order]:
        assert "request" in signature(fn).parameters, (
            f"{fn.__name__} missing 'request: Request' parameter"
        )
```

**Step 2** — Verify test fails:

```bash
docker-compose exec backend python -m pytest tests/api/test_rate_limiting.py::test_auto_trading_order_functions_take_request_param -v
# Expected: AssertionError: approve_order missing 'request: Request' parameter
```

**Step 3** — Modify `backend/app/routers/auto_trading.py`:

Add imports after the existing import block:

```python
from fastapi import Request
from app.core.rate_limits import limiter, TRADING_LIMIT
```

Modify `approve_order` (line 272). Replace:

```python
@router.post("/orders/{order_id}/approve")
def approve_order(
    order_id: int,
    db: Session = Depends(get_db),
):
```

With:

```python
@router.post("/orders/{order_id}/approve")
@limiter.limit(TRADING_LIMIT)
def approve_order(
    request: Request,
    order_id: int,
    db: Session = Depends(get_db),
):
```

Modify `reject_order` (line 325). Replace:

```python
@router.post("/orders/{order_id}/reject")
def reject_order(
    order_id: int,
    payload: Dict[str, Any] = {},
    db: Session = Depends(get_db),
):
```

With:

```python
@router.post("/orders/{order_id}/reject")
@limiter.limit(TRADING_LIMIT)
def reject_order(
    request: Request,
    order_id: int,
    payload: Dict[str, Any] = {},
    db: Session = Depends(get_db),
):
```

Modify `cancel_order` (line 350). Replace:

```python
@router.post("/orders/{order_id}/cancel")
def cancel_order(
    order_id: int,
    db: Session = Depends(get_db),
):
```

With:

```python
@router.post("/orders/{order_id}/cancel")
@limiter.limit(TRADING_LIMIT)
def cancel_order(
    request: Request,
    order_id: int,
    db: Session = Depends(get_db),
):
```

**Step 4** — Verify test passes:

```bash
docker-compose exec backend python -m pytest tests/api/test_rate_limiting.py::test_auto_trading_order_functions_take_request_param -v
# Expected: 1 passed
```

**Step 5** — Verify no regressions:

```bash
docker-compose exec backend python -m pytest tests/api/test_auto_trading.py -v
# Expected: all pass
```

**Step 6** — Commit:

```bash
git add backend/app/routers/auto_trading.py
git commit -m "feat(rate-limiting): apply TRADING_LIMIT to approve/reject/cancel order POSTs"
```

---

### Task 6 — Exempt health check and all remaining WebSocket routes

**Files**: `backend/app/routers/health.py`, `backend/app/routers/live_data.py`, `backend/app/routers/system.py`, `backend/app/routers/tweets.py`, `backend/app/routers/news.py`

**WebSocket routes to exempt** (7 total — scanner WS already done in Task 3):

| File | Handler | Route |
|------|---------|-------|
| `health.py` | `health_check` | `GET /health` |
| `live_data.py` | `stock_live_websocket` | `WS /ws/{ticker}/{resolution}` |
| `live_data.py` | `watchlist_live_websocket` | `WS /ws/watchlist` |
| `live_data.py` | `scan_task_websocket` | `WS /ws/scan-task/{task_id}` |
| `system.py` | `system_tasks_websocket` | `WS /ws/tasks` |
| `tweets.py` | `tweet_feed_websocket` | `WS /feed` |
| `news.py` | `news_websocket` | `WS /ws` |

#### TDD

**Step 1** — Add failing tests to `backend/tests/api/test_rate_limiting.py`:

```python
def test_health_check_is_exempt():
    from app.core.rate_limits import limiter as app_limiter
    from app.routers.health import health_check
    fn = health_check
    assert f"{fn.__module__}.{fn.__name__}" in app_limiter._exempt_routes


def test_websocket_routes_are_exempt():
    from app.core.rate_limits import limiter as app_limiter
    from app.routers.live_data import (
        stock_live_websocket,
        watchlist_live_websocket,
        scan_task_websocket,
    )
    from app.routers.system import system_tasks_websocket
    from app.routers.tweets import tweet_feed_websocket
    from app.routers.news import news_websocket

    ws_handlers = [
        stock_live_websocket,
        watchlist_live_websocket,
        scan_task_websocket,
        system_tasks_websocket,
        tweet_feed_websocket,
        news_websocket,
    ]
    for fn in ws_handlers:
        assert f"{fn.__module__}.{fn.__name__}" in app_limiter._exempt_routes, (
            f"{fn.__name__} is not in limiter._exempt_routes"
        )
```

**Step 2** — Verify tests fail:

```bash
docker-compose exec backend python -m pytest tests/api/test_rate_limiting.py::test_health_check_is_exempt tests/api/test_rate_limiting.py::test_websocket_routes_are_exempt -v
# Expected: both fail
```

**Step 3** — Modify `backend/app/routers/health.py`:

Add import:

```python
from app.core.rate_limits import limiter
```

Add `@limiter.exempt` below `@router.get("/health")` (so the route is registered first, then marked exempt):

```python
@router.get("/health")
@limiter.exempt
def health_check():
    ...
```

**Step 4** — Modify `backend/app/routers/live_data.py`:

Add import:

```python
from app.core.rate_limits import limiter
```

Add `@limiter.exempt` below each WebSocket decorator:

```python
@router.websocket("/ws/{ticker}/{resolution}")
@limiter.exempt
async def stock_live_websocket(websocket: WebSocket, ticker: str, resolution: str):
    ...

@router.websocket("/ws/watchlist")
@limiter.exempt
async def watchlist_live_websocket(websocket: WebSocket):
    ...

@router.websocket("/ws/scan-task/{task_id}")
@limiter.exempt
async def scan_task_websocket(websocket: WebSocket, task_id: str):
    ...
```

**Step 5** — Modify `backend/app/routers/system.py`:

Add import:

```python
from app.core.rate_limits import limiter
```

Add `@limiter.exempt` below `@router.websocket("/ws/tasks")` (line 215):

```python
@router.websocket("/ws/tasks")
@limiter.exempt
async def system_tasks_websocket(websocket: WebSocket):
    ...
```

**Step 6** — Modify `backend/app/routers/tweets.py`:

Add import:

```python
from app.core.rate_limits import limiter
```

Add `@limiter.exempt` below `@router.websocket("/feed")` (line 26):

```python
@router.websocket("/feed")
@limiter.exempt
async def tweet_feed_websocket(websocket: WebSocket):
    ...
```

**Step 7** — Modify `backend/app/routers/news.py`:

Add import:

```python
from app.core.rate_limits import limiter
```

Add `@limiter.exempt` below `@router.websocket("/ws")` (line 83):

```python
@router.websocket("/ws")
@limiter.exempt
async def news_websocket(websocket: WebSocket):
    ...
```

**Step 8** — Verify new tests pass:

```bash
docker-compose exec backend python -m pytest tests/api/test_rate_limiting.py::test_health_check_is_exempt tests/api/test_rate_limiting.py::test_websocket_routes_are_exempt -v
# Expected: 2 passed
```

**Step 9** — Verify health endpoint works:

```bash
curl -s http://localhost:8000/api/health | python -m json.tool
# Expected: 200 {"status": "healthy", ...}
```

**Step 10** — Run full API test suite:

```bash
docker-compose exec backend python -m pytest tests/api/ -v
# Expected: all pass, no regressions
```

**Step 11** — Run full rate limiting test suite:

```bash
docker-compose exec backend python -m pytest tests/api/test_rate_limiting.py -v
# Expected: all tests pass
```

**Step 12** — Commit:

```bash
git add backend/app/routers/health.py backend/app/routers/live_data.py backend/app/routers/system.py backend/app/routers/tweets.py backend/app/routers/news.py backend/tests/api/test_rate_limiting.py
git commit -m "feat(rate-limiting): exempt health check and all WebSocket routes from rate limiting"
```

---

## Summary

| Task | Files Changed | Tests |
|------|--------------|-------|
| 1 — Core infrastructure | `requirements.txt`, `rate_limits.py`, `config.py`, `.env.example` | 3 |
| 2 — Main.py wiring | `main.py` | 3 |
| 3 — Scanner router | `scanner.py` | 3 |
| 4 — Universe router | `universe.py` | 1 |
| 5 — Auto-trading router | `auto_trading.py` | 1 |
| 6 — Health + WebSocket exemptions | `health.py`, `live_data.py`, `system.py`, `tweets.py`, `news.py` | 2 |

**Total**: 6 tasks, 13 tests in `test_rate_limiting.py`
