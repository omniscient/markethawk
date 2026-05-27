# Authentication and CORS Restriction — Implementation Plan

**Issue**: [#84 — Add authentication and restrict CORS origins](https://github.com/omniscient/markethawk/issues/84)  
**Spec**: `Docs/superpowers/specs/2026-05-27-authentication-and-cors-design.md`  
**Date**: 2026-05-27  
**Branch**: `refine/issue-84-add-authentication-and-restrict-cors-ori`

## Goal

Add JWT-in-HttpOnly-cookie authentication to all 60+ API endpoints (except health, auth, and docs routes), restrict CORS to configurable origins, create a bootstrap login/register page, and eliminate the two standalone Axios instances in `alerts.ts` / `trading.ts`.

## Architecture

- **Auth flow**: `POST /api/auth/login` → sets two HttpOnly cookies (`access_token` 15-min JWT, `refresh_token` 7-day opaque token in Redis). All non-exempt requests validated by ASGI middleware before reaching the router.
- **Refresh flow**: `POST /api/auth/refresh` reads the refresh cookie, validates it in Redis, issues a new access token cookie. Frontend interceptor triggers automatically on 401.
- **Bootstrap**: `GET /api/auth/status` returns `{ bootstrapped: bool }`. Login page shows registration form when false.
- **CORS**: `CORS_ORIGINS` env var (comma-separated), defaults to `http://localhost:3333`.

## Tech Stack

Backend: FastAPI, SQLAlchemy 2.0, PostgreSQL, Redis, python-jose, passlib  
Frontend: React 18, TypeScript, Axios, React Query, React Router

## File Structure

| File | Change |
|------|--------|
| `backend/requirements.txt` | Add `python-jose[cryptography]`, `passlib[bcrypt]` |
| `backend/app/models/user.py` | New — `User` SQLAlchemy model |
| `backend/app/models/__init__.py` | Add `User` import and export |
| `backend/app/core/config.py` | Add `JWT_SECRET_KEY`, `JWT_ALGORITHM`, `ACCESS_TOKEN_EXPIRE_MINUTES`, `REFRESH_TOKEN_EXPIRE_DAYS`, fix `CORS_ORIGINS` |
| `backend/app/core/auth.py` | New — password hashing, JWT creation, `get_current_user` dependency |
| `backend/app/routers/auth.py` | New — status, register, login, logout, refresh, me |
| `backend/app/routers/__init__.py` | Export `auth_router` |
| `backend/app/main.py` | Add `auth_middleware`, include `auth_router` |
| `backend/tests/api/test_auth.py` | New — auth endpoint tests |
| `backend/tests/conftest.py` | Add `authed_client` fixture |
| `.env.example` | Document new auth and CORS variables |
| `frontend/src/api/client.ts` | Add `withCredentials: true`, 401 refresh interceptor |
| `frontend/src/api/auth.ts` | New — auth API calls (status, register, login, logout, me) |
| `frontend/src/pages/Login/index.tsx` | New — login + bootstrap registration page |
| `frontend/src/App.tsx` | Add `/login` route, `ProtectedRoute` wrapper |
| `frontend/src/api/alerts.ts` | Remove standalone `axios.create`, use `apiClient` |
| `frontend/src/api/trading.ts` | Remove standalone `axios.create`, use `apiClient` |
| `Docs/adr/0002-jwt-authentication-httponly-cookies.md` | New — architecture decision record |

---

## Task 1: Add backend dependencies and User model

**Files**: `backend/requirements.txt`, `backend/app/models/user.py`, `backend/app/models/__init__.py`

### TDD Steps

**Write failing test** — create `backend/tests/test_user_model.py`:

```python
# backend/tests/test_user_model.py
from app.models.user import User

def test_user_model_has_required_columns():
    cols = {c.key for c in User.__table__.columns}
    assert {"id", "username", "password_hash", "created_at", "is_active"} <= cols

def test_user_tablename():
    assert User.__tablename__ == "users"
```

**Verify test fails**:
```bash
cd backend && python -m pytest tests/test_user_model.py -v
# Expected: ModuleNotFoundError: No module named 'app.models.user'
```

**Implement**:

1. Add to `backend/requirements.txt` (after existing entries):
```
python-jose[cryptography]==3.3.0
passlib[bcrypt]==1.7.4
```

2. Install:
```bash
docker-compose exec backend pip install python-jose[cryptography]==3.3.0 passlib[bcrypt]==1.7.4
```

3. Create `backend/app/models/user.py`:
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
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
```

4. Update `backend/app/models/__init__.py` — add after the last import line:
```python
from app.models.user import User
```
And add `"User"` to the `__all__` list.

**Verify test passes**:
```bash
cd backend && python -m pytest tests/test_user_model.py -v
# Expected: PASSED
```

**Commit**:
```bash
git add backend/requirements.txt backend/app/models/user.py backend/app/models/__init__.py backend/tests/test_user_model.py
git commit -m "feat(auth): add User model and auth dependencies"
```

---

## Task 2: Update config.py with auth settings and configurable CORS

**Files**: `backend/app/core/config.py`

### TDD Steps

**Write failing test** — add to `backend/tests/test_config.py` (create it):

```python
# backend/tests/test_config.py
import os
import importlib

def test_cors_origins_default():
    os.environ.pop("CORS_ORIGINS", None)
    import app.core.config as cfg
    importlib.reload(cfg)
    settings = cfg.Settings()
    assert settings.CORS_ORIGINS == ["http://localhost:3333"]

def test_cors_origins_from_env():
    os.environ["CORS_ORIGINS"] = "http://localhost:3333,https://myapp.example.com"
    import app.core.config as cfg
    importlib.reload(cfg)
    settings = cfg.Settings()
    assert "https://myapp.example.com" in settings.CORS_ORIGINS
    os.environ.pop("CORS_ORIGINS", None)

def test_jwt_secret_key_field_exists():
    import app.core.config as cfg
    importlib.reload(cfg)
    settings = cfg.Settings()
    assert hasattr(settings, "JWT_SECRET_KEY")
    assert hasattr(settings, "JWT_ALGORITHM")
    assert hasattr(settings, "ACCESS_TOKEN_EXPIRE_MINUTES")
    assert hasattr(settings, "REFRESH_TOKEN_EXPIRE_DAYS")
```

**Verify test fails**:
```bash
cd backend && python -m pytest tests/test_config.py -v
# Expected: FAILED (CORS_ORIGINS is ["*"], no JWT fields)
```

**Implement** — edit `backend/app/core/config.py`:

Replace the `CORS_ORIGINS` line:
```python
    # CORS
    CORS_ORIGINS: list = ["*"]
```
with:
```python
    # CORS — comma-separated origins; defaults to frontend dev URL
    CORS_ORIGINS: list = [
        o.strip()
        for o in os.getenv("CORS_ORIGINS", "http://localhost:3333").split(",")
        if o.strip()
    ]

    # Auth
    JWT_SECRET_KEY: str = os.getenv("JWT_SECRET_KEY", "")
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "15"))
    REFRESH_TOKEN_EXPIRE_DAYS: int = int(os.getenv("REFRESH_TOKEN_EXPIRE_DAYS", "7"))
