# WebSocket Authentication — Implementation Plan

**Date:** 2026-06-05  
**Issue:** #191 — [arch-v2][HIGH] Authenticate WebSocket connections  
**Spec:** `docs/superpowers/specs/2026-06-05-websocket-auth-design.md`  
**Branch:** `refine/issue-191--arch-v2--high--authenticate-websocket-c`

---

## Goal

All 7 WebSocket endpoints currently bypass JWT auth because `AuthMiddleware` short-circuits on non-HTTP scopes. Add a `get_current_user_ws` FastAPI dependency to each handler that validates the `access_token` cookie and rejects unauthenticated handshakes with WS close code 1008 — before `accept()` is called.

## Architecture

- **Auth dependency** in `backend/app/core/auth.py`: mirrors `get_current_user` but raises `WebSocketException(code=1008)` instead of `HTTPException(401)`. Uses the same sync `get_db` session and DB `is_active` lookup.
- **Handler change**: each WS handler gains `_user: User = Depends(get_current_user_ws)`. FastAPI resolves this before the handler body, so `accept()` is never called on an unauthenticated connection.
- **No middleware change**: `AuthMiddleware` is untouched per the spec's AVOID constraint.
- **No migration**: no model changes.

## Tech Stack

FastAPI dependency injection · SQLAlchemy sync session · `starlette.websockets.WebSocketException` · pytest / `TestClient`

---

## File Structure

| File | Change |
|------|--------|
| `backend/app/core/auth.py` | Add `get_current_user_ws` |
| `backend/app/routers/live_data.py` | Wire dependency into 3 handlers |
| `backend/app/routers/scanner.py` | Wire dependency into 1 handler |
| `backend/app/routers/news.py` | Wire dependency into 1 handler |
| `backend/app/routers/system.py` | Wire dependency into 1 handler |
| `backend/app/routers/tweets.py` | Wire dependency into 1 handler |
| `backend/tests/test_auth_core.py` | Unit test for `get_current_user_ws` |
| `backend/tests/api/test_live_data_ws_auth.py` | NEW — integration test |
| `backend/tests/api/test_scanner_ws_auth.py` | NEW — integration test |
| `backend/tests/api/test_news_ws_auth.py` | NEW — integration test |
| `backend/tests/api/test_system_ws_auth.py` | NEW — integration test |
| `backend/tests/api/test_tweets_ws_auth.py` | NEW — integration test |

---

## Task 1 — Add `get_current_user_ws` to `auth.py`

**Files:** `backend/app/core/auth.py`, `backend/tests/test_auth_core.py`

### Step 1.1 — Write the failing unit test

Append to `backend/tests/test_auth_core.py`:

```python
import asyncio
from unittest.mock import MagicMock
from starlette.websockets import WebSocketException


def test_get_current_user_ws_raises_1008_when_no_cookie():
    """Dependency raises WebSocketException(code=1008) when no access_token cookie."""
    from app.core.auth import get_current_user_ws

    mock_ws = MagicMock()
    mock_ws.cookies = {}
    mock_db = MagicMock()

    with pytest.raises(WebSocketException) as exc_info:
        asyncio.run(get_current_user_ws(mock_ws, mock_db))
    assert exc_info.value.code == 1008


def test_get_current_user_ws_raises_1008_on_invalid_token():
    """Dependency raises WebSocketException(code=1008) when JWT is malformed."""
    from app.core.auth import get_current_user_ws

    mock_ws = MagicMock()
    mock_ws.cookies = {"access_token": "not.a.valid.jwt"}
    mock_db = MagicMock()

    with pytest.raises(WebSocketException) as exc_info:
        asyncio.run(get_current_user_ws(mock_ws, mock_db))
    assert exc_info.value.code == 1008
```

Also add `import pytest` to the imports at the top of `test_auth_core.py` (it is not currently imported).

### Step 1.2 — Verify the test fails

```bash
docker-compose exec backend bash -c "cd /app && python -m pytest tests/test_auth_core.py::test_get_current_user_ws_raises_1008_when_no_cookie -x -q 2>&1 | tail -10"
```

