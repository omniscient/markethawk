"""
Provider mock helpers.
Patches DataProviderFactory so no real Polygon calls are made during tests.
"""

from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock

import pytest

from app.providers import DataProviderFactory


def _make_canned_bars(ticker: str, count: int = 5) -> list[dict]:
    """Return `count` realistic OHLCV dicts anchored to (now - count days)."""
    base = datetime.now(timezone.utc) - timedelta(days=count)
    bars = []
    price = 150.0
    for i in range(count):
        open_ = round(price + i * 0.5, 2)
        close = round(open_ + 0.25, 2)
        bars.append(
            {
                "timestamp": base + timedelta(days=i),
                "open": open_,
                "high": round(close + 0.75, 2),
                "low": round(open_ - 0.5, 2),
                "close": close,
                "volume": 1_000_000 + i * 50_000,
                "vwap": round((open_ + close) / 2, 2),
                "transactions": 5000 + i * 100,
            }
        )
    return bars


def _make_canned_ticker_details(ticker: str) -> dict:
    return {
        "name": f"{ticker} Corp",
        "sector": "Technology",
        "industry": "Software",
        "market_cap": 500_000_000,
        "description": f"Fictional company for {ticker}",
    }


@pytest.fixture
def mock_polygon_provider():
    """
    Replace the 'massive' (Polygon) provider in DataProviderFactory with a
    MagicMock that returns canned data.  Restores the real provider on teardown.
    """
    mock = MagicMock()
    mock.name = "massive"
    mock.supported_asset_classes = ["stocks"]
    mock.is_available.return_value = (True, "Ready (mock)")
    mock.get_historical_bars.side_effect = lambda symbol, **kwargs: _make_canned_bars(symbol)
    mock.get_ticker_details.side_effect = lambda symbol: _make_canned_ticker_details(symbol)
    mock.get_aggregates = mock.get_historical_bars  # alias used by some callers

    original = DataProviderFactory._providers.get("massive")
    DataProviderFactory._providers["massive"] = mock

    yield mock

    if original is not None:
        DataProviderFactory._providers["massive"] = original
    else:
        DataProviderFactory._providers.pop("massive", None)
