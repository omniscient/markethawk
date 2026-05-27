# Authentication and CORS Restriction — Design Spec

**Issue**: [#84 — Add authentication and restrict CORS origins](https://github.com/omniscient/markethawk/issues/84)
**Date**: 2026-05-27
**Status**: Pending Review (v2 — revised after feedback)

## Overview

All 60+ API endpoints are publicly accessible with no authentication. Combined with `CORS_ORIGINS: list = ["*"]` hardcoded in `config.py`, any website can call any endpoint if the API is network-accessible — including auto-trade submission and system configuration.

The initial spec proposed a static API key stored in `localStorage`. This was rejected: storing any secret in `localStorage` is vulnerable to XSS — any script running on the page can read it. This revised spec adopts the industry-standard approach for single-page applications: **JWT tokens in HttpOnly cookies**, paired with a `User` model that makes multi-user extension trivial without needing a rewrite.

## Requirements

- Every HTTP endpoint returns `401 Unauthorized` if the access token cookie is missing, expired, or invalid, except: `/api/health`, `/api/auth/*`, `/docs`, `/redoc`, `/openapi.json`.
- WebSocket upgrade requests are validated by the same HTTP middleware (Starlette middleware sees all ASGI requests, including WS upgrades). If the access token is expired at connection time, the client refreshes and reconnects.
- Auth uses two HttpOnly cookies: a short-lived **access token** (15 min JWT) and a long-lived **refresh token** (7-day opaque token stored in Redis for revocation).
- No secret is ever stored in `localStorage` or readable by JavaScript.
- A `User` model (`id`, `username`, `password_hash`, `created_at`, `is_active`) is added. Single user initially; multi-user is additive (add rows, add `user_id` FKs to data models as needed).
- First user is created via a **bootstrap endpoint** (`POST /api/auth/register`) that only accepts requests when the `users` table is empty. The login page calls `GET /api/auth/status` on mount and auto-shows a "Create account" form if `{ bootstrapped: false }`.
- CORS origins are configurable via `CORS_ORIGINS` env var (comma-separated), defaulting to `http://localhost:3333`. `allow_credentials=True` remains (already set).
- Celery workers call Python service functions directly and are unaffected by HTTP middleware.
- `alerts.ts` and `trading.ts` standalone Axios instances are consolidated onto the shared `apiClient`.

## Backend

### 1. `requirements.txt` — New packages

```
python-jose[cryptography]   # JWT encoding/decoding
passlib[bcrypt]             # Password hashing
```

### 2. `backend/app/models/user.py` — New model

```python
import uuid
from datetime import datetime, timezone
from sqlalchemy import Boolean, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base

class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(256), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
```

Add to `backend/app/models/__init__.py` and run `alembic revision --autogenerate`.

### 3. `backend/app/core/auth.py` — New module

```python
from datetime import datetime, timedelta, timezone
import secrets
import uuid

from fastapi import Cookie, HTTPException, status
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.config import get_settings
from app.models.user import User

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def hash_password(plain: str) -> str:
    return pwd_context.hash(plain)

def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)

def create_access_token(user_id: str) -> str:
    settings = get_settings()
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    return jwt.encode({"sub": user_id, "exp": expire}, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)

def create_refresh_token() -> str:
    return secrets.token_hex(32)  # opaque, stored in Redis

async def get_current_user(
    access_token: str | None = Cookie(default=None),
    db: AsyncSession = ...,
) -> User:
    if not access_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    settings = get_settings()
    try:
        payload = jwt.decode(access_token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
        user_id: str = payload.get("sub")
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    result = await db.execute(select(User).where(User.id == uuid.UUID(user_id), User.is_active == True))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    return user
```

### 4. `backend/app/core/config.py` — New settings fields

```python
# Auth
JWT_SECRET_KEY: str = ""          # Required — generate: python -c "import secrets; print(secrets.token_hex(32))"
JWT_ALGORITHM: str = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
REFRESH_TOKEN_EXPIRE_DAYS: int = 7

# CORS
CORS_ORIGINS: list = [
    o.strip()
    for o in os.getenv("CORS_ORIGINS", "http://localhost:3333").split(",")
    if o.strip()
]
```

Remove the hardcoded `CORS_ORIGINS: list = ["*"]`.

### 5. `backend/app/routers/auth.py` — New router

| Method | Path | Auth required | Purpose |
|--------|------|---------------|---------|
| `GET` | `/api/auth/status` | No | `{ bootstrapped: bool }` — is at least one user registered? |
| `POST` | `/api/auth/register` | No (only when 0 users exist) | Create first admin user. Returns 403 if any user already exists. |
| `POST` | `/api/auth/login` | No | Validate credentials; set `access_token` + `refresh_token` HttpOnly cookies. |
| `POST` | `/api/auth/logout` | Yes | Delete refresh token from Redis; clear both cookies. |
| `POST` | `/api/auth/refresh` | No (reads refresh cookie) | Validate refresh token from Redis; issue new access token cookie. |
| `GET` | `/api/auth/me` | Yes | Return current user info (`id`, `username`, `created_at`). |

**Cookie spec** (set on login and refresh):

```python
response.set_cookie(
    key="access_token",
    value=access_token,
    httponly=True,
    samesite="lax",
    secure=settings.ENVIRONMENT == "production",
    max_age=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    path="/",
)
response.set_cookie(
    key="refresh_token",
    value=refresh_token,
    httponly=True,
    samesite="lax",
    secure=settings.ENVIRONMENT == "production",
    max_age=settings.REFRESH_TOKEN_EXPIRE_DAYS * 86400,
    path="/api/auth/refresh",  # sent only to the refresh endpoint
)
```

**Refresh token in Redis**: stored as `auth:refresh:{token}` → `user_id`, TTL matching `REFRESH_TOKEN_EXPIRE_DAYS`. Logout deletes the key.

### 6. `backend/app/main.py` — Auth middleware

Add an HTTP middleware that validates the access token cookie on all non-exempt paths:

```python
EXEMPT_PREFIXES = {"/api/auth/", "/api/health", "/docs", "/redoc", "/openapi.json"}

@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    path = request.url.path
    if any(path.startswith(p) for p in EXEMPT_PREFIXES):
        return await call_next(request)
    token = request.cookies.get("access_token")
    if not token:
        return JSONResponse(status_code=401, content={"detail": "Not authenticated"})
    settings = get_settings()
    try:
        jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
    except JWTError:
        return JSONResponse(status_code=401, content={"detail": "Token expired or invalid"})
    return await call_next(request)
```

This middleware runs on WebSocket upgrade requests too (Starlette middleware is ASGI-level). An expired access token on WS upgrade returns 401 before the connection is accepted, prompting the frontend to refresh and reconnect.

### 7. `.env.example` — Document new variables

```
# Auth — generate JWT_SECRET_KEY with: python -c "import secrets; print(secrets.token_hex(32))"
JWT_SECRET_KEY=
ACCESS_TOKEN_EXPIRE_MINUTES=15
REFRESH_TOKEN_EXPIRE_DAYS=7

# CORS — comma-separated list of allowed frontend origins
CORS_ORIGINS=http://localhost:3333
```

## Frontend

### 1. `frontend/src/api/client.ts` — Cookie-based auth

Set `withCredentials: true` so the browser sends HttpOnly cookies with cross-origin requests to the backend (`localhost:3333` → `localhost:8000` are different origins but same-site, so `SameSite=Lax` cookies are included):

```typescript
const apiClient = axios.create({
  baseURL: import.meta.env.VITE_API_TARGET || '',
  withCredentials: true,   // send cookies cross-origin (same-site)
});
```

Remove any `X-API-Key` interceptor logic. Extend the response interceptor to handle `401`:

```typescript
apiClient.interceptors.response.use(
  (response) => response,
  async (error) => {
    const status = error.response?.status;
    if (status === 401 && !error.config._retried && !error.config.url?.includes('/auth/refresh')) {
      error.config._retried = true;
      try {
        await apiClient.post('/api/auth/refresh');
        return apiClient(error.config);   // retry original request
      } catch {
        window.location.href = '/login';
      }
    }
    if (status >= 500) {
      window.dispatchEvent(new CustomEvent('server-error', { detail: error.response?.data }));
    }
    return Promise.reject(error);
  }
);
```

### 2. `frontend/src/pages/Login/index.tsx` — New page

On mount, calls `GET /api/auth/status`:
- `{ bootstrapped: false }` → renders a "Create account" form (username, password, confirm password) calling `POST /api/auth/register`
- `{ bootstrapped: true }` → renders a standard login form (username, password) calling `POST /api/auth/login`

On success (either), redirects to `/`. Follows the existing dark-theme card pattern used in Settings.

If already authenticated (page loads and `/api/auth/me` responds 200), skip to `/`.

### 3. `frontend/src/App.tsx` — Protected route wrapper

```typescript
function ProtectedRoute({ children }: { children: ReactNode }) {
  const { data, isLoading, isError } = useQuery({
    queryKey: ['auth', 'me'],
    queryFn: () => apiClient.get('/api/auth/me').then(r => r.data),
    retry: false,
  });
  if (isLoading) return <LoadingSpinner />;
  if (isError) return <Navigate to="/login" replace />;
  return <>{children}</>;
}
```

Add `/login` route; wrap all existing routes with `<ProtectedRoute>`.

### 4. `frontend/src/api/alerts.ts` and `frontend/src/api/trading.ts` — Consolidate

Remove the local `axios.create(...)` instances. Import and use `apiClient` from `@/api/client`. Both files inherit `withCredentials: true` and the 401/refresh interceptor automatically.

### 5. WebSocket connections

No URL changes needed. The browser automatically includes `SameSite=Lax` HttpOnly cookies in WebSocket upgrade requests to same-site origins. The access token is validated by the HTTP middleware before the connection is accepted.

If the access token is expired at WS connection time, the server returns 401 before accepting. The existing WS reconnect hooks should detect the close/error and trigger a refresh via the HTTP client before reconnecting. If refresh succeeds, the next WS connect attempt will carry a valid cookie.

## Architecture / ADR-002

Write `docs/adr/ADR-002-authentication.md`:

```markdown
# ADR-002: JWT Authentication via HttpOnly Cookies

**Status**: Accepted
**Date**: 2026-05-27

## Context

MarketHawk exposes 60+ API endpoints including auto-trade submission and system configuration with no authentication. An initial design proposed a static API key stored in the browser's `localStorage`. This was rejected: `localStorage` is readable by any JavaScript on the page, making it vulnerable to XSS attacks.

## Decision

Use JWT tokens stored in **HttpOnly cookies**:
- Access token (15-min JWT, stateless validation) — sent on every request by the browser automatically
- Refresh token (7-day opaque token, stored in Redis for revocation) — sent only to /api/auth/refresh

A `User` model (id, username, password_hash) is added to the database. The first user is created via a bootstrap endpoint that rejects registration once any user exists.

## Why Not the Alternatives

| Option | Rejection reason |
|--------|-----------------|
| API key in `localStorage` | XSS-readable; provides no path to multi-user |
| Session-based auth (Redis sessions) | Stateful; adds Redis session management complexity without benefit over stateless JWT at this scale |
| OAuth2 / external provider | External service dependency; over-engineered for a self-hosted personal tool |

## Consequences

- No secrets stored in `localStorage` or readable by JavaScript
- `User` model lays the foundation for multi-user: per-user data isolation is additive (add `user_id` FK to target tables)
- Refresh token revocation (logout) works immediately via Redis key deletion
- `SameSite=Lax` prevents CSRF from third-party origins without requiring a CSRF token
```

## Alternatives Considered

**A — Static API key in localStorage (previous spec)**
Rejected by owner: "pretty poor imo. Might as well keep it like this if we're going to store a secret in localstorage." `localStorage` is readable by JavaScript, making secrets stored there vulnerable to XSS. Additionally, this approach provides no path to multi-user.

**B — JWT in HttpOnly cookies (chosen)**
HttpOnly cookies are invisible to JavaScript (XSS-safe). `SameSite=Lax` protects against CSRF for non-GET cross-site requests. Short-lived access tokens (15 min) limit exposure; long-lived refresh tokens (7 days) allow transparent renewal. The `User` model makes multi-user extension additive rather than a rewrite. No external service dependency.

**C — Session-based auth with Redis sessions**
Identical security posture to B but server-stateful. Each request requires a Redis lookup for session data. Adds session lifecycle management code. Redis is already present (used for Celery) but adding session management is unnecessary complexity when stateless JWT achieves the same result. Rejected.

**D — OAuth2 via external provider**
Appropriate for SaaS multi-user applications. Requires external service dependency, making the self-hosted tool dependent on third-party availability. Over-engineered. Rejected.

## Open Questions (non-blocking)

- Should the `User` model include an `email` field for future password-reset flows?
- Should failed login attempts be rate-limited (e.g., 5 attempts before a 1-minute lockout)?
- When a WebSocket client's access token expires mid-session, should the server proactively close the connection (e.g., every 15 min) or leave the established session open indefinitely?

## Assumptions

- `JWT_SECRET_KEY` will be set in `.env` before first deployment. An unset key causes `jwt.decode` to raise on every request → all non-exempt endpoints return 401 (fail-closed).
- `localhost:3333` (frontend) and `localhost:8000` (backend) share the same registrable domain (`localhost`), so `SameSite=Lax` cookies set by the backend are included in cross-origin requests from the frontend. In production, a reverse proxy (nginx) should serve both under the same domain, making this a non-issue.
- `alerts.ts` and `trading.ts` are the only two files with standalone Axios instances outside `client.ts`.
- The initial deployment has zero users; the bootstrap endpoint creates the first admin. If the database is reset, the bootstrap endpoint re-opens automatically.
