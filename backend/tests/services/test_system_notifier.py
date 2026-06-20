from unittest.mock import patch

import app.services.system_notifier as sn


@patch("app.services.system_notifier.NotificationDispatcher")
def test_email_and_push(mock_disp):
    with patch.object(sn.settings, "OPS_ALERT_EMAIL", "ops@x.com"):
        mock_disp._push_to_subscriptions.return_value = 2
        r = sn.notify_system("T", "B", severity="warning", db=object())
    assert r["email"] == "sent"
    assert r["browser_push"] == "sent:2"
    mock_disp._send_email.assert_called_once()


@patch("app.services.system_notifier.NotificationDispatcher")
def test_email_skipped_when_ops_unset(mock_disp):
    with patch.object(sn.settings, "OPS_ALERT_EMAIL", ""):
        mock_disp._push_to_subscriptions.return_value = 0
        r = sn.notify_system("T", "B", db=object())
    assert r["email"] == "skipped"
    mock_disp._send_email.assert_not_called()


@patch("app.services.system_notifier.NotificationDispatcher")
def test_channel_failure_is_soft(mock_disp):
    with patch.object(sn.settings, "OPS_ALERT_EMAIL", "ops@x.com"):
        mock_disp._send_email.side_effect = RuntimeError("smtp down")
        mock_disp._push_to_subscriptions.return_value = 1
        r = sn.notify_system("T", "B", db=object())
    assert r["email"].startswith("failed:")
    assert r["browser_push"] == "sent:1"


@patch("app.services.system_notifier.NotificationDispatcher")
def test_dedupe_suppresses_within_cooldown(mock_disp):
    with patch.object(sn.settings, "OPS_ALERT_EMAIL", "ops@x.com"):
        mock_disp._push_to_subscriptions.return_value = 0
        first = sn.notify_system("T", "B", dedupe_key="k1", db=object(), cooldown_seconds=100, _now=1000.0)
        second = sn.notify_system("T", "B", dedupe_key="k1", db=object(), cooldown_seconds=100, _now=1050.0)
        third = sn.notify_system("T", "B", dedupe_key="k1", db=object(), cooldown_seconds=100, _now=1200.0)
    assert first["email"] == "sent"
    assert second == {"email": "suppressed", "browser_push": "suppressed"}
    assert third["email"] == "sent"
