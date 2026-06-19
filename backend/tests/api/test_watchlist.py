"""
Integration tests for /api/watchlist endpoints.
DI override is handled by tests/api/conftest.py autouse fixture.
Note: router calls db.commit() for write operations. Tests use unique symbols
      via uuid to avoid unique-constraint conflicts across test runs.
"""

import uuid

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.main import app
from app.models.active_watchlist import WATCHLIST_SOFT_LIMIT, ActiveWatchlist

client = TestClient(app)

# uuid4().hex is 0-9a-f; map the digits onto letters so generated symbols are
# valid letters-only tickers (F-INPUT-02 Ticker pattern rejects digits).
_HEX_TO_ALPHA = str.maketrans("0123456789abcdef", "GHIJKLMNOPABCDEF")


def _sym(prefix="T"):
    """Generate a unique letters-only ≤5-char symbol to avoid unique-constraint conflicts."""
    body = uuid.uuid4().hex.translate(_HEX_TO_ALPHA)
    return (prefix + body).upper()[:5]


def _post(symbol, security_type="STK"):
    return client.post(
        "/api/v1/watchlist/", json={"symbol": symbol, "security_type": security_type}
    )


# ── GET / ─────────────────────────────────────────────────────────────────


def test_list_watchlist_returns_200(db: Session):
    response = client.get("/api/v1/watchlist/")
    assert response.status_code == 200
    assert isinstance(response.json(), list)


def test_list_watchlist_contains_added_entry(db: Session):
    sym = _sym("L")
    _post(sym)
    response = client.get("/api/v1/watchlist/")
    symbols = [e["symbol"] for e in response.json()]
    assert sym in symbols


# ── POST / ────────────────────────────────────────────────────────────────


def test_add_to_watchlist_returns_201(db: Session):
    sym = _sym("A")
    response = _post(sym)
    assert response.status_code == 201
    data = response.json()
    assert data["symbol"] == sym
    assert "id" in data
    assert "added_at" in data


def test_add_duplicate_returns_409(db: Session):
    sym = _sym("D")
    _post(sym)
    response = _post(sym)
    assert response.status_code == 409


def test_add_beyond_soft_limit_returns_422(db: Session):
    """
    Fill the watchlist to the soft limit using direct DB inserts (flushed but not
    committed, so they're visible to the route's count query within the same session
    without persisting across tests).
    """
    existing_count = db.query(ActiveWatchlist).count()
    needed = WATCHLIST_SOFT_LIMIT - existing_count
    for i in range(max(needed, 0)):
        db.add(ActiveWatchlist(symbol=f"F{i:04d}"[:5], security_type="STK"))
    db.flush()
    response = _post(_sym("N"))
    assert response.status_code == 422


# ── PATCH /{symbol} ───────────────────────────────────────────────────────


def test_update_watchlist_notes(db: Session):
    sym = _sym("U")
    _post(sym)
    response = client.patch(f"/api/v1/watchlist/{sym}", json={"notes": "Watching closely"})
    assert response.status_code == 200
    assert response.json()["notes"] == "Watching closely"


def test_update_watchlist_not_found_returns_404(db: Session):
    response = client.patch("/api/v1/watchlist/ZZZZ9", json={"notes": "nothing"})
    assert response.status_code == 404


# ── DELETE /{symbol} ──────────────────────────────────────────────────────


def test_delete_from_watchlist_returns_204(db: Session):
    sym = _sym("E")
    _post(sym)
    response = client.delete(f"/api/v1/watchlist/{sym}")
    assert response.status_code == 204


def test_delete_removes_entry_from_list(db: Session):
    sym = _sym("R")
    _post(sym)
    client.delete(f"/api/v1/watchlist/{sym}")
    response = client.get("/api/v1/watchlist/")
    symbols = [e["symbol"] for e in response.json()]
    assert sym not in symbols


def test_delete_not_found_returns_404(db: Session):
    response = client.delete("/api/v1/watchlist/ZZZZ8")
    assert response.status_code == 404
