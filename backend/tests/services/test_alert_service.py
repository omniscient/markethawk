"""
Tests for AlertRuleService — rule matching, cooldown logic, and delivery dispatch.
"""

from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from sqlalchemy.orm import Session

from app.models.alert_delivery_log import AlertDeliveryLog
from app.models.alert_rule import AlertRule
from app.models.scanner_event import ScannerEvent
from app.services.alert_service import (
    AlertRuleService,
    _validate_jsonb_dict,
    save_event,
)

# ── helpers ────────────────────────────────────────────────────────────────


def _rule(
    db,
    scanner_types=None,
    severity_filter="any",
    cooldown_minutes=0,
    is_active=True,
    channels=None,
):
    r = AlertRule(
        name="Test Rule",
        is_active=is_active,
        scanner_types=scanner_types or [],
        severity_filter=severity_filter,
        cooldown_minutes=cooldown_minutes,
        channels=channels or [],
        channel_config={},
    )
    db.add(r)
    db.flush()
    return r


def _event(db, scanner_type="pre_market_volume_spike", severity="high"):
    ev = ScannerEvent(
        ticker="AAPL",
        event_date=date.today(),
        scanner_type=scanner_type,
        severity=severity,
        indicators={},
        criteria_met={},
        metadata_={},
    )
    db.add(ev)
    db.flush()
    return ev


# ── get_matching_rules ────────────────────────────────────────────────────


def test_matches_rule_with_empty_scanner_types_filter(db: Session):
    rule = _rule(db, scanner_types=[])
    event = _event(db)
    matched = AlertRuleService.get_matching_rules(event, db)
    assert rule in matched


def test_matches_rule_when_scanner_type_in_filter(db: Session):
    rule = _rule(db, scanner_types=["pre_market_volume_spike"])
    event = _event(db, scanner_type="pre_market_volume_spike")
    matched = AlertRuleService.get_matching_rules(event, db)
    assert rule in matched


def test_excludes_rule_when_scanner_type_not_in_filter(db: Session):
    rule = _rule(db, scanner_types=["oversold_bounce"])
    event = _event(db, scanner_type="pre_market_volume_spike")
    matched = AlertRuleService.get_matching_rules(event, db)
    assert rule not in matched


def test_excludes_inactive_rule(db: Session):
    rule = _rule(db, is_active=False)
    event = _event(db)
    matched = AlertRuleService.get_matching_rules(event, db)
    assert rule not in matched


def test_severity_filter_match(db: Session):
    rule = _rule(db, severity_filter="high")
    event = _event(db, severity="high")
    matched = AlertRuleService.get_matching_rules(event, db)
    assert rule in matched


def test_severity_filter_no_match(db: Session):
    rule = _rule(db, severity_filter="high")
    event = _event(db, severity="low")
    matched = AlertRuleService.get_matching_rules(event, db)
    assert rule not in matched


# ── is_on_cooldown ────────────────────────────────────────────────────────


def test_no_cooldown_returns_false(db: Session):
    rule = _rule(db, cooldown_minutes=0)
    assert AlertRuleService.is_on_cooldown(rule, "AAPL", db) is False


def test_cooldown_active_when_recent_delivery_exists(db: Session):
    rule = _rule(db, cooldown_minutes=60)
    log = AlertDeliveryLog(
        rule_id=rule.id,
        ticker="AAPL",
        scanner_type="pre_market_volume_spike",
        channel="browser_push",
        status="sent",
        delivered_at=datetime.now(timezone.utc).replace(tzinfo=None)
        - timedelta(minutes=5),
    )
    db.add(log)
    db.flush()
    assert AlertRuleService.is_on_cooldown(rule, "AAPL", db) is True


def test_cooldown_expired_returns_false(db: Session):
    rule = _rule(db, cooldown_minutes=30)
    log = AlertDeliveryLog(
        rule_id=rule.id,
        ticker="AAPL",
        scanner_type="pre_market_volume_spike",
        channel="browser_push",
        status="sent",
        delivered_at=datetime.now(timezone.utc).replace(tzinfo=None)
        - timedelta(hours=2),
    )
    db.add(log)
    db.flush()
    assert AlertRuleService.is_on_cooldown(rule, "AAPL", db) is False


# ── _validate_jsonb_dict ──────────────────────────────────────────────────


def test_validate_jsonb_dict_accepts_plain_dict():
    _validate_jsonb_dict({"key": "value", "num": 1}, "field")


def test_validate_jsonb_dict_rejects_non_dict():
    with pytest.raises(ValueError, match="must be a dict"):
        _validate_jsonb_dict(["not", "a", "dict"], "field")


def test_validate_jsonb_dict_rejects_datetime_value():
    from datetime import datetime

    with pytest.raises(ValueError, match="non-JSON-serializable"):
        _validate_jsonb_dict({"ts": datetime(2026, 1, 1)}, "field")


def test_validate_jsonb_dict_rejects_decimal_value():
    from decimal import Decimal

    with pytest.raises(ValueError, match="non-JSON-serializable"):
        _validate_jsonb_dict({"amount": Decimal("1.23")}, "field")


# ── save_event validation ─────────────────────────────────────────────────


def test_save_event_rejects_invalid_severity(db: Session):
    with patch(
        "app.services.event_helpers.compute_event_severity", return_value="critical"
    ):
        with pytest.raises(ValueError, match="Invalid severity"):
            save_event(
                db,
                ticker="AAPL",
                event_date=date.today(),
                scanner_type="pre_market_volume_spike",
                indicators={"relative_volume": 5.0},
                criteria_met={},
                enrichment={},
            )


def test_save_event_rejects_non_serializable_indicators(db: Session):
    from datetime import datetime

    with pytest.raises(ValueError, match="non-JSON-serializable"):
        save_event(
            db,
            ticker="AAPL",
            event_date=date.today(),
            scanner_type="pre_market_volume_spike",
            indicators={"ts": datetime(2026, 1, 1)},
            criteria_met={},
            enrichment={},
        )


@patch("app.services.alert_service.trigger_scanner_alert")
def test_save_event_accepts_valid_payload(mock_trigger, db: Session):
    result = save_event(
        db,
        ticker="AAPL",
        event_date=date.today(),
        scanner_type="pre_market_volume_spike",
        indicators={"relative_volume": 5.0},
        criteria_met={"volume_ok": True},
        enrichment={"source": "test"},
    )
    assert "id" in result
    assert result["ticker"] == "AAPL"
    mock_trigger.assert_called_once_with(result["id"])
