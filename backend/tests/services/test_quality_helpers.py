"""
Tests for quality_helpers — pure functions, no DB required.
"""

from datetime import date, datetime, timedelta

from app.services.quality_helpers import (
    _count_weekdays_between,
    _detect_gaps,
    _detect_universe_day_holes,
)

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


def test_holiday_weekend_hour_bars_not_flagged():
    # Fri 2026-05-22 20:00 → Tue 2026-05-26 08:00 spans Memorial Day
    # (Mon 2026-05-25): 4 calendar days but only 1 weekday between.
    friday = _ts(2026, 5, 22, 20)
    tuesday = _ts(2026, 5, 26, 8)
    gaps = _detect_gaps([friday, tuesday], "hour", 1)
    assert gaps == []


def test_holiday_weekend_minute_bars_not_flagged():
    # Thu 2026-07-02 23:10 → Mon 2026-07-06 08:00 spans July 4th observed
    # (Fri 2026-07-03): 4 calendar days but only 1 weekday between.
    thursday = _ts(2026, 7, 2, 23)
    monday = _ts(2026, 7, 6, 8)
    gaps = _detect_gaps([thursday, monday], "minute", 1)
    assert gaps == []


def test_two_missing_weekdays_hour_bars_flagged():
    # Wed 18:00 → next Mon 08:00: Thu + Fri missing (2 weekdays) → gap
    wednesday = _ts(2026, 6, 10, 18)
    monday = _ts(2026, 6, 15, 8)
    gaps = _detect_gaps([wednesday, monday], "hour", 1)
    assert len(gaps) == 1


# ── _detect_universe_day_holes ────────────────────────────────────────────────
#
# Week of Mon 2026-06-01 … Fri 2026-06-12 (all weekdays, no US holidays).


def _weekday_counts(base_count, overrides=None):
    """Counts for each weekday 2026-06-01..2026-06-12, with per-date overrides."""
    overrides = overrides or {}
    counts = {}
    d = date(2026, 6, 1)
    while d <= date(2026, 6, 12):
        if d.weekday() < 5:
            counts[d] = overrides.get(d, base_count)
        d += timedelta(days=1)
    return counts


def test_organic_variation_produces_no_holes():
    # Illiquid universe: 350–470 of 475 tickers trade on any given day
    counts = _weekday_counts(470, {date(2026, 6, 3): 350, date(2026, 6, 9): 390})
    holes = _detect_universe_day_holes(counts, date(2026, 6, 1), date(2026, 6, 12))
    assert holes == []


def test_universe_wide_hole_detected():
    # One day where almost no tickers have bars → systemic sync hole
    counts = _weekday_counts(470, {date(2026, 6, 4): 12})
    holes = _detect_universe_day_holes(counts, date(2026, 6, 1), date(2026, 6, 12))
    assert holes == [date(2026, 6, 4)]


def test_missing_weekday_is_a_hole():
    # A weekday with no bars at all (absent from counts) → hole
    counts = _weekday_counts(470)
    del counts[date(2026, 6, 10)]
    holes = _detect_universe_day_holes(counts, date(2026, 6, 1), date(2026, 6, 12))
    assert holes == [date(2026, 6, 10)]


def test_holiday_is_not_a_hole():
    counts = _weekday_counts(470)
    del counts[date(2026, 6, 10)]
    holes = _detect_universe_day_holes(
        counts,
        date(2026, 6, 1),
        date(2026, 6, 12),
        holidays={date(2026, 6, 10)},
    )
    assert holes == []


def test_weekends_never_holes():
    counts = _weekday_counts(470)
    holes = _detect_universe_day_holes(counts, date(2026, 5, 30), date(2026, 6, 12))
    assert date(2026, 5, 30) not in holes  # Saturday
    assert date(2026, 5, 31) not in holes  # Sunday


def test_no_data_returns_no_holes():
    holes = _detect_universe_day_holes({}, date(2026, 6, 1), date(2026, 6, 12))
    assert holes == []


def test_backward_compat_data_quality_import():
    """_count_weekdays_between is re-exported from data_quality for compat."""
    from app.services.data_quality import _count_weekdays_between as _cw  # noqa: F401

    assert _cw(date(2024, 1, 1), date(2024, 1, 5)) == 3
