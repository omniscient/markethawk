# Auth Brute-Force Rate Limit — Implementation Plan

**Goal**: Close the brute-force attack surface on `/api/auth/login`, `/api/auth/register`, and `/api/auth/refresh` by adding SlowAPI `@limiter.limit(AUTH_LIMIT)` decorators. All three endpoints are auth-middleware-exempt, leaving only the global 100/min default — too permissive for credential mutations.

**Architecture**: SlowAPI decorator pattern — identical to `scanner.py:81` and `auto_trading.py`. No middleware, no new model, no migration, no config change.

**Tech Stack**: FastAPI · SlowAPI · Python 3.11 · pytest

---

## File Structure

| File | Change |
|------|--------|
| `backend/app/core/rate_limits.py` | Add `AUTH_LIMIT = "5/minute"` constant |
| `backend/app/routers/auth.py` | Import `AUTH_LIMIT`, `limiter`, `Request`; apply `@limiter.limit(AUTH_LIMIT)` + `request: Request` to `login`, `register`, `refresh` |
| `backend/tests/api/test_rate_limiting.py` | Add `test_auth_rate_limit_constant()`; add `_make_auth_test_app()`, `test_auth_endpoints_rate_limited()`, `test_auth_handlers_carry_rate_limit()` |

---

## Task 1: Add `AUTH_LIMIT` constant and constant-value test

**Files**: `backend/app/core/rate_limits.py`, `backend/tests/api/test_rate_limiting.py`

### Step 1.1 — Write failing test

Add to the `# ── Task 1: constants and limiter instance ────` block in
`backend/tests/api/test_rate_limiting.py` (after the existing constant assertions):

```python
def test_auth_rate_limit_constant():
    assert AUTH_LIMIT == "5/minute"
```

Also update the top-level import to include `AUTH_LIMIT`:

```python
from app.core.rate_limits import AUTH_LIMIT, GLOBAL_LIMIT, SCANNER_LIMIT, TRADING_LIMIT, limiter
```

### Step 1.2 — Verify test fails

```bash
docker-compose exec backend pytest tests/api/test_rate_limiting.py::test_auth_rate_limit_constant -v
# Expected: ImportError — AUTH_LIMIT does not exist yet
```

### Step 1.3 — Implement: add constant

In `backend/app/core/rate_limits.py`, add `AUTH_LIMIT` after `TRADING_LIMIT`:

```python
GLOBAL_LIMIT = "100/minute"
SCANNER_LIMIT = "5/minute"
TRADING_LIMIT = "10/minute"
AUTH_LIMIT = "5/minute"
```

### Step 1.4 — Verify test passes

```bash
docker-compose exec backend pytest tests/api/test_rate_limiting.py::test_auth_rate_limit_constant -v
# Expected: PASSED
```

### Step 1.5 — Commit

```bash
git add backend/app/core/rate_limits.py backend/tests/api/test_rate_limiting.py
git commit -m "feat(#196): add AUTH_LIMIT constant to rate_limits.py"
```

---

## Task 2: Apply rate-limit decorators to auth endpoints

**Files**: `backend/app/routers/auth.py`

### Step 2.1 — Write behavioral test (add to `test_rate_limiting.py`)

Add a `_make_auth_test_app()` helper and test that mirrors `_make_test_app()` /
`test_429_response_format()` but uses a POST route (matching the auth endpoint method).
Append after the existing `test_429_response_format` block:

```python
# ── Task 2: auth endpoint rate limiting ───────────────────────────────────────


def _make_auth_test_app() -> FastAPI:
    """Minimal FastAPI app with a POST route rate-limited to 1/minute via memory:// storage."""
    auth_test_limiter = Limiter(
        key_func=get_remote_address,
        default_limits=["100/minute"],
        storage_uri="memory://",
        headers_enabled=False,
    )
    auth_test_app = FastAPI()
    auth_test_app.state.limiter = auth_test_limiter
    auth_test_app.add_middleware(SlowAPIASGIMiddleware)

    @auth_test_app.exception_handler(RateLimitExceeded)
    async def rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded):
        retry_after = exc.limit.limit.get_expiry() if exc.limit else 60
        return JSONResponse(
            status_code=429,
            headers={"Retry-After": str(retry_after)},
            content={
                "message": "Rate limit exceeded",
                "error_id": None,
                "retry_after": retry_after,
            },
        )

    @auth_test_app.post("/mock-login")
    @auth_test_limiter.limit("1/minute")
    async def mock_login(request: Request):
        return {"ok": True}

    return auth_test_app


def test_auth_endpoints_rate_limited():
    """Second POST to a rate-limited auth-like endpoint must return 429 with correct body."""
    test_app = _make_auth_test_app()
    client = TestClient(test_app, raise_server_exceptions=False)
    first = client.post("/mock-login")
    assert first.status_code == 200
    second = client.post("/mock-login")
    assert second.status_code == 429
    body = second.json()
    assert body["message"] == "Rate limit exceeded"
    assert body["error_id"] is None
    assert isinstance(body["retry_after"], int)
    assert "Retry-After" in second.headers
```

