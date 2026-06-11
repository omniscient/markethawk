"""
Tests for DiscoveryService — Polygon client interactions mocked via unittest.mock.

Patch target: app.services.discovery_service.RESTClient
(DiscoveryService imports `from polygon import RESTClient` so the module-local
name must be patched, not `polygon.RESTClient` directly.)
"""

import datetime
from unittest.mock import MagicMock, patch

from sqlalchemy.orm import Session

from app.models.futures_contract import FuturesContract
from app.models.ticker_reference import TickerReference
from app.services.discovery_service import DiscoveryService

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


# ── run_screen — integration smoke test ───────────────────────────────────


def test_run_screen_dispatches_stocks_and_futures(db: Session):
    """run_screen dispatches to both StockScreener and FuturesScreener when both asset classes requested."""
    # Seed a stock ticker
    db.add(TickerReference(ticker="SMKE", name="Smoke Test Corp", sector="Technology"))
    # Seed a futures contract
    db.add(
        FuturesContract(
            symbol="CL",
            exchange="NYMEX",
            contract_month="20260321",
            expiry_date=datetime.date(2026, 3, 21),
        )
    )
    db.flush()

    with patch("app.services.discovery_service.RESTClient"):
        service = DiscoveryService(db)
        results = service.run_screen(
            {"asset_classes": ["stocks", "futures"], "futures_symbols": "CL"}
        )

    tickers = {r["ticker"] for r in results}
    assert "SMKE" in tickers
    assert "CL" in tickers

    asset_classes = {r["asset_class"] for r in results}
    assert "stocks" in asset_classes
    assert "futures" in asset_classes
