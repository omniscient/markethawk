# API Rate Limiting Design (SlowAPI)

**Date**: 2026-05-27  
**Status**: Draft  
**Scope**: Add SlowAPI rate limiting middleware to the FastAPI backend with Redis-backed storage, per-endpoint tiers, and a consistent JSON 429 response.

---

## Overview

No rate limiting middleware exists on the backend. Any client can send unlimited requests, risking:

- Denial-of-service against the API
- Polygon.io API quota exhaustion (rate-limited external dependency)
- Database connection pool exhaustion under request floods
- Celery queue flooding via unlimited scan submissions

This is classified as Risk R03 (High) in the Architecture & Quality Report. The fix is a targeted `slowapi` integration: Redis-backed state, three rate-limit tiers keyed by client IP, and a 429 response that matches the existing error envelope.

---

## Requirements

- **R1**: Add `slowapi` to `backend/requirements.txt`.
- **R2**: Rate limiting state stored in Redis at db 1 (isolated from Celery's broker on db 0), derived from the existing `REDIS_URL` setting.
- **R3**: Three rate-limit tiers applied by client IP:

  | Tier | Limit | Endpoints |
  |------|-------|-----------|
  | Exempt | No limit | `GET /api/health`, all WebSocket upgrade paths |
  | Expensive | 5 req/min | Scanner run POSTs, universe sync/quality/normalize POSTs |
  | Auto-trading | 10 req/min | Order approve, reject, cancel POSTs |
  | Global default | 100 req/min | Everything else |

- **R4**: 429 responses return JSON `{"message": "Rate limit exceeded", "error_id": null, "retry_after": N}` with a `Retry-After: N` header. No `X-RateLimit-*` headers added to non-429 responses.
- **R5**: Rate limit constants defined in a single `app/core/rate_limits.py` module. No magic strings in router files.
- **R6**: `RATE_LIMITING_ENABLED: bool = True` setting in `Settings` and `.env.example`. When `false`, the limiter is instantiated with no storage or default limits (no-op). Default is `true` in all environments.

---

## Architecture

### New file: `backend/app/core/rate_limits.py`

```python
GLOBAL_LIMIT = "100/minute"
SCANNER_LIMIT = "5/minute"
TRADING_LIMIT = "10/minute"
```

### Modified: `backend/requirements.txt`

Add:
```
slowapi==0.1.9
```

slowapi 0.1.9 declares `limits` as a dependency and pulls in its Redis storage support automatically.

### Modified: `backend/app/core/config.py`

Add to `Settings`:
```python
RATE_LIMITING_ENABLED: bool = os.getenv("RATE_LIMITING_ENABLED", "true").lower() == "true"
```

### Modified: `backend/app/main.py`

**Limiter setup** (module level, before `create_app()`):

```python
from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.middleware import SlowAPIASGIMiddleware
from slowapi.errors import RateLimitExceeded
from app.core.rate_limits import GLOBAL_LIMIT

def _build_limiter() -> Limiter:
    if not settings.RATE_LIMITING_ENABLED:
        return Limiter(key_func=get_remote_address)
    # Use Redis db 1 to isolate rate-limit keys from Celery broker on db 0
    rate_redis_url = settings.REDIS_URL.rstrip("/0") + "/1" if settings.REDIS_URL.endswith("/0") else settings.REDIS_URL + "/1"
    return Limiter(
        key_func=get_remote_address,
        default_limits=[GLOBAL_LIMIT],
        storage_uri=rate_redis_url,
    )

limiter = _build_limiter()
```

**Inside `create_app()`**, after the GZip middleware line:

```python
app.state.limiter = limiter
app.add_middleware(SlowAPIASGIMiddleware)

@app.exception_handler(RateLimitExceeded)
async def rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded):
    retry_after = int(exc.retry_after) if exc.retry_after else 60
    return JSONResponse(
        status_code=429,
        headers={"Retry-After": str(retry_after)},
        content={"message": "Rate limit exceeded", "error_id": None, "retry_after": retry_after},
    )
```

### Modified: `backend/app/routers/health.py`

Exempt the liveness probe from rate limiting:

```python
@router.get("/health")
@limiter.exempt
async def health_check():
    ...
```

### Modified: `backend/app/routers/scanner.py`

Apply `SCANNER_LIMIT` to expensive scanner POSTs:

```python
from app.core.rate_limits import SCANNER_LIMIT
from app.main import limiter

@router.post("/run", ...)
@limiter.limit(SCANNER_LIMIT)
async def run_scanner(request: Request, ...):
    ...

@router.post("/run-range")
@limiter.limit(SCANNER_LIMIT)
async def run_range_scan(request: Request, ...):
    ...
```

WebSocket routes get `@limiter.exempt`:
- `@router.websocket("/ws/runs/{task_id}")`

### Modified: `backend/app/routers/universe.py`

Apply `SCANNER_LIMIT` (5/min) to bulk data-triggering POSTs:

| Endpoint | Reason |
|----------|--------|
| `POST /sync/fundamentals` | Paginated Polygon ticker sync |
| `POST /sync/details` | Per-ticker detail crawl chain |
| `POST /{universe_id}/sync-missing` | Bulk OHLCV catch-up via Celery |
| `POST /{universe_id}/sync-aggregates` | OHLCV backfill |
| `POST /{universe_id}/analyze-quality` | CPU-intensive quality analysis |
| `POST /{universe_id}/normalize` | Data normalization + re-analysis |

Lighter universe POSTs (`/create`, `/{id}/refresh-stats`, `/{id}/refresh`, `/sync/stop`, `/sync/metrics`, `/{id}/export-aggregates`) receive the global 100/min default — no decorator needed.

### Modified: `backend/app/routers/auto_trading.py`

Apply `TRADING_LIMIT` (10/min) to order state-change POSTs:

```python
from app.core.rate_limits import TRADING_LIMIT
from app.main import limiter

@router.post("/orders/{order_id}/approve")
@limiter.limit(TRADING_LIMIT)
async def approve_order(request: Request, ...):
    ...

@router.post("/orders/{order_id}/reject")
@limiter.limit(TRADING_LIMIT)
async def reject_order(request: Request, ...):
    ...

@router.post("/orders/{order_id}/cancel")
@limiter.limit(TRADING_LIMIT)
async def cancel_order(request: Request, ...):
    ...
```

### Modified: WebSocket routes — exempt from limiting

SlowAPI applies limits to the HTTP handshake, which would trip the counter on every reconnect. All seven WebSocket routes must be exempted:

| File | Route |
|------|-------|
| `live_data.py` | `/ws/{ticker}/{resolution}`, `/ws/watchlist`, `/ws/scan-task/{task_id}` |
| `scanner.py` | `/ws/runs/{task_id}` |
| `system.py` | `/ws/tasks` |
| `tweets.py` | `/feed` |
| `news.py` | `/ws` |

Each gets `@limiter.exempt` above the `@router.websocket(...)` decorator.

### Modified: `backend/.env.example` (or root `.env.example`)

```
RATE_LIMITING_ENABLED=true
```

---

## Redis Key Isolation

slowapi prefixes all keys with `LIMITS:` in Redis. Using db 1 keeps these keys fully segregated from Celery's broker (db 0). The derivation in `_build_limiter()` swaps the trailing `/0` to `/1` — this handles the default `redis://redis:6379/0` URL. If the deployed `REDIS_URL` uses a query string form (e.g. `?db=0`) or a non-zero db, the `RATE_LIMIT_REDIS_URL` env var should be added as a separate override instead.

---

## Alternatives Considered

### Custom Starlette middleware

Writing rate limiting from scratch with Redis `INCR`/`EXPIRE` gives full control of the storage schema and error format, but requires ~200 lines of new code vs. ~50 lines of configuration with slowapi. Not worth it when slowapi already solves the problem.

### Nginx/reverse proxy rate limiting

Handle at the infrastructure layer with `nginx limit_req`. Keeps the concern out of the application entirely. However, the current Docker Compose stack has no Nginx service — adding one exclusively for rate limiting violates YAGNI and adds operational complexity. Nginx would also require duplicating the endpoint-tier config that is already expressible in Python.

---

## Assumptions

- **A1**: `slowapi==0.1.9` is compatible with `fastapi==0.135.3`. If there are import errors at startup, check that slowapi's starlette dependency version does not conflict with the pinned `starlette` version in requirements.
- **A2**: `REDIS_URL` ends with `/0` in all deployment environments (matches the default `redis://redis:6379/0`). The `_build_limiter()` db-swap logic targets this form. A non-standard URL requires a manual `RATE_LIMIT_REDIS_URL` override.
- **A3**: IP-based rate limiting (`get_remote_address`) is sufficient for a single-tenant deployment. No per-user or per-auth-token key function is needed.
- **A4**: The `request: Request` parameter must appear in the function signature for every route decorated with `@limiter.limit()`. Routes that currently omit `Request` need it added.
- **A5**: `POST /api/auto-trading/strategies` (strategy creation) is not order submission and receives the global 100/min default; only the order-state-change endpoints get `TRADING_LIMIT`.

---

## Open Questions

- **OQ1**: Several universe POSTs (`/{id}/refresh`, `/{id}/export-aggregates`) are not pure DB operations but do not directly fire Celery tasks or Polygon calls. If profiling later shows they contribute to overload, bump them into the `SCANNER_LIMIT` tier without a spec revision.
- **OQ2**: `POST /api/scanner/runs/{scan_id}/cancel` cancels an in-flight scan (no new Polygon calls). It is currently in the global 100/min tier. If cancellation itself becomes a spam vector, add `@limiter.limit(SCANNER_LIMIT)`.
