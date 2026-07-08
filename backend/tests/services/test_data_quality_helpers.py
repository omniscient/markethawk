"""
Tests for data_quality module pure helper functions — no DB required.
"""

from datetime import date, datetime, timedelta

from app.services.data_quality import (
    _count_weekdays_between,
    _estimate_expected_bars,
    _grade_color,
    _score_to_grade,
)

# ── _score_to_grade ───────────────────────────────────────────────────────────


def test_score_95_or_above_is_A():
    assert _score_to_grade(95.0) == "A"
    assert _score_to_grade(100.0) == "A"


def test_score_85_to_94_is_B():
    assert _score_to_grade(85.0) == "B"
    assert _score_to_grade(90.0) == "B"


def test_score_70_to_84_is_C():
    assert _score_to_grade(70.0) == "C"
    assert _score_to_grade(75.0) == "C"


def test_score_50_to_69_is_D():
    assert _score_to_grade(50.0) == "D"
    assert _score_to_grade(60.0) == "D"


def test_score_below_50_is_F():
    assert _score_to_grade(49.9) == "F"
    assert _score_to_grade(0.0) == "F"


# ── _grade_color ─────────────────────────────────────────────────────────────


def test_grade_A_is_green():
    assert _grade_color("A") == "green"


def test_grade_B_is_green():
    assert _grade_color("B") == "green"


def test_grade_C_is_yellow():
    assert _grade_color("C") == "yellow"


def test_grade_D_is_orange():
    assert _grade_color("D") == "orange"


def test_grade_F_is_red():
    assert _grade_color("F") == "red"


def test_unknown_grade_is_gray():
    assert _grade_color("Z") == "gray"


# ── _count_weekdays_between ───────────────────────────────────────────────────


def test_adjacent_days_no_weekday_between():
    d = date(2024, 1, 2)  # Tuesday
    assert _count_weekdays_between(d, d + timedelta(days=1)) == 0


def test_monday_to_friday_has_3_weekdays_between():
    monday = date(2024, 1, 1)  # Monday
    friday = date(2024, 1, 5)  # Friday
    # weekdays strictly between Mon and Fri: Tue, Wed, Thu = 3
    assert _count_weekdays_between(monday, friday) == 3


def test_weekend_days_not_counted():
    friday = date(2024, 1, 5)
    monday = date(2024, 1, 8)
    # strictly between Fri and Mon: Sat, Sun → 0 weekdays
    assert _count_weekdays_between(friday, monday) == 0


# ── _estimate_expected_bars ───────────────────────────────────────────────────


def _day_of_hour_bars(year, month, day, count):
    """Generate `count` hourly timestamps within one calendar date."""
    return [datetime(year, month, day, 4 + i) for i in range(count)]


def test_stocks_sparse_days_are_organic_no_partial_penalty():
    # Illiquid stock: bar count varies 8–16 per day. Verified against the
    # provider this is organic trading activity, not missing data — so for
    # stocks expected must equal actual (no partial-day penalty).
    timestamps = (
        _day_of_hour_bars(2026, 6, 22, 16)
        + _day_of_hour_bars(2026, 6, 23, 8)
        + _day_of_hour_bars(2026, 6, 24, 11)
        + _day_of_hour_bars(2026, 6, 25, 9)
    )
    expected, detail = _estimate_expected_bars(timestamps, "hour", 1, is_futures=False)
    assert expected == len(timestamps)
    assert detail["partial_days"] == []
    assert detail["partial_day_count"] == 0


def test_futures_partial_days_still_penalized():
    # Futures sessions are uniform — a below-P90 day (above the stub
    # threshold) is a genuine shortfall and keeps the P90 yardstick.
    timestamps = (
        _day_of_hour_bars(2026, 6, 22, 16)
        + _day_of_hour_bars(2026, 6, 23, 16)
        + _day_of_hour_bars(2026, 6, 24, 16)
        + _day_of_hour_bars(2026, 6, 25, 12)
    )
    expected, detail = _estimate_expected_bars(timestamps, "hour", 1, is_futures=True)
    assert expected == 16 * 4
    assert detail["partial_day_count"] == 1


def test_stocks_full_close_holiday_day_still_excluded():
    # Bars on a full_close holiday are anomalous and excluded from the
    # expected count for stocks too.
    timestamps = _day_of_hour_bars(2026, 6, 22, 16) + _day_of_hour_bars(2026, 6, 19, 3)
    holiday_map = {date(2026, 6, 19): "full_close"}
    expected, detail = _estimate_expected_bars(
        timestamps, "hour", 1, holiday_map, is_futures=False
    )
    assert expected == 16
    assert detail["holiday_day_count"] == 1
