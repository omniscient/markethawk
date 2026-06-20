"""
Unit tests for system_notifier.notify_system.
Uses mocks for smtplib and pywebpush; no real network calls.
"""

import os
from unittest.mock import MagicMock, patch

from sqlalchemy.orm import Session

from app.models.alert_delivery_log import AlertDeliveryLog
from app.models.push_subscription import PushSubscription
from app.services.system_notifier import (
    _SYSTEM_SCANNER_TYPE,
    _hash_dedupe_key,
    notify_system,
)

# ── helpers ────────────────────────────────────────────────────────────────


def _add_subscription(db: Session, endpoint: str = "https://push.example.com/sub1"):
    sub = PushSubscription(
        endpoint=endpoint,
        p256dh="dh_key",
        auth="auth_key",
        user_agent="test",
    )
    db.add(sub)
    db.flush()
    return sub


def _delivery_log_count(db: Session, dedupe_key: str) -> int:
    return (
        db.query(AlertDeliveryLog)
        .filter(
            AlertDeliveryLog.scanner_type == _SYSTEM_SCANNER_TYPE,
            AlertDeliveryLog.ticker == _hash_dedupe_key(dedupe_key),
        )
        .count()
    )


# ── notify_system — email channel ──────────────────────────────────────────


def test_email_skipped_when_ops_alert_email_unset(db: Session):
    """OPS_ALERT_EMAIL empty → email channel returns 'skipped', no raise."""
    with patch.dict(os.environ, {"OPS_ALERT_EMAIL": ""}):
        # Force reload cached settings so the patch takes effect.
        from app.core import config as cfg

        cfg.settings.OPS_ALERT_EMAIL = ""

        result = notify_system(title="Test", body="Hello", channels=["email"], db=db)

    assert result["email"] == "skipped"


def test_email_sent_when_ops_alert_email_set(db: Session):
    """When OPS_ALERT_EMAIL is set and SMTP succeeds, email → 'sent'."""
    from app.core import config as cfg

    original = cfg.settings.OPS_ALERT_EMAIL
    cfg.settings.OPS_ALERT_EMAIL = "ops@example.com"
    try:
        with patch("smtplib.SMTP") as mock_smtp_cls:
            mock_smtp = MagicMock()
            mock_smtp_cls.return_value.__enter__ = lambda s: mock_smtp
            mock_smtp_cls.return_value.__exit__ = MagicMock(return_value=False)

            # Patch settings for SMTP so it doesn't raise "SMTP_USER not set"
            cfg.settings.SMTP_USER = "user@example.com"
            cfg.settings.SMTP_PASSWORD = "secret"

            result = notify_system(
                title="Test Alert",
                body="Something happened.",
                channels=["email"],
                db=db,
            )
    finally:
        cfg.settings.OPS_ALERT_EMAIL = original

    assert result["email"] == "sent"


def test_email_failure_recorded_as_failed(db: Session):
    """SMTP failure → email returns 'failed:<reason>' without raising."""
    from app.core import config as cfg

    original_email = cfg.settings.OPS_ALERT_EMAIL
    original_user = cfg.settings.SMTP_USER
    cfg.settings.OPS_ALERT_EMAIL = "ops@example.com"
    cfg.settings.SMTP_USER = "user@example.com"
    cfg.settings.SMTP_PASSWORD = "secret"
    try:
        with patch("smtplib.SMTP", side_effect=ConnectionRefusedError("refused")):
            result = notify_system(title="Test", body="body", channels=["email"], db=db)
    finally:
        cfg.settings.OPS_ALERT_EMAIL = original_email
        cfg.settings.SMTP_USER = original_user

    assert result["email"].startswith("failed:")


# ── notify_system — browser_push channel ──────────────────────────────────


def test_browser_push_skipped_when_db_is_none():
    """No DB → browser_push channel returns 'skipped' without raising."""
    result = notify_system(
        title="Test", body="body", channels=["browser_push"], db=None
    )
    assert result["browser_push"] == "skipped"


def test_browser_push_sent_when_subscription_exists(db: Session):
    """When a subscription exists and pywebpush succeeds, browser_push → 'sent'."""
    _add_subscription(db)
    from app.core import config as cfg

    cfg.settings.VAPID_PRIVATE_KEY = "test_private_key"
    cfg.settings.VAPID_PUBLIC_KEY = "test_public_key"
    cfg.settings.VAPID_CLAIMS_EMAIL = "mailto:admin@example.com"

    with patch("pywebpush.webpush") as mock_webpush:
        result = notify_system(
            title="Push Test", body="Push body", channels=["browser_push"], db=db
        )

    assert result["browser_push"] == "sent"
    assert mock_webpush.called


