from app.main import app
from app.models import StockUniverse, StockUniverseTicker
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

client = TestClient(app)


def _seed(
    db: Session, universe_name: str, ticker: str, is_active: bool = True
) -> StockUniverse:
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

    response = client.get("/api/v1/universe/by-ticker/AAPL")

    assert response.status_code == 200
    names = [u["name"] for u in response.json()]
    assert "Momentum" in names
    assert "Tech Picks" in names


def test_returns_empty_for_unknown_ticker(db: Session):
    response = client.get("/api/v1/universe/by-ticker/ZZZZ")

    assert response.status_code == 200
    assert response.json() == []


def test_excludes_inactive_universes(db: Session):
    _seed(db, "Active Universe", "MSFT", is_active=True)
    _seed(db, "Inactive Universe", "MSFT", is_active=False)

    response = client.get("/api/v1/universe/by-ticker/MSFT")

    assert response.status_code == 200
    names = [u["name"] for u in response.json()]
    assert "Active Universe" in names
    assert "Inactive Universe" not in names


def test_ticker_lookup_is_case_insensitive(db: Session):
    _seed(db, "Mixed Case", "NVDA")

    response = client.get("/api/v1/universe/by-ticker/nvda")

    assert response.status_code == 200
    assert len(response.json()) == 1
    assert response.json()[0]["name"] == "Mixed Case"
