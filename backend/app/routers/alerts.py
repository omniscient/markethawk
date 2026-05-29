"""
Alerts router — CRUD for alert rules, delivery log, stats, and Web Push endpoints.
"""

import json
import logging
from datetime import date, datetime, timezone
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.alert_delivery_log import AlertDeliveryLog
from app.models.alert_rule import AlertRule
from app.models.push_subscription import PushSubscription
from app.models.scanner_event import ScannerEvent

router = APIRouter(prefix="/api/v1/alerts", tags=["alerts"])
logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────────
# Stats
# ──────────────────────────────────────────────────────────────────────────────


@router.get("/stats")
def get_alert_stats(db: Session = Depends(get_db)) -> Dict[str, Any]:
    """Return dashboard stats for the alerts page header cards."""
    today_start = datetime.combine(date.today(), datetime.min.time())

    active_count = db.query(AlertRule).filter(AlertRule.is_active == True).count()
    total_count = db.query(AlertRule).count()
    triggered_today = (
        db.query(AlertDeliveryLog)
        .filter(
            AlertDeliveryLog.delivered_at >= today_start,
            AlertDeliveryLog.status == "sent",
        )
        .count()
    )
    total_sent = (
        db.query(AlertDeliveryLog).filter(AlertDeliveryLog.status == "sent").count()
    )
    total_failed = (
        db.query(AlertDeliveryLog).filter(AlertDeliveryLog.status == "failed").count()
    )
    total_attempts = total_sent + total_failed
    delivery_rate = (
        round((total_sent / total_attempts * 100), 1) if total_attempts > 0 else 100.0
    )

    push_sub_count = db.query(PushSubscription).count()

    return {
        "active_rules": active_count,
        "total_rules": total_count,
        "triggered_today": triggered_today,
        "delivery_rate": delivery_rate,
        "push_subscriptions": push_sub_count,
    }


# ──────────────────────────────────────────────────────────────────────────────
# Alert Rules — CRUD
# ──────────────────────────────────────────────────────────────────────────────


def _rule_to_dict(rule: AlertRule) -> Dict[str, Any]:
    return {
        "id": rule.id,
        "name": rule.name,
        "is_active": rule.is_active,
        "scanner_types": rule.scanner_types or [],
        "severity_filter": rule.severity_filter,
        "cooldown_minutes": rule.cooldown_minutes,
        "channels": rule.channels or [],
        "channel_config": rule.channel_config or {},
        "auto_trade": rule.auto_trade,
        "trading_strategy_id": rule.trading_strategy_id,
        "created_at": rule.created_at.isoformat() if rule.created_at else None,
        "updated_at": rule.updated_at.isoformat() if rule.updated_at else None,
    }


@router.get("/rules")
def list_rules(db: Session = Depends(get_db)) -> List[Dict[str, Any]]:
    """Return all alert rules ordered by creation date (newest first)."""
    rules = db.query(AlertRule).order_by(AlertRule.created_at.desc()).all()
    return [_rule_to_dict(r) for r in rules]


