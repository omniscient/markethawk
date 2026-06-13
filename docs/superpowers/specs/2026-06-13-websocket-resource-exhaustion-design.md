# WebSocket Resource Exhaustion Hardening (F-WS-01)

**Date:** 2026-06-13
**Issue:** #377
**Epic:** #372 (Defensive Security Review 2026-06-12)
**Status:** Spec
**Standard:** OWASP A04:2021 · CWE-770

---

## Problem

All five WebSocket endpoints across three routers (`live_data.py`, `news.py`, `tweets.py`) are
authenticated but have no resource guardrails:

- No per-user or global connection cap — an authenticated client can open thousands of connections.
- Each connection opens its own `aioredis.from_url()` + `pubsub` object, exhausting Redis connections
  and backend file descriptors linearly with connection count.
- No server-side idle or lifetime timeout — connections can be held open indefinitely.
- No `Origin` header validation on WebSocket upgrade — cross-origin browser scripts can initiate
  connections using the victim's cookie.
- `@limiter.exempt` on all WS routes removes slowapi rate-limit protection.

### Affected endpoints

| File | Route | Channel(s) |
|---|---|---|
| `live_data.py` | `/ws/{ticker}/{resolution}` | `stock_updates:{ticker}:{resolution}` |
| `live_data.py` | `/ws/watchlist` | `watchlist:live_data`, `watchlist:alerts` |
| `live_data.py` | `/ws/scan-task/{task_id}` | `scan_task:{task_id}` |
| `news.py` | `/ws` | `news_updates` |
| `tweets.py` | `/feed` | `tweet_signals:all` |

---

## Requirements

1. **Per-user connection cap** — maximum 10 concurrent WS connections per user (all endpoints pooled), configurable as `WS_MAX_CONNECTIONS_PER_USER` in `config.py`.
2. **Global connection cap** — maximum 100 concurrent WS connections across all users, configurable as `WS_MAX_CONNECTIONS_GLOBAL`.
3. **Rejection before `accept()`** — when either cap is exceeded, the server rejects the upgrade with close code 1008 before calling `websocket.accept()`.
4. **Idle timeout** — connections with no server→client traffic for 5 minutes are closed (code 1000). Configurable as `WS_IDLE_TIMEOUT_SECONDS = 300`. Applies to all endpoints except scan-task.
5. **Scan-task idle timeout** — 30 minutes (`WS_SCAN_TASK_IDLE_TIMEOUT_SECONDS = 1800`), since slow range scans can legitimately produce no progress events for extended periods.
6. **Absolute lifetime cap** — all connections closed after 8 hours maximum (`WS_MAX_LIFETIME_SECONDS = 28800`), covering a full extended trading day and forcing periodic reconnection.
7. **Shared Redis fan-out** — `/ws/{ticker}/{resolution}` and `/ws/watchlist` are refactored to use a shared per-channel pubsub managed by `StockWebSocketManager` rather than opening a new `aioredis` connection and pubsub per WebSocket client. `news.py`, `tweets.py`, and `scan-task` retain per-connection pubsub (bounded by the connection cap).
8. **Origin validation** — a new `verify_ws_origin` FastAPI dependency in `auth.py` checks the `Origin` header against `settings.CORS_ORIGINS` before `accept()`. A missing `Origin` is allowed (non-browser clients, same-origin requests). A present-and-mismatched `Origin` raises `WebSocketException(code=1008, reason="Origin not allowed")`.

---

## Architecture / Approach

### Chosen approach: In-process counters + StockWebSocketManager fan-out + dependency-based guards

#### 1. New config settings (`backend/app/core/config.py`)

```python
WS_MAX_CONNECTIONS_PER_USER: int = 10
WS_MAX_CONNECTIONS_GLOBAL: int = 100
WS_IDLE_TIMEOUT_SECONDS: int = 300
WS_SCAN_TASK_IDLE_TIMEOUT_SECONDS: int = 1800
WS_MAX_LIFETIME_SECONDS: int = 28800
```

Add matching `os.environ.setdefault(...)` lines to `backend/tests/conftest.py` to avoid breaking existing tests that call `Settings()` bare.