Expected: `ImportError: cannot import name 'get_current_user_ws'` or `AttributeError`.

### Step 1.3 — Implement `get_current_user_ws` in `auth.py`

Add the following import at the top of `backend/app/core/auth.py` (alongside existing imports):

```python
from fastapi import WebSocket
from starlette.websockets import WebSocketException
```

Append the new function after `get_current_user`:

```python
async def get_current_user_ws(
    websocket: WebSocket,
    db: Session = Depends(get_db),
) -> User:
    access_token = websocket.cookies.get("access_token")
    if not access_token:
        raise WebSocketException(code=1008)
    settings = get_settings()
    try:
        payload = jwt.decode(
            access_token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM]
        )
        user_id: str = payload.get("sub")
    except JWTError:
        raise WebSocketException(code=1008)
    user = db.execute(
        select(User).where(User.id == uuid.UUID(user_id), User.is_active == True)
    ).scalar_one_or_none()
    if not user:
        raise WebSocketException(code=1008)
    return user
```

### Step 1.4 — Verify the tests pass

```bash
docker-compose exec backend bash -c "cd /app && python -m pytest tests/test_auth_core.py -x -q 2>&1 | tail -10"
```

Expected output:
```
5 passed in 0.XXs
```

### Step 1.5 — Commit

```bash
git add backend/app/core/auth.py backend/tests/test_auth_core.py
git commit -m "feat(#191): add get_current_user_ws dependency to auth.py"
```

---

## Task 2 — Authenticate `live_data.py` handlers (3 handlers)

**Files:** `backend/tests/api/test_live_data_ws_auth.py` (NEW), `backend/app/routers/live_data.py`

### Step 2.1 — Write the failing integration test

Create `backend/tests/api/test_live_data_ws_auth.py`:

```python
import os

os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost/test")
os.environ.setdefault("POLYGON_API_KEY", "test-key-for-unit-tests-only")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-unit-tests-only-32chars!")
os.environ.setdefault("RATE_LIMITING_ENABLED", "false")

from app.core.config import get_settings

get_settings.cache_clear()

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.main import app


def test_stock_live_ws_rejects_unauthenticated(db):
    """WS connect to /api/v1/live/ws/{ticker}/{resolution} without a cookie → close 1008."""
    with TestClient(app) as client:
        with pytest.raises(WebSocketDisconnect) as exc_info:
            with client.websocket_connect("/api/v1/live/ws/AAPL/minute"):
                pass
    assert exc_info.value.code == 1008
```

### Step 2.2 — Verify the test fails

```bash
docker-compose exec backend bash -c "cd /app && python -m pytest tests/api/test_live_data_ws_auth.py -x -q 2>&1 | tail -15"
```

Expected: test enters the WS connection without error (no reject yet) — `AssertionError` or the with-block completes without raising `WebSocketDisconnect`.

### Step 2.3 — Wire dependency into `live_data.py`

**Add imports** at the top of `backend/app/routers/live_data.py` (after existing `from fastapi import ...` line):

```python
from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
```

(Replace the existing import — `Depends` is currently missing.)

Add two more imports after the existing `from app.core.metrics import ...` line:

```python
from app.core.auth import get_current_user_ws
from app.models.user import User
```

**Add the dependency parameter** to each of the three handlers:

Handler 1 — `stock_live_websocket` (line ~20):
```python
async def stock_live_websocket(
    websocket: WebSocket,
    ticker: str,
    resolution: str,
    _user: User = Depends(get_current_user_ws),
):
```

Handler 2 — `watchlist_live_websocket` (line ~71):
```python
async def watchlist_live_websocket(
    websocket: WebSocket,
    _user: User = Depends(get_current_user_ws),
):
```

Handler 3 — `scan_task_websocket` (line ~109):
```python
async def scan_task_websocket(
    websocket: WebSocket,
    task_id: str,
    _user: User = Depends(get_current_user_ws),
):
```

### Step 2.4 — Verify the test passes

```bash
docker-compose exec backend bash -c "cd /app && python -m pytest tests/api/test_live_data_ws_auth.py -x -q 2>&1 | tail -10"
```

Expected:
```
1 passed in X.XXs
```

