# WebSocket Authentication — Design Spec

**Date:** 2026-06-05
**Issue:** #191 — [arch-v2][HIGH] Authenticate WebSocket connections (currently bypass auth)
**Status:** Spec generated → pending review
**Author:** MarketHawk Refinement Pipeline

## Overview

`AuthMiddleware` in `backend/app/main.py` short-circuits for any non-HTTP ASGI scope:

```python
if scope["type"] != "http":
    await self.app(scope, receive, send)
    return
```

WebSocket connections have scope type `"websocket"`, so they bypass JWT validation entirely. All ~9 WS endpoints currently call `websocket.accept()` with no token check, allowing unauthenticated clients to stream live ticks, scan progress, system task state, and tweet signals.

## Requirements

1. **Validate `access_token` cookie before `accept()`** on all WebSocket endpoints.
2. **Reject unauthenticated handshakes with WS close code 1008** (Policy Violation).
3. **Auth depth must match HTTP auth** — JWT decode + DB user lookup (`is_active=True`), not JWT-only.
4. **One representative test per router file** verifying that a WS connect without a valid cookie is rejected with close code 1008.
5. No changes to the HTTP auth path; existing `get_current_user` dependency and `AuthMiddleware` are untouched.

## Affected Endpoints

| Router file | Endpoint | Handler |
|-------------|----------|---------|
| `routers/live_data.py` | `/api/v1/live/ws/{ticker}/{resolution}` | `stock_live_websocket` |
| `routers/live_data.py` | `/api/v1/live/ws/watchlist` | `watchlist_live_websocket` |
| `routers/live_data.py` | `/api/v1/live/ws/scan-task/{task_id}` | `scan_task_websocket` |
| `routers/scanner.py` | `/api/v1/scanner/ws/runs/{task_id}` | `scan_run_websocket` |
| `routers/news.py` | `/api/v1/news/ws` | `news_websocket` |
| `routers/system.py` | `/api/v1/system/ws/tasks` | `system_tasks_websocket` |
| `routers/tweets.py` | `/api/v1/tweets/feed` | `tweet_feed_websocket` |

## Chosen Approach — Per-Handler Dependency (`get_current_user_ws`)

### Design

Create a WebSocket-specific auth dependency in `backend/app/core/auth.py` that shares the same cookie/JWT/DB-lookup logic as `get_current_user` but raises `WebSocketException(code=1008)` instead of `HTTPException(401)`:

```python
from fastapi import WebSocket
from fastapi.websockets import WebSocketDisconnect
from starlette.websockets import WebSocketException

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

### Handler changes

Each WS handler gains one additional parameter:

```python
@router.websocket("/ws/watchlist")
@limiter.exempt
async def watchlist_live_websocket(
    websocket: WebSocket,
    _user: User = Depends(get_current_user_ws),   # ← added
):
    await websocket.accept()
    ...
```

FastAPI resolves `Depends(get_current_user_ws)` before entering the handler body and before `accept()` is called. If auth fails, FastAPI sends the WS close frame with code 1008 during the handshake — the connection is never fully established.

### Implementation checklist

- [ ] Add `get_current_user_ws` to `backend/app/core/auth.py`
- [ ] Add `_user: User = Depends(get_current_user_ws)` to all 7 handlers listed above
- [ ] Add tests (one per router file): `tests/api/test_live_data_ws_auth.py`, `tests/api/test_scanner_ws_auth.py`, `tests/api/test_news_ws_auth.py`, `tests/api/test_system_ws_auth.py`, `tests/api/test_tweets_ws_auth.py` — each asserts `WebSocketDisconnect.code == 1008` when no cookie is sent

## Alternatives Considered

### A — Extend `AuthMiddleware` to handle `websocket` scope

Parse the cookie from raw ASGI header bytes, validate the JWT, and reject the HTTP upgrade with a 401/403 if invalid. Centralizes auth in one place.

**Rejected:** The `AuthMiddleware` comment explicitly warns it is a minimal hand-rolled pure-ASGI passthrough to avoid GZip/streaming breakage from `BaseHTTPMiddleware`. Adding byte-level cookie parsing plus a second protocol's reject sequence (WebSocket close frame) to this already-specialized class risks subtle ASGI message-ordering bugs. The reject path for HTTP returns a `JSONResponse`, which is meaningless for a WS scope — a separate WS reject path would be needed anyway.

### B — JWT-only dependency (no DB user lookup)

Skip the DB call at WS handshake time; validate only JWT signature and expiry.

**Rejected:** Creates auth divergence between HTTP and WS paths. Does not enforce `is_active=True`. At the scale of a single-user app the per-handshake DB round-trip cost is negligible. Consistent behavior across transport types is easier to reason about and audit.

## Open Questions

- None blocking implementation.

## Assumptions

- **Cookie sent automatically by browser:** Browsers send same-origin cookies on WS upgrade requests. The frontend doesn't need changes — it already relies on cookie auth for HTTP (`withCredentials: true`), and that same cookie is present in the WS handshake.
- **`WebSocketException` is Starlette-native:** FastAPI/Starlette supports `WebSocketException` since Starlette 0.20. The dependency raising it before `accept()` is the intended pattern for pre-accept rejection.
- **Sync DB session for WS auth:** The codebase uses sync SQLAlchemy (`create_engine` + `sessionmaker` in `database.py`). `get_current_user_ws` uses the same sync `get_db` dependency as `get_current_user`.
