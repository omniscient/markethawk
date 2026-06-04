# API Rate Limiting Design Spec

**Issue**: #87 — Add API rate limiting (SlowAPI)  
**Date**: 2026-05-27  
**ADR**: [ADR-003](../../adr/0003-slowapi-middleware-for-rate-limiting.md)

## Summary

SlowAPI middleware wired into `main.py` with Redis db 1 as storage backend. Three rate-limit tiers defined in `app/core/rate_limits.py`. WebSocket upgrade endpoints and `GET /api/health` exempt.

## Requirements

- `slowapi==0.1.9` in `backend/requirements.txt`
- Redis db 1 storage, derived from `REDIS_URL` setting (db 0 reserved for Celery)
- `app/core/rate_limits.py` with `GLOBAL_LIMIT = "100/minute"`, `SCANNER_LIMIT = "5/minute"`, `TRADING_LIMIT = "10/minute"`
- `RATE_LIMITING_ENABLED: bool = True` in `Settings`
- Exempt: `GET /api/health`, all 7 WebSocket routes
- 5/min: `POST /api/scanner/run`, `POST /api/scanner/run-range`, and 6 universe bulk-sync/quality POSTs
- 10/min: `POST /api/trading/orders/{id}/approve|reject|cancel`
- 100/min global default: everything else
- Custom `RateLimitExceeded` handler returning `{"message": "Rate limit exceeded", "error_id": null, "retry_after": N}` + `Retry-After` header
- No `X-RateLimit-*` headers on any response (`headers_enabled=False`)

## Architecture

**Circular import avoidance**: `limiter` lives in `app/core/rate_limits.py`. `main.py` imports all routers; routers import `limiter`. Putting `limiter` in `main.py` would create a circular dependency.

**Redis isolation**: Rate limit counters use Redis db 1. Celery broker uses db 0. Keys never collide.

**Disabled mode**: `RATE_LIMITING_ENABLED=false` uses `enabled=False` — SlowAPI's purpose-built no-op flag. Disables enforcement at both middleware and decorator level simultaneously. Middleware is still added to the stack (avoids a conditional `add_middleware` call that would change app structure).

**Naming conflict pattern**: Routes decorated with `@limiter.limit()` require `request: Request` as first positional parameter. Existing Pydantic body params named `request` are renamed to `body`.

## Alternatives Considered

See [ADR-003](../../adr/0003-slowapi-middleware-for-rate-limiting.md) for the gateway vs. middleware trade-off analysis and upgrade path documentation.
