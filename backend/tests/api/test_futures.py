"""
Integration tests for futures API endpoints.
Runs against a real Postgres DB (via testcontainers).
IBKR is never called — the mock_futures_provider fixture intercepts all provider calls.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.main import app
from app.core.database import get_db
from tests.fixtures.providers import mock_futures_provider  # noqa: F401
from tests.fixtures.futures import (
    seed_futures_contracts,
    seed_futures_aggregates,
    seed_futures_rollover,
)

client = TestClient(app)


# ---------------------------------------------------------------------------
# GET /api/futures/contracts/{symbol}
# ---------------------------------------------------------------------------


def test_contracts_returns_correct_shape(db: Session):
    seed_futures_contracts(db, symbol="ES", exchange="CME", count=2)

    app.dependency_overrides[get_db] = lambda: db
    response = client.get("/api/futures/contracts/ES")
    app.dependency_overrides.clear()

    assert response.status_code == 200
    data = response.json()
    assert data["symbol"] == "ES"
    assert data["count"] == 2
    assert len(data["contracts"]) == 2
    contract = data["contracts"][0]
    assert "contract_month" in contract
    assert "exchange" in contract
    assert "is_expired" in contract
    assert "data_downloaded" in contract


def test_contracts_symbol_is_case_insensitive(db: Session):
    seed_futures_contracts(db, symbol="NQ", exchange="CME", count=1)

    app.dependency_overrides[get_db] = lambda: db
    response = client.get("/api/futures/contracts/nq")
    app.dependency_overrides.clear()

    assert response.status_code == 200
    data = response.json()
    assert data["symbol"] == "NQ"
    assert data["count"] == 1


def test_contracts_empty_db_returns_zero(db: Session):
    app.dependency_overrides[get_db] = lambda: db
    response = client.get("/api/futures/contracts/ZZ")
    app.dependency_overrides.clear()

    assert response.status_code == 200
    data = response.json()
    assert data["symbol"] == "ZZ"
    assert data["count"] == 0
    assert data["contracts"] == []


# ---------------------------------------------------------------------------
# GET /api/futures/rollovers/{symbol}
# ---------------------------------------------------------------------------


def test_rollovers_returns_correct_shape(db: Session):
    seed_futures_rollover(
        db,
        symbol="ES",
        exchange="CME",
        from_contract="20250321",
        to_contract="20250620",
    )

    app.dependency_overrides[get_db] = lambda: db
    response = client.get("/api/futures/rollovers/ES")
    app.dependency_overrides.clear()

    assert response.status_code == 200
    data = response.json()
    assert data["symbol"] == "ES"
    assert data["count"] == 1
    rv = data["rollovers"][0]
    assert rv["symbol"] == "ES"
    assert rv["from_contract"] == "20250321"
    assert rv["to_contract"] == "20250620"
    assert rv["roll_date"] == "2025-03-10"
    assert rv["detection_method"] == "volume"


def test_rollovers_empty_db_returns_zero(db: Session):
    app.dependency_overrides[get_db] = lambda: db
    response = client.get("/api/futures/rollovers/ZZ")
    app.dependency_overrides.clear()

    assert response.status_code == 200
    data = response.json()
    assert data["symbol"] == "ZZ"
    assert data["count"] == 0
    assert data["rollovers"] == []


# ---------------------------------------------------------------------------
# GET /api/futures/history/{symbol}
# ---------------------------------------------------------------------------


def test_history_returns_correct_shape(db: Session):
    seed_futures_contracts(db, symbol="ES", exchange="CME", count=1)
    seed_futures_aggregates(db, symbol="ES", contract_month="20250321", count=5)

    app.dependency_overrides[get_db] = lambda: db
    response = client.get("/api/futures/history/ES")
    app.dependency_overrides.clear()

    assert response.status_code == 200
    data = response.json()
    assert data["symbol"] == "ES"
    assert data["timespan"] == "day"
    assert data["data_points"] == 5
    bar = data["data"][0]
    assert "timestamp" in bar
    assert "open" in bar
    assert "high" in bar
    assert "low" in bar
    assert "close" in bar
    assert "volume" in bar


def test_history_empty_db_returns_zero_data_points(db: Session):
    app.dependency_overrides[get_db] = lambda: db
    response = client.get("/api/futures/history/ZZ")
    app.dependency_overrides.clear()

    assert response.status_code == 200
    data = response.json()
    assert data["symbol"] == "ZZ"
    assert data["data_points"] == 0
    assert data["data"] == []


def test_history_symbol_is_case_insensitive(db: Session):
    seed_futures_contracts(db, symbol="NQ", exchange="CME", count=1)
    seed_futures_aggregates(db, symbol="NQ", contract_month="20250321", count=3)

    app.dependency_overrides[get_db] = lambda: db
    response = client.get("/api/futures/history/nq")
    app.dependency_overrides.clear()

    assert response.status_code == 200
    data = response.json()
    assert data["symbol"] == "NQ"
    assert data["data_points"] == 3


# ---------------------------------------------------------------------------
# GET /api/futures/providers
# ---------------------------------------------------------------------------


def test_providers_lists_ibkr(mock_futures_provider):
    response = client.get("/api/futures/providers")

    assert response.status_code == 200
    data = response.json()
    providers = {p["name"]: p for p in data["available"]}
    assert "ibkr" in providers
    assert providers["ibkr"]["available"] is True
    assert "futures" in providers["ibkr"]["classes"]


def test_providers_response_shape(mock_futures_provider):
    response = client.get("/api/futures/providers")

    assert response.status_code == 200
    data = response.json()
    assert "available" in data
    for provider in data["available"]:
        assert "name" in provider
        assert "classes" in provider
        assert "available" in provider
        assert "status_message" in provider
