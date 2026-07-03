"""
Alert Service — rule evaluation and multi-channel notification dispatch.

Channels supported (all free):
  - browser_push  : VAPID Web Push via pywebpush
  - email         : Gmail SMTP via smtplib
  - google_chat   : Incoming Webhook (HTTP POST)
  - webhook       : Generic HTTP POST
"""

import json
import logging
import smtplib
import ssl
from datetime import date, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any, Dict, List, Optional, get_args

import httpx
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.alert_delivery_log import AlertDeliveryLog
from app.models.alert_rule import AlertRule
from app.models.push_subscription import PushSubscription
from app.models.scanner_event import ScannerEvent
from app.schemas.event import SeverityLiteral
from app.utils.time import utc_now

logger = logging.getLogger(__name__)

_VALID_SEVERITIES: frozenset = frozenset(get_args(SeverityLiteral))


# ──────────────────────────────────────────────────────────────────────────────
# Rule Evaluation
# ──────────────────────────────────────────────────────────────────────────────


class AlertRuleService:
    """Evaluates scanner events against stored alert rules."""

    @staticmethod
    def get_matching_rules(event: ScannerEvent, db: Session) -> List[AlertRule]:
        """Return all active AlertRules that match a ScannerEvent."""
        rules = db.query(AlertRule).filter(AlertRule.is_active == True).all()
        matched = []

        for rule in rules:
            # 1. Scanner type filter (empty list = match all)
            if rule.scanner_types and event.scanner_type not in rule.scanner_types:
                continue

            # 2. Severity filter
            if rule.severity_filter and rule.severity_filter != "any":
                if event.severity != rule.severity_filter:
                    continue

            # 3. Cooldown — has this rule fired for this ticker recently?
            if AlertRuleService.is_on_cooldown(rule, event.ticker, db):
                logger.debug(
                    f"Rule {rule.id} '{rule.name}' on cooldown "
                    f"for {event.ticker} — skipping."
                )
                continue

            matched.append(rule)

        return matched

    @staticmethod
    def is_on_cooldown(rule: AlertRule, ticker: str, db: Session) -> bool:
        """Return True if a delivery was logged for this rule+ticker within cooldown_minutes."""
        if rule.cooldown_minutes <= 0:
            return False

        cutoff = utc_now() - timedelta(minutes=rule.cooldown_minutes)
        recent = (
            db.query(AlertDeliveryLog)
            .filter(
                AlertDeliveryLog.rule_id == rule.id,
                AlertDeliveryLog.ticker == ticker,
                AlertDeliveryLog.status == "sent",
                AlertDeliveryLog.delivered_at >= cutoff,
            )
            .first()
        )
        return recent is not None


# ──────────────────────────────────────────────────────────────────────────────
# Notification Dispatcher
# ──────────────────────────────────────────────────────────────────────────────


