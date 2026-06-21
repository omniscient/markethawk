"""
Tests for quality_helpers — pure functions, no DB required.
"""

from datetime import date, datetime, timedelta

from app.services.quality_helpers import _count_weekdays_between, _detect_gaps

# ── _count_weekdays_between ───────────────────────────────────────────────────


def test_adjacent_days_no_weekday_between():
    d = date(2024, 1, 2)  # Tuesday
    assert _count_weekdays_between(d, d + timedelta(days=1)) == 0


def test_monday_to_friday_has_3_weekdays_between():
    monday = date(2024, 1, 1)
    friday = date(2024, 1, 5)
    assert _count_weekdays_between(monday, friday) == 3


def test_weekend_days_not_counted():
    friday = date(2024, 1, 5)
    monday = date(2024, 1, 8)
    assert _count_weekdays_between(friday, monday) == 0


# ── _detect_gaps ──────────────────────────────────────────────────────────────


def _ts(year, month, day, hour=0):
    return datetime(year, month, day, hour, 0, 0)


def test_no_gaps_with_consecutive_day_bars():
    timestamps = [_ts(2024, 1, i) for i in range(1, 6)]
    gaps = _detect_gaps(timestamps, "day", 1)
    assert gaps == []


def test_single_timestamp_returns_no_gaps():
    assert _detect_gaps([_ts(2024, 1, 1)], "day", 1) == []


def test_empty_timestamps_returns_no_gaps():
    assert _detect_gaps([], "day", 1) == []


def test_weekend_gap_not_flagged():
    # Friday to Monday — normal weekend, should not be a gap
    friday = _ts(2024, 1, 5)
    monday = _ts(2024, 1, 8)
    gaps = _detect_gaps([friday, monday], "day", 1)
    assert gaps == []


def test_multi_week_gap_flagged():
    # Two weeks apart — definitely a gap with weekdays between
    ts1 = _ts(2024, 1, 2)  # Tuesday
    ts2 = _ts(2024, 1, 16)  # Tuesday 2 weeks later
    gaps = _detect_gaps([ts1, ts2], "day", 1)
    assert len(gaps) == 1
    assert gaps[0]["missing_bars"] > 0


def test_backward_compat_data_quality_import():
    """_count_weekdays_between is re-exported from data_quality for compat."""
    from app.services.data_quality import _count_weekdays_between as _cw  # noqa: F401

    assert _cw(date(2024, 1, 1), date(2024, 1, 5)) == 3
