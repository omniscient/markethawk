"""
Shared helpers for aggregate data-quality computations.

Extracted from data_quality.py so the lightweight nightly staleness/gap sweep
(check_aggregate_staleness task) can reuse them without importing the full
DataQualityService.
"""

from datetime import date, timedelta
from typing import Dict, List, Optional, Set


def _count_weekdays_between(d1, d2) -> int:
    """Count weekdays (Mon–Fri) strictly between two dates."""
    count = 0
    current = d1 + timedelta(days=1)
    while current < d2:
        if current.weekday() < 5:
            count += 1
        current += timedelta(days=1)
    return count


def _detect_gaps(timestamps: List, timespan: str, multiplier: int) -> List[Dict]:
    """
    Return a list of data gaps.

    A gap is a consecutive-timestamp pair where:
      • the elapsed time exceeds 5 × the expected bar interval, AND
      • more than 1 weekday falls between the two timestamps
        (this filters out weekends and single-day holidays naturally).
    """
    if len(timestamps) < 2:
        return []

    expected_seconds = {
        "minute": 60,
        "hour": 3600,
        "day": 86400,
        "week": 604800,
        "month": 2592000,
    }.get(timespan, 60) * multiplier

    threshold_seconds = expected_seconds * 5

    gaps = []
    for i in range(1, len(timestamps)):
        prev = timestamps[i - 1]
        curr = timestamps[i]
        diff_seconds = (curr - prev).total_seconds()

        if diff_seconds < threshold_seconds:
            continue

        # ≤1 weekday between the bars means the span is a weekend or a
        # holiday long weekend (e.g. Fri→Tue over Memorial Day) — not a gap.
        weekdays = _count_weekdays_between(prev.date(), curr.date())
        if weekdays <= 1:
            continue

        missing_bars = max(0, int(diff_seconds / expected_seconds) - 1)
        gaps.append(
            {
                "from": prev,
                "to": curr,
                "duration_hours": round(diff_seconds / 3600, 1),
                "missing_bars": missing_bars,
            }
        )

    return gaps


def _detect_universe_day_holes(
    counts_by_day: Dict[date, int],
    start: date,
    end: date,
    holidays: Optional[Set[date]] = None,
) -> List[date]:
    """
    Detect universe-wide day-bar holes: weekdays where far fewer tickers than
    usual have a day bar.

    Per-ticker missing day bars are indistinguishable from organic no-trade
    days on illiquid tickers (verified bar-for-bar against the provider), so
    ticker-level gap counting over-alarms on small-cap universes.  A genuine
    sync outage instead shows up as a calendar day where the number of tickers
    with bars collapses relative to the norm.

    ``counts_by_day`` maps date → number of tickers with a day bar that date.
    A weekday inside [start, end] (excluding known holidays) is a hole when
    its ticker count is below 50 % of the median active day's count.
    """
    holidays = holidays or set()

    active_counts = sorted(v for v in counts_by_day.values() if v > 0)
    if not active_counts:
        return []
    median = active_counts[len(active_counts) // 2]
    threshold = median * 0.5

    holes: List[date] = []
    d = start
    while d <= end:
        if d.weekday() < 5 and d not in holidays:
            if counts_by_day.get(d, 0) < threshold:
                holes.append(d)
        d += timedelta(days=1)
    return holes