```

**Verify test passes**:
```bash
cd backend && python -m pytest tests/test_config.py -v
# Expected: 3 passed
```

**Commit**:
```bash
git add backend/app/core/config.py backend/tests/test_config.py
git commit -m "feat(auth): add JWT config fields and configurable CORS_ORIGINS"
```

---

## Task 3: Create core auth module

**Files**: `backend/app/core/auth.py`

### TDD Steps

**Write failing test** — create `backend/tests/test_auth_core.py`:

```python
# backend/tests/test_auth_core.py
import os
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-unit-tests-only-32chars!")

from app.core.auth import hash_password, verify_password, create_access_token, create_refresh_token
from jose import jwt


def test_hash_and_verify():
    hashed = hash_password("mysecret")
    assert hashed != "mysecret"
    assert verify_password("mysecret", hashed)
    assert not verify_password("wrong", hashed)


def test_create_access_token_is_valid_jwt():
    token = create_access_token("user-123")
    payload = jwt.decode(token, "test-secret-key-for-unit-tests-only-32chars!", algorithms=["HS256"])
    assert payload["sub"] == "user-123"
    assert "exp" in payload


def test_create_refresh_token_is_hex():
    token = create_refresh_token()
    assert len(token) == 64
    int(token, 16)  # raises ValueError if not hex
```

**Verify test fails**:
```bash
cd backend && python -m pytest tests/test_auth_core.py -v
# Expected: ModuleNotFoundError: No module named 'app.core.auth'
```

**Implement** — create `backend/app/core/auth.py`:

```python
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import Cookie, Depends, HTTPException, status
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session
from sqlalchemy import select

from app.core.config import get_settings
from app.core.database import get_db
from app.models.user import User

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(plain: str) -> str:
    return pwd_context.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def create_access_token(user_id: str) -> str:
    settings = get_settings()
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    return jwt.encode(
        {"sub": user_id, "exp": expire},
        settings.JWT_SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM,
    )


def create_refresh_token() -> str:
    return secrets.token_hex(32)