### Step 2.5 — Commit

```bash
git add backend/app/routers/live_data.py backend/tests/api/test_live_data_ws_auth.py
git commit -m "feat(#191): authenticate live_data WebSocket handlers"
```

---

## Task 3 — Authenticate `scanner.py` handler

**Files:** `backend/tests/api/test_scanner_ws_auth.py` (NEW), `backend/app/routers/scanner.py`

### Step 3.1 — Write the failing test

Create `backend/tests/api/test_scanner_ws_auth.py`:

```python
import os

os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost/test")
os.environ.setdefault("POLYGON_API_KEY", "test-key-for-unit-tests-only")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-unit-tests-only-32chars!")
os.environ.setdefault("RATE_LIMITING_ENABLED", "false")

from app.core.config import get_settings

get_settings.cache_clear()

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.main import app


def test_scan_run_ws_rejects_unauthenticated(db):
    """WS connect to /api/v1/scanner/ws/runs/{task_id} without a cookie → close 1008."""
    with TestClient(app) as client:
        with pytest.raises(WebSocketDisconnect) as exc_info:
            with client.websocket_connect("/api/v1/scanner/ws/runs/test-task-id"):
                pass
    assert exc_info.value.code == 1008
```

### Step 3.2 — Verify the test fails

```bash
docker-compose exec backend bash -c "cd /app && python -m pytest tests/api/test_scanner_ws_auth.py -x -q 2>&1 | tail -15"
```

Expected: test does not raise `WebSocketDisconnect` or raises with wrong code.

### Step 3.3 — Wire dependency into `scanner.py`

**Add imports** after the existing `from app.models.signal_review import SignalReview` line:

```python
from app.core.auth import get_current_user_ws
from app.models.user import User
```

**Add the dependency parameter** to `scan_run_websocket` (line ~249):

```python
async def scan_run_websocket(
    websocket: WebSocket,
    task_id: str,
    _user: User = Depends(get_current_user_ws),
):
```

(`Depends` is already imported in scanner.py.)

### Step 3.4 — Verify the test passes

```bash
docker-compose exec backend bash -c "cd /app && python -m pytest tests/api/test_scanner_ws_auth.py -x -q 2>&1 | tail -10"
```

Expected:
```
1 passed in X.XXs
```

### Step 3.5 — Commit

```bash
git add backend/app/routers/scanner.py backend/tests/api/test_scanner_ws_auth.py
git commit -m "feat(#191): authenticate scanner WebSocket handler"
```

---

## Task 4 — Authenticate `news.py` handler

**Files:** `backend/tests/api/test_news_ws_auth.py` (NEW), `backend/app/routers/news.py`

### Step 4.1 — Write the failing test

Create `backend/tests/api/test_news_ws_auth.py`:

```python
import os

os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost/test")
os.environ.setdefault("POLYGON_API_KEY", "test-key-for-unit-tests-only")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-unit-tests-only-32chars!")
os.environ.setdefault("RATE_LIMITING_ENABLED", "false")

from app.core.config import get_settings

get_settings.cache_clear()

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.main import app


def test_news_ws_rejects_unauthenticated(db):
    """WS connect to /api/v1/news/ws without a cookie → close 1008."""
    with TestClient(app) as client:
        with pytest.raises(WebSocketDisconnect) as exc_info:
            with client.websocket_connect("/api/v1/news/ws"):
                pass
    assert exc_info.value.code == 1008
```

### Step 4.2 — Verify the test fails

```bash
docker-compose exec backend bash -c "cd /app && python -m pytest tests/api/test_news_ws_auth.py -x -q 2>&1 | tail -15"
```

### Step 4.3 — Wire dependency into `news.py`

The `news.py` router uses a two-section import layout with `# noqa: E402` annotations for the WS section. Add the auth imports to the `noqa` section (after the existing `from app.core.rate_limits import limiter  # noqa: E402` line):

```python
from app.core.auth import get_current_user_ws  # noqa: E402
from app.models.user import User  # noqa: E402
```

Also add `Depends` to the WS-section import of fastapi. Change:

```python
from fastapi import WebSocket, WebSocketDisconnect  # noqa: E402
```