class NotificationDispatcher:
    """Dispatches alert notifications across all enabled channels."""

    @staticmethod
    def dispatch(rule: AlertRule, event: ScannerEvent, db: Session) -> None:
        """Fan-out to all channels configured on this rule."""
        channels = rule.channels or []
        config = rule.channel_config or {}

        for channel in channels:
            status = "sent"
            error_msg = None
            try:
                if channel == "browser_push":
                    NotificationDispatcher._send_browser_push(event, db)
                elif channel == "email":
                    to = config.get("email")
                    if to:
                        NotificationDispatcher._send_email(
                            to=to,
                            subject=f"MarketHawk Alert: {event.ticker} — {event.scanner_type.replace('_', ' ').title()}",
                            body=NotificationDispatcher._build_email_body(event),
                        )
                    else:
                        raise ValueError("No email address configured for this rule.")
                elif channel == "google_chat":
                    webhook_url = config.get("google_chat_webhook")
                    if webhook_url:
                        NotificationDispatcher._send_google_chat(
                            webhook_url=webhook_url,
                            message=NotificationDispatcher._build_chat_message(event),
                        )
                    else:
                        raise ValueError("No Google Chat webhook URL configured.")
                elif channel == "webhook":
                    url = config.get("webhook_url")
                    if url:
                        NotificationDispatcher._send_webhook(
                            url=url,
                            payload=NotificationDispatcher._build_webhook_payload(
                                event, rule
                            ),
                        )
                    else:
                        raise ValueError("No webhook URL configured.")
                else:
                    logger.warning(
                        f"Unknown alert channel '{channel}' on rule {rule.id}"
                    )
                    continue

                logger.info(
                    f"✅ Alert sent — rule={rule.id} ticker={event.ticker} "
                    f"scanner={event.scanner_type} channel={channel}"
                )
            except Exception as exc:
                status = "failed"
                error_msg = str(exc)
                logger.error(
                    f"❌ Alert delivery failed — rule={rule.id} ticker={event.ticker} "
                    f"channel={channel}: {exc}"
                )

            # Record delivery attempt
            log = AlertDeliveryLog(
                rule_id=rule.id,
                scanner_event_id=event.id,
                ticker=event.ticker,
                scanner_type=event.scanner_type,
                channel=channel,
                status=status,
                error_message=error_msg,
            )
            db.add(log)

        db.commit()

    # ── Browser Push ──────────────────────────────────────────────────────────

    @staticmethod
    def _push_to_subscriptions(payload: dict, db: Session) -> int:
        """Web-push a pre-built `payload` dict to all stored subscriptions.

        Generic core shared by scanner-event push and system notifications.
        Returns the number delivered. Raises RuntimeError only if ALL deliveries fail.
        """
        try:
            from pywebpush import webpush  # noqa: F401
        except ImportError:
            raise RuntimeError(
                "pywebpush is not installed. "
                "Add 'pywebpush' to requirements.txt and rebuild the container."
            )

        if not settings.VAPID_PRIVATE_KEY or not settings.VAPID_PUBLIC_KEY:
            raise ValueError(
                "VAPID_PRIVATE_KEY and VAPID_PUBLIC_KEY must be set in .env to send browser push."
            )

        subscriptions = db.query(PushSubscription).all()
        if not subscriptions:
            logger.debug("No push subscriptions registered — skipping browser push.")
            return 0

        data = json.dumps(payload)
        vapid_claims = {"sub": settings.VAPID_CLAIMS_EMAIL}
        # Key is stored as raw base64url (43 chars, no PEM headers) — py_vapid from_string
        # only supports this format; PEM is not recognized in this version.
        vapid_private_key = settings.VAPID_PRIVATE_KEY

        failed = 0
        for sub in subscriptions:
            try:
                webpush(
                    subscription_info={
                        "endpoint": sub.endpoint,
                        "keys": {"p256dh": sub.p256dh, "auth": sub.auth},
                    },
                    data=data,
                    vapid_private_key=vapid_private_key,
                    vapid_claims=vapid_claims,
                )
            except Exception as exc:
                failed += 1
                # 410 Gone = subscription expired; clean it up
                err_str = str(exc)
                if "410" in err_str or "404" in err_str:
                    logger.info(f"Removing expired push subscription id={sub.id}")
                    db.delete(sub)
                else:
                    logger.warning(f"Push failed for subscription {sub.id}: {exc}")

        if failed == len(subscriptions):
            raise RuntimeError(f"All {failed} push deliveries failed.")
        return len(subscriptions) - failed

    @staticmethod
    def _send_browser_push(event: ScannerEvent, db: Session) -> None:
        """Scanner-event browser push (thin wrapper over the generic sender)."""
        NotificationDispatcher._push_to_subscriptions(
            NotificationDispatcher._build_push_payload(event), db
        )

    # ── Email ─────────────────────────────────────────────────────────────────

    @staticmethod
    def _send_email(to: str, subject: str, body: str) -> None:
        """Send an HTML email via SMTP (defaults to Gmail TLS)."""
        if not settings.SMTP_USER or not settings.SMTP_PASSWORD:
            raise ValueError(
                "SMTP_USER and SMTP_PASSWORD must be set in .env to send email alerts."
            )

        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = settings.SMTP_FROM_EMAIL
        msg["To"] = to
        msg.attach(MIMEText(body, "html"))

        context = ssl.create_default_context()
        with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT) as server:
            server.ehlo()
            server.starttls(context=context)
            server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
            server.sendmail(settings.SMTP_USER, to, msg.as_string())

    # ── Google Chat ───────────────────────────────────────────────────────────

    @staticmethod
    def _send_google_chat(webhook_url: str, message: str) -> None:
        """POST a message to a Google Chat Incoming Webhook."""
        with httpx.Client(timeout=10.0) as client:
            r = client.post(webhook_url, json={"text": message})
            r.raise_for_status()

    # ── Generic Webhook ───────────────────────────────────────────────────────

    @staticmethod
    def _send_webhook(url: str, payload: dict) -> None:
        """POST a JSON payload to a generic webhook URL."""
        with httpx.Client(timeout=10.0) as client:
            r = client.post(url, json=payload)
            r.raise_for_status()

    # ── Payload Builders ──────────────────────────────────────────────────────

    @staticmethod
    def _build_push_payload(event: ScannerEvent) -> dict:
        scanner_type_display = event.scanner_type.replace("_", " ").title()
        return {
            "title": f"MarketHawk: {event.ticker} — {scanner_type_display}",
            "body": event.summary
            or f"{scanner_type_display} detected on {event.ticker}",
            "severity": event.severity,
            "ticker": event.ticker,
            "scanner_type": event.scanner_type,
            "event_date": str(event.event_date),
            "url": f"/stock/{event.ticker}",
        }

    @staticmethod
    def _build_email_body(event: ScannerEvent) -> str:
        scanner_type_display = event.scanner_type.replace("_", " ").title()
        indicators_html = "".join(
            f"<tr><td style='padding:4px 8px;color:#9ca3af'>{k}</td>"
            f"<td style='padding:4px 8px;color:#f3f4f6'>{v}</td></tr>"
            for k, v in (event.indicators or {}).items()
        )
        return f"""
        <html><body style="font-family:sans-serif;background:#111827;color:#f3f4f6;padding:24px">
          <h2 style="color:#3b82f6">🔔 MarketHawk Alert</h2>
          <h3 style="color:#f3f4f6">{event.ticker} — {scanner_type_display}</h3>
          <p style="color:#9ca3af">{event.event_date}</p>
          <p>{event.summary or "Scanner event detected."}</p>
          <table style="border-collapse:collapse;margin-top:16px">
            {indicators_html}
          </table>
          <p style="margin-top:24px;font-size:12px;color:#6b7280">
            Sent by MarketHawk · Manage alerts in the app
          </p>
        </body></html>
        """

    @staticmethod
    def _build_chat_message(event: ScannerEvent) -> str:
        scanner_type_display = event.scanner_type.replace("_", " ").title()
        indicators = event.indicators or {}
        indicator_lines = "\n".join(
            f"• *{k}:* {v}" for k, v in list(indicators.items())[:6]
        )
        return (
            f"🔔 *MarketHawk Alert*\n"
            f"*{event.ticker}* — {scanner_type_display}\n"
            f"_{event.event_date}_ · Severity: {event.severity}\n\n"
            f"{event.summary or ''}\n\n"
            f"{indicator_lines}"
        )

    @staticmethod
    def _build_webhook_payload(event: ScannerEvent, rule: AlertRule) -> dict:
        return {
            "source": "MarketHawk",
            "rule_id": rule.id,
            "rule_name": rule.name,
            "ticker": event.ticker,
            "scanner_type": event.scanner_type,
            "severity": event.severity,
            "summary": event.summary,
            "event_date": str(event.event_date),
            "indicators": event.indicators or {},
        }