Also add a structural test (mirrors the existing `test_*_is_exempt` checks at lines 115–158) that
will **fail until** Step 2.3 applies the decorators. Append immediately after `test_auth_endpoints_rate_limited`:

```python
def test_auth_handlers_carry_rate_limit():
    """login, register, and refresh must be registered in limiter._route_limits."""
    # Importing main ensures all routers — including auth — are registered.
    from app.main import app as _  # noqa: F401
    from app.routers.auth import login, refresh, register

    for fn in (login, register, refresh):
        route_key = f"{fn.__module__}.{fn.__name__}"
        assert route_key in limiter._route_limits, (
            f"{fn.__name__} is not registered in limiter._route_limits — "
            f"@limiter.limit(AUTH_LIMIT) is missing from auth.py"
        )
```

### Step 2.2 — Verify structural test fails (behavioral test passes)

```bash
docker-compose exec backend pytest tests/api/test_rate_limiting.py::test_auth_endpoints_rate_limited tests/api/test_rate_limiting.py::test_auth_handlers_carry_rate_limit -v
# Expected:
#   test_auth_endpoints_rate_limited — PASSED  (self-contained mock app)
#   test_auth_handlers_carry_rate_limit — FAILED  (decorators not applied to auth.py yet)
```

### Step 2.3 — Implement: update `auth.py`

**Update the `fastapi` import** — add `Request` to the existing import line:

```python
from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response, status
```

**Add rate-limit imports** after the existing `app.core` imports:

```python
from app.core.rate_limits import AUTH_LIMIT, limiter
```

**Decorate `register`** — add `@limiter.limit(AUTH_LIMIT)` below `@router.post` and add
`request: Request` as the first positional parameter:

```python
@router.post("/register", response_model=UserResponse)
@limiter.limit(AUTH_LIMIT)
def register(request: Request, body: RegisterRequest, db: Session = Depends(get_db)):
    count = db.execute(select(func.count()).select_from(User)).scalar_one()
    if count > 0:
        raise HTTPException(
            status_code=403, detail="Registration is closed — a user already exists"
        )
    user = User(username=body.username, password_hash=hash_password(body.password))
    db.add(user)
    db.commit()
    db.refresh(user)
    return UserResponse(id=user.id, username=user.username, created_at=user.created_at)
```

**Decorate `login`** — add `@limiter.limit(AUTH_LIMIT)` below `@router.post` and add
`request: Request` as the first positional parameter:

```python
@router.post("/login")
@limiter.limit(AUTH_LIMIT)
def login(request: Request, body: LoginRequest, db: Session = Depends(get_db)):
    user = db.execute(
        select(User).where(User.username == body.username, User.is_active == True)
    ).scalar_one_or_none()
    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials"
        )

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
```

**Decorate `refresh`** — add `@limiter.limit(AUTH_LIMIT)` below `@router.post` and add
`request: Request` as the first positional parameter:

```python
@router.post("/refresh")
@limiter.limit(AUTH_LIMIT)
def refresh(request: Request, refresh_token: str | None = Cookie(default=None)):
    if not refresh_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)

    r = _get_redis()
    user_id = r.get(f"auth:refresh:{refresh_token}")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
        )

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
```

Note: `GET /api/auth/status`, `GET /api/auth/me`, and `POST /api/auth/logout` receive **no** decorator — they stay on the global `100/minute` default as specified.

### Step 2.4 — Confirm backend reloaded cleanly

```bash
docker-compose logs backend --tail=10
# Expected: no ImportError or startup errors; last line is "Application startup complete."
```

### Step 2.5 — Smoke test via curl

```bash
# Endpoint exists and responds (rate limit may be transparent if RATE_LIMITING_ENABLED=false in dev)
curl -s -X POST http://localhost:8000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"noone","password":"x"}' | python -m json.tool
# Expected: 401 {"detail": "Invalid credentials"} — not 422 (signature accepted) and not 500
```

### Step 2.6 — Run full backend test suite

```bash
docker-compose exec backend pytest -x -v
# Expected: all tests PASSED — catches any import-time regression from auth.py signature changes
```

### Step 2.7 — Commit

```bash
git add backend/app/routers/auth.py backend/tests/api/test_rate_limiting.py
git commit -m "feat(#196): apply AUTH_LIMIT rate-limit decorators to login, register, refresh"
```
