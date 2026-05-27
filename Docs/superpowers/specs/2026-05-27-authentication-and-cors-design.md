# Authentication and CORS Restriction — Design Spec

**Issue**: [#84 — Add authentication and restrict CORS origins](https://github.com/omniscient/markethawk/issues/84)
**Date**: 2026-05-27
**Status**: Pending Review

## Overview

All 60+ API endpoints are publicly accessible with no authentication. Combined with `CORS_ORIGINS: list = ["*"]` hardcoded in `config.py`, any website can call any endpoint if the API is network-accessible — including auto-trade submission and system configuration. This spec adds a static API key gate to every endpoint and makes CORS origins environment-configurable.

## Requirements

- Every HTTP endpoint returns `401 Unauthorized` if the `X-API-Key` header is missing or incorrect, except: `/api/health`, `/docs`, `/redoc`, `/openapi.json`.
- WebSocket endpoints authenticate via `?api_key=<value>` query parameter, rejecting with close code 1008 before `accept()` if invalid.
- The API key is set once in `.env` as `API_KEY` (server-side secret, never in JS bundle).
- The frontend prompts for the key at `/login`, stores it in `localStorage`, and attaches it to every request via an Axios interceptor.
- `401` responses redirect the user to `/login` and clear the stored key.
- CORS origins are configurable via `CORS_ORIGINS` env var (comma-separated list), defaulting to `http://localhost:3333`.
- Celery workers are unaffected — they call Python service functions directly, not over HTTP.

## Backend

### 1. `backend/app/core/config.py` — New settings fields

```python
# Auth
API_KEY: str = os.getenv("API_KEY", "")

# CORS — comma-separated list, e.g. "http://localhost:3333,https://app.example.com"
CORS_ORIGINS: list = [
    o.strip()
    for o in os.getenv("CORS_ORIGINS", "http://localhost:3333").split(",")
    if o.strip()
]
```

Remove the hardcoded `CORS_ORIGINS: list = ["*"]` on line 49.

### 2. `backend/app/core/auth.py` — New module

```python
from fastapi import Header, HTTPException, status
from app.core.config import settings

async def require_api_key(x_api_key: str = Header(...)):
    if not settings.API_KEY or x_api_key != settings.API_KEY:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")

def verify_ws_api_key(api_key: str) -> bool:
    return bool(settings.API_KEY) and api_key == settings.API_KEY
```

### 3. `backend/app/main.py` — Global dependency

Add `require_api_key` as a global dependency on app creation, with path-based exemptions:

```python
from app.core.auth import require_api_key

EXEMPT_PATHS = {"/api/health", "/docs", "/redoc", "/openapi.json"}

@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    if request.url.path in EXEMPT_PATHS or request.url.path.startswith("/docs"):
        return await call_next(request)
    api_key = request.headers.get("X-API-Key", "")
    if not settings.API_KEY or api_key != settings.API_KEY:
        return JSONResponse(status_code=401, content={"detail": "Invalid API key"})
    return await call_next(request)
```

Use HTTP middleware (not `Depends`) so WebSocket upgrade requests are handled separately and the exempt list stays in one place.

### 4. `backend/app/routers/live_data.py` — WebSocket auth

For each of the three WebSocket routes (`/ws/{ticker}/{resolution}`, `/ws/watchlist`, `/ws/scan-task/{task_id}`), add an `api_key` query parameter and validate before `accept()`:

```python
from fastapi import Query, WebSocketDisconnect, status as ws_status
from app.core.auth import verify_ws_api_key

@router.websocket("/ws/{ticker}/{resolution}")
async def ws_ticker(websocket: WebSocket, ticker: str, resolution: str, api_key: str = Query("")):
    if not verify_ws_api_key(api_key):
        await websocket.close(code=1008)
        return
    await websocket.accept()
    # ... existing logic unchanged
```

Apply the same pattern to `/ws/watchlist` and `/ws/scan-task/{task_id}`.

### 5. `.env.example` — Document new variable

```
# Authentication
# Generate with: python -c "import secrets; print(secrets.token_hex(32))"
API_KEY=

# CORS — comma-separated list of allowed frontend origins
CORS_ORIGINS=http://localhost:3333
```

## Frontend

### 1. `frontend/src/api/client.ts` — Auth interceptors

Add a request interceptor to attach the stored key, and extend the response interceptor to handle 401:

```typescript
const API_KEY_LS = 'markethawk_api_key';

// Request interceptor — attach key from localStorage
apiClient.interceptors.request.use((config) => {
  const key = localStorage.getItem(API_KEY_LS);
  if (key) config.headers['X-API-Key'] = key;
  return config;
});

// Extend existing response interceptor to handle 401
// In the error branch, before checking status >= 500:
if (status === 401) {
  localStorage.removeItem(API_KEY_LS);
  window.location.href = '/login';
  return Promise.reject(error);
}
```

### 2. `frontend/src/pages/LoginPage.tsx` — New page

A minimal single-field form:
- Label: "API Key"
- Input: `type="password"` (masks key value)
- Button: "Connect"
- On submit: write value to `localStorage.setItem('markethawk_api_key', value)`, then redirect to `/`
- If `localStorage` already contains a valid key, skip to `/` (checked on mount via a test request to `/api/health` or presence check)

Styling: follows existing dark-theme card pattern used in Settings and other pages.

### 3. `frontend/src/App.tsx` — Protected route wrapper

Add a `<ProtectedRoute>` component that checks `localStorage.getItem('markethawk_api_key')`:
- If absent, redirect to `/login`
- If present, render children

Wrap all existing routes except `/login` with `<ProtectedRoute>`.

Add the `/login` route pointing to `<LoginPage />`.

### 4. `frontend/src/api/alerts.ts` and `frontend/src/api/trading.ts` — Consolidate Axios instances

Remove the local `axios.create({ baseURL: ... })` instances from both files. Import and use `apiClient` from `@/api/client` instead. This means both files automatically inherit the auth header and 401 redirect from the central interceptors.

```typescript
// Before
import axios from 'axios';
const api = axios.create({ baseURL: import.meta.env.VITE_API_URL || '' });

// After
import { apiClient as api } from '@/api/client';
```

Update all `api.get(...)` / `api.post(...)` calls in both files — the call signatures are identical.

### 5. WebSocket connections — append api_key query param

In the frontend code that opens WebSocket connections (likely in a hook or live_data helper), append `?api_key=<value>` when constructing the WebSocket URL:

```typescript
const key = localStorage.getItem('markethawk_api_key') ?? '';
const ws = new WebSocket(`${wsBase}/api/live/ws/${ticker}/${resolution}?api_key=${encodeURIComponent(key)}`);
```

If the key is missing or wrong the server closes with code 1008 and the frontend should surface a reconnect prompt.

## Architecture / ADR-002

Write `docs/adr/ADR-002-authentication.md`:

```markdown
# ADR-002: Static API Key Authentication

**Status**: Accepted
**Date**: 2026-05-27

## Context

MarketHawk is a single-user personal trading platform. There is no User model, all data is global, and the tool runs on a personal installation. The threat model is: unauthorized access from the internet while the API port is exposed.

## Decision

Use a static API key stored in `.env` as `API_KEY`. The key is checked via HTTP middleware on every request. The frontend stores it in `localStorage` after a one-time login and attaches it as `X-API-Key` on every request.

## Consequences

- No database user tables needed
- Single shared secret — if compromised, rotate `API_KEY` in `.env` and restart
- Not suitable for multi-user scenarios (a future migration to JWT would require adding a User model)
```

## Alternatives Considered

**A — JWT with username/password login form**
Standard for SPAs. Would require a `User` model, hashed password storage (`bcrypt`), token issuance and refresh endpoints, and token expiry logic. Significant overhead for a single-user tool with no user identity concept in the data model. Rejected as over-engineered for the use case.

**B — Build-time env var (`VITE_API_KEY`)**
Key is injected at Vite build time and baked into the JS bundle. Simple but the key is readable in browser DevTools. Inconsistent with the established convention of keeping secrets server-side (`.env` holds `SECRET_KEY`, `POSTGRES_PASSWORD`, etc. — none are exposed to Vite). Rejected on security posture grounds.

**C (chosen) — Static API key, runtime login, localStorage persistence**
Balances simplicity (no user tables, no token refresh) with usability (one-time login, persisted across sessions). The key lives only on the server and in the user's own browser — consistent with the single-user threat model.

## Open Questions (non-blocking)

- Should the API key have a minimum length enforced at startup (e.g., warn if `API_KEY` is fewer than 32 characters)?
- Should `API_KEY` being unset (empty string) lock all endpoints or pass all requests? Current spec: unset means all requests are rejected (fail-closed).

## Assumptions

- `API_KEY` will be set in `.env` before the first deployment. An unset key fails closed (401 for all non-exempt requests).
- The frontend URL in development is `http://localhost:3333`. Production operators set `CORS_ORIGINS` in their environment.
- WebSocket connections that fail auth (code 1008) are expected to surface an error in the browser console; no special reconnect UI is required beyond what already exists.
- `alerts.ts` and `trading.ts` are the only two files with standalone Axios instances (confirmed by codebase search).
