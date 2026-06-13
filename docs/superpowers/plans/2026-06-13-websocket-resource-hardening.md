# WebSocket Resource Exhaustion Hardening — Implementation Plan

**Date:** 2026-06-13
**Issue:** #377
**Epic:** #372 (Defensive Security Review 2026-06-12)
**Spec:** `docs/superpowers/specs/2026-06-13-websocket-resource-exhaustion-design.md`
**Branch:** `refine/issue-377--security--f-ws-01--websocket-resource-e`

---

## Goal

Harden all five WebSocket endpoints across three routers against resource exhaustion:
per-user and global connection caps enforced before `accept()`, shared Redis fan-out
for the two high-traffic live-data endpoints, server-side idle and lifetime timeouts,
and `Origin` header validation before connection acceptance.

## Architecture

All guards are implemented as FastAPI dependencies or async context managers, run
before `websocket.accept()`, following the established `ws_get_current_user` pattern.
No ASGI middleware is introduced — consistent with the `[AVOID]` architectural decision
in `.archon/memory/architecture.md` and the `[PATTERN]` in `backend-patterns.md`
documenting that `AuthMiddleware`, `CSRFMiddleware`, and `PrometheusMiddleware` all
explicitly skip `scope["type"] == "websocket"`.

In-process counters (not Redis) are used for connection caps. The backend runs as a
single process in the current Docker Compose deployment; in-memory integers are cheaper
and correct. If the stack ever scales horizontally, migrate counters to Redis
`INCR`/`DECR`.

```
app/core/
  config.py             ← 5 new WS_* settings
  ws_limits.py          ← in-process connection counter (new module)
  auth.py               ← verify_ws_origin dependency added
app/services/
  websocket_manager.py  ← fan-out register/unregister/_fan_out added
app/routers/
  live_data.py          ← 3 handlers hardened
  news.py               ← 1 handler hardened
  tweets.py             ← 1 handler hardened
backend/tests/
  conftest.py                              ← WS setting setdefaults
  core/test_ws_limits.py                  ← new
  api/test_ws_guards.py                   ← new
  services/test_websocket_manager.py      ← new
```

## Tech Stack

- FastAPI `WebSocketException`, `Depends` for dependency injection
- `asynccontextmanager` + `collections.defaultdict` for in-process counters
- `asyncio.Queue(maxsize=100)` for per-subscriber fan-out buffers
- `time.monotonic()` for idle/lifetime timeout tracking

---

## File Structure

| File | Change | Notes |
|---|---|---|
| `backend/app/core/config.py` | Add 5 `WS_*` fields | No validators needed |
| `backend/tests/conftest.py` | Add 5 `os.environ.setdefault` | Per spec requirement |
| `backend/app/core/ws_limits.py` | New module | `ws_connection_slot` context manager |
| `backend/app/core/auth.py` | Add function | `verify_ws_origin` |
| `backend/app/services/websocket_manager.py` | Add 3 methods + imports | Fan-out registry |
| `backend/app/routers/live_data.py` | Update 3 handlers | Guards + timeouts + fan-out (ticker/watchlist) |
| `backend/app/routers/news.py` | Update 1 handler | Guards + timeout |
| `backend/app/routers/tweets.py` | Update 1 handler | Guards + timeout |
| `backend/tests/core/test_ws_limits.py` | New file | Counter unit tests |
| `backend/tests/api/test_ws_guards.py` | New file | Origin + cap integration tests |
| `backend/tests/services/test_websocket_manager.py` | New file | Fan-out unit tests |

---

## Tasks

### Task 1: WS config settings + conftest defaults

**Files:**
- `backend/app/core/config.py`
- `backend/tests/conftest.py`
- `backend/tests/core/test_config.py` (add test)

#### Step 1.1 — Write failing test

Add to `backend/tests/core/test_config.py` (existing file):

```python
def test_ws_settings_have_correct_defaults():
    from app.core.config import get_settings, Settings
    get_settings.cache_clear()
    s = Settings(
        DATABASE_URL="postgresql://test:test@localhost/test",
        POLYGON_API_KEY="test-key",
        JWT_SECRET_KEY="test-jwt-secret-key-for-unit-tests-only-aaa",
    )
    assert s.WS_MAX_CONNECTIONS_PER_USER == 10
    assert s.WS_MAX_CONNECTIONS_GLOBAL == 100
    assert s.WS_IDLE_TIMEOUT_SECONDS == 300
    assert s.WS_SCAN_TASK_IDLE_TIMEOUT_SECONDS == 1800
    assert s.WS_MAX_LIFETIME_SECONDS == 28800
    get_settings.cache_clear()
```

#### Step 1.2 — Verify test fails

```bash
docker-compose exec -T backend python -m pytest backend/tests/core/test_config.py::test_ws_settings_have_correct_defaults -x 2>&1 | tail -10
```

Expected: `AttributeError: 'Settings' object has no attribute 'WS_MAX_CONNECTIONS_PER_USER'`

#### Step 1.3 — Add settings to config.py

In `backend/app/core/config.py`, after the `VAPID_CLAIMS_EMAIL` line and before the `@field_validator("DATABASE_URL")` block:

