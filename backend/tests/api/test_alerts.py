"""
Integration tests for alerts API endpoints.
Runs against a real Postgres DB (via testcontainers).
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.main import app
from app.core.database import get_db
from tests.fixtures.alerts import seed_alert_rules, seed_alert_delivery_logs

client = TestClient(app)


# ---------------------------------------------------------------------------
# GET /api/alerts/stats
# ---------------------------------------------------------------------------


def test_stats_returns_correct_shape(db: Session):
    app.dependency_overrides[get_db] = lambda: db
    response = client.get("/api/alerts/stats")
    app.dependency_overrides.clear()

    assert response.status_code == 200
    data = response.json()
    for field in ("active_rules", "total_rules", "triggered_today", "delivery_rate", "push_subscriptions"):
        assert field in data, f"Missing field: {field}"


def test_stats_counts_active_rules(db: Session):
    seed_alert_rules(db)  # 3 active, 1 inactive

    app.dependency_overrides[get_db] = lambda: db
    response = client.get("/api/alerts/stats")
    app.dependency_overrides.clear()

    data = response.json()
    assert data["active_rules"] == 3
    assert data["total_rules"] == 4


def test_stats_delivery_rate_reflects_sent_vs_failed(db: Session):
    rules = seed_alert_rules(db)
    seed_alert_delivery_logs(db, rules)  # 4 sent, 2 failed out of 6 total

    app.dependency_overrides[get_db] = lambda: db
    response = client.get("/api/alerts/stats")
    app.dependency_overrides.clear()

    data = response.json()
    # 4 sent / 6 total = 66.7%
    assert data["delivery_rate"] == pytest.approx(66.7, abs=0.1)


def test_stats_empty_db_returns_100_delivery_rate(db: Session):
    app.dependency_overrides[get_db] = lambda: db
    response = client.get("/api/alerts/stats")
    app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["delivery_rate"] == 100.0


# ---------------------------------------------------------------------------
# GET /api/alerts/rules
# ---------------------------------------------------------------------------


def test_list_rules_returns_all_rules(db: Session):
    seed_alert_rules(db)

    app.dependency_overrides[get_db] = lambda: db
    response = client.get("/api/alerts/rules")
    app.dependency_overrides.clear()

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 4
    names = [r["name"] for r in data]
    assert "Volume Spike — Browser Push" in names
    assert "Inactive Rule" in names


def test_list_rules_empty_returns_empty_list(db: Session):
    app.dependency_overrides[get_db] = lambda: db
    response = client.get("/api/alerts/rules")
    app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == []


def test_list_rules_response_shape(db: Session):
    seed_alert_rules(db)

    app.dependency_overrides[get_db] = lambda: db
    response = client.get("/api/alerts/rules")
    app.dependency_overrides.clear()

    assert response.status_code == 200
    rule = response.json()[0]
    for field in (
        "id", "name", "is_active", "scanner_types", "severity_filter",
        "cooldown_minutes", "channels", "channel_config", "auto_trade",
        "created_at",
    ):
        assert field in rule, f"Missing field: {field}"


def test_list_rules_ordered_newest_first(db: Session):
    rules = seed_alert_rules(db)
    last_created_name = rules[-1].name  # last inserted = most recently created

    app.dependency_overrides[get_db] = lambda: db
    response = client.get("/api/alerts/rules")
    app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()[0]["name"] == last_created_name


# ---------------------------------------------------------------------------
# POST /api/alerts/rules
# ---------------------------------------------------------------------------


def test_create_rule_returns_201_and_persists(db: Session):
    payload = {
        "name": "My New Rule",
        "scanner_types": ["pre_market_volume_spike"],
        "severity_filter": "high",
        "cooldown_minutes": 45,
        "channels": ["browser_push"],
        "channel_config": {},
    }

    app.dependency_overrides[get_db] = lambda: db
    response = client.post("/api/alerts/rules", json=payload)
    app.dependency_overrides.clear()

    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "My New Rule"
    assert data["scanner_types"] == ["pre_market_volume_spike"]
    assert data["severity_filter"] == "high"
    assert data["cooldown_minutes"] == 45
    assert data["is_active"] is True
    assert "id" in data


def test_create_rule_applies_defaults(db: Session):
    app.dependency_overrides[get_db] = lambda: db
    response = client.post("/api/alerts/rules", json={})
    app.dependency_overrides.clear()

    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "Untitled Rule"
    assert data["severity_filter"] == "any"
    assert data["cooldown_minutes"] == 60
    assert data["is_active"] is True
    assert data["auto_trade"] is False


def test_create_rule_appears_in_list(db: Session):
    payload = {"name": "Discoverable Rule"}

    app.dependency_overrides[get_db] = lambda: db
    client.post("/api/alerts/rules", json=payload)
    list_response = client.get("/api/alerts/rules")
    app.dependency_overrides.clear()

    names = [r["name"] for r in list_response.json()]
    assert "Discoverable Rule" in names


# ---------------------------------------------------------------------------
# PATCH /api/alerts/rules/{rule_id}
# ---------------------------------------------------------------------------


def test_update_rule_name(db: Session):
    rules = seed_alert_rules(db)
    rule_id = rules[0].id

    app.dependency_overrides[get_db] = lambda: db
    response = client.patch(f"/api/alerts/rules/{rule_id}", json={"name": "Renamed Rule"})
    app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["name"] == "Renamed Rule"
    assert response.json()["id"] == rule_id


def test_update_rule_toggle_active(db: Session):
    rules = seed_alert_rules(db)
    rule_id = rules[0].id  # starts active

    app.dependency_overrides[get_db] = lambda: db
    response = client.patch(f"/api/alerts/rules/{rule_id}", json={"is_active": False})
    app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["is_active"] is False


def test_update_rule_channels(db: Session):
    rules = seed_alert_rules(db)
    rule_id = rules[1].id

    app.dependency_overrides[get_db] = lambda: db
    response = client.patch(
        f"/api/alerts/rules/{rule_id}",
        json={"channels": ["webhook"], "channel_config": {"webhook_url": "https://example.com/hook"}},
    )
    app.dependency_overrides.clear()

    assert response.status_code == 200
    data = response.json()
    assert data["channels"] == ["webhook"]
    assert data["channel_config"]["webhook_url"] == "https://example.com/hook"


def test_update_rule_not_found(db: Session):
    app.dependency_overrides[get_db] = lambda: db
    response = client.patch("/api/alerts/rules/99999", json={"name": "Ghost"})
    app.dependency_overrides.clear()

    assert response.status_code == 404


# ---------------------------------------------------------------------------
# DELETE /api/alerts/rules/{rule_id}
# ---------------------------------------------------------------------------


def test_delete_rule_returns_204(db: Session):
    rules = seed_alert_rules(db)
    rule_id = rules[0].id

    app.dependency_overrides[get_db] = lambda: db
    response = client.delete(f"/api/alerts/rules/{rule_id}")
    app.dependency_overrides.clear()

    assert response.status_code == 204


def test_delete_rule_removes_from_list(db: Session):
    rules = seed_alert_rules(db)
    rule_id = rules[0].id

    app.dependency_overrides[get_db] = lambda: db
    client.delete(f"/api/alerts/rules/{rule_id}")
    list_response = client.get("/api/alerts/rules")
    app.dependency_overrides.clear()

    ids = [r["id"] for r in list_response.json()]
    assert rule_id not in ids


def test_delete_rule_not_found(db: Session):
    app.dependency_overrides[get_db] = lambda: db
    response = client.delete("/api/alerts/rules/99999")
    app.dependency_overrides.clear()

    assert response.status_code == 404


# ---------------------------------------------------------------------------
# GET /api/alerts/logs
# ---------------------------------------------------------------------------


def test_list_logs_returns_seeded_entries(db: Session):
    rules = seed_alert_rules(db)
    seed_alert_delivery_logs(db, rules)

    app.dependency_overrides[get_db] = lambda: db
    response = client.get("/api/alerts/logs")
    app.dependency_overrides.clear()

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 6


def test_list_logs_empty_returns_empty_list(db: Session):
    app.dependency_overrides[get_db] = lambda: db
    response = client.get("/api/alerts/logs")
    app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == []


def test_list_logs_response_shape(db: Session):
    rules = seed_alert_rules(db)
    seed_alert_delivery_logs(db, rules)

    app.dependency_overrides[get_db] = lambda: db
    response = client.get("/api/alerts/logs")
    app.dependency_overrides.clear()

    assert response.status_code == 200
    log = response.json()[0]
    for field in ("id", "rule_id", "ticker", "scanner_type", "channel", "status", "delivered_at"):
        assert field in log, f"Missing field: {field}"


def test_list_logs_ordered_newest_first(db: Session):
    rules = seed_alert_rules(db)
    seed_alert_delivery_logs(db, rules)  # first entry has newest delivered_at

    app.dependency_overrides[get_db] = lambda: db
    response = client.get("/api/alerts/logs")
    app.dependency_overrides.clear()

    data = response.json()
    assert data[0]["ticker"] == "AAPL"  # most recently delivered
    assert data[0]["channel"] == "browser_push"


def test_list_logs_limit_param(db: Session):
    rules = seed_alert_rules(db)
    seed_alert_delivery_logs(db, rules)  # 6 entries

    app.dependency_overrides[get_db] = lambda: db
    response = client.get("/api/alerts/logs?limit=3")
    app.dependency_overrides.clear()

    assert response.status_code == 200
    assert len(response.json()) == 3


def test_list_logs_includes_failed_entries(db: Session):
    rules = seed_alert_rules(db)
    seed_alert_delivery_logs(db, rules)

    app.dependency_overrides[get_db] = lambda: db
    response = client.get("/api/alerts/logs")
    app.dependency_overrides.clear()

    statuses = {log["status"] for log in response.json()}
    assert "sent" in statuses
    assert "failed" in statuses
