"""
Integration tests for /api/trading endpoints.
DI override is handled by tests/api/conftest.py autouse fixture.
"""
from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.main import app
from app.models.auto_trade_order import AutoTradeOrder
from app.models.trading_strategy import TradingStrategy

client = TestClient(app)


# ── helpers ────────────────────────────────────────────────────────────────

def _strategy(db, name="Test Strategy", paper_mode=True):
    s = TradingStrategy(
        name=name,
        is_active=True,
        paper_mode=paper_mode,
        requires_approval=False,
        direction="long_only",
        max_trades_per_day=5,
        max_concurrent_positions=3,
        stop_pct=Decimal("2.0"),
        risk_per_trade_pct=Decimal("1.0"),
        risk_reward_ratio=Decimal("2.0"),
        allowed_sessions=["regular"],
    )
    db.add(s)
    db.flush()
    return s


def _order(db, strategy, symbol="AAPL", status="submitted"):
    o = AutoTradeOrder(
        trading_strategy_id=strategy.id,
        symbol=symbol,
        side="long",
        event_date=date.today(),
        status=status,
        is_paper=True,
        broker_order_id="PAPER-TEST-1",
        trigger_price=Decimal("100.00"),
    )
    db.add(o)
    db.flush()
    return o


# ── GET /strategies ────────────────────────────────────────────────────────

def test_list_strategies_returns_200(db: Session):
    response = client.get("/api/trading/strategies")
    assert response.status_code == 200
    assert isinstance(response.json(), list)


def test_list_strategies_contains_created(db: Session):
    _strategy(db, name="Visible Strategy")
    db.flush()
    response = client.get("/api/trading/strategies")
    names = [s["name"] for s in response.json()]
    assert "Visible Strategy" in names


# ── POST /strategies ───────────────────────────────────────────────────────

def test_create_strategy_returns_201(db: Session):
    payload = {"name": "New Strategy", "stop_pct": 2.5, "direction": "long_only"}
    response = client.post("/api/trading/strategies", json=payload)
    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "New Strategy"
    assert "id" in data
    assert data["paper_mode"] is True   # safety default


def test_create_strategy_defaults_paper_mode(db: Session):
    response = client.post("/api/trading/strategies", json={"name": "Safe"})
    assert response.status_code == 201
    assert response.json()["paper_mode"] is True


# ── GET /strategies/{id} ──────────────────────────────────────────────────

def test_get_strategy_returns_200(db: Session):
    s = _strategy(db)
    response = client.get(f"/api/trading/strategies/{s.id}")
    assert response.status_code == 200
    assert response.json()["id"] == s.id


def test_get_strategy_not_found_returns_404(db: Session):
    response = client.get("/api/trading/strategies/999999")
    assert response.status_code == 404


# ── PATCH /strategies/{id} ────────────────────────────────────────────────

def test_patch_strategy_updates_field(db: Session):
    s = _strategy(db)
    response = client.patch(
        f"/api/trading/strategies/{s.id}",
        json={"is_active": False},
    )
    assert response.status_code == 200
    assert response.json()["is_active"] is False


def test_patch_strategy_not_found_returns_404(db: Session):
    response = client.patch("/api/trading/strategies/999999", json={"is_active": True})
    assert response.status_code == 404


# ── DELETE /strategies/{id} ───────────────────────────────────────────────

def test_delete_strategy_returns_204(db: Session):
    s = _strategy(db)
    response = client.delete(f"/api/trading/strategies/{s.id}")
    assert response.status_code == 204


def test_delete_strategy_soft_deletes(db: Session):
    s = _strategy(db)
    client.delete(f"/api/trading/strategies/{s.id}")
    db.refresh(s)
    assert s.is_active is False


def test_delete_strategy_with_open_orders_returns_409(db: Session):
    s = _strategy(db)
    _order(db, s, status="submitted")
    response = client.delete(f"/api/trading/strategies/{s.id}")
    assert response.status_code == 409


def test_delete_strategy_not_found_returns_404(db: Session):
    response = client.delete("/api/trading/strategies/999999")
    assert response.status_code == 404


# ── GET /orders ────────────────────────────────────────────────────────────

def test_list_orders_returns_200(db: Session):
    response = client.get("/api/trading/orders")
    assert response.status_code == 200
    assert isinstance(response.json(), list)


def test_list_orders_contains_created(db: Session):
    s = _strategy(db)
    o = _order(db, s, symbol="TSLA")
    response = client.get("/api/trading/orders")
    ids = [r["id"] for r in response.json()]
    assert o.id in ids


# ── GET /orders/{id} ──────────────────────────────────────────────────────

def test_get_order_returns_200(db: Session):
    s = _strategy(db)
    o = _order(db, s)
    response = client.get(f"/api/trading/orders/{o.id}")
    assert response.status_code == 200
    assert response.json()["id"] == o.id


def test_get_order_not_found_returns_404(db: Session):
    response = client.get("/api/trading/orders/999999")
    assert response.status_code == 404


# ── POST /orders/{id}/approve ─────────────────────────────────────────────

def test_approve_pending_order_sets_submitted(db: Session):
    s = _strategy(db)
    o = _order(db, s, status="pending_approval")
    response = client.post(f"/api/trading/orders/{o.id}/approve")
    assert response.status_code == 200
    assert response.json()["status"] == "submitted"


# ── POST /orders/{id}/reject ──────────────────────────────────────────────

def test_reject_pending_order_sets_rejected(db: Session):
    s = _strategy(db)
    o = _order(db, s, status="pending_approval")
    response = client.post(
        f"/api/trading/orders/{o.id}/reject",
        json={"reason": "Too risky"},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "rejected"


# ── POST /orders/{id}/cancel ──────────────────────────────────────────────

def test_cancel_submitted_order_sets_cancelled(db: Session):
    s = _strategy(db)
    o = _order(db, s, status="submitted")
    response = client.post(f"/api/trading/orders/{o.id}/cancel")
    assert response.status_code == 200
    assert response.json()["status"] == "cancelled"


def test_cancel_already_closed_order_returns_409(db: Session):
    s = _strategy(db)
    o = _order(db, s, status="closed")
    response = client.post(f"/api/trading/orders/{o.id}/cancel")
    assert response.status_code == 409


# ── GET /stats ────────────────────────────────────────────────────────────

def test_stats_returns_expected_shape(db: Session):
    response = client.get("/api/trading/stats")
    assert response.status_code == 200
    data = response.json()
    assert "total_orders" in data
    assert "by_status" in data
    assert "period_days" in data
    assert "win_rate" in data


# ── GET /config + PATCH /config ───────────────────────────────────────────

def test_get_config_returns_200(db: Session):
    response = client.get("/api/trading/config")
    assert response.status_code == 200
    data = response.json()
    assert "AUTO_TRADING_ENABLED" in data
    assert "PAPER_ACCOUNT_SIZE" in data


def test_patch_config_updates_enabled_flag(db: Session):
    response = client.patch(
        "/api/trading/config",
        json={"AUTO_TRADING_ENABLED": True},
    )
    assert response.status_code == 200
    assert response.json()["AUTO_TRADING_ENABLED"] is True