#### 2. Connection-limit context manager (`backend/app/core/ws_limits.py`)

A new module provides an async context manager that:
- Maintains a module-level `defaultdict(int)` keyed on `user.id` (per-user counter) and a single `int` (global counter).
- On enter: increments both; if either exceeds its cap, decrements and raises `WebSocketException(code=1008, reason="Connection limit reached")`.
- On exit: decrements both (via `finally` — handles disconnect, timeout, and exception paths uniformly).

Since the app runs a single backend process (no replicas), an in-memory counter is correct and avoids Redis round-trips on every connection handshake.

```python
# Sketch
_per_user_counts: dict[int, int] = defaultdict(int)
_global_count: int = 0

@asynccontextmanager
async def ws_connection_slot(user_id: int):
    global _global_count
    # Check + increment atomically (event loop is single-threaded)
    if _per_user_counts[user_id] >= settings.WS_MAX_CONNECTIONS_PER_USER:
        raise WebSocketException(code=1008, reason="Per-user connection limit reached")
    if _global_count >= settings.WS_MAX_CONNECTIONS_GLOBAL:
        raise WebSocketException(code=1008, reason="Global connection limit reached")
    _per_user_counts[user_id] += 1
    _global_count += 1
    try:
        yield
    finally:
        _per_user_counts[user_id] -= 1
        _global_count -= 1
```

Event-loop single-threadedness makes these integer operations effectively atomic — no lock needed.

#### 3. Origin validation dependency (`backend/app/core/auth.py`)

```python
async def verify_ws_origin(websocket: WebSocket) -> None:
    origin = websocket.headers.get("origin")
    if origin and origin not in settings.CORS_ORIGINS:
        raise WebSocketException(code=1008, reason="Origin not allowed")
```

Added to each WS handler as `Depends(verify_ws_origin)`. Follows the established pattern of `ws_get_current_user` (WS auth via dependency, not middleware), consistent with the existing `AuthMiddleware` / `CSRFMiddleware` deliberately skipping `scope["type"] == "websocket"`.

#### 4. Timeout loop pattern

Each WS handler tracks two timestamps — connection start (`connected_at`) and last server→client send (`last_send`). The existing polling loop (`pubsub.get_message(timeout=1.0)` + `asyncio.sleep(0.01)`) gains two checks:

```python
now = time.monotonic()
if now - connected_at > settings.WS_MAX_LIFETIME_SECONDS:
    await websocket.close(code=1001, reason="Max lifetime reached")
    break
idle_limit = settings.WS_SCAN_TASK_IDLE_TIMEOUT_SECONDS if is_scan_task else settings.WS_IDLE_TIMEOUT_SECONDS
if now - last_send > idle_limit:
    await websocket.close(code=1000, reason="Idle timeout")
    break
```

`last_send` is updated on every `await websocket.send_text(...)` call.

#### 5. Shared fan-out in `StockWebSocketManager` (`backend/app/services/websocket_manager.py`)

A new fan-out registry is added to the existing singleton:

```python
_channel_queues: dict[str, set[asyncio.Queue]] = defaultdict(set)
_channel_tasks: dict[str, asyncio.Task] = {}

async def register(self, channel: str) -> asyncio.Queue:
    queue: asyncio.Queue = asyncio.Queue(maxsize=100)
    self._channel_queues[channel].add(queue)
    if channel not in self._channel_tasks:
        self._channel_tasks[channel] = asyncio.create_task(self._fan_out(channel))
    return queue

async def unregister(self, channel: str, queue: asyncio.Queue) -> None:
    self._channel_queues[channel].discard(queue)
    if not self._channel_queues[channel]:
        task = self._channel_tasks.pop(channel, None)
        if task:
            task.cancel()

async def _fan_out(self, channel: str) -> None:
    redis = await self._get_redis()
    pubsub = redis.pubsub()
    await pubsub.subscribe(channel)
    try:
        while True:
            msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
            if msg:
                dead = set()
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

WS handlers for `/ws/{ticker}/{resolution}` and `/ws/watchlist` replace their current `aioredis.from_url() + pubsub` block with:

```python
queue = await websocket_manager.register(channel)
try:
    while True:
        data = await asyncio.wait_for(queue.get(), timeout=1.0)
        await websocket.send_text(data)
        last_send = time.monotonic()
        # ... timeout checks ...
