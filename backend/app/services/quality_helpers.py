"""
Shared helpers for aggregate data-quality computations.

Extracted from data_quality.py so the lightweight nightly staleness/gap sweep
(check_aggregate_staleness task) can reuse them without importing the full
DataQualityService.
"""

from datetime import timedelta
from typing import Dict, List


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

        calendar_days = (curr.date() - prev.date()).days
        if calendar_days <= 3:
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
