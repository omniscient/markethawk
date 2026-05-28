import app.utils.session as session_mod
import live_scanner.bar_aggregator as mod


def test_session_for_ts_is_from_app_utils():
    """bar_aggregator must use app.utils.session.session_for_ts, not define its own."""
    assert mod.session_for_ts is session_mod.session_for_ts


def test_session_total_minutes_is_from_app_utils():
    assert mod.session_total_minutes is session_mod.session_total_minutes
