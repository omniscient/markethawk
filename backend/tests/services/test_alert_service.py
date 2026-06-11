"""
Tests for AlertRuleService — rule matching, cooldown logic, and delivery dispatch.
"""

from datetime import date, datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.models.alert_delivery_log import AlertDeliveryLog
from app.models.alert_rule import AlertRule
from app.models.scanner_event import ScannerEvent
from app.services.alert_service import AlertRuleService

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
