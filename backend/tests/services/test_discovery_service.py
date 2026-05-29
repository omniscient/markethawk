"""
Tests for DiscoveryService — Polygon client interactions mocked via unittest.mock.

Patch target: app.services.discovery_service.RESTClient
(DiscoveryService imports `from polygon import RESTClient` so the module-local
name must be patched, not `polygon.RESTClient` directly.)
"""

from unittest.mock import MagicMock, patch

from app.services.discovery_service import DiscoveryService
from sqlalchemy.orm import Session

# ── sync_fundamental_data ──────────────────────────────────────────────────


def test_sync_fundamental_data_starts_celery_task(db: Session):
    """sync_fundamental_data delegates to Celery — verify it returns 'started'."""
    with (
        patch("app.services.discovery_service.RESTClient"),
        patch("app.tasks.sync_tickers_batch") as mock_task,
    ):
        mock_task.delay = MagicMock()
        service = DiscoveryService(db)
        result = service.sync_fundamental_data()

    assert result["status"] == "started"
    mock_task.delay.assert_called_once()


# ── update_daily_metrics_snapshot ─────────────────────────────────────────


def test_update_daily_metrics_no_aggs_returns_early(db: Session):
    """When Polygon returns no aggregates, method returns without error."""
    with patch("app.services.discovery_service.RESTClient") as MockRESTClient:
        mock_client = MockRESTClient.return_value
        mock_client.get_grouped_daily_aggs.return_value = []
        service = DiscoveryService(db)
        result = service.update_daily_metrics_snapshot()
        assert result is None


def test_update_daily_metrics_skips_unknown_tickers(db: Session):
    """Tickers not in ticker_reference table are skipped silently."""
    mock_agg = MagicMock()
    mock_agg.ticker = "UNKNWN"
    mock_agg.open = 10.0
    mock_agg.high = 11.0
    mock_agg.low = 9.5
    mock_agg.close = 10.5
    mock_agg.volume = 100000
    mock_agg.vwap = 10.2
    mock_agg.transactions = 500

    with patch("app.services.discovery_service.RESTClient") as MockRESTClient:
        mock_client = MockRESTClient.return_value
        mock_client.get_grouped_daily_aggs.return_value = [mock_agg]
        service = DiscoveryService(db)
        # Should not raise even though ticker is not in DB
        service.update_daily_metrics_snapshot()
