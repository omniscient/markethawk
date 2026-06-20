"""
Integration tests for alerts API endpoints.
Runs against a real Postgres DB (via testcontainers).
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.main import app
from tests.fixtures.alerts import seed_alert_delivery_logs, seed_alert_rules

client = TestClient(app)


# ---------------------------------------------------------------------------
# GET /api/alerts/stats
# ---------------------------------------------------------------------------


def test_stats_returns_correct_shape(db: Session):
    response = client.get("/api/v1/alerts/stats")

    assert response.status_code == 200
    data = response.json()
    for field in (
        "active_rules",
        "total_rules",
        "triggered_today",
        "delivery_rate",
        "push_subscriptions",
    ):
        assert field in data, f"Missing field: {field}"


def test_stats_counts_active_rules(db: Session):
    seed_alert_rules(db)  # 3 active, 1 inactive

    response = client.get("/api/v1/alerts/stats")

    data = response.json()
    assert data["active_rules"] == 3
    assert data["total_rules"] == 4


def test_stats_delivery_rate_reflects_sent_vs_failed(db: Session):
    rules = seed_alert_rules(db)
    seed_alert_delivery_logs(db, rules)  # 4 sent, 2 failed out of 6 total

    response = client.get("/api/v1/alerts/stats")

    data = response.json()
    # 4 sent / 6 total = 66.7%
    assert data["delivery_rate"] == pytest.approx(66.7, abs=0.1)


def test_stats_empty_db_returns_100_delivery_rate(db: Session):
    response = client.get("/api/v1/alerts/stats")

    assert response.status_code == 200
    assert response.json()["delivery_rate"] == 100.0


# ---------------------------------------------------------------------------
# GET /api/alerts/rules
# ---------------------------------------------------------------------------


def test_list_rules_returns_all_rules(db: Session):
    seed_alert_rules(db)

    response = client.get("/api/v1/alerts/rules")

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 4
    names = [r["name"] for r in data]
    assert "Volume Spike — Browser Push" in names
    assert "Inactive Rule" in names


def test_list_rules_empty_returns_empty_list(db: Session):
    response = client.get("/api/v1/alerts/rules")

    assert response.status_code == 200
    assert response.json() == []


def test_list_rules_response_shape(db: Session):
    seed_alert_rules(db)

    response = client.get("/api/v1/alerts/rules")

    assert response.status_code == 200
    rule = response.json()[0]
    for field in (
        "id",
        "name",
        "is_active",
        "scanner_types",
        "severity_filter",
        "cooldown_minutes",
        "channels",
        "channel_config",
        "auto_trade",
        "created_at",
    ):
        assert field in rule, f"Missing field: {field}"


def test_list_rules_ordered_newest_first(db: Session):
    rules = seed_alert_rules(db)
    last_created_name = rules[-1].name  # last inserted = most recently created

    response = client.get("/api/v1/alerts/rules")

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

    response = client.post("/api/v1/alerts/rules", json=payload)

    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "My New Rule"
    assert data["scanner_types"] == ["pre_market_volume_spike"]
    assert data["severity_filter"] == "high"
    assert data["cooldown_minutes"] == 45
    assert data["is_active"] is True
    assert "id" in data


def test_create_rule_applies_defaults(db: Session):
    response = client.post("/api/v1/alerts/rules", json={})

    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "Untitled Rule"
    assert data["severity_filter"] == "any"
    assert data["cooldown_minutes"] == 60
    assert data["is_active"] is True
    assert data["auto_trade"] is False


def test_create_rule_appears_in_list(db: Session):
    payload = {"name": "Discoverable Rule"}

    client.post("/api/v1/alerts/rules", json=payload)
    list_response = client.get("/api/v1/alerts/rules")

    names = [r["name"] for r in list_response.json()]
    assert "Discoverable Rule" in names


# ---------------------------------------------------------------------------
# PATCH /api/alerts/rules/{rule_id}
# ---------------------------------------------------------------------------


def test_update_rule_name(db: Session):
    rules = seed_alert_rules(db)
    rule_id = rules[0].id

    response = client.patch(
        f"/api/v1/alerts/rules/{rule_id}", json={"name": "Renamed Rule"}
    )

    assert response.status_code == 200
    assert response.json()["name"] == "Renamed Rule"
    assert response.json()["id"] == rule_id


def test_update_rule_toggle_active(db: Session):
    rules = seed_alert_rules(db)
    rule_id = rules[0].id  # starts active

    response = client.patch(
        f"/api/v1/alerts/rules/{rule_id}", json={"is_active": False}
    )

    assert response.status_code == 200
    assert response.json()["is_active"] is False


def test_update_rule_channels(db: Session):
    rules = seed_alert_rules(db)
    rule_id = rules[1].id

    response = client.patch(
        f"/api/v1/alerts/rules/{rule_id}",
        json={
            "channels": ["webhook"],
            "channel_config": {"webhook_url": "https://example.com/hook"},
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["channels"] == ["webhook"]
    assert data["channel_config"]["webhook_url"] == "https://example.com/hook"


def test_update_rule_not_found(db: Session):
    response = client.patch("/api/v1/alerts/rules/99999", json={"name": "Ghost"})

    assert response.status_code == 404


# ---------------------------------------------------------------------------
# DELETE /api/alerts/rules/{rule_id}
# ---------------------------------------------------------------------------


def test_delete_rule_returns_204(db: Session):
    rules = seed_alert_rules(db)
    rule_id = rules[0].id

    response = client.delete(f"/api/v1/alerts/rules/{rule_id}")

    assert response.status_code == 204


def test_delete_rule_removes_from_list(db: Session):
    rules = seed_alert_rules(db)
    rule_id = rules[0].id

    client.delete(f"/api/v1/alerts/rules/{rule_id}")
    list_response = client.get("/api/v1/alerts/rules")

    ids = [r["id"] for r in list_response.json()]
    assert rule_id not in ids


def test_delete_rule_not_found(db: Session):
    response = client.delete("/api/v1/alerts/rules/99999")

    assert response.status_code == 404


# ---------------------------------------------------------------------------
# GET /api/alerts/logs
# ---------------------------------------------------------------------------


def test_list_logs_returns_seeded_entries(db: Session):
    rules = seed_alert_rules(db)
    seed_alert_delivery_logs(db, rules)

    response = client.get("/api/v1/alerts/logs")

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 6


def test_list_logs_empty_returns_empty_list(db: Session):
    response = client.get("/api/v1/alerts/logs")

    assert response.status_code == 200
    assert response.json() == []


def test_list_logs_response_shape(db: Session):
    rules = seed_alert_rules(db)
    seed_alert_delivery_logs(db, rules)

    response = client.get("/api/v1/alerts/logs")

    assert response.status_code == 200
    log = response.json()[0]
    for field in (
        "id",
        "rule_id",
        "ticker",
        "scanner_type",
        "channel",
        "status",
        "delivered_at",
    ):
        assert field in log, f"Missing field: {field}"


def test_list_logs_ordered_newest_first(db: Session):
    rules = seed_alert_rules(db)
    seed_alert_delivery_logs(db, rules)  # first entry has newest delivered_at

    response = client.get("/api/v1/alerts/logs")

    data = response.json()
    assert data[0]["ticker"] == "AAPL"  # most recently delivered
    assert data[0]["channel"] == "browser_push"


def test_list_logs_limit_param(db: Session):
    rules = seed_alert_rules(db)
    seed_alert_delivery_logs(db, rules)  # 6 entries

    response = client.get("/api/v1/alerts/logs?limit=3")

    assert response.status_code == 200
    assert len(response.json()) == 3


def test_list_logs_includes_failed_entries(db: Session):
    rules = seed_alert_rules(db)
    seed_alert_delivery_logs(db, rules)

    response = client.get("/api/v1/alerts/logs")

    statuses = {log["status"] for log in response.json()}
    assert "sent" in statuses
    assert "failed" in statuses


# ---------------------------------------------------------------------------
# channel_config validation — POST and PATCH
# ---------------------------------------------------------------------------


def test_create_rule_rejects_unknown_channel_config_key(db: Session):
    payload = {
        "name": "Bad Config Rule",
        "channels": ["email"],
        "channel_config": {"gmail": "user@example.com"},
    }

    response = client.post("/api/v1/alerts/rules", json=payload)

    assert response.status_code == 422
    data = response.json()
    assert "channel_config" in data["detail"]


def test_create_rule_accepts_valid_channel_config(db: Session):
    payload = {
        "name": "Good Config Rule",
        "channels": ["email"],
        "channel_config": {"email": "user@example.com"},
    }

    response = client.post("/api/v1/alerts/rules", json=payload)

    assert response.status_code == 201
    assert response.json()["channel_config"]["email"] == "user@example.com"


def test_update_rule_rejects_invalid_channel_config(db: Session):
    rules = seed_alert_rules(db)
    rule_id = rules[0].id

    response = client.patch(
        f"/api/v1/alerts/rules/{rule_id}",
        json={"channel_config": {"slack_webhook": "https://hooks.slack.com/bad"}},
    )

    assert response.status_code == 422
    data = response.json()
    assert "channel_config" in data["detail"]


def test_update_rule_accepts_valid_channel_config(db: Session):
    rules = seed_alert_rules(db)
    rule_id = rules[0].id

    response = client.patch(
        f"/api/v1/alerts/rules/{rule_id}",
        json={"channel_config": {"webhook_url": "https://example.com/hook"}},
    )

    assert response.status_code == 200
    assert (
        response.json()["channel_config"]["webhook_url"] == "https://example.com/hook"
    )


def test_create_rule_rejects_invalid_email_format(db: Session):
    payload = {
        "name": "Invalid Email Rule",
        "channels": ["email"],
        "channel_config": {"email": "not-an-email-address"},
    }

    response = client.post("/api/v1/alerts/rules", json=payload)

    assert response.status_code == 422
    assert "channel_config" in response.json()["detail"]


def test_create_rule_rejects_non_url_webhook(db: Session):
    payload = {
        "name": "Invalid Webhook Rule",
        "channels": ["webhook"],
        "channel_config": {"webhook_url": "not-a-valid-url"},
    }

    response = client.post("/api/v1/alerts/rules", json=payload)

    assert response.status_code == 422
    assert "channel_config" in response.json()["detail"]


def test_create_rule_rejects_http_webhook(db: Session):
    """F-INPUT-02: webhook URLs must be https, not http (returns 422, not 500)."""
    payload = {
        "name": "Insecure Webhook Rule",
        "channels": ["webhook"],
        "channel_config": {"webhook_url": "http://evil.example.com/hook"},
    }

    response = client.post("/api/v1/alerts/rules", json=payload)

    assert response.status_code == 422
    assert "channel_config" in response.json()["detail"]


# ---------------------------------------------------------------------------
# POST /api/alerts/system
# ---------------------------------------------------------------------------


def test_system_notify_returns_503_when_token_unset(db):
    """INTERNAL_API_TOKEN unset → 503 (fail-closed)."""
    from app.core import config as cfg

    original = cfg.settings.INTERNAL_API_TOKEN
    cfg.settings.INTERNAL_API_TOKEN = ""
    try:
        response = client.post(
            "/api/v1/alerts/system",
            json={"title": "Test", "body": "body"},
            headers={"X-Internal-Token": "anything"},
        )
    finally:
        cfg.settings.INTERNAL_API_TOKEN = original

    assert response.status_code == 503


def test_system_notify_returns_401_when_token_missing(db):
    """Missing X-Internal-Token header → 401."""
    from app.core import config as cfg

    original = cfg.settings.INTERNAL_API_TOKEN
    cfg.settings.INTERNAL_API_TOKEN = "secret-token"
    try:
        response = client.post(
            "/api/v1/alerts/system",
            json={"title": "Test", "body": "body"},
        )
    finally:
        cfg.settings.INTERNAL_API_TOKEN = original

    assert response.status_code == 401


def test_system_notify_returns_401_when_token_wrong(db):
    """Wrong X-Internal-Token → 401."""
    from app.core import config as cfg

    original = cfg.settings.INTERNAL_API_TOKEN
    cfg.settings.INTERNAL_API_TOKEN = "correct-token"
    try:
        response = client.post(
            "/api/v1/alerts/system",
            json={"title": "Test", "body": "body"},
            headers={"X-Internal-Token": "wrong-token"},
        )
    finally:
        cfg.settings.INTERNAL_API_TOKEN = original

    assert response.status_code == 401


def test_system_notify_returns_200_with_valid_token(db):
    """Valid token → 200 with a per-channel summary dict."""
    from app.core import config as cfg

    original_token = cfg.settings.INTERNAL_API_TOKEN
    original_email = cfg.settings.OPS_ALERT_EMAIL
    cfg.settings.INTERNAL_API_TOKEN = "valid-secret"
    cfg.settings.OPS_ALERT_EMAIL = ""  # email skipped
    try:
        response = client.post(
            "/api/v1/alerts/system",
            json={"title": "CI failed", "body": "main is red", "channels": ["email"]},
            headers={"X-Internal-Token": "valid-secret"},
        )
    finally:
        cfg.settings.INTERNAL_API_TOKEN = original_token
        cfg.settings.OPS_ALERT_EMAIL = original_email

    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, dict)
    assert "email" in data
    assert data["email"] == "skipped"  # OPS_ALERT_EMAIL was empty


def test_system_notify_delivers_email_when_configured(db):
    """Valid token + OPS_ALERT_EMAIL set + SMTP mocked → email 'sent'."""
    from unittest.mock import MagicMock, patch

    from app.core import config as cfg

    original_token = cfg.settings.INTERNAL_API_TOKEN
    original_email = cfg.settings.OPS_ALERT_EMAIL
    original_user = cfg.settings.SMTP_USER
    cfg.settings.INTERNAL_API_TOKEN = "valid-secret"
    cfg.settings.OPS_ALERT_EMAIL = "ops@example.com"
    cfg.settings.SMTP_USER = "user@example.com"
    cfg.settings.SMTP_PASSWORD = "pw"
    try:
        with patch("smtplib.SMTP") as mock_smtp_cls:
            smtp_instance = MagicMock()
            mock_smtp_cls.return_value.__enter__ = lambda s: smtp_instance
            mock_smtp_cls.return_value.__exit__ = MagicMock(return_value=False)
            response = client.post(
                "/api/v1/alerts/system",
                json={
                    "title": "Deploy done",
                    "body": "v1.2.3 live",
                    "channels": ["email"],
                },
                headers={"X-Internal-Token": "valid-secret"},
            )
    finally:
        cfg.settings.INTERNAL_API_TOKEN = original_token
        cfg.settings.OPS_ALERT_EMAIL = original_email
        cfg.settings.SMTP_USER = original_user

    assert response.status_code == 200
    assert response.json().get("email") == "sent"
