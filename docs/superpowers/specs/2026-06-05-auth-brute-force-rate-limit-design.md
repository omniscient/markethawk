# Auth Brute-Force Rate Limit — Design Spec

**Date:** 2026-06-05
**Issue:** [#196](https://github.com/omniscient/markethawk/issues/196)
**Status:** Spec generated — pending review
**Source:** Architecture Quality Report v2, risk R08 (MEDIUM)

## Overview

`/api/auth/login` and `/api/auth/register` carry no `@limiter.limit` decorator.
Because `/api/auth/*` is wholly exempt from the JWT auth middleware, only the
global `100/minute` SlowAPI default applies — generous enough that an attacker
with a known username can brute-force passwords within seconds.

This spec adds a strict per-IP rate cap to the three credential-sensitive auth
mutation endpoints: `login`, `register`, and `refresh`.

## Requirements

- A new named constant `AUTH_LIMIT = "5/minute"` is defined in
  `backend/app/core/rate_limits.py` alongside the existing `SCANNER_LIMIT` and
  `TRADING_LIMIT`.
- `POST /api/auth/login` is decorated with `@limiter.limit(AUTH_LIMIT)`.
- `POST /api/auth/register` is decorated with `@limiter.limit(AUTH_LIMIT)`.
- `POST /api/auth/refresh` is decorated with `@limiter.limit(AUTH_LIMIT)` (defense-in-depth — refresh is not password-guessable, but is a credential-adjacent mutation endpoint left at the global 100/min default without this change).
- `GET /api/auth/status`, `GET /api/auth/me`, and `POST /api/auth/logout` remain
  on the global `100/minute` default (not sensitive credential operations).
- Exceeding the limit returns `HTTP 429` with the existing standardized body:
  `{"message": "Rate limit exceeded", "error_id": null, "retry_after": <seconds>}`
  and a `Retry-After` header. No new exception handler is needed — the handler in
  `main.py` already covers all `RateLimitExceeded` errors.
- A test verifies that a POST to a rate-limited auth-like endpoint returns `200`
  on the first call and `429` on the next, using the `memory://` storage pattern
  already established in `tests/api/test_rate_limiting.py`.

## Architecture / Approach

### Chosen approach: SlowAPI decorator on each endpoint

Add `@limiter.limit(AUTH_LIMIT)` directly to the three route handler functions.
This is the identical pattern used on `scanner.py:81` and throughout
`auto_trading.py`. SlowAPI requires that the decorated route handler accept a
`request: Request` positional argument — `login`, `register`, and `refresh`
currently omit it, so it must be added to each signature.

**Implementation steps:**

1. **`backend/app/core/rate_limits.py`** — add one constant:
   ```python
   AUTH_LIMIT = "5/minute"
   ```

2. **`backend/app/routers/auth.py`** — import `AUTH_LIMIT` and `limiter` from
   `app.core.rate_limits`; import `Request` from `fastapi`. Apply the decorator
   and add `request: Request` to `login`, `register`, and `refresh`:
   ```python
   @router.post("/login")
   @limiter.limit(AUTH_LIMIT)
   def login(request: Request, body: LoginRequest, db: Session = Depends(get_db)):
       ...
   ```

3. **`backend/tests/api/test_rate_limiting.py`** — add a `_make_auth_test_app()`
   helper and a test `test_auth_endpoints_rate_limited()` that mirrors the
   existing `test_429_response_format()` test: creates a minimal FastAPI app
   with `storage_uri="memory://"`, applies a `1/minute` limit to a mock
   POST route, verifies the second request returns `429` with the correct body
   shape.

No database migration, no new model, no config change is needed.

## Alternatives Considered

### A. Inline string literals `@limiter.limit("5/minute")`

Simple, no constant required. Rejected: the existing codebase defines named
constants per rate-limit concern (`SCANNER_LIMIT`, `TRADING_LIMIT`). Inline
strings make it impossible to grep for all callers when the limit needs to
change, and obscure semantic intent at the call site.

### B. Middleware-level IP block after N failures

A custom ASGI middleware that tracks failed attempts per IP in Redis and returns
429 after a threshold. More sophisticated (could distinguish failed vs. successful
attempts) but over-engineered for a single-operator app that already has SlowAPI
wired. YAGNI — the decorator approach satisfies the acceptance criteria cleanly.

## Open Questions

- **Burst vs. sliding window:** SlowAPI defaults to a fixed window (not sliding).
  A burst of 5 requests in the first second of a window succeeds, then blocks for
  the remainder of the minute. This is acceptable for the current threat model;
  re-evaluate if the app goes multi-tenant.

## Assumptions

- `RATE_LIMITING_ENABLED=true` is set in the production environment. When
  `false`, the existing `enabled=False` limiter no-op means decorators are
  transparent — no behavior change in dev where this may be off.
- The application has a single operator (single `User` record); the 5/min cap
  has no legitimate UX impact.
- IP-keyed rate limiting (`get_remote_address`) is appropriate. If the app runs
  behind a proxy that rewrites IP headers, `FORWARDED_ALLOW_IPS` may need to be
  set in the FastAPI/Uvicorn config (out of scope for this issue).