def test_browser_push_failure_does_not_raise(db: Session):
    """pywebpush failure → 'failed:<reason>' without raising."""
    _add_subscription(db)
    from app.core import config as cfg

    cfg.settings.VAPID_PRIVATE_KEY = "test_private_key"
    cfg.settings.VAPID_PUBLIC_KEY = "test_public_key"

    with patch("pywebpush.webpush", side_effect=RuntimeError("push failed")):
        result = notify_system(
            title="Push Test", body="Push body", channels=["browser_push"], db=db
        )

    assert result["browser_push"].startswith("failed:")


# ── notify_system — multi-channel independence ─────────────────────────────


def test_email_failure_does_not_block_push(db: Session):
    """Email failing must not prevent push channel from being attempted."""
    _add_subscription(db)
    from app.core import config as cfg

    cfg.settings.OPS_ALERT_EMAIL = "ops@example.com"
    cfg.settings.SMTP_USER = "user@example.com"
    cfg.settings.SMTP_PASSWORD = "secret"
    cfg.settings.VAPID_PRIVATE_KEY = "test_private_key"
    cfg.settings.VAPID_PUBLIC_KEY = "test_public_key"

    with patch("smtplib.SMTP", side_effect=ConnectionRefusedError("refused")):
        with patch("pywebpush.webpush") as mock_webpush:
            result = notify_system(
                title="Test",
                body="body",
                channels=["email", "browser_push"],
                db=db,
            )

    assert result["email"].startswith("failed:")
    assert result["browser_push"] == "sent"
    assert mock_webpush.called


# ── notify_system — dedupe / cooldown ──────────────────────────────────────


def test_dedupe_key_suppresses_repeat_within_cooldown(db: Session):
    """Second call with same dedupe_key within cooldown → all channels 'skipped'."""
    from app.core import config as cfg

    cfg.settings.OPS_ALERT_EMAIL = "ops@example.com"
    cfg.settings.SMTP_USER = "user@example.com"
    cfg.settings.SMTP_PASSWORD = "secret"

    with patch("smtplib.SMTP") as mock_smtp_cls:
        smtp_instance = MagicMock()
        mock_smtp_cls.return_value.__enter__ = lambda s: smtp_instance
        mock_smtp_cls.return_value.__exit__ = MagicMock(return_value=False)

        # First call — should send
        result1 = notify_system(
            title="Test",
            body="body",
            dedupe_key="unique-event-1",
            channels=["email"],
            db=db,
        )
        assert result1["email"] == "sent"

        # Second call with same key — should be suppressed
        result2 = notify_system(
            title="Test",
            body="body",
            dedupe_key="unique-event-1",
            channels=["email"],
            db=db,
        )

    assert result2 == {"email": "skipped"}


def test_delivery_logged_in_alert_delivery_log(db: Session):
    """Successful send records a row in AlertDeliveryLog for dedupe tracking."""
    from app.core import config as cfg

    cfg.settings.OPS_ALERT_EMAIL = "ops@example.com"
    cfg.settings.SMTP_USER = "user@example.com"
    cfg.settings.SMTP_PASSWORD = "secret"

    with patch("smtplib.SMTP") as mock_smtp_cls:
        smtp_instance = MagicMock()
        mock_smtp_cls.return_value.__enter__ = lambda s: smtp_instance
        mock_smtp_cls.return_value.__exit__ = MagicMock(return_value=False)

        notify_system(
            title="Test",
            body="body",
            dedupe_key="my-dedupe-key",
            channels=["email"],
            db=db,
        )

    count = _delivery_log_count(db, "my-dedupe-key")
    assert count == 1


def test_no_dedupe_key_does_not_suppress(db: Session):
    """Calls without dedupe_key are never suppressed, even if identical."""
    from app.core import config as cfg

    cfg.settings.OPS_ALERT_EMAIL = "ops@example.com"
    cfg.settings.SMTP_USER = "user@example.com"
    cfg.settings.SMTP_PASSWORD = "secret"

    with patch("smtplib.SMTP") as mock_smtp_cls:
        smtp_instance = MagicMock()
        mock_smtp_cls.return_value.__enter__ = lambda s: smtp_instance
        mock_smtp_cls.return_value.__exit__ = MagicMock(return_value=False)

        result1 = notify_system(title="T", body="b", channels=["email"], db=db)
        result2 = notify_system(title="T", body="b", channels=["email"], db=db)

    assert result1["email"] == "sent"
    assert result2["email"] == "sent"


# ── severity prefix ────────────────────────────────────────────────────────


def test_warning_severity_prefixes_subject(db: Session):
    """Warning severity should prefix '[WARNING]' on the email subject."""
    from app.core import config as cfg
    from app.services import alert_service

    cfg.settings.OPS_ALERT_EMAIL = "ops@example.com"

    captured_subjects = []

    with patch.object(
        alert_service.NotificationDispatcher,
        "_send_email",
        staticmethod(lambda to, subject, body: captured_subjects.append(subject)),
    ):
        notify_system(
            title="Deploy failed",
            body="The preview stack crashed.",
            severity="warning",
            channels=["email"],
            db=db,
        )

    assert len(captured_subjects) == 1
    assert "[WARNING]" in captured_subjects[0]