```python
    # ── WebSocket resource guards (issue #377) ─────────────────────────
    # In-process caps; correct for single-process deployment. Migrate to
    # Redis INCR/DECR if the stack ever scales horizontally.
    WS_MAX_CONNECTIONS_PER_USER: int = 10
    WS_MAX_CONNECTIONS_GLOBAL: int = 100
    WS_IDLE_TIMEOUT_SECONDS: int = 300
    WS_SCAN_TASK_IDLE_TIMEOUT_SECONDS: int = 1800
    WS_MAX_LIFETIME_SECONDS: int = 28800
```

#### Step 1.4 — Add conftest setdefaults

In `backend/tests/conftest.py`, after the three existing `os.environ.setdefault(...)` lines (before any `import` statements):

```python
os.environ.setdefault("WS_MAX_CONNECTIONS_PER_USER", "10")
os.environ.setdefault("WS_MAX_CONNECTIONS_GLOBAL", "100")
os.environ.setdefault("WS_IDLE_TIMEOUT_SECONDS", "300")
os.environ.setdefault("WS_SCAN_TASK_IDLE_TIMEOUT_SECONDS", "1800")
os.environ.setdefault("WS_MAX_LIFETIME_SECONDS", "28800")
```

#### Step 1.5 — Verify test passes

```bash
docker-compose exec -T backend python -m pytest backend/tests/core/test_config.py::test_ws_settings_have_correct_defaults -x 2>&1 | tail -5
```

Expected: `1 passed`

#### Step 1.6 — Commit

```bash
git add backend/app/core/config.py backend/tests/conftest.py backend/tests/core/test_config.py
git commit -m "config: add WS resource-guard settings (caps, idle/lifetime timeouts)"
```

---

### Task 2: ws_limits.py — in-process connection counter

**Files:**
- `backend/app/core/ws_limits.py` (new)
- `backend/tests/core/test_ws_limits.py` (new)

#### Step 2.1 — Write failing tests

Create `backend/tests/core/test_ws_limits.py`:

```python
"""
Unit tests for the WS connection-limit context manager (issue #377).
"""

import os

os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost/test")
os.environ.setdefault("POLYGON_API_KEY", "test-key")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret-key-for-unit-tests-only-aaa")

import uuid

import pytest
from fastapi import WebSocketException

import app.core.ws_limits as ws_limits
from app.core.ws_limits import ws_connection_slot

USER_A = uuid.UUID("00000000-0000-0000-0000-000000000001")
USER_B = uuid.UUID("00000000-0000-0000-0000-000000000002")


@pytest.fixture(autouse=True)
def reset_counters():
    ws_limits._per_user_counts.clear()
    ws_limits._global_count = 0
    yield
    ws_limits._per_user_counts.clear()
    ws_limits._global_count = 0


@pytest.mark.asyncio
async def test_slot_increments_and_decrements():
    assert ws_limits._global_count == 0
    async with ws_connection_slot(USER_A):
        assert ws_limits._global_count == 1
        assert ws_limits._per_user_counts[USER_A] == 1
    assert ws_limits._global_count == 0
    assert ws_limits._per_user_counts[USER_A] == 0


@pytest.mark.asyncio
async def test_per_user_cap_raises_1008(monkeypatch):
    monkeypatch.setattr("app.core.ws_limits.settings.WS_MAX_CONNECTIONS_PER_USER", 2)
    ws_limits._per_user_counts[USER_A] = 2
    with pytest.raises(WebSocketException) as exc_info:
        async with ws_connection_slot(USER_A):
            pass
    assert exc_info.value.code == 1008
    assert "Per-user" in exc_info.value.reason
    # Counter must not have been incremented
    assert ws_limits._per_user_counts[USER_A] == 2
    assert ws_limits._global_count == 0


@pytest.mark.asyncio
async def test_global_cap_raises_1008(monkeypatch):
    monkeypatch.setattr("app.core.ws_limits.settings.WS_MAX_CONNECTIONS_GLOBAL", 5)
    ws_limits._global_count = 5
    with pytest.raises(WebSocketException) as exc_info:
        async with ws_connection_slot(USER_B):
            pass
    assert exc_info.value.code == 1008
    assert "Global" in exc_info.value.reason
    assert ws_limits._global_count == 5


@pytest.mark.asyncio
async def test_decrement_on_exception_in_body():
    """finally block decrements even when the handler body raises."""
    with pytest.raises(ValueError):
        async with ws_connection_slot(USER_A):
            raise ValueError("simulated handler error")
    assert ws_limits._global_count == 0
    assert ws_limits._per_user_counts[USER_A] == 0


@pytest.mark.asyncio
async def test_multiple_users_independent():
    async with ws_connection_slot(USER_A):
        async with ws_connection_slot(USER_B):
            assert ws_limits._global_count == 2
            assert ws_limits._per_user_counts[USER_A] == 1
            assert ws_limits._per_user_counts[USER_B] == 1
    assert ws_limits._global_count == 0
```

#### Step 2.2 — Verify tests fail

```bash
docker-compose exec -T backend python -m pytest backend/tests/core/test_ws_limits.py -x 2>&1 | tail -5
```