to:

```python
from fastapi import Depends, WebSocket, WebSocketDisconnect  # noqa: E402
```

**Add the dependency parameter** to `news_websocket`:

```python
@router.websocket("/ws")
@limiter.exempt
async def news_websocket(
    websocket: WebSocket,
    _user: User = Depends(get_current_user_ws),
):
    await websocket.accept()
    ...
```

### Step 4.4 — Verify the test passes

```bash
docker-compose exec backend bash -c "cd /app && python -m pytest tests/api/test_news_ws_auth.py -x -q 2>&1 | tail -10"
```

Expected:
```
1 passed in X.XXs
```

### Step 4.5 — Commit

```bash
git add backend/app/routers/news.py backend/tests/api/test_news_ws_auth.py
git commit -m "feat(#191): authenticate news WebSocket handler"
```

---

## Task 5 — Authenticate `system.py` handler

**Files:** `backend/tests/api/test_system_ws_auth.py` (NEW), `backend/app/routers/system.py`

### Step 5.1 — Write the failing test

Create `backend/tests/api/test_system_ws_auth.py`:

```python
import os

os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost/test")
os.environ.setdefault("POLYGON_API_KEY", "test-key-for-unit-tests-only")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-unit-tests-only-32chars!")
os.environ.setdefault("RATE_LIMITING_ENABLED", "false")

from app.core.config import get_settings

get_settings.cache_clear()

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.main import app


def test_system_tasks_ws_rejects_unauthenticated(db):
    """WS connect to /api/v1/system/ws/tasks without a cookie → close 1008."""
    with TestClient(app) as client:
        with pytest.raises(WebSocketDisconnect) as exc_info:
            with client.websocket_connect("/api/v1/system/ws/tasks"):
                pass
    assert exc_info.value.code == 1008
```

### Step 5.2 — Verify the test fails

```bash
docker-compose exec backend bash -c "cd /app && python -m pytest tests/api/test_system_ws_auth.py -x -q 2>&1 | tail -15"
```

### Step 5.3 — Wire dependency into `system.py`

**Add imports** after the existing `from app.services.system_service import SystemService` line:

```python
from app.core.auth import get_current_user_ws
from app.models.user import User
```

(`Depends` is already imported in system.py.)

**Add the dependency parameter** to `system_tasks_websocket` (line ~109):

```python
@router.websocket("/ws/tasks")
@limiter.exempt
async def system_tasks_websocket(
    websocket: WebSocket,
    _user: User = Depends(get_current_user_ws),
):
```

### Step 5.4 — Verify the test passes

```bash
docker-compose exec backend bash -c "cd /app && python -m pytest tests/api/test_system_ws_auth.py -x -q 2>&1 | tail -10"
```

Expected:
```
1 passed in X.XXs
```

### Step 5.5 — Commit

```bash
git add backend/app/routers/system.py backend/tests/api/test_system_ws_auth.py
git commit -m "feat(#191): authenticate system WebSocket handler"
```

---

## Task 6 — Authenticate `tweets.py` handler

**Files:** `backend/tests/api/test_tweets_ws_auth.py` (NEW), `backend/app/routers/tweets.py`

### Step 6.1 — Write the failing test

Create `backend/tests/api/test_tweets_ws_auth.py`:

```python
import os

os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost/test")
os.environ.setdefault("POLYGON_API_KEY", "test-key-for-unit-tests-only")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-unit-tests-only-32chars!")
os.environ.setdefault("RATE_LIMITING_ENABLED", "false")

from app.core.config import get_settings

get_settings.cache_clear()

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.main import app


def test_tweet_feed_ws_rejects_unauthenticated(db):
    """WS connect to /api/v1/tweets/feed without a cookie → close 1008."""
    with TestClient(app) as client:
        with pytest.raises(WebSocketDisconnect) as exc_info:
            with client.websocket_connect("/api/v1/tweets/feed"):
                pass
    assert exc_info.value.code == 1008
```

### Step 6.2 — Verify the test fails

```bash
docker-compose exec backend bash -c "cd /app && python -m pytest tests/api/test_tweets_ws_auth.py -x -q 2>&1 | tail -15"
```

