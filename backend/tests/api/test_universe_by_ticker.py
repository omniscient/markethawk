import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.main import app
from app.models import StockUniverse, StockUniverseTicker
from app.core.database import get_db

client = TestClient(app)


def _seed(db: Session, universe_name: str, ticker: str, is_active: bool = True) -> StockUniverse:
    universe = StockUniverse(
        name=universe_name,
        description=None,
        criteria={},
        is_active=is_active,
    )
    db.add(universe)
    db.flush()
    db.add(StockUniverseTicker(universe_id=universe.id, ticker=ticker))
    db.flush()
    return universe


def test_returns_universes_for_ticker(db: Session):
    _seed(db, "Momentum", "AAPL")
    _seed(db, "Tech Picks", "AAPL")

    app.dependency_overrides[get_db] = lambda: db
    response = client.get("/api/universe/by-ticker/AAPL")
    app.dependency_overrides.clear()

    assert response.status_code == 200
    names = [u["name"] for u in response.json()]
    assert "Momentum" in names
    assert "Tech Picks" in names


def test_returns_empty_for_unknown_ticker(db: Session):
    app.dependency_overrides[get_db] = lambda: db
    response = client.get("/api/universe/by-ticker/ZZZZ")
    app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == []


def test_excludes_inactive_universes(db: Session):
    _seed(db, "Active Universe", "MSFT", is_active=True)
    _seed(db, "Inactive Universe", "MSFT", is_active=False)

    app.dependency_overrides[get_db] = lambda: db
    response = client.get("/api/universe/by-ticker/MSFT")
    app.dependency_overrides.clear()

    assert response.status_code == 200
    names = [u["name"] for u in response.json()]
    assert "Active Universe" in names
    assert "Inactive Universe" not in names


def test_ticker_lookup_is_case_insensitive(db: Session):
    _seed(db, "Mixed Case", "NVDA")

    app.dependency_overrides[get_db] = lambda: db
    response = client.get("/api/universe/by-ticker/nvda")
    app.dependency_overrides.clear()

    assert response.status_code == 200
    assert len(response.json()) >= 1