Expected: `ModuleNotFoundError: No module named 'app.core.ws_limits'`

#### Step 2.3 — Create ws_limits.py

Create `backend/app/core/ws_limits.py`:

```python
"""
WebSocket connection-limit guards (issue #377).

Maintains in-process counters for per-user and global WS connection counts.
FastAPI's single-threaded event loop makes synchronous integer mutations atomic
— no lock needed.

NOTE: Assumes a single backend process. If the stack ever scales horizontally,
migrate to Redis INCR/DECR with atomic compare-and-set.
"""

import uuid
from collections import defaultdict
from contextlib import asynccontextmanager

from fastapi import WebSocketException

from app.core.config import settings

_per_user_counts: dict[uuid.UUID, int] = defaultdict(int)
_global_count: int = 0


@asynccontextmanager
async def ws_connection_slot(user_id: uuid.UUID):
    """Enforce per-user and global WS connection caps before accept().

    Raises WebSocketException(1008) if either cap is exceeded. Decrements both
    counters in a finally block so disconnect, timeout, and exception paths all
    release the slot correctly.
    """
    global _global_count
    if _per_user_counts[user_id] >= settings.WS_MAX_CONNECTIONS_PER_USER:
        raise WebSocketException(
            code=1008, reason="Per-user connection limit reached"
        )
    if _global_count >= settings.WS_MAX_CONNECTIONS_GLOBAL:
        raise WebSocketException(
            code=1008, reason="Global connection limit reached"
        )
    _per_user_counts[user_id] += 1
    _global_count += 1
    try:
        yield
    finally:
        _per_user_counts[user_id] -= 1
        _global_count -= 1
```

#### Step 2.4 — Verify tests pass

```bash
docker-compose exec -T backend python -m pytest backend/tests/core/test_ws_limits.py -v 2>&1 | tail -15
```

Expected: `5 passed`

#### Step 2.5 — Commit

```bash
git add backend/app/core/ws_limits.py backend/tests/core/test_ws_limits.py
git commit -m "feat(ws): add ws_limits.py — in-process per-user and global connection caps"
```

---

### Task 3: verify_ws_origin dependency

**Files:**
- `backend/app/core/auth.py`
- `backend/tests/api/test_ws_guards.py` (new)

#### Step 3.1 — Write failing tests

Create `backend/tests/api/test_ws_guards.py`:

```python
"""
Tests for WebSocket resource guard dependencies (issue #377).

Covers: Origin validation (unit) and connection-cap rejection (integration).

Infrastructure note: backend/tests/api/conftest.py defines `override_get_db`
(autouse=True) which overrides `get_db` to yield the test `db` session. This
means `ws_get_current_user` (which uses `Depends(get_db)`) sees flushed-but-
not-committed test users. Auth succeeds, so the cap or origin guard is the
actual rejection reason — confirmed by the `reason` assertions below.
"""

import os
import uuid

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-unit-tests-only-32chars!")
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost/test")
os.environ.setdefault("POLYGON_API_KEY", "test-key-for-unit-tests-only")
os.environ.setdefault("RATE_LIMITING_ENABLED", "false")

from app.core.config import get_settings

get_settings.cache_clear()

import pytest
from fastapi import WebSocketException
from fastapi.testclient import TestClient
from fastapi.websockets import WebSocketDisconnect

import app.core.ws_limits as ws_limits
from app.core.auth import create_access_token, verify_ws_origin
from app.main import app
from app.models.user import User

client = TestClient(app, raise_server_exceptions=False)


class _FakeWS:
    """Minimal WebSocket stub — only headers.get() is exercised."""

    def __init__(self, origin: str | None):
        self.headers: dict[str, str] = {}
        if origin is not None:
            self.headers["origin"] = origin


# ── Unit tests: verify_ws_origin ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_missing_origin_is_allowed():
    """Non-browser clients that omit Origin must not be rejected."""
    await verify_ws_origin(_FakeWS(origin=None))  # must not raise


@pytest.mark.asyncio
async def test_matching_origin_is_allowed():
    """An Origin in CORS_ORIGINS (default: localhost:3333) must pass."""
    await verify_ws_origin(_FakeWS(origin="http://localhost:3333"))


@pytest.mark.asyncio
async def test_mismatched_origin_is_rejected():
    ws = _FakeWS(origin="https://evil.example.com")
    with pytest.raises(WebSocketException) as exc_info:
        await verify_ws_origin(ws)
    assert exc_info.value.code == 1008
    assert "Origin not allowed" in exc_info.value.reason


# ── Integration tests: connection-cap rejection ───────────────────────────────
# override_get_db (autouse, api/conftest.py) ensures auth succeeds so that
# the guard under test — not auth — is the source of the 1008.
# The `reason` string assertion distinguishes cap/origin rejection from auth.

def _make_user(db, uid=None):
    uid = uid or uuid.UUID("00000000-0000-0000-0000-000000000001")
    user = User(id=uid, username="wsguardtest", password_hash="x", is_active=True)
    db.add(user)
    db.flush()
    return user, create_access_token(str(uid))


def test_global_cap_rejects_with_1008(db):
    """Global cap exceeded → rejected with 1008 before accept(); reason confirms cap fired."""
    _, token = _make_user(db)
    ws_limits._global_count = 100  # at the cap
    try:
        with pytest.raises(WebSocketDisconnect) as exc_info:
            with client.websocket_connect(
                "/api/v1/live/ws/AAPL/minute",
                cookies={"access_token": token},
            ):
                pass
        assert exc_info.value.code == 1008
        assert "limit" in (exc_info.value.reason or "").lower()
    finally:
        ws_limits._global_count = 0


def test_per_user_cap_rejects_with_1008(db):
    """Per-user cap exceeded → rejected with 1008 before accept(); reason confirms cap fired."""
    user, token = _make_user(db)
    ws_limits._per_user_counts[user.id] = 10  # at the default cap
    try:
        with pytest.raises(WebSocketDisconnect) as exc_info:
            with client.websocket_connect(
                "/api/v1/news/ws",
                cookies={"access_token": token},
            ):
                pass
        assert exc_info.value.code == 1008
        assert "limit" in (exc_info.value.reason or "").lower()
    finally:
        ws_limits._per_user_counts.clear()


def test_disallowed_origin_rejects_with_1008(db):
    """Auth succeeds then origin guard fires — reason confirms origin, not auth, rejected."""
    _, token = _make_user(db)
    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect(
            "/api/v1/tweets/feed",
            cookies={"access_token": token},
            headers={"Origin": "https://evil.example.com"},
        ):
            pass
    assert exc_info.value.code == 1008
    assert "Origin" in (exc_info.value.reason or "")
```

