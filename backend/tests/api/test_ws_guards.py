"""
Tests for WebSocket resource-exhaustion guards (issue #377).

Verifies:
- Per-user connection cap (WS_MAX_CONNECTIONS_PER_USER) -> 1008 before accept()
- Global connection cap (WS_MAX_CONNECTIONS_GLOBAL) -> 1008 before accept()
- Origin validation: mismatched Origin -> 1008; missing Origin -> allowed
- ws_limits counter semantics (unit tests)

Infrastructure note: `api/conftest.py` provides `override_get_db` (autouse=True)
which wires `get_db` to the test session — auth succeeds for a valid token.
"""

import os
import uuid

os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret-key-for-unit-tests-only-aaa")
os.environ.setdefault("WS_MAX_CONNECTIONS_PER_USER", "10")
os.environ.setdefault("WS_MAX_CONNECTIONS_GLOBAL", "100")

from app.core.config import get_settings

get_settings.cache_clear()

from unittest.mock import MagicMock, patch

import pytest
from fastapi import WebSocketException
from fastapi.testclient import TestClient
from fastapi.websockets import WebSocketDisconnect

from app.core.auth import verify_ws_origin
from app.core.ws_limits import (
    get_global_count,
    get_per_user_count,
    reset_counts,
    ws_connection_slot,
)
from app.main import app
from app.models.user import User

client = TestClient(app, raise_server_exceptions=False)


# ─── Fixtures ──────────────────────────────────────────────────────────────────

TEST_USER_ID = "00000000-0000-0000-0000-000000000077"


@pytest.fixture(autouse=True)
def clean_ws_counts():
    reset_counts()
    yield
    reset_counts()


@pytest.fixture
def mock_auth():
    """Override ws_get_current_user and verify_ws_origin dependencies on all routes."""
    mock_user = User(
        id=uuid.UUID(TEST_USER_ID),
        username="wsguard_test",
        password_hash="x",
        is_active=True,
    )
    from app.core.auth import ws_get_current_user
    from app.main import app

    app.dependency_overrides[ws_get_current_user] = lambda: mock_user
    yield mock_user
    app.dependency_overrides.pop(ws_get_current_user, None)


@pytest.fixture
def mock_auth_with_origin():
    """Override only ws_get_current_user so origin guard still fires."""
    mock_user = User(
        id=uuid.UUID(TEST_USER_ID),
        username="wsguard_test",
        password_hash="x",
        is_active=True,
    )
    from app.core.auth import ws_get_current_user
    from app.main import app

    app.dependency_overrides[ws_get_current_user] = lambda: mock_user
    yield mock_user
    app.dependency_overrides.pop(ws_get_current_user, None)


# ─── Unit tests: ws_limits ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_ws_connection_slot_increments_and_decrements():
    user_id = "test-user-123"
    assert get_per_user_count(user_id) == 0
    assert get_global_count() == 0

    async with ws_connection_slot(user_id):
        assert get_per_user_count(user_id) == 1
        assert get_global_count() == 1

    assert get_per_user_count(user_id) == 0
    assert get_global_count() == 0


@pytest.mark.asyncio
async def test_ws_connection_slot_per_user_cap_raises_1008():
    user_id = "capped-user"
    settings = get_settings()
    cap = settings.WS_MAX_CONNECTIONS_PER_USER

    # Fill up to cap
    slots = []
    for _ in range(cap):
        ctx = ws_connection_slot(user_id)
        await ctx.__aenter__()
        slots.append(ctx)

    assert get_per_user_count(user_id) == cap

    with pytest.raises(WebSocketException) as exc_info:
        async with ws_connection_slot(user_id):
            pass

    assert exc_info.value.code == 1008
    assert "limit" in (exc_info.value.reason or "").lower()

    # Cleanup
    for ctx in slots:
        await ctx.__aexit__(None, None, None)


