"""
Alerts seed helpers — alert rules and delivery logs.
Each function inserts rows and flushes; the caller's transaction provides rollback.
"""

from datetime import datetime, timedelta, timezone

from app.models.alert_delivery_log import AlertDeliveryLog
from app.models.alert_rule import AlertRule
from sqlalchemy.orm import Session


def seed_alert_rules(db: Session) -> list[AlertRule]:
    rules = [
        AlertRule(
            name="Volume Spike — Browser Push",
            is_active=True,
            scanner_types=["pre_market_volume_spike"],
            severity_filter="high",
            cooldown_minutes=30,
            channels=["browser_push"],
            channel_config={},
            auto_trade=False,
        ),
        AlertRule(
            name="Any Event — Email + Chat",
            is_active=True,
            scanner_types=[],
            severity_filter="any",
            cooldown_minutes=60,
            channels=["email", "google_chat"],
            channel_config={
                "email": "trader@example.com",
                "google_chat_webhook": "https://chat.googleapis.com/webhook/test",
            },
            auto_trade=False,
        ),
        AlertRule(
            name="Liquidity Hunt — Webhook",
            is_active=True,
            scanner_types=["liquidity_hunt"],
            severity_filter="medium",
            cooldown_minutes=15,
            channels=["webhook"],
            channel_config={"webhook_url": "https://hooks.example.com/alert"},
            auto_trade=False,
        ),
        AlertRule(
            name="Inactive Rule",
            is_active=False,
            scanner_types=["oversold_bounce"],
            severity_filter="low",
            cooldown_minutes=120,
            channels=[],
            channel_config={},
            auto_trade=False,
        ),
    ]
    for rule in rules:
        db.add(rule)
    db.flush()
    return rules


def seed_alert_delivery_logs(
    db: Session, rules: list[AlertRule]
) -> list[AlertDeliveryLog]:
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    specs = [
        (
            rules[0],
            "AAPL",
            "pre_market_volume_spike",
            "browser_push",
            "sent",
            None,
            now,
        ),
        (
            rules[0],
            "MSFT",
            "pre_market_volume_spike",
            "browser_push",
            "sent",
            None,
            now - timedelta(hours=1),
        ),
        (
            rules[1],
            "NVDA",
            "pre_market_volume_spike",
            "email",
            "sent",
            None,
            now - timedelta(hours=2),
        ),
        (
            rules[1],
            "MRNA",
            "liquidity_hunt",
            "google_chat",
            "failed",
            "Webhook timeout",
            now - timedelta(hours=3),
        ),
        (
            rules[2],
            "BNTX",
            "liquidity_hunt",
            "webhook",
            "sent",
            None,
            now - timedelta(hours=4),
        ),
        (
            rules[2],
            "AAPL",
            "liquidity_hunt",
            "webhook",
            "failed",
            "Connection refused",
            now - timedelta(hours=5),
        ),
    ]
    logs = []
    for rule, ticker, scanner_type, channel, status, error, delivered_at in specs:
        log = AlertDeliveryLog(
            rule_id=rule.id,
            ticker=ticker,
            scanner_type=scanner_type,
            channel=channel,
            status=status,
            error_message=error,
            delivered_at=delivered_at,
        )
        db.add(log)
        logs.append(log)
    db.flush()
    return logs
