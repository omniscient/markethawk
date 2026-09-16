from unittest.mock import MagicMock, patch

from app.services.alert_service import NotificationDispatcher


@patch("app.services.alert_service.settings")
def test_push_to_subscriptions_sends_to_all(mock_settings):
    mock_settings.VAPID_PRIVATE_KEY = "k"
    mock_settings.VAPID_PUBLIC_KEY = "p"
    mock_settings.VAPID_CLAIMS_EMAIL = "mailto:a@b.c"
    db = MagicMock()
    sub = MagicMock(endpoint="e", p256dh="x", auth="y", id=1)
    db.query.return_value.all.return_value = [sub]
    with patch("pywebpush.webpush") as wp:
        count = NotificationDispatcher._push_to_subscriptions(
            {"title": "T", "body": "B", "severity": "warning", "url": "/"}, db
        )
    assert count == 1
    wp.assert_called_once()


@patch("app.services.alert_service.settings")
def test_push_no_subscriptions_returns_zero(mock_settings):
    mock_settings.VAPID_PRIVATE_KEY = "k"
    mock_settings.VAPID_PUBLIC_KEY = "p"
    db = MagicMock()
    db.query.return_value.all.return_value = []
    count = NotificationDispatcher._push_to_subscriptions({"title": "T", "body": "B"}, db)
    assert count == 0
