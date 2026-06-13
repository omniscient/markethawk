from unittest.mock import MagicMock, patch

from app.services.websocket_manager import StockWebSocketManager


def test_start_skips_polygon_client_when_live_websocket_disabled():
    StockWebSocketManager._instance = None
    manager = StockWebSocketManager()
    manager.api_key = "demo_no_live_key"

    with (
        patch("app.services.websocket_manager.settings.LIVE_WEBSOCKET_ENABLED", False),
        patch("app.services.websocket_manager.WebSocketClient") as client_cls,
        patch("app.services.websocket_manager.asyncio.get_event_loop", return_value=MagicMock()),
    ):
        manager.start()

    client_cls.assert_not_called()
    assert manager._connected is False