#### Step 3.2 — Verify unit tests fail

```bash
docker-compose exec -T backend python -m pytest backend/tests/api/test_ws_guards.py::test_missing_origin_is_allowed -x 2>&1 | tail -5
```

Expected: `ImportError: cannot import name 'verify_ws_origin' from 'app.core.auth'`

#### Step 3.3 — Add verify_ws_origin to auth.py

Append to `backend/app/core/auth.py` (after `ws_get_current_user`), also adding
`from app.core.config import settings` to the imports block (the file currently
imports `from app.core.config import get_settings` — add `settings` to that import):

Add import (update existing line):
```python
from app.core.config import get_settings, settings
```

Add function:
```python
async def verify_ws_origin(websocket: WebSocket) -> None:
    """Reject WS upgrades from disallowed browser origins before accept().

    Missing Origin is allowed — non-browser clients and same-origin requests
    do not send this header. Only a present-and-mismatched Origin is rejected.
    """
    origin = websocket.headers.get("origin")
    if origin and origin not in settings.CORS_ORIGINS:
        raise WebSocketException(code=1008, reason="Origin not allowed")
```

#### Step 3.4 — Verify all guard tests pass

```bash
docker-compose exec -T backend python -m pytest backend/tests/api/test_ws_guards.py -v 2>&1 | tail -20
```

