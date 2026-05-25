"""
Integration tests for news API endpoints.
Runs against a real Postgres DB (via testcontainers).
Polygon is never called — seed_news_articles populates the DB directly,
and mock_news_provider patches httpx for any test touching POST /refresh.
"""

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.main import app
from tests.fixtures.providers import mock_news_provider, seed_news_articles  # noqa: F401

client = TestClient(app)


# ---------------------------------------------------------------------------
# GET /api/news/recent — list
# ---------------------------------------------------------------------------


def test_recent_empty_db_returns_empty_list(db: Session):
    response = client.get("/api/news/recent")

    assert response.status_code == 200
    assert response.json() == []


def test_recent_returns_seeded_articles(db: Session):
    seed_news_articles(db, count=3)

    response = client.get("/api/news/recent")

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 3


def test_recent_response_shape(db: Session):
    seed_news_articles(db, count=1)

    response = client.get("/api/news/recent")

    assert response.status_code == 200
    article = response.json()[0]
    assert "id" in article
    assert "title" in article
    assert "published_utc" in article
    assert "article_url" in article
    assert "tickers" in article


def test_recent_ordered_newest_first(db: Session):
    seed_news_articles(db, count=3)

    response = client.get("/api/news/recent")

    assert response.status_code == 200
    articles = response.json()
    times = [a["published_utc"] for a in articles]
    assert times == sorted(times, reverse=True)


def test_recent_capped_at_100_articles(db: Session):
    seed_news_articles(db, count=105)

    response = client.get("/api/news/recent")

    assert response.status_code == 200
    assert len(response.json()) == 100


# ---------------------------------------------------------------------------
# GET /api/news/recent?ticker=X — filter by ticker
# ---------------------------------------------------------------------------


def test_recent_ticker_filter_returns_matching_articles(db: Session):
    seed_news_articles(db, count=2, tickers=["AAPL"])
    seed_news_articles(db, count=2, tickers=["MSFT"])

    response = client.get("/api/news/recent?ticker=AAPL")

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    for article in data:
        assert "AAPL" in article["tickers"]


def test_recent_ticker_filter_no_match_returns_empty(db: Session):
    seed_news_articles(db, count=3, tickers=["NVDA"])

    response = client.get("/api/news/recent?ticker=TSLA")

    assert response.status_code == 200
    assert response.json() == []


def test_recent_ticker_filter_is_case_insensitive(db: Session):
    seed_news_articles(db, count=2, tickers=["AAPL"])

    response = client.get("/api/news/recent?ticker=aapl")

    assert response.status_code == 200
    assert len(response.json()) == 2


def test_recent_no_ticker_param_returns_all_articles(db: Session):
    seed_news_articles(db, count=2, tickers=["AAPL"])
    seed_news_articles(db, count=2, tickers=["MSFT"])

    response = client.get("/api/news/recent")

    assert response.status_code == 200
    assert len(response.json()) == 4


# ---------------------------------------------------------------------------
# GET /api/news/preferences
# ---------------------------------------------------------------------------


def test_get_preferences_creates_default_when_none(db: Session):
    response = client.get("/api/news/preferences")

    assert response.status_code == 200
    data = response.json()
    assert data["tracked_tickers"] == []
    assert data["tracked_universes"] == []


def test_get_preferences_response_shape(db: Session):
    response = client.get("/api/news/preferences")

    assert response.status_code == 200
    data = response.json()
    assert "id" in data
    assert "tracked_tickers" in data
    assert "tracked_universes" in data
    assert "refresh_interval_minutes" in data
    assert "created_at" in data
    assert "updated_at" in data


def test_get_preferences_idempotent(db: Session):
    r1 = client.get("/api/news/preferences")
    r2 = client.get("/api/news/preferences")

    assert r1.status_code == 200
    assert r2.status_code == 200
    assert r1.json()["id"] == r2.json()["id"]


# ---------------------------------------------------------------------------
# PUT /api/news/preferences
# ---------------------------------------------------------------------------


def test_put_preferences_updates_tracked_tickers(db: Session):
    response = client.put(
        "/api/news/preferences",
        json={"tracked_tickers": ["AAPL", "NVDA"], "tracked_universes": []},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["tracked_tickers"] == ["AAPL", "NVDA"]


def test_put_preferences_updates_refresh_interval(db: Session):
    response = client.put(
        "/api/news/preferences",
        json={"tracked_tickers": [], "tracked_universes": [], "refresh_interval_minutes": 15},
    )

    assert response.status_code == 200
    assert response.json()["refresh_interval_minutes"] == 15


def test_put_preferences_persists_on_get(db: Session):
    client.put(
        "/api/news/preferences",
        json={"tracked_tickers": ["TSLA"], "tracked_universes": []},
    )
    response = client.get("/api/news/preferences")

    assert response.status_code == 200
    assert "TSLA" in response.json()["tracked_tickers"]


def test_put_preferences_creates_if_none_exist(db: Session):
    response = client.put(
        "/api/news/preferences",
        json={"tracked_tickers": ["AMD"], "tracked_universes": []},
    )

    assert response.status_code == 200
    assert response.json()["tracked_tickers"] == ["AMD"]


# ---------------------------------------------------------------------------
# POST /api/news/refresh — triggers Celery task (apply_async mocked)
# ---------------------------------------------------------------------------


def test_refresh_returns_ok_and_task_id(mock_news_provider):
    fake_result = MagicMock()
    fake_result.id = "test-task-id-abc123"

    with patch("app.tasks.poll_massive_news.apply_async", return_value=fake_result):
        response = client.post("/api/news/refresh")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "task_id" in data


def test_refresh_polygon_not_called_directly(mock_news_provider):
    fake_result = MagicMock()
    fake_result.id = "test-task-id-def456"

    with patch("app.tasks.poll_massive_news.apply_async", return_value=fake_result):
        client.post("/api/news/refresh")

    mock_news_provider.assert_not_called()