### Step 6.3 — Wire dependency into `tweets.py`

**Add imports** after the existing `from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect` line, change it to include `Depends`:

```python
from fastapi import APIRouter, Depends, Query, WebSocket, WebSocketDisconnect
```

Add auth imports after the existing model imports:

```python
from app.core.auth import get_current_user_ws
from app.models.user import User
```

**Add the dependency parameter** to `tweet_feed_websocket`:

```python
@router.websocket("/feed")
@limiter.exempt
async def tweet_feed_websocket(
    websocket: WebSocket,
    _user: User = Depends(get_current_user_ws),
):
    """WebSocket: streams real-time tweet signals from Redis channel tweet_signals:all."""
    await websocket.accept()
    ...
```

### Step 6.4 — Verify the test passes

```bash
docker-compose exec backend bash -c "cd /app && python -m pytest tests/api/test_tweets_ws_auth.py -x -q 2>&1 | tail -10"
```

Expected:
```
1 passed in X.XXs
```

### Step 6.5 — Commit

```bash
git add backend/app/routers/tweets.py backend/tests/api/test_tweets_ws_auth.py
git commit -m "feat(#191): authenticate tweets WebSocket handler"
```

---

## Task 7 — Full-suite validation

**Files:** none (validation only)

### Step 7.1 — Confirm backend reloaded

```bash
docker-compose logs backend --tail=10
```

Expected: no `ImportError` or `SyntaxError`; the last line shows `Application startup complete`.

### Step 7.2 — Run all new tests together

```bash
docker-compose exec backend bash -c "cd /app && python -m pytest tests/test_auth_core.py tests/api/test_live_data_ws_auth.py tests/api/test_scanner_ws_auth.py tests/api/test_news_ws_auth.py tests/api/test_system_ws_auth.py tests/api/test_tweets_ws_auth.py -v 2>&1 | tail -20"
```

Expected output (7 tests):
```
tests/test_auth_core.py::test_get_current_user_ws_raises_1008_when_no_cookie PASSED
tests/test_auth_core.py::test_get_current_user_ws_raises_1008_on_invalid_token PASSED
tests/api/test_live_data_ws_auth.py::test_stock_live_ws_rejects_unauthenticated PASSED
tests/api/test_scanner_ws_auth.py::test_scan_run_ws_rejects_unauthenticated PASSED
tests/api/test_news_ws_auth.py::test_news_ws_rejects_unauthenticated PASSED
tests/api/test_system_ws_auth.py::test_system_tasks_ws_rejects_unauthenticated PASSED
tests/api/test_tweets_ws_auth.py::test_tweet_feed_ws_rejects_unauthenticated PASSED
7 passed
```

### Step 7.3 — Confirm no regressions

```bash
docker-compose exec backend bash -c "cd /app && python -m pytest tests/ -x -q --ignore=tests/test_auth_core.py --ignore=tests/api/test_live_data_ws_auth.py --ignore=tests/api/test_scanner_ws_auth.py --ignore=tests/api/test_news_ws_auth.py --ignore=tests/api/test_system_ws_auth.py --ignore=tests/api/test_tweets_ws_auth.py 2>&1 | tail -5"
```

Expected: existing test suite passes without new failures (skipped tests remain skipped).

---

## Summary

| Task | Files touched | New tests |
|------|--------------|-----------|
| 1 — Add `get_current_user_ws` | `core/auth.py`, `test_auth_core.py` | 2 unit tests |
| 2 — live_data.py | `routers/live_data.py`, `test_live_data_ws_auth.py` | 1 integration test |
| 3 — scanner.py | `routers/scanner.py`, `test_scanner_ws_auth.py` | 1 integration test |
| 4 — news.py | `routers/news.py`, `test_news_ws_auth.py` | 1 integration test |
| 5 — system.py | `routers/system.py`, `test_system_ws_auth.py` | 1 integration test |
| 6 — tweets.py | `routers/tweets.py`, `test_tweets_ws_auth.py` | 1 integration test |
| 7 — Validate | — | — |

**Total:** 7 tasks · 28 steps · 7 new tests · 0 migrations
