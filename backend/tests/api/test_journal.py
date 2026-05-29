"""
Integration tests for journal API endpoints.
Runs against a real Postgres DB (via testcontainers).
"""

from app.main import app
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from tests.fixtures.journal import seed_journal_entries, seed_tags, seed_trades

client = TestClient(app)


# ---------------------------------------------------------------------------
# GET /api/journal/trades
# ---------------------------------------------------------------------------


def test_list_trades_returns_all_seeded(db: Session):
    seed_trades(db)

    response = client.get("/api/journal/trades")

    assert response.status_code == 200
    assert len(response.json()) == 6


def test_list_trades_empty_when_none(db: Session):
    response = client.get("/api/journal/trades")

    assert response.status_code == 200
    assert response.json() == []


def test_list_trades_filter_by_symbol(db: Session):
    seed_trades(db)

    response = client.get("/api/journal/trades?symbol=AAPL")

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    assert all(t["symbol"] == "AAPL" for t in data)


def test_list_trades_filter_by_status_open(db: Session):
    seed_trades(db)

    response = client.get("/api/journal/trades?status=open")

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    assert all(t["status"] == "open" for t in data)


def test_list_trades_filter_by_status_closed(db: Session):
    seed_trades(db)

    response = client.get("/api/journal/trades?status=closed")

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 4
    assert all(t["status"] == "closed" for t in data)


def test_list_trades_response_shape(db: Session):
    seed_trades(db)

    response = client.get("/api/journal/trades")

    assert response.status_code == 200
    trade = response.json()[0]
    for field in (
        "id",
        "symbol",
        "status",
        "side",
        "quantity",
        "avg_entry_price",
        "executions",
        "tags",
        "created_at",
        "updated_at",
    ):
        assert field in trade, f"Missing field: {field}"


# ---------------------------------------------------------------------------
# POST /api/journal/trades
# ---------------------------------------------------------------------------


def test_create_trade_returns_new_record(db: Session):
    payload = {
        "symbol": "GOOG",
        "side": "long",
        "status": "open",
        "quantity": "10",
        "avg_entry_price": "175.50",
    }

    response = client.post("/api/journal/trades", json=payload)

    assert response.status_code == 200
    data = response.json()
    assert data["symbol"] == "GOOG"
    assert data["side"] == "long"
    assert data["status"] == "open"
    assert "id" in data
    assert data["executions"] == []
    assert data["tags"] == []


def test_create_trade_minimal_payload(db: Session):
    payload = {"symbol": "SPY", "status": "open"}

    response = client.post("/api/journal/trades", json=payload)

    assert response.status_code == 200
    assert response.json()["symbol"] == "SPY"


# ---------------------------------------------------------------------------
# GET /api/journal/trades/{id}
# ---------------------------------------------------------------------------


def test_get_trade_by_id_happy_path(db: Session):
    trades = seed_trades(db)
    trade_id = trades[0].id

    response = client.get(f"/api/journal/trades/{trade_id}")

    assert response.status_code == 200
    data = response.json()
    assert data["id"] == trade_id
    assert data["symbol"] == trades[0].symbol


def test_get_trade_by_id_not_found(db: Session):
    response = client.get("/api/journal/trades/99999")

    assert response.status_code == 404


# ---------------------------------------------------------------------------
# PATCH /api/journal/trades/{id}
# ---------------------------------------------------------------------------


def test_update_trade_status(db: Session):
    trades = seed_trades(db)
    open_trade = next(t for t in trades if t.status == "open")
    trade_id = open_trade.id

    response = client.patch(
        f"/api/journal/trades/{trade_id}", json={"status": "closed"}
    )

    assert response.status_code == 200
    assert response.json()["status"] == "closed"
    assert response.json()["id"] == trade_id


def test_update_trade_notes(db: Session):
    trades = seed_trades(db)
    trade_id = trades[0].id

    response = client.patch(
        f"/api/journal/trades/{trade_id}",
        json={"notes": "Strong breakout with volume confirmation."},
    )

    assert response.status_code == 200
    assert response.json()["notes"] == "Strong breakout with volume confirmation."