@router.post("/rules", status_code=201)
def create_rule(
    payload: Dict[str, Any], db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """Create a new alert rule."""
    rule = AlertRule(
        name=payload.get("name", "Untitled Rule"),
        is_active=payload.get("is_active", True),
        scanner_types=payload.get("scanner_types", []),
        severity_filter=payload.get("severity_filter", "any"),
        cooldown_minutes=int(payload.get("cooldown_minutes", 60)),
        channels=payload.get("channels", []),
        channel_config=payload.get("channel_config", {}),
        auto_trade=payload.get("auto_trade", False),
        trading_strategy_id=payload.get("trading_strategy_id"),
    )
    db.add(rule)
    db.commit()
    db.refresh(rule)
    logger.info(f"Created alert rule id={rule.id} name='{rule.name}'")
    return _rule_to_dict(rule)


@router.patch("/rules/{rule_id}")
def update_rule(
    rule_id: int, payload: Dict[str, Any], db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """Update an alert rule (full or partial). Used for toggles too."""
    rule = db.query(AlertRule).filter(AlertRule.id == rule_id).first()
    if not rule:
        raise HTTPException(status_code=404, detail="Alert rule not found.")

    updatable = {
        "name",
        "is_active",
        "scanner_types",
        "severity_filter",
        "cooldown_minutes",
        "channels",
        "channel_config",
        "auto_trade",
        "trading_strategy_id",
    }
    for key, value in payload.items():
        if key in updatable:
            setattr(rule, key, value)

    rule.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
    db.commit()
    db.refresh(rule)
    return _rule_to_dict(rule)


@router.delete("/rules/{rule_id}", status_code=204)
def delete_rule(rule_id: int, db: Session = Depends(get_db)) -> None:
    """Delete an alert rule."""
    rule = db.query(AlertRule).filter(AlertRule.id == rule_id).first()
    if not rule:
        raise HTTPException(status_code=404, detail="Alert rule not found.")
    db.delete(rule)
    db.commit()
    logger.info(f"Deleted alert rule id={rule_id}")


# ──────────────────────────────────────────────────────────────────────────────
# Test Alert
# ──────────────────────────────────────────────────────────────────────────────


@router.post("/rules/{rule_id}/test")
def test_rule(rule_id: int, db: Session = Depends(get_db)) -> Dict[str, Any]:
    """Send a test notification through all channels configured on this rule."""
    rule = db.query(AlertRule).filter(AlertRule.id == rule_id).first()
    if not rule:
        raise HTTPException(status_code=404, detail="Alert rule not found.")

    # Build a synthetic scanner event for the test
    test_event = ScannerEvent(
        id=-1,
        ticker="TEST",
        event_date=date.today(),
        scanner_type=rule.scanner_types[0]
        if rule.scanner_types
        else "pre_market_volume_spike",
        summary="This is a test alert from MarketHawk. Your notification channel is working!",
        severity=rule.severity_filter if rule.severity_filter != "any" else "high",
        indicators={
            "relative_volume": 5.2,
            "gap_pct": 3.1,
            "pre_market_volume": 500000,
        },
        criteria_met={},
        metadata_={},
    )

    from app.services.alert_service import NotificationDispatcher

    results = []
    channels = rule.channels or []
    config = rule.channel_config or {}

    for channel in channels:
        try:
            if channel == "browser_push":
                NotificationDispatcher._send_browser_push(test_event, db)
            elif channel == "email":
                to = config.get("email")
                if not to:
                    raise ValueError("No email configured.")
                NotificationDispatcher._send_email(
                    to=to,
                    subject="✅ MarketHawk Test Alert",
                    body=NotificationDispatcher._build_email_body(test_event),
                )
            elif channel == "google_chat":
                webhook_url = config.get("google_chat_webhook")
                if not webhook_url:
                    raise ValueError("No Google Chat webhook configured.")
                NotificationDispatcher._send_google_chat(
                    webhook_url=webhook_url,
                    message=f"✅ TEST: {NotificationDispatcher._build_chat_message(test_event)}",
                )
            elif channel == "webhook":
                url = config.get("webhook_url")
                if not url:
                    raise ValueError("No webhook URL configured.")
                NotificationDispatcher._send_webhook(
                    url=url,
                    payload=NotificationDispatcher._build_webhook_payload(
                        test_event, rule
                    ),
                )
            results.append({"channel": channel, "status": "sent"})
        except Exception as exc:
            results.append({"channel": channel, "status": "failed", "error": str(exc)})

    return {"results": results}


# ──────────────────────────────────────────────────────────────────────────────
# Delivery Log
# ──────────────────────────────────────────────────────────────────────────────


@router.get("/logs")
def list_delivery_logs(
    limit: int = 50,
    db: Session = Depends(get_db),
) -> List[Dict[str, Any]]:
    """Return the most recent alert delivery log entries."""
    logs = (
        db.query(AlertDeliveryLog)
        .order_by(AlertDeliveryLog.delivered_at.desc())
        .limit(min(limit, 200))
        .all()
    )
    return [
        {
            "id": log.id,
            "rule_id": log.rule_id,
            "scanner_event_id": log.scanner_event_id,
            "ticker": log.ticker,
            "scanner_type": log.scanner_type,
            "channel": log.channel,
            "status": log.status,
            "error_message": log.error_message,
            "delivered_at": log.delivered_at.isoformat() if log.delivered_at else None,
        }
        for log in logs
    ]


# ──────────────────────────────────────────────────────────────────────────────
# Browser Push — VAPID + Subscriptions
# ──────────────────────────────────────────────────────────────────────────────


@router.get("/push/vapid-key")
def get_vapid_public_key() -> Dict[str, str]:
    """Return the VAPID public key so the frontend can subscribe."""
    from app.core.config import settings

    if not settings.VAPID_PUBLIC_KEY:
        raise HTTPException(
            status_code=503,
            detail="VAPID keys not configured. Set VAPID_PUBLIC_KEY in .env.",
        )
    return {"public_key": settings.VAPID_PUBLIC_KEY}


@router.get("/push/generate-keys")
def generate_vapid_keys() -> Dict[str, str]:
    """
    One-time key generation helper. Run once, copy output to .env.
    This endpoint should be removed or restricted in production.
    """
    import base64

    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.serialization import (
        Encoding,
        NoEncryption,
        PrivateFormat,
        PublicFormat,
    )

    private_key = ec.generate_private_key(ec.SECP256R1())

    # Raw 32-byte private scalar — base64url encoded.
    # py_vapid's from_string() only accepts this format (not PEM).
    # Single-line, safe for .env and Docker env var injection.
    der = private_key.private_bytes(
        Encoding.DER, PrivateFormat.TraditionalOpenSSL, NoEncryption()
    )
    raw_priv = der[7:39]  # SEC1 DER: 7-byte header, then 32-byte key scalar
    private_b64 = base64.urlsafe_b64encode(raw_priv).decode().rstrip("=")

    # Uncompressed EC point, URL-safe base64 — what browsers expect for applicationServerKey
    pub_bytes = private_key.public_key().public_bytes(
        Encoding.X962, PublicFormat.UncompressedPoint
    )
    public_b64 = base64.urlsafe_b64encode(pub_bytes).decode().rstrip("=")

    return {
        "VAPID_PUBLIC_KEY": public_b64,
        "VAPID_PRIVATE_KEY": private_b64,
        "instructions": (
            "Paste both values into .env without quotes. "
            "Then run: docker-compose up -d --force-recreate backend"
        ),
    }


@router.post("/push/subscribe", status_code=201)
def subscribe_push(
    payload: Dict[str, Any], request: Request, db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """
    Save a browser PushSubscription.
    Payload matches the JSON serialization of the browser's PushSubscription object:
      { "endpoint": "...", "keys": { "p256dh": "...", "auth": "..." } }
    """
    endpoint = payload.get("endpoint")
    keys = payload.get("keys", {})
    p256dh = keys.get("p256dh")
    auth = keys.get("auth")

    if not endpoint or not p256dh or not auth:
        raise HTTPException(
            status_code=422, detail="endpoint, keys.p256dh, and keys.auth are required."
        )

    # Upsert: update keys if endpoint already exists
    existing = (
        db.query(PushSubscription).filter(PushSubscription.endpoint == endpoint).first()
    )
    if existing:
        existing.p256dh = p256dh
        existing.auth = auth
        db.commit()
        return {"status": "updated", "id": existing.id}

    sub = PushSubscription(
        endpoint=endpoint,
        p256dh=p256dh,
        auth=auth,
        user_agent=request.headers.get("User-Agent", "")[:500],
    )
    db.add(sub)
    db.commit()
    db.refresh(sub)
    logger.info(f"New push subscription registered id={sub.id}")
    return {"status": "created", "id": sub.id}


@router.delete("/push/unsubscribe")
def unsubscribe_push(
    payload: Dict[str, Any], db: Session = Depends(get_db)
) -> Dict[str, str]:
    """Remove a push subscription by endpoint URL."""
    endpoint = payload.get("endpoint")
    if not endpoint:
        raise HTTPException(status_code=422, detail="endpoint is required.")

    sub = (
        db.query(PushSubscription).filter(PushSubscription.endpoint == endpoint).first()
    )
    if sub:
        db.delete(sub)
        db.commit()
        return {"status": "unsubscribed"}
    return {"status": "not_found"}


@router.post("/infrastructure", status_code=200)
def receive_infrastructure_alert(payload: Dict[str, Any]) -> Dict[str, str]:
    """Receive Grafana alerting webhook payloads and log them."""
    title = payload.get("title") or payload.get("message") or "unknown"
    state = payload.get("state") or payload.get("status") or "unknown"
    logger.warning(
        "Grafana infrastructure alert received: title=%s state=%s payload=%s",
        title,
        state,
        json.dumps(payload),
    )
    return {"status": "received"}
