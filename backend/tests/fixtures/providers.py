"""
Provider mock helpers.
Patches DataProviderFactory so no real Polygon calls are made during tests.
Also provides news article seeding and a mock for the Polygon news HTTP call.
"""

import uuid as _uuid
from datetime import datetime, timedelta, timezone
from typing import Optional
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.orm import Session

from app.models.news_article import NewsArticle
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
    mock.get_bars.side_effect = lambda symbol, **kwargs: _make_canned_bars(symbol)
    mock.get_ticker_details.side_effect = lambda symbol: _make_canned_ticker_details(
        symbol
    )
    mock.get_snapshots.return_value = []

    original = DataProviderFactory._providers.get("massive")
    DataProviderFactory._providers["massive"] = mock

    yield mock

    if original is not None:
        DataProviderFactory._providers["massive"] = original
    else:
        DataProviderFactory._providers.pop("massive", None)


def seed_news_articles(
    db: Session,
    count: int = 3,
    tickers: Optional[list[str]] = None,
) -> list[NewsArticle]:
    """
    Insert `count` NewsArticle rows into `db`.
    If `tickers` is provided each article is tagged with all of them;
    otherwise articles cycle through ["AAPL", "MSFT", "NVDA"].
    Returns the list of created rows.
    """
    default_tickers = ["AAPL", "MSFT", "NVDA"]
    base_time = datetime.now(timezone.utc) - timedelta(hours=count)
    rows = []
    for i in range(count):
        article_tickers = (
            tickers
            if tickers is not None
            else [default_tickers[i % len(default_tickers)]]
        )
        row = NewsArticle(
            title=f"Test Article {i + 1}: Market Update",
            author="Test Author",
            published_utc=(base_time + timedelta(hours=i)).replace(tzinfo=None),
            article_url=f"https://test.example.com/news/{_uuid.uuid4()}",
            image_url=f"https://test.example.com/images/{i + 1}.jpg",
            description=f"Description for test article {i + 1}.",
            provider="Test Provider",
            tickers=article_tickers,
        )
        db.add(row)
        rows.append(row)
    db.flush()
    return rows


def _make_canned_polygon_news_response(tickers: list[str] | None = None) -> dict:
    """Return a fake Polygon /v2/reference/news JSON response body."""
    if tickers is None:
        tickers = ["AAPL"]
    now = datetime.now(timezone.utc)
    return {
        "results": [
            {
                "title": "Canned News Article 1",
                "author": "Polygon Test",
                "published_utc": (now - timedelta(hours=2)).strftime(
                    "%Y-%m-%dT%H:%M:%SZ"
                ),
                "article_url": "https://polygon.test/news/canned-1",
                "image_url": "https://polygon.test/images/canned-1.jpg",
                "description": "Canned article 1 description.",
                "publisher": {"name": "PolygonTest"},
                "tickers": tickers,
            },
            {
                "title": "Canned News Article 2",
                "author": "Polygon Test",
                "published_utc": (now - timedelta(hours=1)).strftime(
                    "%Y-%m-%dT%H:%M:%SZ"
                ),
                "article_url": "https://polygon.test/news/canned-2",
                "image_url": None,
                "description": "Canned article 2 description.",
                "publisher": {"name": "PolygonTest"},
                "tickers": tickers,
            },
        ],
        "status": "OK",
        "count": 2,
    }


@pytest.fixture
def mock_futures_provider():
    """
    Replace the 'ibkr' provider in DataProviderFactory with a MagicMock that
    reports as available and supports futures. Restores the real provider on teardown.
    """
    mock = MagicMock()
    mock.name = "ibkr"
    mock.supported_asset_classes = ["futures"]
    mock.is_available.return_value = (True, "Ready (mock)")

    original = DataProviderFactory._providers.get("ibkr")
    DataProviderFactory._providers["ibkr"] = mock

    yield mock

    if original is not None:
        DataProviderFactory._providers["ibkr"] = original
    else:
        DataProviderFactory._providers.pop("ibkr", None)


@pytest.fixture
def mock_news_provider():
    """
    Patch httpx.Client.get so poll_massive_news never calls the real Polygon API.
    Yields the mock for optional assertion in tests.
    """
    from unittest.mock import MagicMock

    fake_response = MagicMock()
    fake_response.status_code = 200
    fake_response.json.return_value = _make_canned_polygon_news_response()
    fake_response.raise_for_status = MagicMock()

    with patch("httpx.Client.get", return_value=fake_response) as mock_get:
        yield mock_get