# ──────────────────────────────────────────────────────────────────────────────
# Scanner Event Persistence
# ──────────────────────────────────────────────────────────────────────────────


def _validate_jsonb_dict(value: Any, field_name: str) -> None:
    if not isinstance(value, dict):
        raise ValueError(f"{field_name} must be a dict, got {type(value).__name__}")
    try:
        json.dumps(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"{field_name} contains non-JSON-serializable value: {exc}"
        ) from exc


def trigger_scanner_alert(event_id: int) -> None:
    """Enqueue alert evaluation for a newly persisted ScannerEvent."""
    from app.tasks import evaluate_scanner_alerts

    evaluate_scanner_alerts.delay(event_id)


def save_event(
    db: Session,
    ticker: str,
    event_date: date,
    scanner_type: str,
    indicators: Dict[str, Any],
    criteria_met: Dict[str, Any],
    enrichment: Dict[str, Any],
    previous_close: float = None,
    opening_price: float = None,
    closing_price: float = None,
    ranker_config: Optional[Dict[str, Any]] = None,
    gate_metadata: Optional[Dict[str, Any]] = None,
    explanation: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Persist a ScannerEvent and enqueue alert evaluation for new events."""
    from app.services.event_helpers import (
        compute_event_severity,
        generate_event_summary,
    )
    from app.services.signal_ranker import compute_signal_quality_score

    summary = generate_event_summary(scanner_type, indicators)
    severity = compute_event_severity(scanner_type, indicators)

    if severity not in _VALID_SEVERITIES:
        raise ValueError(
            f"Invalid severity '{severity}': must be one of {_VALID_SEVERITIES}"
        )

    _validate_jsonb_dict(indicators, "indicators")
    _validate_jsonb_dict(criteria_met, "criteria_met")
    _validate_jsonb_dict(enrichment, "enrichment")
    if explanation is not None:
        _validate_jsonb_dict(explanation, "explanation")

    score = None
    if ranker_config and ranker_config.get("enabled") and ranker_config.get("weights"):
        score = compute_signal_quality_score(indicators, ranker_config["weights"])

    try:
        from app.services.regime_service import RegimeService

        regime = RegimeService.get_regime_at_date(db, event_date)
    except Exception as exc:
        logger.warning(
            "save_event: regime lookup failed for %s %s: %s", ticker, event_date, exc
        )
        regime = None

    metadata_payload = dict(enrichment)
    if gate_metadata is not None:
        metadata_payload["quality_gate"] = gate_metadata

    event_dict = {
        "ticker": ticker,
        "event_date": event_date,
        "scanner_type": scanner_type,
        "summary": summary,
        "severity": severity,
        "previous_close": previous_close,
        "opening_price": opening_price,
        "closing_price": closing_price,
        "indicators": indicators,
        "criteria_met": criteria_met,
        "metadata": metadata_payload,
        "signal_quality_score": score,
        "regime": regime,
    }
    if explanation is not None:
        event_dict["explanation"] = explanation

    existing = (
        db.query(ScannerEvent)
        .filter(
            ScannerEvent.ticker == ticker,
            ScannerEvent.event_date == event_date,
            ScannerEvent.scanner_type == scanner_type,
        )
        .first()
    )

    if existing:
        for key, value in event_dict.items():
            if key == "metadata":
                setattr(existing, "metadata_", value)
            else:
                setattr(existing, key, value)
        db.flush()
        event_dict["id"] = existing.id
    else:
        model_data = event_dict.copy()
        model_data["metadata_"] = model_data.pop("metadata")
        new_event = ScannerEvent(**model_data)
        db.add(new_event)
        db.flush()
        event_dict["id"] = new_event.id
        trigger_scanner_alert(new_event.id)

    return event_dict
