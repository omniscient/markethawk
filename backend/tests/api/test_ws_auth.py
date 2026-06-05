"""
Tests for WebSocket authentication enforcement (issue #191).

All WS endpoints must reject connections without a valid access_token cookie
(close code 1008) and accept connections with a valid token.
"""

import os
import uuid

os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret-key-for-unit-tests-only-aaa")

from app.core.config import get_settings

get_settings.cache_clear()

import pytest
from fastapi.testclient import TestClient
from fastapi.websockets import WebSocketDisconnect

from app.core.auth import create_access_token, ws_get_current_user
from app.main import app
from app.models.user import User

client = TestClient(app, raise_server_exceptions=False)

# All protected WS endpoints
WS_ENDPOINTS = [
    "/api/v1/live/ws/AAPL/minute",
    "/api/v1/live/ws/watchlist",
    "/api/v1/live/ws/scan-task/test-task-id",
    "/api/v1/scanner/ws/runs/test-task-id",
    "/api/v1/news/ws",
    "/api/v1/system/ws/tasks",
    "/api/v1/tweets/feed",
]


@pytest.mark.parametrize("url", WS_ENDPOINTS)
def test_ws_rejected_without_token(url, db):
    """Unauthenticated WS connect must be closed with code 1008."""
    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect(url):
            pass
    assert exc_info.value.code == 1008


@pytest.mark.parametrize("url", WS_ENDPOINTS)
def test_ws_rejected_with_invalid_token(url, db):
    """A malformed JWT must be rejected with code 1008."""
    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect(url, cookies={"access_token": "not.a.valid.jwt"}):
            pass
    assert exc_info.value.code == 1008


def test_ws_auth_dependency_accepts_valid_token(db):
    """ws_get_current_user returns the User when token and DB record are valid."""
    from unittest.mock import MagicMock

    user = User(
        id=uuid.UUID("00000000-0000-0000-0000-000000000099"),
        username="wsauthtest",
        password_hash="x",
        is_active=True,
    )
    db.add(user)
    db.flush()

    token = create_access_token(str(user.id))

    mock_ws = MagicMock()
    mock_ws.cookies = {"access_token": token}

    result = ws_get_current_user(mock_ws, db)
    assert result.id == user.id
    assert result.username == "wsauthtest"


def test_ws_auth_dependency_rejects_inactive_user(db):
    """ws_get_current_user raises WebSocketException for a deactivated user."""
    from unittest.mock import MagicMock

    from fastapi import WebSocketException

    user = User(
        id=uuid.UUID("00000000-0000-0000-0000-000000000098"),
        username="inactive",
        password_hash="x",
        is_active=False,
    )
    db.add(user)
    db.flush()

    token = create_access_token(str(user.id))

    mock_ws = MagicMock()
    mock_ws.cookies = {"access_token": token}

    with pytest.raises(WebSocketException) as exc_info:
        ws_get_current_user(mock_ws, db)
    assert exc_info.value.code == 1008
