"""
Bar aggregator — converts 5-second IBKR real-time bars into 1-minute bars.

Also tracks session type (pre / regular / post) and cumulative session volume
so callers can compute projected-volume ratios and price-move percentages.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")

# Session windows expressed as (name, start_minute, end_minute) in ET minutes-from-midnight
_SESSIONS = [
    ("pre",     4 * 60,      9 * 60 + 30),
    ("regular", 9 * 60 + 30, 16 * 60),
    ("post",    16 * 60,     20 * 60),
]


def session_for_ts(ts: datetime) -> str:
    """Return the trading session name for a UTC timestamp."""
    et = ts.astimezone(ET)
    m = et.hour * 60 + et.minute
    for name, start, end in _SESSIONS:
        if start <= m < end:
            return name
    return "closed"


def session_total_minutes(session: str) -> float:
    """Total minutes in a session (used to project full-session volume)."""
    for name, start, end in _SESSIONS:
        if name == session:
            return float(end - start)
    return 390.0  # fallback to regular session length


@dataclass
class MinuteBar:
    minute_ts: datetime       # start of the minute (UTC)
    symbol: str
    open: float
    high: float
    low: float
    close: float
    volume: int
    vwap: float
    bar_count: int            # number of 5s bars aggregated into this minute
    session: str
    session_volume: int       # cumulative volume since session start
    minutes_elapsed: float    # minutes into the current session (≥ 1)
    prior_close: float
    avg_daily_volume: float


class BarAggregator:
    """
    Aggregates 5-second IBKR real-time bars into 1-minute bars.

    Call update(bar) for each incoming RealTimeBar. When a minute rolls over,
    a completed MinuteBar is returned; otherwise None.
    """

    def __init__(self, symbol: str, prior_close: float, avg_daily_volume: float):
        self.symbol = symbol
        self.prior_close = prior_close
        self.avg_daily_volume = avg_daily_volume

        self._current_minute_ts: Optional[datetime] = None
        self._current_session = "closed"
        self._open = self._high = self._low = self._close = 0.0
        self._volume = 0
        self._vwap_sum = 0.0   # Σ(wap * volume) for computing bar VWAP
        self._bar_count = 0

        self._session_volume = 0
        self._last_session = "closed"
        self._session_start_minute: Optional[datetime] = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def update(self, bar) -> Optional[MinuteBar]:
        """
        Feed one 5-second RealTimeBar. Returns a completed MinuteBar when a
        minute boundary is crossed, otherwise None.
        """
        t = bar.time
        if isinstance(t, datetime):
            ts = t if t.tzinfo else t.replace(tzinfo=timezone.utc)
        else:
            ts = datetime.fromtimestamp(float(t), tz=timezone.utc)
        session = session_for_ts(ts)

        # Session boundary → reset session accumulators
        if session != self._last_session and session != "closed":
            self._session_volume = 0
            self._session_start_minute = None
        self._last_session = session

        bar_vol = max(0, int(bar.volume))
        self._session_volume += bar_vol

        # Round down to the start of the minute
        minute_ts = ts.replace(second=0, microsecond=0)

        # Track when this session started (first non-closed bar)
        if self._session_start_minute is None and session != "closed":
            self._session_start_minute = minute_ts

        completed: Optional[MinuteBar] = None

        if self._current_minute_ts is None:
            self._open_new_minute(minute_ts, bar, bar_vol, session)
        elif minute_ts != self._current_minute_ts:
            # Minute rolled — emit the completed bar then open a fresh one
            completed = self._emit_bar()
            self._open_new_minute(minute_ts, bar, bar_vol, session)
        else:
            # Same minute — accumulate
            self._high = max(self._high, float(bar.high))
            self._low = min(self._low, float(bar.low))
            self._close = float(bar.close)
            self._volume += bar_vol
            self._vwap_sum += float(bar.wap) * bar_vol
            self._bar_count += 1

        return completed

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _open_new_minute(self, minute_ts: datetime, bar, bar_vol: int, session: str):
        self._current_minute_ts = minute_ts
        self._current_session = session
        self._open = float(bar.open_)
        self._high = float(bar.high)
        self._low = float(bar.low)
        self._close = float(bar.close)
        self._volume = bar_vol
        self._vwap_sum = float(bar.wap) * bar_vol
        self._bar_count = 1

    def _emit_bar(self) -> MinuteBar:
        if self._session_start_minute and self._current_minute_ts:
            minutes_elapsed = (
                (self._current_minute_ts - self._session_start_minute).total_seconds() / 60.0
            ) + 1.0
        else:
            minutes_elapsed = 1.0

        vwap = (
            self._vwap_sum / self._volume
            if self._volume > 0
            else self._close
        )

        return MinuteBar(
            minute_ts=self._current_minute_ts,
            symbol=self.symbol,
            open=self._open,
            high=self._high,
            low=self._low,
            close=self._close,
            volume=self._volume,
            vwap=round(vwap, 4),
            bar_count=self._bar_count,
            session=self._current_session,
            session_volume=self._session_volume,
            minutes_elapsed=round(minutes_elapsed, 1),
            prior_close=self.prior_close,
            avg_daily_volume=self.avg_daily_volume,
        )
