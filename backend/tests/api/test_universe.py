"""
Integration tests for universe API endpoints.
Runs against a real Postgres DB (via testcontainers).
"""

from app.main import app
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from tests.fixtures.core import seed_monitored_stocks, seed_tickers, seed_universes

client = TestClient(app)


# ---------------------------------------------------------------------------
# GET /api/universe/list
# ---------------------------------------------------------------------------


def test_list_returns_only_active_universes(db: Session):
    seed_universes(db)

    response = client.get("/api/universe/list")

    assert response.status_code == 200
    data = response.json()
    assert all(u["is_active"] for u in data)
    names = [u["name"] for u in data]
    assert "Tech Stocks" in names
    assert "Biotech" in names
    assert "Inactive Universe" not in names


def test_list_returns_empty_when_no_universes(db: Session):
    response = client.get("/api/universe/list")

    assert response.status_code == 200
    assert response.json() == []


def test_list_response_shape(db: Session):
    seed_universes(db)

    response = client.get("/api/universe/list")

    assert response.status_code == 200
    universe = response.json()[0]
    for field in (
        "id",
        "uuid",
        "name",
        "description",
        "criteria",
        "created_at",
        "is_active",
    ):
        assert field in universe, f"Missing field: {field}"


def test_list_include_stats_false_returns_zero_counts(db: Session):
    seed_universes(db)

    response = client.get("/api/universe/list?include_stats=false")

    assert response.status_code == 200
    for u in response.json():
        assert u["ticker_count"] == 0
        assert u["aggregate_count"] == 0


# ---------------------------------------------------------------------------
# POST /api/universe/create
# ---------------------------------------------------------------------------


def test_create_universe_returns_new_record(db: Session):
    payload = {
        "name": "My New Universe",
        "description": "Test description",
        "criteria": {"sector": "tech"},
    }

    response = client.post("/api/universe/create", json=payload)

    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "My New Universe"
    assert data["description"] == "Test description"
    assert data["criteria"] == {"sector": "tech"}
    assert data["is_active"] is True
    assert "id" in data
    assert "uuid" in data


def test_create_universe_without_description(db: Session):
    payload = {"name": "Minimal Universe", "criteria": {}}

    response = client.post("/api/universe/create", json=payload)

    assert response.status_code == 200
    assert response.json()["name"] == "Minimal Universe"
    assert response.json()["description"] is None


# ---------------------------------------------------------------------------
# PUT /api/universe/{id}
# ---------------------------------------------------------------------------


def test_update_universe_name(db: Session):
    universes = seed_universes(db)
    uid = universes[0].id

    response = client.put(f"/api/universe/{uid}", json={"name": "Updated Name"})

    assert response.status_code == 200
    assert response.json()["name"] == "Updated Name"
    assert response.json()["id"] == uid


def test_update_universe_description_and_criteria(db: Session):
    universes = seed_universes(db)
    uid = universes[1].id

    response = client.put(
        f"/api/universe/{uid}",
        json={"description": "New desc", "criteria": {"sector": "pharma"}},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["description"] == "New desc"
    assert data["criteria"] == {"sector": "pharma"}


def test_update_universe_not_found(db: Session):
    response = client.put("/api/universe/99999", json={"name": "Ghost"})

    assert response.status_code == 404


# ---------------------------------------------------------------------------
# DELETE /api/universe/{id}
# ---------------------------------------------------------------------------


def test_delete_universe_soft_deletes(db: Session):
    universes = seed_universes(db)
    uid = universes[0].id

    response = client.delete(f"/api/universe/{uid}")

    assert response.status_code == 200
    assert "deleted" in response.json()["message"].lower()

    # Confirm it no longer appears in list
    list_response = client.get("/api/universe/list")

    ids = [u["id"] for u in list_response.json()]
    assert uid not in ids


def test_delete_universe_not_found(db: Session):
    response = client.delete("/api/universe/99999")

    assert response.status_code == 404


# ---------------------------------------------------------------------------
# GET /api/universe/{id}/stocks
# ---------------------------------------------------------------------------


def test_get_universe_stocks_returns_seeded_stocks(db: Session):
    universes = seed_universes(db)
    seed_monitored_stocks(db, universes)
    uid = universes[0].id  # Tech Stocks: AAPL, MSFT, NVDA

    response = client.get(f"/api/universe/{uid}/stocks")

    assert response.status_code == 200
    tickers = {s["ticker"] for s in response.json()}
    assert tickers == {"AAPL", "MSFT", "NVDA"}


def test_get_universe_stocks_empty_when_none(db: Session):
    universes = seed_universes(db)
    uid = universes[0].id

    response = client.get(f"/api/universe/{uid}/stocks")

    assert response.status_code == 200
    assert response.json() == []


def test_get_universe_stocks_response_shape(db: Session):
    universes = seed_universes(db)
    seed_monitored_stocks(db, universes)
    uid = universes[0].id

    response = client.get(f"/api/universe/{uid}/stocks")

    assert response.status_code == 200
    stock = response.json()[0]
    for field in ("id", "ticker", "is_active", "added_date"):
        assert field in stock, f"Missing field: {field}"


# ---------------------------------------------------------------------------
# POST /api/universe/{id}/refresh
# ---------------------------------------------------------------------------


def test_refresh_universe_not_found(db: Session):
    response = client.post("/api/universe/99999/refresh")

    assert response.status_code == 404


def test_refresh_universe_returns_completed_status(db: Session):
    universes = seed_universes(db)
    uid = universes[0].id

    response = client.post(f"/api/universe/{uid}/refresh")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "completed"
    assert "added" in data
    assert isinstance(data["added"], int)


# ---------------------------------------------------------------------------
# GET /api/universe/by-ticker/{ticker}
# ---------------------------------------------------------------------------


def test_by_ticker_returns_universes_containing_ticker(db: Session):
    universes = seed_universes(db)
    seed_tickers(db, universes)

    response = client.get("/api/universe/by-ticker/AAPL")

    assert response.status_code == 200
    names = [u["name"] for u in response.json()]
    assert "Tech Stocks" in names
    assert "Biotech" in names  # AAPL appears in both


def test_by_ticker_excludes_inactive_universes(db: Session):
    universes = seed_universes(db)
    seed_tickers(db, universes)

    response = client.get("/api/universe/by-ticker/AAPL")

    assert response.status_code == 200
    names = [u["name"] for u in response.json()]
    assert "Inactive Universe" not in names


def test_by_ticker_returns_empty_for_unknown_ticker(db: Session):
    seed_universes(db)

    response = client.get("/api/universe/by-ticker/ZZZZ")

    assert response.status_code == 200
    assert response.json() == []