except asyncio.TimeoutError:
    pass  # continue loop for timeout checks
finally:
    await websocket_manager.unregister(channel, queue)
```

Slow-consumer queues (full) are silently dropped from the registry — the connection-cap limit bounds the damage further.

#### 6. Handler changes summary

Each of the 5 WS handlers gets:
- `Depends(verify_ws_origin)` added to signature.
- `async with ws_connection_slot(user.id):` wrapping the body after auth resolves and before `accept()`.
- Timeout loop additions (lifetime + idle).

`/ws/{ticker}/{resolution}` and `/ws/watchlist` additionally replace per-connection pubsub with `websocket_manager.register/unregister`.

---

## Alternatives Considered

### Alternative A: ASGI middleware for WS guards

Add a single `WebSocketLimitMiddleware` that intercepts all WS upgrade requests, checks Origin and counts, and rejects before dispatch.

**Rejected:** The existing middlewares (`AuthMiddleware`, `CSRFMiddleware`) explicitly skip `scope["type"] == "websocket"` — this is a deliberate architectural choice to keep WS auth in FastAPI dependencies. A new WS-aware middleware would be the only one in the stack handling WS, creating an inconsistency. The dependency approach mirrors the existing `ws_get_current_user` pattern and keeps all WS guard logic co-located with the handlers. Backend patterns memory (issue #191) explicitly documents this separation.

### Alternative B: Full shared-pubsub refactor for all 5 endpoints

Extend the fan-out registry to also cover `news_updates`, `tweet_signals:all`, and `scan_task:{task_id}`.

**Rejected:** This is `size:M`. The connection cap of 10/user and 100 global already bounds these low-volume, single-fixed-channel endpoints. The fan-out benefit for news and tweets is minimal (single channel, few simultaneous viewers), and scan-task is self-terminating. Scope is kept to the two highest-risk endpoints where the fan-out ROI is clearest.

---

## Open Questions

1. **Frontend reconnect on 1008** — Does the React frontend handle WS close code 1008 gracefully (show a user-facing error vs. silently retry)? This spec doesn't change frontend behavior; the frontend already reconnects on close. If the backend rejects during a DoS-style event, reconnect storms could be a concern — but the per-user cap makes this self-limiting.

2. **Multi-replica readiness** — The in-memory per-user counter assumes a single backend process (true today). If the stack is ever scaled horizontally, the counter must migrate to a Redis counter (`INCR`/`DECR` with atomic checks). Add a comment in `ws_limits.py` noting this assumption.

3. **Inbound message-size limit** — The issue lists "no inbound message-size limit" as a risk. None of the five endpoints currently process inbound WebSocket messages (they are all server→client push streams; inbound frames are ignored). The idle timeout and connection cap address the resource exhaustion path. If bidirectional messaging is added in the future, a message-size guard should be added at that point.

---

## Assumptions

- **Single backend process**: The in-memory connection counter is correct only as long as there is one backend replica. This is true for the current Docker Compose deployment.
- **Event-loop thread safety**: All counter operations are synchronous integer mutations inside `async` context managers; FastAPI's single-threaded event loop makes these atomic without locks.
- **`asyncio.Queue(maxsize=100)` per subscriber is sufficient**: At 1 message/second (minute aggregates) this holds 100 seconds of backlog. A slow consumer that fills the queue is dropped from the fan-out set (not killed — the WebSocket is still open, it just stops receiving). This is acceptable; the timeout will eventually close it.
- **Missing `Origin` allowed**: Non-browser clients (API testing tools, the live-scanner container) do not send `Origin`. Rejecting them would break internal tooling. Only present-and-mismatched origins are rejected.
- **`WS_IDLE_TIMEOUT_SECONDS = 300`**: During non-market hours the streaming endpoints will produce no data, so this timeout will fire on idle overnight connections. This is intentional — force reconnection at market open rather than holding dead connections.
