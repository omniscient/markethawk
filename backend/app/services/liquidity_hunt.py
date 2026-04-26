"""
Liquidity Hunt Scanner

Detects off-hours (pre-market or after-market) volume anomalies where:
- Session volume is unusually large relative to the ticker's own history
- Session price spiked ≥10% UP from reference close
- The regular trading session that same day was quiet (normal volume + range)

Two event types are emitted: liquidity_hunt_pre and liquidity_hunt_post.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session
from sqlalchemy import desc

from app.models.stock_aggregate import StockAggregate
from app.models.monitored_stock import MonitoredStock
from app.models.ticker_reference import TickerReference
from app.models.stock_split import StockSplit
from app.services.catalyst_parser import CatalystParser
from app.services.scanner import ScannerService

_ET = ZoneInfo("America/New_York")
_LOG = logging.getLogger(__name__)

DEFAULT_CONFIG: dict[str, float] = {
    "volume_ratio_min": 4.0,           # criterion 1: session vol / 20d avg session vol
    "volume_pct_of_daily_min": 0.30,   # criterion 2: session vol / 20d avg total daily vol
    "spike_pct_min": 0.10,             # criterion 3: (session_high / reference_close) - 1
    "regular_vol_ratio_max": 1.20,     # criterion 4: regular vol / 20d avg regular vol
    "regular_range_ratio_max": 1.50,   # criterion 5: today range% / 20d avg range%
    "session_volume_floor": 50_000,    # criterion 6: absolute minimum shares
}


def _evaluate_criteria(
    session: str,
    session_vol: float,
    session_high: float,
    reference_close: float,
    regular_vol: float,
    regular_high: float,
    regular_low: float,
    regular_open: float,
    baselines: dict[str, Any],
    config: dict[str, Any] | None,
) -> tuple[bool, dict[str, Any], dict[str, bool]]:
    """
    Evaluate all six liquidity-hunt criteria against session metrics.

    Returns (fires, indicators_dict, criteria_met_dict).
    Does not access the database — all inputs are plain Python values.

    session: "pre" or "post" — determines which baseline vol to use.
    reference_close: prior_day_close for "pre"; event_date_regular_close for "post".
    """
    cfg = {**DEFAULT_CONFIG, **(config or {})}

    avg_session_vol = (
        baselines["avg_pre_vol_20d"] if session == "pre" else baselines["avg_post_vol_20d"]
    )
    avg_regular_vol = baselines["avg_regular_vol_20d"]
    avg_total_daily_vol = baselines["avg_total_daily_vol_20d"]
    avg_range_pct = baselines["avg_regular_range_pct_20d"]

    # Criterion 1: volume ratio (trivially satisfied when baseline is zero)
    if avg_session_vol > 0:
        vol_ratio = session_vol / avg_session_vol
        c1 = vol_ratio >= cfg["volume_ratio_min"]
    else:
        vol_ratio = None  # infinite — baseline was zero
        c1 = True

    # Criterion 2: materiality
    vol_pct_of_daily = (
        session_vol / avg_total_daily_vol if avg_total_daily_vol > 0 else 0.0
    )
    c2 = vol_pct_of_daily >= cfg["volume_pct_of_daily_min"]

    # Criterion 3: UP spike
    spike_pct = (
        (session_high - reference_close) / reference_close
        if reference_close > 0 else 0.0
    )
    c3 = spike_pct >= cfg["spike_pct_min"]

    # Criterion 4: quiet regular volume
    regular_vol_ratio = (
        regular_vol / avg_regular_vol if avg_regular_vol > 0 else float("inf")
    )
    c4 = regular_vol_ratio <= cfg["regular_vol_ratio_max"]

    # Criterion 5: quiet regular range
    regular_range_pct = (
        (regular_high - regular_low) / regular_open if regular_open > 0 else 0.0
    )
    regular_range_ratio = (
        regular_range_pct / avg_range_pct if avg_range_pct > 0 else float("inf")
    )
    c5 = regular_range_ratio <= cfg["regular_range_ratio_max"]

    # Criterion 6: absolute floor
    c6 = session_vol >= cfg["session_volume_floor"]

    fires = c1 and c2 and c3 and c4 and c5 and c6

    indicators: dict[str, Any] = {
        "session": session,
        "session_volume": int(session_vol),
        "avg_session_volume_20d": int(avg_session_vol) if avg_session_vol else 0,
        "session_volume_ratio": round(vol_ratio, 2) if vol_ratio is not None else None,
        "session_volume_pct_of_daily": round(vol_pct_of_daily, 4),
        "session_high": float(session_high),
        "reference_close": float(reference_close),
        "session_spike_pct": round(spike_pct, 4),
        "regular_volume": int(regular_vol),
        "avg_regular_volume_20d": int(avg_regular_vol),
        "regular_volume_ratio": round(regular_vol_ratio, 4),
        "regular_range_pct": round(regular_range_pct, 4),
        "avg_regular_range_pct_20d": round(avg_range_pct, 4),
        "regular_range_ratio": round(regular_range_ratio, 4),
    }

    criteria_met: dict[str, bool] = {
        "volume_ratio": c1,
        "volume_materiality": c2,
        "session_spike": c3,
        "quiet_regular_vol": c4,
        "quiet_regular_range": c5,
        "volume_floor": c6,
    }

    return fires, indicators, criteria_met
