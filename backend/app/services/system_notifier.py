"""Generic system notifications (non-scanner) reusing the alert delivery channels."""
import logging
import time
from typing import Optional

from sqlalchemy.orm import Session

from app.core.config import settings
from app.services.alert_service import NotificationDispatcher

logger = logging.getLogger(__name__)

# In-process dedupe cache: dedupe_key -> last-sent monotonic timestamp.
# Best-effort (per-process, resets on restart) — acceptable for fail-soft alerts.
_dedupe_cache: dict = {}

_SEV_COLOR = {"info": "#3b82f6", "warning": "#f59e0b", "critical": "#ef4444"}


def _html(title: str, body: str, severity: str) -> str:
    color = _SEV_COLOR.get(severity, "#3b82f6")
    return (
        '<html><body style="font-family:sans-serif;background:#111827;color:#f3f4f6;padding:24px">'
        f'<h2 style="color:{color}">{title}</h2><p>{body}</p></body></html>'
    )


def notify_system(
    title: str,
    body: str,
    severity: str = "info",
    dedupe_key: Optional[str] = None,
    channels: Optional[list] = None,
    db: Optional[Session] = None,
    cooldown_seconds: int = 3600,
    _now: Optional[float] = None,
) -> dict:
    """Fan out a system notification to email + browser push. Never raises.

    Returns a per-channel status dict:
    "sent" | "sent:<n>" | "skipped" | "suppressed" | "unknown_channel" | "failed:<reason>".
    """
    channels = channels if channels is not None else ["email", "browser_push"]
    now = _now if _now is not None else time.monotonic()

    if dedupe_key is not None:
        last = _dedupe_cache.get(dedupe_key)
        if last is not None and (now - last) < cooldown_seconds:
            return {ch: "suppressed" for ch in channels}
        _dedupe_cache[dedupe_key] = now

    subject = title if severity == "info" else f"[{severity.upper()}] {title}"
    result: dict = {}
    for ch in channels:
        try:
            if ch == "email":
                if settings.OPS_ALERT_EMAIL:
                    NotificationDispatcher._send_email(
                        settings.OPS_ALERT_EMAIL, subject, _html(title, body, severity)
                    )
                    result[ch] = "sent"
                else:
                    result[ch] = "skipped"
            elif ch == "browser_push":
                if db is not None:
                    count = NotificationDispatcher._push_to_subscriptions(
                        {"title": title, "body": body, "severity": severity, "url": "/"}, db
                    )
                    result[ch] = f"sent:{count}"
                else:
                    result[ch] = "skipped"
            else:
                result[ch] = "unknown_channel"
        except Exception as exc:  # fail-soft per channel
            logger.error("system notification channel=%s failed: %s", ch, exc)
            result[ch] = f"failed:{exc}"
    return result