Expected: `6 passed` (3 unit + 3 integration; integration cap/origin tests may show
skips if Redis is unavailable — that's acceptable, the unit tests cover the logic)

Note: Integration tests `test_global_cap_rejects_with_1008` and
`test_per_user_cap_rejects_with_1008` will fail if the handlers have not yet been
updated in Tasks 5–8. These tests can be run again after those tasks complete.
The unit tests (`test_missing_origin_is_allowed`, `test_matching_origin_is_allowed`,
`test_mismatched_origin_is_rejected`) must pass at this step.

```bash
docker-compose exec -T backend python -m pytest backend/tests/api/test_ws_guards.py -k "origin" -v 2>&1 | tail -10
```

Expected: `3 passed`

#### Step 3.5 — Commit

```bash
git add backend/app/core/auth.py backend/tests/api/test_ws_guards.py
git commit -m "feat(ws): add verify_ws_origin dependency — rejects mismatched browser origins"
```

---

### Task 4: Fan-out registry in StockWebSocketManager

**Files:**
- `backend/app/services/websocket_manager.py`
- `backend/tests/services/test_websocket_manager.py` (new)

#### Step 4.1 — Write failing tests

Create `backend/tests/services/test_websocket_manager.py`:

```python
"""
Unit tests for StockWebSocketManager fan-out registry (issue #377).
"""

import asyncio
import os
from collections import defaultdict
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost/test")
os.environ.setdefault("POLYGON_API_KEY", "test-key")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret-key-for-unit-tests-only-aaa")

import pytest

from app.services.websocket_manager import StockWebSocketManager


def _fresh_manager() -> StockWebSocketManager:
    """Return a StockWebSocketManager instance with fan-out state initialised."""
    mgr = object.__new__(StockWebSocketManager)
    mgr._initialized = True
    mgr.api_key = "test"
    mgr.client = None
    mgr.active_tickers = set()
    mgr.redis_client = None
    mgr._loop = None
    mgr._connected = False
    mgr._channel_queues = defaultdict(set)
    mgr._channel_tasks = {}
    return mgr


@pytest.mark.asyncio
async def test_register_returns_queue_and_starts_task():
    mgr = _fresh_manager()

    async def _noop_fan_out(channel):
        await asyncio.sleep(100)

    with patch.object(mgr, "_fan_out", _noop_fan_out):
        queue = await mgr.register("chan_a")

    assert isinstance(queue, asyncio.Queue)
    assert queue in mgr._channel_queues["chan_a"]
    assert "chan_a" in mgr._channel_tasks

    # Cleanup
    mgr._channel_tasks["chan_a"].cancel()
    await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_register_same_channel_twice_shares_task():
    mgr = _fresh_manager()
    task_created = []

    async def _noop_fan_out(channel):
        task_created.append(channel)
        await asyncio.sleep(100)

    with patch.object(mgr, "_fan_out", _noop_fan_out):
        q1 = await mgr.register("chan_b")
        q2 = await mgr.register("chan_b")

    assert q1 is not q2
    assert len(task_created) == 1  # only one _fan_out task created

    mgr._channel_tasks["chan_b"].cancel()
    await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_unregister_removes_queue_and_cancels_task():
    mgr = _fresh_manager()

    async def _noop_fan_out(channel):
        await asyncio.sleep(100)

    with patch.object(mgr, "_fan_out", _noop_fan_out):
        queue = await mgr.register("chan_c")

    task = mgr._channel_tasks["chan_c"]
    await mgr.unregister("chan_c", queue)

    assert queue not in mgr._channel_queues["chan_c"]
    assert "chan_c" not in mgr._channel_tasks
    assert task.cancelled() or task.done()


@pytest.mark.asyncio
async def test_fan_out_delivers_message_to_all_queues():
    """_fan_out reads a message from Redis pubsub and puts data into all queues."""
    mgr = _fresh_manager()

    # Build mock pubsub: one real message then a timeout, then CancelledError
    call_count = 0

    async def mock_get_message(**kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return {"data": "hello"}
        await asyncio.sleep(100)  # blocks until task is cancelled

    mock_pubsub = MagicMock()
    mock_pubsub.subscribe = AsyncMock()
    mock_pubsub.get_message = mock_get_message
    mock_pubsub.unsubscribe = AsyncMock()
    mock_pubsub.aclose = AsyncMock()

    mock_redis = MagicMock()
    mock_redis.pubsub = MagicMock(return_value=mock_pubsub)

    mgr._get_redis = AsyncMock(return_value=mock_redis)

    q1: asyncio.Queue = asyncio.Queue()
    q2: asyncio.Queue = asyncio.Queue()
    mgr._channel_queues["chan_d"] = {q1, q2}

    task = asyncio.create_task(mgr._fan_out("chan_d"))
    # Give the fan-out task time to process the first message
    await asyncio.sleep(0.05)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    assert not q1.empty()
    assert not q2.empty()
    assert await q1.get() == "hello"
    assert await q2.get() == "hello"
```

#### Step 4.2 — Verify tests fail

```bash
docker-compose exec -T backend python -m pytest backend/tests/services/test_websocket_manager.py -x 2>&1 | tail -10
```

Expected: `AttributeError: 'StockWebSocketManager' object has no attribute '_channel_queues'`
(or similar — the fan-out methods don't exist yet)

#### Step 4.3 — Update websocket_manager.py

**Add `from collections import defaultdict` to imports** at the top of
`backend/app/services/websocket_manager.py`:

```python
import asyncio
import json
import logging
import threading
from collections import defaultdict
from typing import Any, Dict, Optional, Set
```

**Update `__init__`** — append two lines after `self._connected = False`:

```python
        # Fan-out registry: shared pubsub per channel, one asyncio.Queue per subscriber
        self._channel_queues: dict[str, set[asyncio.Queue]] = defaultdict(set)
        self._channel_tasks: dict[str, asyncio.Task] = {}
```

**Add three new methods** after the existing `unsubscribe` method:

```python
    async def register(self, channel: str) -> asyncio.Queue:
        """Return a new subscriber queue for channel; start _fan_out if first subscriber."""
        queue: asyncio.Queue = asyncio.Queue(maxsize=100)
        self._channel_queues[channel].add(queue)
        if channel not in self._channel_tasks:
            self._channel_tasks[channel] = asyncio.create_task(
                self._fan_out(channel)
            )
        return queue

    async def unregister(self, channel: str, queue: asyncio.Queue) -> None:
        """Remove subscriber queue; cancel _fan_out task when channel has no subscribers."""
        self._channel_queues[channel].discard(queue)
        if not self._channel_queues[channel]:
            task = self._channel_tasks.pop(channel, None)
            if task:
                task.cancel()

    async def _fan_out(self, channel: str) -> None:
        """Single Redis pubsub reader that fans out to all registered queues.

        Slow-consumer queues that are full are silently dropped from the registry;
        the connection-cap limits the blast radius.
        """
        redis = await self._get_redis()
        pubsub = redis.pubsub()
        await pubsub.subscribe(channel)
        try:
            while True:
                msg = await pubsub.get_message(
                    ignore_subscribe_messages=True, timeout=1.0
                )
                if msg:
                    dead: set[asyncio.Queue] = set()
                    for q in list(self._channel_queues[channel]):
                        try:
                            q.put_nowait(msg["data"])
                        except asyncio.QueueFull:
                            dead.add(q)
                    self._channel_queues[channel] -= dead
                await asyncio.sleep(0.01)
        finally:
            await pubsub.unsubscribe(channel)
            await pubsub.aclose()
```

#### Step 4.4 — Verify tests pass

```bash
docker-compose exec -T backend python -m pytest backend/tests/services/test_websocket_manager.py -v 2>&1 | tail -15
```

Expected: `4 passed`

#### Step 4.5 — Commit

```bash
git add backend/app/services/websocket_manager.py backend/tests/services/test_websocket_manager.py
git commit -m "feat(ws): add fan-out registry (register/unregister/_fan_out) to StockWebSocketManager"
```

---

### Task 5: Harden live_data.py — ticker and watchlist handlers (fan-out)

**Files:**
- `backend/app/routers/live_data.py`

Both `/ws/{ticker}/{resolution}` and `/ws/watchlist` switch from per-connection
aioredis/pubsub to the shared fan-out registry. All five guards are applied:
`verify_ws_origin`, `ws_connection_slot`, idle timeout, lifetime timeout.

#### Step 5.1 — Verify existing auth tests still pass (baseline)

```bash
docker-compose exec -T backend python -m pytest backend/tests/api/test_ws_auth.py -v 2>&1 | tail -10
```

Expected: all existing tests pass (they send no Origin and use no-user tokens →
auth rejection path unchanged).

#### Step 5.2 — Update imports in live_data.py

Replace the current import block at the top of `backend/app/routers/live_data.py`:

```python
import asyncio
import json
import logging
import time

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect

from app.core.auth import verify_ws_origin, ws_get_current_user
from app.core.config import settings
from app.core.metrics import active_websocket_connections
from app.core.rate_limits import limiter
from app.core.ws_limits import ws_connection_slot
from app.models.user import User
from app.services.websocket_manager import websocket_manager
```

(`aioredis` is kept because `scan_task_websocket` still uses it. `time` is new.
`verify_ws_origin` and `ws_connection_slot` are new.)

#### Step 5.3 — Replace stock_live_websocket handler

Replace the full `stock_live_websocket` function with:

```python
@router.websocket("/ws/{ticker}/{resolution}")
@limiter.exempt
async def stock_live_websocket(
    websocket: WebSocket,
    ticker: str,
    resolution: str,
    user: User = Depends(ws_get_current_user),
    _: None = Depends(verify_ws_origin),
):
    ticker = ticker.upper()
    resolution = resolution.lower()
    if resolution not in ["minute", "second"]:
        resolution = "minute"
    channel = f"stock_updates:{ticker}:{resolution}"

    async with ws_connection_slot(user.id):
        await websocket.accept()
        active_websocket_connections.inc()
        websocket_manager.subscribe(ticker)

        queue = await websocket_manager.register(channel)
        connected_at = time.monotonic()
        last_send = time.monotonic()
        logger.info(f"Client connected to {resolution} updates for {ticker}")

        try:
            while True:
                now = time.monotonic()
                if now - connected_at > settings.WS_MAX_LIFETIME_SECONDS:
                    await websocket.close(code=1001, reason="Max lifetime reached")
                    break
                if now - last_send > settings.WS_IDLE_TIMEOUT_SECONDS:
                    await websocket.close(code=1000, reason="Idle timeout")
                    break
                try:
                    data = await asyncio.wait_for(queue.get(), timeout=1.0)
                    await websocket.send_text(data)
                    last_send = time.monotonic()
                except asyncio.TimeoutError:
                    pass
        except WebSocketDisconnect:
            logger.info(f"Client disconnected from live updates for {ticker}")
        except Exception as e:
            logger.error(f"WebSocket error for {ticker}: {e}")
        finally:
            active_websocket_connections.dec()
            await websocket_manager.unregister(channel, queue)
```

#### Step 5.4 — Replace watchlist_live_websocket handler

Replace the full `watchlist_live_websocket` function with:

```python
@router.websocket("/ws/watchlist")
@limiter.exempt
async def watchlist_live_websocket(
    websocket: WebSocket,
    user: User = Depends(ws_get_current_user),
    _: None = Depends(verify_ws_origin),
):
    async with ws_connection_slot(user.id):
        await websocket.accept()
        active_websocket_connections.inc()

        queue_ld = await websocket_manager.register("watchlist:live_data")
        queue_al = await websocket_manager.register("watchlist:alerts")
        connected_at = time.monotonic()
        last_send = time.monotonic()
        logger.info("Client connected to watchlist live stream")

        try:
            while True:
                now = time.monotonic()
                if now - connected_at > settings.WS_MAX_LIFETIME_SECONDS:
                    await websocket.close(code=1001, reason="Max lifetime reached")
                    break
                if now - last_send > settings.WS_IDLE_TIMEOUT_SECONDS:
                    await websocket.close(code=1000, reason="Idle timeout")
                    break
                for queue in (queue_ld, queue_al):
                    try:
                        data = queue.get_nowait()
                        await websocket.send_text(data)
                        last_send = time.monotonic()
                    except asyncio.QueueEmpty:
                        pass
                await asyncio.sleep(0.05)
        except WebSocketDisconnect:
            logger.info("Client disconnected from watchlist live stream")
        except Exception as e:
            logger.error(f"Watchlist WebSocket error: {e}")
        finally:
            active_websocket_connections.dec()
            await websocket_manager.unregister("watchlist:live_data", queue_ld)
            await websocket_manager.unregister("watchlist:alerts", queue_al)
```

#### Step 5.5 — Run regression tests

```bash
docker-compose exec -T backend python -m pytest backend/tests/api/test_ws_auth.py -v 2>&1 | tail -15
```

Expected: all existing tests pass.

#### Step 5.6 — Commit

```bash
git add backend/app/routers/live_data.py
git commit -m "feat(ws): harden ticker+watchlist WS handlers — fan-out, caps, timeouts, origin check"
```

---

### Task 6: Harden live_data.py — scan-task handler (per-connection)

**Files:**
- `backend/app/routers/live_data.py`

The scan-task endpoint retains its own per-connection aioredis/pubsub (spec: bounded
by connection cap; self-terminating; fan-out ROI minimal). It gains all five guards.
The idle timeout uses `WS_SCAN_TASK_IDLE_TIMEOUT_SECONDS` (30 min) instead of 5 min.

#### Step 6.1 — Replace scan_task_websocket handler

Replace the full `scan_task_websocket` function with:

```python
@router.websocket("/ws/scan-task/{task_id}")
@limiter.exempt
async def scan_task_websocket(
    websocket: WebSocket,
    task_id: str,
    user: User = Depends(ws_get_current_user),
    _: None = Depends(verify_ws_origin),
):
    async with ws_connection_slot(user.id):
        await websocket.accept()
        active_websocket_connections.inc()

        redis_client = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
        pubsub = redis_client.pubsub()
        channel = f"scan_task:{task_id}"
        await pubsub.subscribe(channel)
        connected_at = time.monotonic()
        last_send = time.monotonic()
        logger.info(f"Client connected to scan task: {task_id}")

        try:
            while True:
                now = time.monotonic()
                if now - connected_at > settings.WS_MAX_LIFETIME_SECONDS:
                    await websocket.close(code=1001, reason="Max lifetime reached")
                    break
                if now - last_send > settings.WS_SCAN_TASK_IDLE_TIMEOUT_SECONDS:
                    await websocket.close(code=1000, reason="Idle timeout")
                    break
                message = await pubsub.get_message(
                    ignore_subscribe_messages=True, timeout=1.0
                )
                if message:
                    await websocket.send_text(message["data"])
                    last_send = time.monotonic()
                    try:
                        parsed = json.loads(message["data"])
                        if parsed.get("status") in ("completed", "failed"):
                            break
                    except Exception:
                        pass
                await asyncio.sleep(0.01)
        except WebSocketDisconnect:
            logger.info(f"Client disconnected from scan task: {task_id}")
        except Exception as e:
            logger.error(f"Scan task WebSocket error for {task_id}: {e}")
        finally:
            active_websocket_connections.dec()
            await pubsub.unsubscribe(channel)
            await redis_client.aclose()
```

#### Step 6.2 — Run regression tests

```bash
docker-compose exec -T backend python -m pytest backend/tests/api/test_ws_auth.py -v 2>&1 | tail -10
```

Expected: all existing tests pass.

#### Step 6.3 — Commit

```bash
git add backend/app/routers/live_data.py
git commit -m "feat(ws): harden scan-task WS handler — connection cap, origin check, 30-min idle timeout"
```

---

### Task 7: Harden news.py WebSocket endpoint

**Files:**
- `backend/app/routers/news.py`

#### Step 7.1 — Update imports in news.py

The WS-related imports currently appear mid-file with `# noqa: E402` comments.
Update the WS import block (lines 72–81) to add `verify_ws_origin` and `ws_connection_slot`:

```python
import asyncio  # noqa: E402
import time  # noqa: E402

import redis.asyncio as aioredis  # noqa: E402
from fastapi import Depends, WebSocket, WebSocketDisconnect  # noqa: E402

from app.core.auth import verify_ws_origin, ws_get_current_user  # noqa: E402
from app.core.config import settings  # noqa: E402
from app.core.rate_limits import limiter  # noqa: E402
from app.core.ws_limits import ws_connection_slot  # noqa: E402
from app.models.user import User  # noqa: E402
```

#### Step 7.2 — Replace news_websocket handler

Replace the full `news_websocket` function with:

```python
@router.websocket("/ws")
@limiter.exempt
async def news_websocket(
    websocket: WebSocket,
    user: User = Depends(ws_get_current_user),
    _: None = Depends(verify_ws_origin),
):
    async with ws_connection_slot(user.id):
        await websocket.accept()
        redis_client = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
        pubsub = redis_client.pubsub()
        await pubsub.subscribe("news_updates")
        connected_at = time.monotonic()
        last_send = time.monotonic()

        try:
            while True:
                now = time.monotonic()
                if now - connected_at > settings.WS_MAX_LIFETIME_SECONDS:
                    await websocket.close(code=1001, reason="Max lifetime reached")
                    break
                if now - last_send > settings.WS_IDLE_TIMEOUT_SECONDS:
                    await websocket.close(code=1000, reason="Idle timeout")
                    break
                message = await pubsub.get_message(
                    ignore_subscribe_messages=True, timeout=1.0
                )
                if message:
                    await websocket.send_text(message["data"])
                    last_send = time.monotonic()
                await asyncio.sleep(0.1)
        except WebSocketDisconnect:
            pass
        except Exception as e:
            print(f"WS Exception: {e}")
        finally:
            await pubsub.unsubscribe("news_updates")
            await redis_client.close()
```

#### Step 7.3 — Run regression + guard tests

```bash
docker-compose exec -T backend python -m pytest backend/tests/api/test_ws_auth.py backend/tests/api/test_ws_guards.py -v 2>&1 | tail -20
```

Expected: all pass. The `test_per_user_cap_rejects_with_1008` integration test (which
targets `/api/v1/news/ws`) should now pass.

#### Step 7.4 — Commit

```bash
git add backend/app/routers/news.py
git commit -m "feat(ws): harden news WS endpoint — connection cap, origin check, idle/lifetime timeout"
```

---

### Task 8: Harden tweets.py WebSocket endpoint

**Files:**
- `backend/app/routers/tweets.py`

#### Step 8.1 — Update imports in tweets.py

Add `import time` and the two new imports to the existing import block:

```python
import asyncio
import logging
import time
from typing import Optional

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, Query, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session

from app.core.auth import verify_ws_origin, ws_get_current_user
from app.core.config import settings
from app.core.database import SessionLocal
from app.core.rate_limits import limiter
from app.core.ws_limits import ws_connection_slot
from app.models.monitored_account import MonitoredAccount
from app.models.tweet_signal import TweetSignal
from app.models.user import User
```

#### Step 8.2 — Replace tweet_feed_websocket handler

Replace the full `tweet_feed_websocket` function with:

```python
@router.websocket("/feed")
@limiter.exempt
async def tweet_feed_websocket(
    websocket: WebSocket,
    user: User = Depends(ws_get_current_user),
    _: None = Depends(verify_ws_origin),
):
    async with ws_connection_slot(user.id):
        await websocket.accept()
        redis_client = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
        pubsub = redis_client.pubsub()
        await pubsub.subscribe("tweet_signals:all")
        connected_at = time.monotonic()
        last_send = time.monotonic()

        try:
            while True:
                now = time.monotonic()
                if now - connected_at > settings.WS_MAX_LIFETIME_SECONDS:
                    await websocket.close(code=1001, reason="Max lifetime reached")
                    break
                if now - last_send > settings.WS_IDLE_TIMEOUT_SECONDS:
                    await websocket.close(code=1000, reason="Idle timeout")
                    break
                message = await pubsub.get_message(
                    ignore_subscribe_messages=True, timeout=1.0
                )
                if message:
                    await websocket.send_text(message["data"])
                    last_send = time.monotonic()
                await asyncio.sleep(0.01)
        except WebSocketDisconnect:
            logger.info("Client disconnected from tweet feed")
        finally:
            await pubsub.unsubscribe("tweet_signals:all")
            await redis_client.aclose()
```

#### Step 8.3 — Run full guard test suite

```bash
docker-compose exec -T backend python -m pytest \
  backend/tests/api/test_ws_auth.py \
  backend/tests/api/test_ws_guards.py \
  backend/tests/core/test_ws_limits.py \
  backend/tests/services/test_websocket_manager.py \
  -v 2>&1 | tail -30
```

Expected: all tests pass. The `test_disallowed_origin_rejects_with_1008` integration
test (which targets `/api/v1/tweets/feed`) should now pass.

#### Step 8.4 — Run the full test suite

```bash
docker-compose exec -T backend python -m pytest backend/tests/ -x --timeout=60 2>&1 | tail -20
```

Expected: no regressions.

#### Step 8.5 — Commit

```bash
git add backend/app/routers/tweets.py
git commit -m "feat(ws): harden tweets WS endpoint — connection cap, origin check, idle/lifetime timeout"
```

---

## Summary

| Task | Deliverable | Tests |
|---|---|---|
| 1 | 5 `WS_*` settings in config + conftest defaults | `test_ws_settings_have_correct_defaults` |
| 2 | `ws_limits.py` — per-user + global counter | `test_ws_limits.py` (5 tests) |
| 3 | `verify_ws_origin` dependency in `auth.py` | `test_ws_guards.py` (3 unit + 3 integration) |
| 4 | Fan-out `register`/`unregister`/`_fan_out` in `websocket_manager.py` | `test_websocket_manager.py` (4 tests) |
| 5 | Hardened ticker + watchlist handlers (fan-out) | regression: `test_ws_auth.py` |
| 6 | Hardened scan-task handler (per-connection, 30-min idle) | regression: `test_ws_auth.py` |
| 7 | Hardened news handler | integration: cap test |
| 8 | Hardened tweets handler | integration: origin test |

**8 tasks, 38 steps**