def get_current_user(
    access_token: str | None = Cookie(default=None),
    db: Session = Depends(get_db),
) -> User:
    if not access_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    settings = get_settings()
    try:
        payload = jwt.decode(access_token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
        user_id: str = payload.get("sub")
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    user = db.execute(select(User).where(User.id == uuid.UUID(user_id), User.is_active == True)).scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    return user
```

**Verify test passes**:
```bash
cd backend && python -m pytest tests/test_auth_core.py -v
# Expected: 3 passed
```

**Commit**:
```bash
git add backend/app/core/auth.py backend/tests/test_auth_core.py
git commit -m "feat(auth): add core auth utilities (hashing, JWT, refresh token)"
```

---

## Task 4: Run database migration for User model

**Files**: `backend/alembic/versions/<hash>_add_users_table.py` (auto-generated)

### Steps

**Generate migration**:
```bash
docker-compose exec backend python -m alembic revision --autogenerate -m "add_users_table"
# Expected output: Generating .../alembic/versions/<hash>_add_users_table.py ... done
```

**Inspect the generated file**:
```bash
grep -n "create_table\|drop_table" backend/app/alembic/versions/*users*.py
# Expected: create_table("users", ...) in upgrade, drop_table("users") in downgrade
```
Verify it contains columns `id`, `username`, `password_hash`, `created_at`, `is_active`.

**Apply migration**:
```bash
docker-compose exec backend python -m alembic upgrade head
# Expected: INFO  [alembic.runtime.migration] Running upgrade ... -> <hash>, add_users_table
```

**Verify table exists**:
```bash
docker-compose exec postgres psql -U postgres -d stockscanner -c "\d users"
# Expected: table with id (uuid), username, password_hash, created_at, is_active columns
```

**Commit**:
```bash
git add backend/app/alembic/versions/
git commit -m "feat(auth): migration — add users table"
```

---

## Task 5: Create auth router

**Files**: `backend/app/routers/auth.py`, `backend/app/routers/__init__.py`, `backend/app/main.py`

### TDD Steps

**Write failing test** — create `backend/tests/api/test_auth.py`:

```python
# backend/tests/api/test_auth.py
import os
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-unit-tests-only-32chars!")

import pytest
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_auth_status_returns_bootstrapped_false_when_no_users(db):
    response = client.get("/api/auth/status")
    assert response.status_code == 200
    assert response.json() == {"bootstrapped": False}


def test_register_creates_first_user(db):
    response = client.post(
        "/api/auth/register",
        json={"username": "admin", "password": "hunter2"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["username"] == "admin"
    assert "id" in data


def test_register_blocked_when_user_exists(db):
    client.post("/api/auth/register", json={"username": "admin", "password": "hunter2"})
    response = client.post(
        "/api/auth/register",
        json={"username": "admin2", "password": "hunter2"},
    )
    assert response.status_code == 403


def test_login_sets_cookies(db):
    client.post("/api/auth/register", json={"username": "admin", "password": "hunter2"})
    response = client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "hunter2"},
    )
    assert response.status_code == 200
    assert "access_token" in response.cookies
    assert "refresh_token" in response.cookies


def test_login_wrong_password_returns_401(db):
    client.post("/api/auth/register", json={"username": "admin", "password": "hunter2"})
    response = client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "wrongpassword"},
    )
    assert response.status_code == 401


def test_me_returns_current_user(db):
    client.post("/api/auth/register", json={"username": "admin", "password": "hunter2"})
    login_resp = client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "hunter2"},
    )
    cookies = login_resp.cookies
    response = client.get("/api/auth/me", cookies=cookies)
    assert response.status_code == 200
    assert response.json()["username"] == "admin"


def test_logout_clears_cookies(db):
    client.post("/api/auth/register", json={"username": "admin", "password": "hunter2"})
    login_resp = client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "hunter2"},
    )
    cookies = login_resp.cookies
    response = client.post("/api/auth/logout", cookies=cookies)
    assert response.status_code == 200
    assert response.cookies.get("access_token") == "" or "access_token" not in response.cookies
```

**Verify tests fail**:
```bash
cd backend && python -m pytest tests/api/test_auth.py -v
# Expected: ImportError or 404 on /api/auth/*
```

**Implement** — create `backend/app/routers/auth.py`:

```python
import uuid
from datetime import datetime, timezone

import redis
from fastapi import APIRouter, Cookie, Depends, HTTPException, Response, status
from fastapi.responses import JSONResponse
from jose import JWTError, jwt
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.auth import (
    create_access_token,
    create_refresh_token,
    get_current_user,
    hash_password,
    verify_password,
)
from app.core.config import get_settings
from app.core.database import get_db
from app.models.user import User

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _get_redis():
    settings = get_settings()
    return redis.from_url(settings.REDIS_URL, decode_responses=True)


def _set_auth_cookies(response: Response, access_token: str, refresh_token: str) -> None:
    settings = get_settings()
    is_prod = settings.ENVIRONMENT == "production"
    response.set_cookie(
        key="access_token",
        value=access_token,
        httponly=True,
        samesite="lax",
        secure=is_prod,
        max_age=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        path="/",
    )
    response.set_cookie(
        key="refresh_token",
        value=refresh_token,
        httponly=True,
        samesite="lax",
        secure=is_prod,
        max_age=settings.REFRESH_TOKEN_EXPIRE_DAYS * 86400,
        path="/api/auth/refresh",
    )


class RegisterRequest(BaseModel):
    username: str
    password: str


class LoginRequest(BaseModel):
    username: str
    password: str


class UserResponse(BaseModel):
    id: uuid.UUID
    username: str
    created_at: datetime


@router.get("/status")
def auth_status(db: Session = Depends(get_db)):
    count = db.execute(select(func.count()).select_from(User)).scalar_one()
    return {"bootstrapped": count > 0}


@router.post("/register", response_model=UserResponse)
def register(body: RegisterRequest, db: Session = Depends(get_db)):
    count = db.execute(select(func.count()).select_from(User)).scalar_one()
    if count > 0:
        raise HTTPException(status_code=403, detail="Registration is closed — a user already exists")
    user = User(username=body.username, password_hash=hash_password(body.password))
    db.add(user)
    db.commit()
    db.refresh(user)
    return UserResponse(id=user.id, username=user.username, created_at=user.created_at)


@router.post("/login")
def login(body: LoginRequest, db: Session = Depends(get_db)):
    user = db.execute(
        select(User).where(User.username == body.username, User.is_active == True)
    ).scalar_one_or_none()
    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    access_token = create_access_token(str(user.id))
    refresh_token = create_refresh_token()

    settings = get_settings()
    r = _get_redis()
    r.setex(
        f"auth:refresh:{refresh_token}",
        settings.REFRESH_TOKEN_EXPIRE_DAYS * 86400,
        str(user.id),
    )

    response = JSONResponse(content={"message": "Logged in"})
    _set_auth_cookies(response, access_token, refresh_token)
    return response


@router.post("/logout")
def logout(
    refresh_token: str | None = Cookie(default=None),
    _current_user: User = Depends(get_current_user),
):
    if refresh_token:
        r = _get_redis()
        r.delete(f"auth:refresh:{refresh_token}")

    response = JSONResponse(content={"message": "Logged out"})
    response.delete_cookie("access_token", path="/")
    response.delete_cookie("refresh_token", path="/api/auth/refresh")
    return response


@router.post("/refresh")
def refresh(refresh_token: str | None = Cookie(default=None)):
    if not refresh_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)

    r = _get_redis()
    user_id = r.get(f"auth:refresh:{refresh_token}")
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired refresh token")

    settings = get_settings()
    new_access_token = create_access_token(user_id)
    new_refresh_token = create_refresh_token()

    r.delete(f"auth:refresh:{refresh_token}")
    r.setex(
        f"auth:refresh:{new_refresh_token}",
        settings.REFRESH_TOKEN_EXPIRE_DAYS * 86400,
        user_id,
    )

    response = JSONResponse(content={"message": "Token refreshed"})
    _set_auth_cookies(response, new_access_token, new_refresh_token)
    return response


@router.get("/me", response_model=UserResponse)
def me(current_user: User = Depends(get_current_user)):
    return UserResponse(
        id=current_user.id,
        username=current_user.username,
        created_at=current_user.created_at,
    )
```

**Update `backend/app/routers/__init__.py`** — add:
```python
from app.routers.auth import router as auth_router
```
And add `"auth_router"` to `__all__`.

**Update `backend/app/main.py`** — in `create_app()`, add the import at the top of the function body and include the router. After the `from app.routers import ...` line, add `auth_router` to the import, then add:
```python
    app.include_router(auth_router)
```
before the other `app.include_router(...)` calls.

**Verify tests pass**:
```bash
cd backend && python -m pytest tests/api/test_auth.py -v
# Expected: 7 passed
```

**Commit**:
```bash
git add backend/app/routers/auth.py backend/app/routers/__init__.py backend/app/main.py backend/tests/api/test_auth.py
git commit -m "feat(auth): add auth router with register, login, logout, refresh, me endpoints"
```

---

## Task 6: Add auth middleware and update test infrastructure

**Files**: `backend/app/main.py`, `backend/tests/conftest.py`

This task adds the ASGI middleware that enforces authentication on all non-exempt paths. It also updates the test infrastructure so existing tests keep passing.

### TDD Steps

**Write failing tests** — add to `backend/tests/api/test_health.py` a test that confirms the health endpoint still works without auth, and add a new test that a protected endpoint returns 401 without a cookie:

```python
# Add to backend/tests/api/test_health.py
def test_protected_endpoint_returns_401_without_cookie():
    from fastapi.testclient import TestClient
    from app.main import app
    c = TestClient(app, raise_server_exceptions=False)
    response = c.get("/api/scanner/runs")
    assert response.status_code == 401

def test_health_is_exempt_from_auth():
    from fastapi.testclient import TestClient
    from app.main import app
    c = TestClient(app)
    response = c.get("/api/health")
    assert response.status_code == 200
```

**Verify the first test fails** (returns 200 currently):
```bash
cd backend && python -m pytest tests/api/test_health.py::test_protected_endpoint_returns_401_without_cookie -v
# Expected: FAILED (assert 200 == 401)
```

**Implement middleware** — in `backend/app/main.py`, add these imports at the top:
```python
from fastapi.responses import JSONResponse
from jose import JWTError, jwt
```

Inside `create_app()`, immediately after the `app = FastAPI(...)` constructor call (before the middleware block), add:

```python
    EXEMPT_PREFIXES = ("/api/auth/", "/api/health", "/docs", "/redoc", "/openapi.json")

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

**Update test infrastructure** — all 17 existing test files define `client = TestClient(app)` at module level and use it directly (not via fixture injection). After the middleware is added, every test that calls a protected endpoint through this module-level variable will receive 401.

The fix: add an `autouse=True` function-scoped fixture to `api/conftest.py` that injects a valid JWT cookie into the module-level `client` before each test. The auth middleware only calls `jwt.decode()` — it does not look up the user in the database — so a token with a dummy UUID subject is sufficient to pass the middleware.

**Update `backend/tests/api/conftest.py`** — replace the full contents:

```python
# backend/tests/api/conftest.py
import os
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-unit-tests-only-32chars!")

import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.core.database import get_db


@pytest.fixture(autouse=True)
def override_get_db(db):
    app.dependency_overrides[get_db] = lambda: db
    yield
    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def inject_auth_into_module_client(request):
    """Inject a valid JWT cookie into any module-level TestClient.

    Existing test files define `client = TestClient(app)` at module level.
    The auth middleware only validates jwt.decode() — no DB lookup — so any
    token signed with the test secret passes, regardless of subject UUID.
    """
    from app.core.auth import create_access_token
    module = request.module
    if hasattr(module, "client") and isinstance(module.client, TestClient):
        token = create_access_token("00000000-0000-0000-0000-000000000001")
        module.client.cookies.set("access_token", token)
```

**Verify all tests pass**:
```bash
cd backend && python -m pytest tests/api/ -v
# Expected: all tests pass including the new 401 tests
```

**Commit**:
```bash
git add backend/app/main.py backend/tests/conftest.py backend/tests/api/conftest.py
git commit -m "feat(auth): add HTTP auth middleware; update test fixtures for authenticated client"
```

---

## Task 7: Update .env.example with auth and CORS variables

**Files**: `.env.example`

### Steps

Add the following section to `.env.example` after the existing `SECRET_KEY` section:

```bash
# =============================================================================
# REQUIRED: Authentication (JWT)
# =============================================================================
# Generate with: python -c "import secrets; print(secrets.token_hex(32))"
JWT_SECRET_KEY=
ACCESS_TOKEN_EXPIRE_MINUTES=15
REFRESH_TOKEN_EXPIRE_DAYS=7

# =============================================================================
# OPTIONAL: CORS Origins
# =============================================================================
# Comma-separated list of allowed frontend origins.
# Default: http://localhost:3333
# CORS_ORIGINS=http://localhost:3333,https://your-domain.com
```

**Verify backend reloaded with new config**:
```bash
docker-compose logs backend --tail=5
# No errors about missing JWT_SECRET_KEY (it defaults to empty string)
```

**Commit**:
```bash
git add .env.example
git commit -m "docs: document JWT_SECRET_KEY, CORS_ORIGINS env vars in .env.example"
```

---

## Task 8: Update frontend API client — withCredentials and 401 interceptor

**Files**: `frontend/src/api/client.ts`

### TDD Steps

**TypeScript check before**:
```bash
cd frontend && npx tsc --noEmit
# Expected: 0 errors (baseline)
```

**Implement** — replace the content of `frontend/src/api/client.ts`:

```typescript
import axios from 'axios';

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? '/api';

export const apiClient = axios.create({
  baseURL: API_BASE,
  withCredentials: true,
  headers: {
    'Content-Type': 'application/json',
  },
});

apiClient.interceptors.response.use(
  (response) => response,
  async (error) => {
    const status = error.response?.status;
    const isNetworkError = !error.response;

    if (status === 401 && !error.config._retried && !error.config.url?.includes('/auth/refresh')) {
      error.config._retried = true;
      try {
        await apiClient.post('/auth/refresh');
        return apiClient(error.config);
      } catch {
        window.location.href = '/login';
      }
    }

    if (status >= 500 || isNetworkError || status === undefined) {
      const data = error.response?.data;
      const isJson = error.response?.headers?.['content-type']?.includes('application/json');
      window.dispatchEvent(
        new CustomEvent('server-error', {
          detail: {
            message:
              isJson && data?.message
                ? data.message
                : isNetworkError
                  ? 'Network error or server timeout. Please check your connection or dashboard status.'
                  : 'An unexpected server error occurred.',
            error_id: isJson && data?.error_id ? data.error_id : null,
            detail: isJson && data?.detail ? data.detail : null,
            stack_trace: isJson && data?.stack_trace ? data.stack_trace : null,
          },
        }),
      );
    }

    return Promise.reject(error);
  },
);
```

**TypeScript check after**:
```bash
cd frontend && npx tsc --noEmit
# Expected: 0 errors
```

**Commit**:
```bash
git add frontend/src/api/client.ts
git commit -m "feat(auth): add withCredentials and 401 auto-refresh interceptor to apiClient"
```

---

## Task 9: Create frontend auth API module

**Files**: `frontend/src/api/auth.ts` (new)

### TDD Steps

**Implement** — create `frontend/src/api/auth.ts`:

```typescript
import { apiClient } from './client';

export interface AuthStatus {
  bootstrapped: boolean;
}

export interface UserInfo {
  id: string;
  username: string;
  created_at: string;
}

export async function getAuthStatus(): Promise<AuthStatus> {
  const response = await apiClient.get<AuthStatus>('/auth/status');
  return response.data;
}

export async function register(username: string, password: string): Promise<UserInfo> {
  const response = await apiClient.post<UserInfo>('/auth/register', { username, password });
  return response.data;
}

export async function login(username: string, password: string): Promise<void> {
  await apiClient.post('/auth/login', { username, password });
}

export async function logout(): Promise<void> {
  await apiClient.post('/auth/logout');
}

export async function getMe(): Promise<UserInfo> {
  const response = await apiClient.get<UserInfo>('/auth/me');
  return response.data;
}
```

**TypeScript check**:
```bash
cd frontend && npx tsc --noEmit
# Expected: 0 errors
```

**Commit**:
```bash
git add frontend/src/api/auth.ts
git commit -m "feat(auth): add frontend auth API module"
```

---

## Task 10: Create Login page

**Files**: `frontend/src/pages/Login/index.tsx` (new)

### TDD Steps

**Implement** — create `frontend/src/pages/Login/index.tsx`:

```tsx
import React, { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { getAuthStatus, getMe, login, register } from '../../api/auth';

type Mode = 'loading' | 'login' | 'register' | 'redirecting';

export default function Login() {
  const navigate = useNavigate();
  const [mode, setMode] = useState<Mode>('loading');
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [error, setError] = useState('');
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    let cancelled = false;
    getMe()
      .then(() => { if (!cancelled) navigate('/', { replace: true }); })
      .catch(() =>
        getAuthStatus().then((s) => {
          if (!cancelled) setMode(s.bootstrapped ? 'login' : 'register');
        })
      );
    return () => { cancelled = true; };
  }, [navigate]);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError('');
    if (mode === 'register' && password !== confirmPassword) {
      setError('Passwords do not match');
      return;
    }
    setSubmitting(true);
    try {
      if (mode === 'register') {
        await register(username, password);
        await login(username, password);
      } else {
        await login(username, password);
      }
      navigate('/', { replace: true });
    } catch {
      setError(mode === 'register' ? 'Registration failed' : 'Invalid username or password');
    } finally {
      setSubmitting(false);
    }
  }

  if (mode === 'loading' || mode === 'redirecting') {
    return (
      <div className="min-h-screen bg-financial-dark flex items-center justify-center">
        <div className="text-financial-light">Loading...</div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-financial-dark flex items-center justify-center">
      <div className="w-full max-w-sm bg-financial-surface border border-financial-border rounded-lg p-8 shadow-xl">
        <h1 className="text-2xl font-bold text-financial-light mb-2">MarketHawk</h1>
        <p className="text-financial-muted text-sm mb-6">
          {mode === 'register' ? 'Create your account to get started' : 'Sign in to continue'}
        </p>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-sm text-financial-light mb-1">Username</label>
            <input
              type="text"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              required
              autoFocus
              className="w-full bg-financial-dark border border-financial-border rounded px-3 py-2 text-financial-light focus:outline-none focus:border-blue-500"
            />
          </div>
          <div>
            <label className="block text-sm text-financial-light mb-1">Password</label>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              className="w-full bg-financial-dark border border-financial-border rounded px-3 py-2 text-financial-light focus:outline-none focus:border-blue-500"
            />
          </div>
          {mode === 'register' && (
            <div>
              <label className="block text-sm text-financial-light mb-1">Confirm Password</label>
              <input
                type="password"
                value={confirmPassword}
                onChange={(e) => setConfirmPassword(e.target.value)}
                required
                className="w-full bg-financial-dark border border-financial-border rounded px-3 py-2 text-financial-light focus:outline-none focus:border-blue-500"
              />
            </div>
          )}
          {error && <p className="text-red-400 text-sm">{error}</p>}
          <button
            type="submit"
            disabled={submitting}
            className="w-full bg-blue-600 hover:bg-blue-700 disabled:opacity-50 text-white rounded py-2 font-medium transition-colors"
          >
            {submitting ? 'Please wait...' : mode === 'register' ? 'Create Account' : 'Sign In'}
          </button>
        </form>
      </div>
    </div>
  );
}
```

**TypeScript check**:
```bash
cd frontend && npx tsc --noEmit
# Expected: 0 errors
```

**Commit**:
```bash
git add frontend/src/pages/Login/index.tsx
git commit -m "feat(auth): add Login page with bootstrap-aware register/login form"
```

---

## Task 11: Update App.tsx — ProtectedRoute and /login route

**Files**: `frontend/src/App.tsx`

### TDD Steps

**TypeScript check before**:
```bash
cd frontend && npx tsc --noEmit
# Expected: 0 errors (baseline)
```

**Implement** — replace the contents of `frontend/src/App.tsx`:

```tsx
import React, { ReactNode } from 'react';
import { BrowserRouter as Router, Routes, Route, Navigate } from 'react-router-dom';
import { QueryClient, QueryClientProvider, useQuery } from '@tanstack/react-query';
import { ReactQueryDevtools } from '@tanstack/react-query-devtools';

import Layout from './components/Layout';
import Dashboard from './pages/Dashboard';
import Scanner from './pages/Scanner';
import Universes from './pages/Universes';
import Alerts from './pages/Alerts';
import Settings from './pages/Settings';
import StockDetailPage from './pages/StockDetailPage';
import Journal from './pages/Journal';
import EdgeExplorer from './pages/EdgeExplorer';
import PreMarketMovers from './pages/PreMarketMovers';
import ActiveWatchlist from './pages/ActiveWatchlist';
import AutoTrading from './pages/AutoTrading';
import ScorecardOverview from './pages/ScorecardOverview';
import ScorecardDetail from './pages/ScorecardDetail';
import Login from './pages/Login';
import { GlobalErrorToast } from './components/ui/GlobalErrorToast';
import { apiClient } from './api/client';

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 1000 * 60 * 5,
      retry: 1,
    },
  },
});

function ProtectedRoute({ children }: { children: ReactNode }) {
  const { isLoading, isError } = useQuery({
    queryKey: ['auth', 'me'],
    queryFn: () => apiClient.get('/auth/me').then((r) => r.data),
    retry: false,
  });
  if (isLoading) return <div className="min-h-screen bg-financial-dark" />;
  if (isError) return <Navigate to="/login" replace />;
  return <>{children}</>;
}

function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <Router>
        <div className="min-h-screen bg-financial-dark text-financial-light relative">
          <Routes>
            <Route path="/login" element={<Login />} />
            <Route
              path="/*"
              element={
                <ProtectedRoute>
                  <Layout>
                    <Routes>
                      <Route path="/" element={<Dashboard />} />
                      <Route path="/scanner" element={<Scanner />} />
                      <Route path="/universes" element={<Universes />} />
                      <Route path="/alerts" element={<Alerts />} />
                      <Route path="/settings" element={<Settings />} />
                      <Route path="/journal" element={<Journal />} />
                      <Route path="/edge-explorer" element={<EdgeExplorer />} />
                      <Route path="/scorecard" element={<ScorecardOverview />} />
                      <Route path="/scorecard/:scannerType" element={<ScorecardDetail />} />
                      <Route path="/movers/pre-market" element={<PreMarketMovers />} />
                      <Route path="/watchlist" element={<ActiveWatchlist />} />
                      <Route path="/trading" element={<AutoTrading />} />
                      <Route path="/stock/:ticker" element={<StockDetailPage />} />
                    </Routes>
                  </Layout>
                </ProtectedRoute>
              }
            />
          </Routes>
          <GlobalErrorToast />
        </div>
      </Router>
      <ReactQueryDevtools initialIsOpen={false} />
    </QueryClientProvider>
  );
}

export default App;
```

**TypeScript check after**:
```bash
cd frontend && npx tsc --noEmit
# Expected: 0 errors
```

**Commit**:
```bash
git add frontend/src/App.tsx
git commit -m "feat(auth): add ProtectedRoute and /login route to App.tsx"
```

---

## Task 12: Consolidate alerts.ts and trading.ts onto shared apiClient

**Files**: `frontend/src/api/alerts.ts`, `frontend/src/api/trading.ts`

### TDD Steps

**TypeScript check before**:
```bash
cd frontend && npx tsc --noEmit
# Expected: 0 errors (baseline)
```

**Critical path-prefix change**: The existing `axios.create({ baseURL: '' })` instances use full paths starting with `/api/` (e.g., `/api/alerts/stats`). The shared `apiClient` has `baseURL: '/api'`, so naively swapping the import would produce double-prefix URLs like `/api/api/alerts/stats`. All `/api` path prefixes must be stripped in both files.

**Implement `alerts.ts`**:

1. Remove the standalone Axios instance:
```typescript
// REMOVE:
import axios from 'axios';

const api = axios.create({
  baseURL: import.meta.env.VITE_API_URL || '',
});
```
Replace with:
```typescript
import { apiClient as api } from './client';
```

2. Strip `/api` prefix from every URL string in the file. The bulk-replace instruction below is authoritative — apply it to every URL, not just the examples listed:

```typescript
// Partial list of examples (not exhaustive — use bulk replace below):
api.get('/api/alerts/stats')              → api.get('/alerts/stats')
api.get('/api/alerts/rules')              → api.get('/alerts/rules')
api.post('/api/alerts/rules', ...)        → api.post('/alerts/rules', ...)
api.patch(`/api/alerts/rules/${id}`)      → api.patch(`/alerts/rules/${id}`)
api.delete(`/api/alerts/rules/${id}`)     → api.delete(`/alerts/rules/${id}`)
api.get(`/api/alerts/logs?limit=...`)     → api.get(`/alerts/logs?limit=...`)
api.get('/api/alerts/push/vapid-key')     → api.get('/alerts/push/vapid-key')
api.post('/api/alerts/push/subscribe')    → api.post('/alerts/push/subscribe')
api.delete('/api/alerts/push/unsubscribe') → api.delete('/alerts/push/unsubscribe')
```
**Bulk replace** (apply to entire file): replace all occurrences of `'/api/alerts` with `'/alerts` and `` `/api/alerts `` with `` `/alerts ``.

**Implement `trading.ts`**:

1. Same import swap:
```typescript
import { apiClient as api } from './client';
```

2. Strip `/api` prefix from every URL string in the file. The bulk-replace instruction below is authoritative — apply it to every URL, not just the examples listed:

```typescript
// Partial list of examples (not exhaustive — use bulk replace below):
api.get('/api/trading/strategies')              → api.get('/trading/strategies')
api.post('/api/trading/strategies', ...)        → api.post('/trading/strategies', ...)
api.patch(`/api/trading/strategies/${id}`)      → api.patch(`/trading/strategies/${id}`)
api.delete(`/api/trading/strategies/${id}`)     → api.delete(`/trading/strategies/${id}`)
api.get('/api/trading/orders', ...)             → api.get('/trading/orders', ...)
api.post(`/api/trading/orders/${id}/approve`)   → api.post(`/trading/orders/${id}/approve`)
api.post(`/api/trading/orders/${id}/reject`)    → api.post(`/trading/orders/${id}/reject`)
api.post(`/api/trading/orders/${id}/cancel`)    → api.post(`/trading/orders/${id}/cancel`)
api.get('/api/trading/stats', ...)              → api.get('/trading/stats', ...)
api.get('/api/trading/config')                  → api.get('/trading/config')
api.get('/api/trading/account')                 → api.get('/trading/account')
```
**Bulk replace** (apply to entire file): replace all occurrences of `'/api/trading` with `'/trading` and `` `/api/trading `` with `` `/trading ``.

**TypeScript check after**:
```bash
cd frontend && npx tsc --noEmit
# Expected: 0 errors
```

**Smoke test** — with cookies from Task 7's final validation section (logged in):
```bash
# Verify alerts endpoint still reachable (no double-prefix)
curl -sb /tmp/cookies.txt http://localhost:8000/api/alerts/rules | python -m json.tool
# Expected: 200 with rules array (not 404 or /api/api/... error)

# Verify trading endpoint still reachable
curl -sb /tmp/cookies.txt http://localhost:8000/api/trading/strategies | python -m json.tool
# Expected: 200 with strategies array
```

**Commit**:
```bash
git add frontend/src/api/alerts.ts frontend/src/api/trading.ts
git commit -m "refactor(auth): consolidate alerts.ts and trading.ts onto shared apiClient"
```

---

## Task 13: Write ADR-002

**Files**: `Docs/adr/0002-jwt-authentication-httponly-cookies.md` (new)

### Steps

Create `Docs/adr/0002-jwt-authentication-httponly-cookies.md` with the content from the spec's "Architecture / ADR-002" section verbatim (copied from spec file).

**Commit**:
```bash
git add Docs/adr/0002-jwt-authentication-httponly-cookies.md
git commit -m "docs(adr): ADR-002 — JWT authentication via HttpOnly cookies"
```

---

## Final Validation

```bash
# Backend: all tests pass
cd backend && python -m pytest tests/ -v
# Expected: all pass

# Frontend: TypeScript compiles cleanly
cd frontend && npx tsc --noEmit
# Expected: 0 errors

# Live validation: backend reloaded
docker-compose logs backend --tail=10
# Expected: no errors

# Live: health still works (exempt from auth)
curl -s http://localhost:8000/api/health | python -m json.tool
# Expected: {"status": "healthy", ...}

# Live: protected endpoint returns 401 without cookie
curl -s http://localhost:8000/api/scanner/runs | python -m json.tool
# Expected: {"detail": "Not authenticated"}

# Live: register first user
curl -s -X POST http://localhost:8000/api/auth/register \
  -H "Content-Type: application/json" \
  -d '{"username": "admin", "password": "changeme"}' | python -m json.tool
# Expected: {"id": "...", "username": "admin", ...}

# Live: login and get cookies
curl -sc /tmp/cookies.txt -X POST http://localhost:8000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username": "admin", "password": "changeme"}'
# Expected: {"message": "Logged in"} + cookies set

# Live: access protected endpoint with cookies
curl -sb /tmp/cookies.txt http://localhost:8000/api/scanner/runs | python -m json.tool
# Expected: 200 with scanner data

# Live: auth/me returns user info
curl -sb /tmp/cookies.txt http://localhost:8000/api/auth/me | python -m json.tool
# Expected: {"id": "...", "username": "admin", ...}
```
