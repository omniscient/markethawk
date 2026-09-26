"""#388: the per-ticker live WS reports Polygon stream status as a feed_status frame."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

from app.core.auth import verify_ws_origin, ws_get_current_user
from app.main import app


def test_ticker_ws_sends_feed_status_on_connect():
    app.dependency_overrides[ws_get_current_user] = lambda: SimpleNamespace(id="u-388")
    app.dependency_overrides[verify_ws_origin] = lambda: None
    manager = "app.routers.live_data.websocket_manager"
    try:
        with (
            patch(f"{manager}.subscribe", MagicMock()),
            patch(f"{manager}.register", AsyncMock(return_value=asyncio.Queue())),
            patch(f"{manager}.unregister", MagicMock()),
            patch(f"{manager}.feed_status", MagicMock(return_value=False)),
            patch("app.routers.live_data.FEED_STATUS_POLL_SECONDS", 0.05),
            patch("app.routers.live_data.settings.WS_IDLE_TIMEOUT_SECONDS", 0.3),
        ):
            with TestClient(app).websocket_connect("/api/v1/live/ws/AAPL/minute") as ws:
                assert ws.receive_json() == {
                    "type": "feed_status",
                    "polygon_ws_connected": False,
                }
    finally:
        app.dependency_overrides.pop(ws_get_current_user, None)
        app.dependency_overrides.pop(verify_ws_origin, None)
