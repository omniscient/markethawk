# CSRF Protection for Cookie-Based Auth

> Tracking issue: [#192](https://github.com/omniscient/markethawk/issues/192)

## Overview

MarketHawk authenticates using HttpOnly JWT cookies with `SameSite=Lax`. There is no CSRF token mechanism. `SameSite=Lax` does not prevent cross-site attacks via top-level navigations or same-site subdomain requests, leaving state-changing endpoints (scanner runs, auto-trading order submission, universe mutations) reachable from a malicious cross-origin page.

This spec adds a custom-header CSRF check — a lightweight, proven defense that requires no token generation or cookie management.

## Requirements

1. All mutating HTTP methods (POST/PUT/PATCH/DELETE) to authenticated endpoints must require the `X-Requested-With: XMLHttpRequest` header.
2. Requests missing the header are rejected with HTTP 403.
3. Auth endpoints (`/api/auth/`) are exempt from CSRF enforcement (pre-authentication, CSRF not applicable; login CSRF requires the victim's credentials and is out-of-scope).
4. Safe methods (GET/HEAD/OPTIONS) are never blocked by CSRF logic.
5. The frontend axios clients (`apiClient` and `unversionedClient`) send the header on every request via static defaults.
6. A pytest integration test confirms: POST to a protected endpoint without `X-Requested-With` → 403; with the header → passes CSRF (may still fail auth if no cookie).

## Architecture

### Defense Mechanism

**Custom header check** (`X-Requested-With: XMLHttpRequest`).

Browsers enforce the "simple request" rules of the CORS spec: HTML forms and top-level navigations cannot set arbitrary request headers. Any request that carries a custom header (outside the [CORS safelisted headers](https://fetch.spec.whatwg.org/#cors-safelisted-request-header)) must pass a CORS preflight. Because the backend's CORS config restricts `allow_origins` to `settings.CORS_ORIGINS`, preflights from non-allowlisted origins fail — so a malicious page cannot forge the header. Mere presence of `X-Requested-With` proves JavaScript origin.

This is sufficient for the threat model (forged cross-site form submissions and navigation attacks). It costs no entropy generation, no cookie management, and no per-session state.

### Backend: `CSRFMiddleware` (pure ASGI)

A new pure ASGI class registered in `backend/app/main.py`, following the existing `AuthMiddleware`/`PrometheusMiddleware` pattern exactly.

**Middleware order (innermost → outermost, request processing order reversed):**

```
route handler
  ← CSRFMiddleware       (added first = innermost — runs after auth)
  ← AuthMiddleware       (added second = outer)
  ← CORSMiddleware
  ← SelectiveGZipMiddleware
  ← SlowAPIASGIMiddleware
  ← PrometheusMiddleware  (outermost)
```

`CSRFMiddleware` is registered with `app.add_middleware(CSRFMiddleware)` on the line immediately before `app.add_middleware(AuthMiddleware)`. This places CSRF innermost (closest to routes), so inbound requests reach `AuthMiddleware` first (401 if no cookie), then `CSRFMiddleware` (403 if no CSRF header), then the route handler.

**CSRF_EXEMPT_PREFIXES** — a dedicated tuple, not reusing `EXEMPT_PREFIXES`:

```python
CSRF_EXEMPT_PREFIXES = ("/api/auth/",)
```

Rationale: `EXEMPT_PREFIXES` contains `/docs`, `/redoc`, `/openapi.json`, `/metrics`, `/api/health`, `/api/alerts/infrastructure` — exempted for reasons unrelated to CSRF. Those paths serve GET-only or infrastructure traffic that CSRF never applies to (safe methods are excluded by method check). Coupling CSRF to the auth exempt list would conflate two distinct security concerns.

**Logic:**

```python
CSRF_EXEMPT_PREFIXES = ("/api/auth/",)
CSRF_MUTATING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

class CSRFMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        method = scope.get("method", "")
        if method not in CSRF_MUTATING_METHODS:
            await self.app(scope, receive, send)
            return
        path = scope.get("path", "")
        if any(path.startswith(p) for p in CSRF_EXEMPT_PREFIXES):
            await self.app(scope, receive, send)
            return
        headers = dict(scope.get("headers", []))
        if b"x-requested-with" not in headers:
            await JSONResponse(
                status_code=403,
                content={"detail": "CSRF check failed: X-Requested-With header required"},
            )(scope, receive, send)
            return
        await self.app(scope, receive, send)
```

### Frontend: axios default headers

`frontend/src/api/client.ts` — add `X-Requested-With` to the static `headers` block of both clients:

```typescript
export const apiClient = axios.create({
  baseURL: API_BASE,
  withCredentials: true,
  headers: {
    'Content-Type': 'application/json',
    'X-Requested-With': 'XMLHttpRequest',
  },
});

export const unversionedClient = axios.create({
  baseURL: '/api',
  withCredentials: true,
  headers: {
    'Content-Type': 'application/json',
    'X-Requested-With': 'XMLHttpRequest',
  },
});
```

Sending the header globally (all methods, all routes) is intentional: it's harmless on GETs, and means auth routes naturally receive it too (no special frontend-side exemption needed).

### Tests

New test file `backend/tests/api/test_csrf.py`:

```python
# Tests CSRF enforcement in CSRFMiddleware.
# Uses a valid JWT cookie to pass auth, then varies the CSRF header presence.
```

Test cases:

| Case | Auth cookie | X-Requested-With | Expected |
|------|-------------|-----------------|---------|
| POST without CSRF header | valid | absent | 403 |
| POST with CSRF header | valid | XMLHttpRequest | 2xx (route processes) |
| GET without CSRF header | valid | absent | 2xx (GET not guarded) |
| POST to /api/auth/login | none | absent | not 403 (exempt path) |

Auth cookie must be a real JWT generated via `app.core.auth.create_access_token` and injected into the test client's cookies — the pure-ASGI `AuthMiddleware` cannot be dependency-overridden.

## Alternatives Considered

### Option A: Extend AuthMiddleware

Add CSRF header check inside the existing `AuthMiddleware.__call__`, after JWT validation.

**Rejected:** conflates two distinct security concerns in one class, making `AuthMiddleware` harder to reason about and test independently. The pure ASGI pattern is already established for separation (Prometheus is separate from auth).

### Option C: FastAPI dependency (`Depends(verify_csrf_header)`)

Inject a dependency on every mutating route handler.

**Rejected:** requires retrofitting every router file and every future route. A single middleware registration is a universal enforcement point with no risk of omission.

## Assumptions

- `settings.CORS_ORIGINS` is correctly configured to allowlist only legitimate origins (the CORS preflight is what makes the custom-header approach robust). If `CORS_ORIGINS = ["*"]` in production, the preflight would pass for any origin and the defense weakens. The spec assumes CORS is correctly locked down (a separate concern from this issue).
- No API clients other than `apiClient` and `unversionedClient` exist. If a direct `fetch()` or `XMLHttpRequest` call is added in future frontend code, it must include the header manually.
- The app serves only one origin in production. Multi-tenant or multi-subdomain deployments would need additional review.

## Open Questions

- Should `POST /api/alerts/infrastructure` (in `EXEMPT_PREFIXES` but not `/api/auth/`) also be CSRF-exempt? It is Grafana-sourced (server-to-server), so it never carries an auth cookie — auth already exempts it, and CSRF won't fire on unauthenticated requests (auth rejects first). No change needed, but worth noting the dependency on order.
