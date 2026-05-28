# ADR-003: SlowAPI Middleware for Rate Limiting

**Date**: 2026-05-28  
**Status**: Accepted  
**Issue**: [#87 — Add API rate limiting (slowapi)](https://github.com/omniscient/markethawk/issues/87)

## Context

No API rate limiting existed on the backend. Any client could send unlimited requests, risking Polygon.io quota exhaustion (external API with monthly call caps), DB connection pool saturation under request floods, and Celery queue flooding via unlimited scan submissions.

The threat model is self-inflicted: automation scripts gone wrong, not adversarial DDoS. Every risk named in the issue originates from developer tooling misbehaving, not an external attacker.

### Options Considered

**A. SlowAPI ASGI middleware** — Python decorator-based rate limiting on the FastAPI app. Redis-backed counters. Per-endpoint granularity via `@limiter.limit()` decorators. No new infrastructure service.

**B. Reverse proxy gateway (Nginx/Traefik)** — Rate limiting at the socket layer. Rejects connections before Python processes them. Lower CPU cost per rejected request under high load.

| Factor | SlowAPI middleware | Gateway (Nginx/Traefik) |
|---|---|---|
| Protects Polygon quota | ✓ | ✓ |
| Sheds load before Python | ✗ | ✓ |
| Per-endpoint granularity | ✓ | Limited |
| Throttles Celery-indirect calls | ✓ | ✗ |
| New infrastructure service | None | Required |

The gateway's key advantage — socket-layer rejection — only matters for adversarial floods where the attacker has motivation to bypass or overwhelm the rate limiter. Self-inflicted accidents back off on a 429 response. The gateway's key blind spot: Polygon API calls originate from Celery workers, which bypass any reverse proxy entirely. The scan submission endpoints (`POST /api/scanner/run`) are the only lever that controls Polygon quota consumption — and only middleware-level limiting can throttle those.

## Decision

**Option A**: SlowAPI ASGI middleware with Redis db 1 storage.

### Parameters

| Parameter | Value |
|---|---|
| Storage backend | Redis db 1 (`REDIS_URL` with `/0` swapped to `/1`, isolated from Celery) |
| Global default | 100 req/min per IP |
| Scanner tier | 5/min — `POST /api/scanner/run`, `POST /api/scanner/run-range`, 6 universe sync POSTs |
| Trading tier | 10/min — `POST /api/trading/orders/{id}/approve|reject|cancel` |
| Exempt | `GET /api/health` (Docker liveness probe), all 7 WebSocket upgrade routes |
| Disabled mode | `RATE_LIMITING_ENABLED=false` uses `enabled=False` — no-op at both middleware and decorator level |
| Response | `429 {"message": "Rate limit exceeded", "error_id": null, "retry_after": N}` + `Retry-After` header |
| Rate limit headers | None emitted on non-429 responses (`headers_enabled=False`) |

### Architecture note

The `limiter` instance lives in `app/core/rate_limits.py`, not `main.py`. `main.py` imports all routers, and routers need to import `limiter` for `@limiter.limit()` decorators — keeping `limiter` in `core/` breaks the circular import.

## Consequences

- All POST endpoints not listed as exempt receive the global 100/min default.
- Expensive scan and sync POSTs are capped at 5/min; order state-change POSTs at 10/min.
- When Redis is unavailable, SlowAPI falls back to in-memory storage (single-process accuracy only).
- If MarketHawk becomes multi-tenant or internet-facing, a reverse proxy should be added in front of the backend in addition to this middleware (defense in depth — complementary roles, not substitutes).
- `RATE_LIMITING_ENABLED=false` disables enforcement entirely for local development without removing the middleware from the app.
