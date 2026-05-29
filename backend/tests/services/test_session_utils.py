from datetime import datetime, timezone
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")


def _et(h, m=0):
    """UTC datetime corresponding to hour:minute in ET on a known EDT date (2026-05-26)."""
    return datetime(2026, 5, 26, h, m, tzinfo=ET).astimezone(timezone.utc)


class TestSessionForTs:
    def test_pre_market_mid(self):
        from app.utils.session import session_for_ts

        assert session_for_ts(_et(6)) == "pre"

    def test_pre_market_boundary_open(self):
        from app.utils.session import session_for_ts

        assert session_for_ts(_et(4, 0)) == "pre"

    def test_pre_market_boundary_close(self):
        from app.utils.session import session_for_ts

        assert session_for_ts(_et(9, 29)) == "pre"

    def test_regular_open(self):
        from app.utils.session import session_for_ts

        assert session_for_ts(_et(9, 30)) == "regular"

    def test_regular_mid(self):
        from app.utils.session import session_for_ts

        assert session_for_ts(_et(12, 0)) == "regular"

    def test_regular_boundary_close(self):
        from app.utils.session import session_for_ts

        assert session_for_ts(_et(15, 59)) == "regular"

    def test_post_starts_at_1600(self):
        from app.utils.session import session_for_ts

        assert session_for_ts(_et(16, 0)) == "post"

    def test_post_mid(self):
        from app.utils.session import session_for_ts

        assert session_for_ts(_et(17, 30)) == "post"

    def test_closed_overnight(self):
        from app.utils.session import session_for_ts

        assert session_for_ts(_et(2, 0)) == "closed"

    def test_naive_datetime_treated_as_utc(self):
        from app.utils.session import session_for_ts

        # 13:00 UTC = 9:00 ET on 2026-05-26 → pre-market
        naive = datetime(2026, 5, 26, 13, 0)
        assert session_for_ts(naive) == "pre"


class TestSessionTotalMinutes:
    def test_pre(self):
        from app.utils.session import session_total_minutes

        assert session_total_minutes("pre") == 330.0  # 4:00–9:30

    def test_regular(self):
        from app.utils.session import session_total_minutes

        assert session_total_minutes("regular") == 390.0

    def test_post(self):
        from app.utils.session import session_total_minutes

        assert session_total_minutes("post") == 240.0  # 16:00–20:00

    def test_unknown_falls_back_to_regular(self):
        from app.utils.session import session_total_minutes

        assert session_total_minutes("closed") == 390.0


class TestClassifySessionShim:
    def test_pre_market(self):
        from app.utils.session import classify_session

        is_pre, is_post = classify_session(_et(6))
        assert is_pre is True and is_post is False

    def test_regular(self):
        from app.utils.session import classify_session

        is_pre, is_post = classify_session(_et(12))
        assert is_pre is False and is_post is False

    def test_post_at_1600_exact(self):
        from app.utils.session import classify_session

        # Bug fix: 16:00 ET must be post, not missed (old code used m >= 1)
        is_pre, is_post = classify_session(_et(16, 0))
        assert is_pre is False and is_post is True