@pytest.mark.asyncio
async def test_ws_connection_slot_global_cap_raises_1008():
    settings = get_settings()
    global_cap = settings.WS_MAX_CONNECTIONS_GLOBAL

    slots = []
    for i in range(global_cap):
        ctx = ws_connection_slot(f"user-{i}")
        await ctx.__aenter__()
        slots.append(ctx)

    assert get_global_count() == global_cap

    with pytest.raises(WebSocketException) as exc_info:
        async with ws_connection_slot("overflow-user"):
            pass

    assert exc_info.value.code == 1008
    assert "limit" in (exc_info.value.reason or "").lower()

    for ctx in slots:
        await ctx.__aexit__(None, None, None)


@pytest.mark.asyncio
async def test_ws_connection_slot_releases_on_exception():
    user_id = "error-user"

    with pytest.raises(RuntimeError):
        async with ws_connection_slot(user_id):
            raise RuntimeError("test error")

    assert get_per_user_count(user_id) == 0
    assert get_global_count() == 0


# ─── Unit tests: verify_ws_origin ────────────────────────────────────────────


def _make_websocket(origin=None):
    ws = MagicMock()
    ws.headers = {"origin": origin} if origin is not None else {}
    return ws


def test_verify_ws_origin_missing_origin_is_allowed():
    ws = _make_websocket(origin=None)
    # Should not raise
    verify_ws_origin(ws)


def test_verify_ws_origin_matching_origin_is_allowed():
    ws = _make_websocket(origin="http://localhost:3333")
    with patch("app.core.auth.get_settings") as mock_get_settings:
        mock_settings = MagicMock()
        mock_settings.CORS_ORIGINS = ["http://localhost:3333"]
        mock_get_settings.return_value = mock_settings
        # Should not raise
        verify_ws_origin(ws)


def test_verify_ws_origin_mismatched_origin_raises_1008():
    ws = _make_websocket(origin="https://evil.example.com")
    with patch("app.core.auth.get_settings") as mock_get_settings:
        mock_settings = MagicMock()
        mock_settings.CORS_ORIGINS = ["http://localhost:3333"]
        mock_get_settings.return_value = mock_settings

        with pytest.raises(WebSocketException) as exc_info:
            verify_ws_origin(ws)

    assert exc_info.value.code == 1008
    assert "Origin" in (exc_info.value.reason or "")


# ─── Integration tests: cap rejection via HTTP TestClient ─────────────────────


def test_per_user_cap_rejected_before_accept(mock_auth):
    """Filling per-user cap then connecting again is rejected with 1008."""
    settings = get_settings()
    cap = settings.WS_MAX_CONNECTIONS_PER_USER

    # Manually fill the counter for this user
    from app.core import ws_limits

    ws_limits._per_user_counts[TEST_USER_ID] = cap
    ws_limits._global_count = cap

    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect("/api/v1/news/ws"):
            pass

    assert exc_info.value.code == 1008
    assert "limit" in (exc_info.value.reason or "").lower()


def test_global_cap_rejected_before_accept(mock_auth):
    """Filling global cap causes the next connection to be rejected with 1008."""
    settings = get_settings()

    from app.core import ws_limits

    ws_limits._global_count = settings.WS_MAX_CONNECTIONS_GLOBAL

    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect("/api/v1/news/ws"):
            pass

    assert exc_info.value.code == 1008
    assert "limit" in (exc_info.value.reason or "").lower()


def test_origin_mismatch_rejected_before_accept(mock_auth_with_origin):
    """A mismatched Origin header is rejected with 1008."""
    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect(
            "/api/v1/tweets/feed",
            headers={"origin": "https://evil.example.com"},
        ):
            pass

    assert exc_info.value.code == 1008
    assert "Origin" in (exc_info.value.reason or "")


def test_missing_origin_allowed(mock_auth_with_origin):
    """A connection without an Origin header is allowed (non-browser client).

    The connection is accepted but we don't actually send any messages, so
    it closes normally via disconnect on our side.
    """
    try:
        with client.websocket_connect(
            "/api/v1/tweets/feed",
            # No 'origin' header — simulates a non-browser client
        ) as ws:
            pass
    except WebSocketDisconnect as exc:
        assert exc.code != 1008, (
            f"Missing-origin should not trigger 1008, got {exc.code}"
        )
