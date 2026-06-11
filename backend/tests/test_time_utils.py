"""Unit tests for app/utils/time.py — utc_now() and to_utc_naive()."""

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from app.utils.time import to_utc_naive, utc_now


class TestUtcNow:
    def test_returns_naive_datetime(self):
        result = utc_now()
        assert result.tzinfo is None

    def test_is_close_to_now(self):
        before = datetime.now(timezone.utc).replace(tzinfo=None)
        result = utc_now()
        after = datetime.now(timezone.utc).replace(tzinfo=None)
        assert before <= result <= after


class TestToUtcNaive:
    def test_aware_utc_returns_naive(self):
        aware = datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
        result = to_utc_naive(aware)
        assert result == datetime(2024, 1, 15, 12, 0, 0)
        assert result.tzinfo is None

    def test_aware_non_utc_converts_correctly(self):
        et = ZoneInfo("America/New_York")
        # EST = UTC-5, so noon ET = 17:00 UTC
        aware = datetime(2024, 1, 15, 12, 0, 0, tzinfo=et)
        result = to_utc_naive(aware)
        assert result == datetime(2024, 1, 15, 17, 0, 0)
        assert result.tzinfo is None

    def test_naive_passthrough_unchanged(self):
        naive = datetime(2024, 1, 15, 12, 0, 0)
        result = to_utc_naive(naive)
        assert result is naive

    def test_idempotent_on_already_naive(self):
        aware = datetime(2024, 6, 1, 10, 30, tzinfo=timezone.utc)
        once = to_utc_naive(aware)
        twice = to_utc_naive(once)
        assert once == twice
        assert twice.tzinfo is None
