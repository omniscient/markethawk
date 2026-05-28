"""
Live scanner conditions — evaluated on each completed 1-minute bar.
"""

from dataclasses import dataclass
from typing import List

from live_scanner.bar_aggregator import MinuteBar, session_total_minutes

# ── Thresholds ─────────────────────────────────────────────────────────────
VOLUME_SPIKE_RATIO = 4.0  # projected full-session volume vs avg daily volume
PRICE_MOVE_PCT = 0.01  # 1% move from prior close
MIN_AVG_VOLUME = 50_000  # skip symbols too illiquid to produce meaningful ratios
MIN_MINUTES_ELAPSED = 2.0  # don't fire in the very first minute (noisy)


@dataclass
class ConditionResult:
    scanner_type: str
    indicators: dict
    criteria_met: dict


def check_conditions(bar: MinuteBar) -> List[ConditionResult]:
    """
    Evaluate all live conditions against a completed 1-minute bar.
    Returns only the conditions that fired.
    """
    triggered: List[ConditionResult] = []

    # ── Volume spike ───────────────────────────────────────────────────────
    if (
        bar.avg_daily_volume >= MIN_AVG_VOLUME
        and bar.minutes_elapsed >= MIN_MINUTES_ELAPSED
        and bar.session != "closed"
    ):
        session_total = session_total_minutes(bar.session)
        projected_vol = bar.session_volume / bar.minutes_elapsed * session_total
        vol_ratio = projected_vol / bar.avg_daily_volume

        if vol_ratio >= VOLUME_SPIKE_RATIO:
            triggered.append(
                ConditionResult(
                    scanner_type="live_volume_spike",
                    indicators={
                        "volume_spike_ratio": round(vol_ratio, 2),
                        "session_volume": bar.session_volume,
                        "avg_daily_volume": int(bar.avg_daily_volume),
                        "projected_volume": int(projected_vol),
                        "minutes_elapsed": bar.minutes_elapsed,
                        "session": bar.session,
                    },
                    criteria_met={
                        "volume_spike_4x": True,
                        "sufficient_avg_volume": True,
                    },
                )
            )

    # ── Price move ─────────────────────────────────────────────────────────
    if bar.prior_close > 0 and bar.session != "closed":
        move_pct = (bar.close - bar.prior_close) / bar.prior_close * 100.0
        if abs(move_pct) >= PRICE_MOVE_PCT * 100:
            triggered.append(
                ConditionResult(
                    scanner_type="live_price_move",
                    indicators={
                        "price_move_pct": round(move_pct, 2),
                        "current_price": bar.close,
                        "prior_close": bar.prior_close,
                        "session": bar.session,
                    },
                    criteria_met={
                        "price_move_1pct": True,
                    },
                )
            )

    return triggered
