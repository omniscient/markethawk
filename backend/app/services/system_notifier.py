"""
System Notifier — generic email/push notifications for non-scanner events.

Decoupled from AlertRule/ScannerEvent; usable by the autopilot, circuit breakers,
preview failures, and any other internal component.
"""

import hashlib
import logging
from datetime import timedelta
from typing import Optional

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.alert_delivery_log import AlertDeliveryLog
from app.utils.time import utc_now

logger = logging.getLogger(__name__)

_SYSTEM_SCANNER_TYPE = "system_notification"
_DEFAULT_COOLDOWN_MINUTES = 60
_DEFAULT_CHANNELS = ["email", "browser_push"]

_SEVERITY_PREFIX = {
    "warning": "[WARNING] ",
    "critical": "[CRITICAL] ",
}


def _hash_dedupe_key(key: str) -> str:
    """Truncate a dedupe key to fit in AlertDeliveryLog.ticker (VARCHAR 10)."""
    return hashlib.sha256(key.encode()).hexdigest()[:10]


def _is_on_cooldown(
    dedupe_key: str, db: Session, cooldown_minutes: int = _DEFAULT_COOLDOWN_MINUTES
) -> bool:
    cutoff = utc_now() - timedelta(minutes=cooldown_minutes)
    ticker_key = _hash_dedupe_key(dedupe_key)
    return (
        db.query(AlertDeliveryLog)
        .filter(
            AlertDeliveryLog.scanner_type == _SYSTEM_SCANNER_TYPE,
            AlertDeliveryLog.ticker == ticker_key,
            AlertDeliveryLog.status == "sent",
            AlertDeliveryLog.delivered_at >= cutoff,
        )
        .first()
        is not None
    )


def _record_delivery(
    dedupe_key: Optional[str],
    channel: str,
    status: str,
    error_msg: Optional[str],
    db: Session,
) -> None:
    ticker_key = _hash_dedupe_key(dedupe_key) if dedupe_key else None
    log = AlertDeliveryLog(
        rule_id=None,
        scanner_event_id=None,
        ticker=ticker_key,
        scanner_type=_SYSTEM_SCANNER_TYPE,
        channel=channel,
        status=status,
        error_message=error_msg,
    )
    db.add(log)
    try:
        db.commit()
    except Exception as exc:
        logger.warning("system_notifier: failed to record delivery log: %s", exc)
        db.rollback()


def _build_system_email_body(title: str, body: str, severity: str) -> str:
    severity_color = {"critical": "#ef4444", "warning": "#f59e0b"}.get(
        severity, "#3b82f6"
    )
    severity_label = severity.upper()
    return f"""
    <html><body style="font-family:sans-serif;background:#111827;color:#f3f4f6;padding:24px">
      <h2 style="color:{severity_color}">&#128276; MarketHawk System Alert</h2>
      <p style="display:inline-block;padding:2px 8px;border-radius:4px;
                background:{severity_color};color:#fff;font-size:12px;font-weight:bold">
        {severity_label}
      </p>
      <h3 style="color:#f3f4f6;margin-top:12px">{title}</h3>
      <p style="color:#d1d5db;white-space:pre-line">{body}</p>
      <p style="margin-top:24px;font-size:12px;color:#6b7280">
        Sent by MarketHawk System Notifier
      </p>
    </body></html>
    """


def notify_system(
    title: str,
    body: str,
    severity: str = "info",
    dedupe_key: Optional[str] = None,
    channels: Optional[list] = None,
    db: Optional[Session] = None,
) -> dict:
    """
    Deliver a system notification via email and/or browser push.

    Returns a dict mapping channel → "sent" | "skipped" | "failed:<reason>".
    Never raises; each channel fails independently.
    """
    if channels is None:
        channels = list(_DEFAULT_CHANNELS)

    if dedupe_key and db and _is_on_cooldown(dedupe_key, db):
        logger.info(
            "system_notifier: dedupe_key=%r still on cooldown — suppressing", dedupe_key
        )
        return {ch: "skipped" for ch in channels}

    prefix = _SEVERITY_PREFIX.get(severity, "")
    subject = f"{prefix}MarketHawk: {title}"
    results: dict = {}

    for channel in channels:
        status = "sent"
        error_msg: Optional[str] = None
        try:
            if channel == "email":
                if not settings.OPS_ALERT_EMAIL:
                    logger.warning(
                        "system_notifier: OPS_ALERT_EMAIL not set — skipping email"
                    )
                    results["email"] = "skipped"
                    continue
                from app.services.alert_service import NotificationDispatcher

                NotificationDispatcher._send_email(
                    to=settings.OPS_ALERT_EMAIL,
                    subject=subject,
                    body=_build_system_email_body(title, body, severity),
                )

            elif channel == "browser_push":
                if db is None:
                    results["browser_push"] = "skipped"
                    continue
                from app.services.alert_service import NotificationDispatcher

                NotificationDispatcher._send_browser_push_generic(
                    title=f"{prefix}{title}",
                    body=body,
                    db=db,
                )

            else:
                results[channel] = f"failed:unknown channel '{channel}'"
                continue

        except Exception as exc:
            status = "failed"
            reason = str(exc).replace("\n", " ")[:200]
            error_msg = reason
            results[channel] = f"failed:{reason}"
            logger.error(
                "system_notifier: channel=%s failed: %s", channel, exc, exc_info=True
            )
        else:
            results[channel] = "sent"

        if db is not None:
            _record_delivery(dedupe_key, channel, status, error_msg, db)

    return results
