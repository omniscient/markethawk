"""Trading session classification utilities."""

from datetime import datetime, time, date, timezone
from zoneinfo import ZoneInfo

_ET = ZoneInfo("America/New_York")


def classify_session(ts_utc: datetime) -> tuple[bool, bool]:
    """Return (is_pre_market, is_after_market) for a UTC timestamp.

    Session boundaries (US/Eastern):
      pre-market:   4:00 AM – 9:29 AM
      regular:      9:30 AM – 4:00 PM  (16:00 bar is the last regular bar)
      after-market: 4:01 PM – 7:59 PM
    """
    if ts_utc.tzinfo is None:
        ts_utc = ts_utc.replace(tzinfo=timezone.utc)
    ts_et = ts_utc.astimezone(_ET)
    h, m = ts_et.hour, ts_et.minute
    is_pre  = (h >= 4 and h < 9) or (h == 9 and m < 30)
    is_post = (h == 16 and m >= 1) or (h > 16 and h < 20)
    return is_pre, is_post


def get_market_now() -> datetime:
    """Return the current time in America/New_York."""
    return datetime.now(_ET)


def get_market_today() -> date:
    """Return the current date in America/New_York."""
    return get_market_now().date()