def test_update_trade_not_found(db: Session):
    response = client.patch("/api/journal/trades/99999", json={"status": "closed"})

    assert response.status_code == 404


# ---------------------------------------------------------------------------
# GET /api/journal/stats
# ---------------------------------------------------------------------------


def test_stats_returns_correct_shape(db: Session):
    seed_trades(db)

    response = client.get("/api/journal/stats")

    assert response.status_code == 200
    data = response.json()
    for field in (
        "total_trades",
        "winning_trades",
        "losing_trades",
        "win_rate",
        "total_pnl",
        "avg_profit",
        "profit_factor",
    ):
        assert field in data, f"Missing field: {field}"


def test_stats_counts_match_seeded_trades(db: Session):
    seed_trades(db)

    response = client.get("/api/journal/stats")

    assert response.status_code == 200
    data = response.json()
    # 6 total trades; 3 with positive net_pnl, 1 negative, 2 open (no net_pnl)
    assert data["total_trades"] == 6
    assert data["winning_trades"] == 3
    assert data["losing_trades"] == 1
    assert 0 < data["win_rate"] <= 1


def test_stats_empty_database(db: Session):
    response = client.get("/api/journal/stats")

    assert response.status_code == 200
    data = response.json()
    assert data["total_trades"] == 0
    assert data["win_rate"] == 0


# ---------------------------------------------------------------------------
# GET /api/journal/entries
# ---------------------------------------------------------------------------


def test_list_entries_returns_seeded(db: Session):
    seed_journal_entries(db)

    response = client.get("/api/journal/entries")

    assert response.status_code == 200
    assert len(response.json()) == 3


def test_list_entries_empty(db: Session):
    response = client.get("/api/journal/entries")

    assert response.status_code == 200
    assert response.json() == []


def test_list_entries_response_shape(db: Session):
    seed_journal_entries(db)

    response = client.get("/api/journal/entries")

    assert response.status_code == 200
    entry = response.json()[0]
    for field in (
        "id",
        "entry_date",
        "content",
        "sentiment",
        "created_at",
        "updated_at",
    ):
        assert field in entry, f"Missing field: {field}"


# ---------------------------------------------------------------------------
# POST /api/journal/entries
# ---------------------------------------------------------------------------


def test_create_journal_entry(db: Session):
    payload = {
        "entry_date": "2026-05-11",
        "content": "Excellent session. Captured a clean gap-and-go on NVDA.",
        "sentiment": "bullish",
    }

    response = client.post("/api/journal/entries", json=payload)

    assert response.status_code == 200
    data = response.json()
    assert data["content"] == payload["content"]
    assert data["sentiment"] == "bullish"
    assert "id" in data


def test_create_journal_entry_without_sentiment(db: Session):
    payload = {
        "entry_date": "2026-05-10",
        "content": "Quiet day, no trades taken.",
    }

    response = client.post("/api/journal/entries", json=payload)

    assert response.status_code == 200
    assert response.json()["sentiment"] is None


# ---------------------------------------------------------------------------
# GET /api/journal/tags
# ---------------------------------------------------------------------------


def test_list_tags_returns_seeded(db: Session):
    seed_tags(db)

    response = client.get("/api/journal/tags")

    assert response.status_code == 200
    names = {t["name"] for t in response.json()}
    assert names == {"momentum", "breakout", "reversal"}


def test_list_tags_empty(db: Session):
    response = client.get("/api/journal/tags")

    assert response.status_code == 200
    assert response.json() == []


# ---------------------------------------------------------------------------
# POST /api/journal/tags
# ---------------------------------------------------------------------------


def test_create_tag(db: Session):
    payload = {"name": "scalp", "color": "#FF5733"}

    response = client.post("/api/journal/tags", json=payload)

    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "scalp"
    assert data["color"] == "#FF5733"
    assert "id" in data


def test_create_tag_without_color(db: Session):
    payload = {"name": "swing"}

    response = client.post("/api/journal/tags", json=payload)

    assert response.status_code == 200
    assert response.json()["name"] == "swing"
    assert response.json()["color"] is None
