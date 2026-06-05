# Plan: CSRF Protection via Custom-Header Check

**Goal**: Block forged cross-site mutations by requiring `X-Requested-With: XMLHttpRequest` on all POST/PUT/PATCH/DELETE to authenticated endpoints. Browsers cannot set arbitrary headers on cross-site requests without a CORS preflight; the locked-down `CORS_ORIGINS` config makes the header unforgeable.

**Issue**: [#192](https://github.com/omniscient/markethawk/issues/192)
**Spec**: [docs/superpowers/specs/2026-06-05-csrf-protection-design.md](../specs/2026-06-05-csrf-protection-design.md)
**Component**: `backend/app/main.py`, `frontend/src/api/client.ts`
**Size**: M (1-4 hours)

---

## Architecture

- **`CSRFMiddleware`**: pure ASGI class defined at module level in `main.py` (above `create_app`). Module-level placement keeps it importable for tests without triggering the full app factory. This follows the same pure-ASGI pattern as `AuthMiddleware`/`PrometheusMiddleware` but is importable.
- **`CSRF_EXEMPT_PREFIXES = ("/api/auth/",)`**: separate tuple, not reusing the auth `EXEMPT_PREFIXES`. The two lists serve different concerns.
- **Registration**: `app.add_middleware(CSRFMiddleware)` immediately before `app.add_middleware(AuthMiddleware)` in `create_app()`. In Starlette's LIFO stack this places CSRF innermost (between auth and routes). Inbound request flow: `AuthMiddleware` (401 if no cookie) → `CSRFMiddleware` (403 if no header) → route.
- **Frontend**: two-line change — add `'X-Requested-With': 'XMLHttpRequest'` to the static `headers` block of both axios clients in `client.ts`.

## Tech Stack

- Backend: Python + FastAPI + pure ASGI middleware
- Frontend: TypeScript + axios
- Tests: pytest + `fastapi.testclient.TestClient` (test-app pattern, no DB dependency)

---

## File Structure

| File | Change |
|------|--------|
| `backend/app/main.py` | Add `CSRF_EXEMPT_PREFIXES`, `CSRF_MUTATING_METHODS`, `CSRFMiddleware` at module level; register before `AuthMiddleware` in `create_app()` |
| `frontend/src/api/client.ts` | Add `'X-Requested-With': 'XMLHttpRequest'` to `apiClient` and `unversionedClient` headers |
| `backend/tests/api/test_csrf.py` | New: 4 integration test cases via test-app pattern |

---

## Tasks

### Task 1 — Backend: CSRFMiddleware + integration tests

**Files**: `backend/app/main.py`, `backend/tests/api/test_csrf.py`

#### Step 1.1 — Write failing test file

Create `backend/tests/api/test_csrf.py`. At this point the import of `CSRFMiddleware` will fail (it doesn't exist yet), causing a collection error.

```python
"""Tests CSRF enforcement via CSRFMiddleware (issue #192)."""
import os

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-unit-tests-only-32chars!")
os.environ.setdefault("RATE_LIMITING_ENABLED", "false")

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from jose import jwt

from app.core.auth import create_access_token
from app.core.config import get_settings
from app.main import CSRFMiddleware  # fails until Task 1.3 adds the class


def _make_app() -> FastAPI:
    """Minimal test app: auth + CSRF middleware, no DB dependency."""
    _app = FastAPI()
    _settings = get_settings()

    class _AuthMiddleware:
        def __init__(self, app):
            self.app = app

        async def __call__(self, scope, receive, send):
            if scope["type"] != "http":
                await self.app(scope, receive, send)
                return
            from starlette.requests import Request
            request = Request(scope)
            if request.url.path.startswith("/api/auth/"):
                await self.app(scope, receive, send)
                return
            token = request.cookies.get("access_token")
            if not token:
                await JSONResponse(
                    status_code=401, content={"detail": "Not authenticated"}
                )(scope, receive, send)
                return
            try:
                jwt.decode(
                    token,
                    _settings.JWT_SECRET_KEY,
                    algorithms=[_settings.JWT_ALGORITHM],
                )
            except Exception:
                await JSONResponse(
                    status_code=401, content={"detail": "Invalid token"}
                )(scope, receive, send)
                return
            await self.app(scope, receive, send)

    _app.add_middleware(CSRFMiddleware)   # innermost: between auth and routes
    _app.add_middleware(_AuthMiddleware)  # outermost: validates JWT before CSRF check

    @_app.post("/api/v1/resource")
    async def post_resource():
        return {"ok": True}

    @_app.get("/api/v1/resource")
    async def get_resource():
        return {"ok": True}

    @_app.post("/api/auth/login")
    async def auth_login():
        return {"ok": True}

    return _app


_test_app = _make_app()


def _authed_client() -> TestClient:
    token = create_access_token("test-user-id")
    c = TestClient(_test_app)
    c.cookies.set("access_token", token)
    return c


def test_post_without_csrf_header_returns_403():
    response = _authed_client().post("/api/v1/resource", json={})
    assert response.status_code == 403
    assert "X-Requested-With" in response.json()["detail"]


def test_post_with_csrf_header_passes_csrf():
    response = _authed_client().post(
        "/api/v1/resource",
        json={},
        headers={"X-Requested-With": "XMLHttpRequest"},
    )
    assert response.status_code == 200


def test_get_without_csrf_header_passes():
    response = _authed_client().get("/api/v1/resource")
    assert response.status_code == 200


def test_auth_endpoint_exempt_from_csrf():
    # no auth cookie — path is CSRF-exempt and auth-exempt
    c = TestClient(_test_app)
    response = c.post("/api/auth/login", json={})
    assert response.status_code != 403
```

#### Step 1.2 — Verify tests fail

```bash
cd /workspace/markethawk/backend
python -m pytest tests/api/test_csrf.py -v 2>&1 | head -20
```

**Expected output** (import error before CSRFMiddleware exists):
```
ImportError: cannot import name 'CSRFMiddleware' from 'app.main'
```

#### Step 1.3 — Add CSRFMiddleware at module level in `main.py`

Insert the following block in `backend/app/main.py` **between the import block (line ~47) and the `lifespan` function (line 52)**:

```python
# CSRF header check — module-level so it is importable by the test suite without
# triggering the full create_app() factory. Pure ASGI (not BaseHTTPMiddleware) to
# avoid the chunked-gzip termination bug described at the AuthMiddleware comment.
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

#### Step 1.4 — Register CSRFMiddleware in `create_app()`

In `backend/app/main.py`, replace the single `add_middleware(AuthMiddleware)` line (around line 278–280) with:

```python
    # CSRFMiddleware first = innermost (between auth and routes).
    # AuthMiddleware second = outer: validates JWT before CSRF check fires.
    # Inbound flow: AuthMiddleware (401) → CSRFMiddleware (403) → route handler.
    app.add_middleware(CSRFMiddleware)
    app.add_middleware(AuthMiddleware)
```

The lines immediately surrounding for context (to make the edit unambiguous):

**Before:**
```python
    # Added first => innermost middleware (closest to the routes), matching the prior
    # @app.middleware("http") ordering.
    app.add_middleware(AuthMiddleware)
```

**After:**
```python
    # CSRFMiddleware first = innermost (between auth and routes).
    # AuthMiddleware second = outer: validates JWT before CSRF check fires.
    # Inbound flow: AuthMiddleware (401) → CSRFMiddleware (403) → route handler.
    app.add_middleware(CSRFMiddleware)
    app.add_middleware(AuthMiddleware)
```

#### Step 1.5 — Verify all 4 CSRF tests pass

```bash
cd /workspace/markethawk/backend
python -m pytest tests/api/test_csrf.py -v
```

**Expected output:**
```
tests/api/test_csrf.py::test_post_without_csrf_header_returns_403 PASSED
tests/api/test_csrf.py::test_post_with_csrf_header_passes_csrf PASSED
tests/api/test_csrf.py::test_get_without_csrf_header_passes PASSED
tests/api/test_csrf.py::test_auth_endpoint_exempt_from_csrf PASSED

4 passed in X.XXs
```

#### Step 1.6 — Confirm backend reloaded and CSRFMiddleware is live

```bash
docker-compose logs backend --tail=10
```

Confirm: no tracebacks, app reloaded successfully.

```bash
docker-compose exec backend python -c "from app.main import CSRFMiddleware; print('CSRFMiddleware module-level OK')"
```

Expected output: `CSRFMiddleware module-level OK`

#### Step 1.7 — Commit

```bash
git add backend/app/main.py backend/tests/api/test_csrf.py
git commit -m "feat(#192): add CSRFMiddleware to main.py — custom-header CSRF check"
```

---

### Task 2 — Frontend: add X-Requested-With header to axios clients

**Files**: `frontend/src/api/client.ts`

#### Step 2.1 — Confirm baseline tsc passes

```bash
cd /workspace/markethawk/frontend && npx tsc --noEmit
```

Expected: `0 errors`.

#### Step 2.2 — Add header to both axios clients

In `frontend/src/api/client.ts`, update both axios `create` calls to include the header:

**`apiClient` (lines 18–24):**

```typescript
export const apiClient = axios.create({
  baseURL: API_BASE,
  withCredentials: true,
  headers: {
    'Content-Type': 'application/json',
    'X-Requested-With': 'XMLHttpRequest',
  },
});
```

**`unversionedClient` (lines 28–34):**

```typescript
export const unversionedClient = axios.create({
  baseURL: '/api',
  withCredentials: true,
  headers: {
    'Content-Type': 'application/json',
    'X-Requested-With': 'XMLHttpRequest',
  },
});
```

The header is set globally on all methods and routes. It is harmless on GETs (CSRF middleware skips them) and means auth routes receive it naturally — no frontend-side exemption is needed.

#### Step 2.3 — Verify tsc passes

```bash
cd /workspace/markethawk/frontend && npx tsc --noEmit
```

Expected: `0 errors`.

#### Step 2.4 — Commit

```bash
git add frontend/src/api/client.ts
git commit -m "feat(#192): add X-Requested-With header to axios clients"
```
