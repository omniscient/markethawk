"""Trading session classification utilities."""

from datetime import datetime, date, timezone
from zoneinfo import ZoneInfo

_ET = ZoneInfo("America/New_York")

_SESSIONS = [
    ("pre",     4 * 60,       9 * 60 + 30),
    ("regular", 9 * 60 + 30,  16 * 60),
    ("post",    16 * 60,       20 * 60),
]


def session_for_ts(ts: datetime) -> str:
    """Return 'pre', 'regular', 'post', or 'closed' for a UTC or timezone-aware timestamp."""
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    et = ts.astimezone(_ET)
    m = et.hour * 60 + et.minute
    for name, start, end in _SESSIONS:
        if start <= m < end:
            return name
    return "closed"


def session_total_minutes(session: str) -> float:
    """Total minutes in a named session (pre=330, regular=390, post=240)."""
    for name, start, end in _SESSIONS:
        if name == session:
            return float(end - start)
    return 390.0


def classify_session(ts_utc: datetime) -> tuple[bool, bool]:
    """Deprecated. Use session_for_ts() instead. Returns (is_pre, is_post)."""
    session = session_for_ts(ts_utc)
    return session == "pre", session == "post"


def get_market_now() -> datetime:
    """Return the current time in America/New_York."""
    return datetime.now(_ET)


def get_market_today() -> date:
    """Return the current date in America/New_York."""
    return get_market_now().date()
