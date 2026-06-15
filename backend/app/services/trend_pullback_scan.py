"""
Trend Pullback Scanner

Detects stocks in confirmed uptrends (close > SMA50 > SMA200, SMA50 rising) pulling
back in an orderly way to their rising 20-day SMA. Severity is 'high' when depth ≤8%
and RSI(5) <30; 'medium' otherwise.

Runs nightly at 02:00 UTC Mon-Fri via Celery beat.
Self-registers with the scan orchestrator at import time.
"""

from __future__ import annotations

import logging
import time as _time
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Optional
from zoneinfo import ZoneInfo

import pandas as pd
from sqlalchemy.orm import Session

from app.core.metrics import (
    scan_duration_seconds,
    scan_failed_tickers_ratio,
    scan_last_success_timestamp,
    scanner_events_total,
)
from app.models.stock_aggregate import StockAggregate
from app.services.alert_service import save_event as _save_event
from app.utils.session import get_market_today

_ET = ZoneInfo("America/New_York")
_LOG = logging.getLogger(__name__)

_LOOKBACK_DAYS = 300  # bars fetched; 252 needed + buffer

DEFAULT_CONFIG: dict[str, Any] = {
    "trend_sma_fast": 50,
    "trend_sma_slow": 200,
    "sma_rising_lookback": 20,
    "max_pct_off_high": 15,
    "pullback_sma": 20,
    "pullback_sma_tolerance_pct": 1,
    "min_days_above_sma": 5,
    "pullback_min_pct": 3,
    "pullback_max_pct": 12,
    "rsi_period": 5,
    "rsi_max": 40,
    "min_dollar_vol": 5_000_000,
    "min_price": 5.0,
}


def _get_daily_bars(db: Session, ticker: str, event_date: date, lookback: int) -> list:
    """Fetch up to `lookback` daily bars ending on event_date (inclusive), ascending."""
    day_end_utc = (
        datetime.combine(event_date + timedelta(days=1), time.min, tzinfo=_ET)
        .astimezone(timezone.utc)
        .replace(tzinfo=None)
    )
    cutoff_utc = (
        datetime.combine(
            event_date - timedelta(days=lookback + 30), time.min, tzinfo=_ET
        )
        .astimezone(timezone.utc)
        .replace(tzinfo=None)
    )
    rows = (
        db.query(StockAggregate)
        .filter(
            StockAggregate.ticker == ticker,
            StockAggregate.timespan == "day",
            StockAggregate.timestamp >= cutoff_utc,
            StockAggregate.timestamp < day_end_utc,
        )
        .order_by(StockAggregate.timestamp.asc())
        .all()
    )
    return rows[-lookback:] if len(rows) > lookback else rows


def _calc_rsi(series: "pd.Series", period: int) -> "pd.Series":
    delta = series.diff()
    up = delta.clip(lower=0)
    down = -delta.clip(upper=0)
    ema_up = up.ewm(com=period - 1, adjust=False).mean()
    ema_down = down.ewm(com=period - 1, adjust=False).mean()
    rs = ema_up / ema_down
    return 100 - (100 / (1 + rs))


def _calc_atr(df: "pd.DataFrame", period: int) -> "pd.Series":
    tr = pd.concat(
        [
            df["High"] - df["Low"],
            (df["High"] - df["Close"].shift(1)).abs(),
            (df["Low"] - df["Close"].shift(1)).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr.ewm(com=period - 1, adjust=False).mean()


def _evaluate_ticker(
    ticker: str,
    event_date: date,
    bars: list,
    cfg: dict[str, Any],
) -> dict[str, Any] | None:
    """
    Evaluate one ticker against the trend_pullback criteria.
    Returns an indicators+criteria dict if the signal fires, else None.
    """
    if len(bars) < cfg["trend_sma_slow"] + 10:
        return None

    df = pd.DataFrame(
        [
            {
                "Close": float(b.close),
                "Open": float(b.open),
                "High": float(b.high),
                "Low": float(b.low),
                "Volume": float(b.volume),
            }
            for b in bars
        ]
    )

    sma20 = df["Close"].rolling(cfg["pullback_sma"]).mean()
    sma50 = df["Close"].rolling(cfg["trend_sma_fast"]).mean()
    sma200 = df["Close"].rolling(cfg["trend_sma_slow"]).mean()
    rsi5 = _calc_rsi(df["Close"], cfg["rsi_period"])
    atr14 = _calc_atr(df, 14)

    typ_price = (df["High"] + df["Low"] + df["Close"]) / 3
    dollar_vol = df["Volume"] * typ_price
    avg_dollar_vol_20 = dollar_vol.rolling(20).mean()

    idx = len(df) - 1  # today (the event_date bar)

    close_today = df["Close"].iloc[idx]
    low_today = df["Low"].iloc[idx]
    sma20_today = sma20.iloc[idx]
    sma50_today = sma50.iloc[idx]
    sma200_today = sma200.iloc[idx]
    rsi5_today = rsi5.iloc[idx]
    atr14_today = atr14.iloc[idx]
    avg_dv_today = avg_dollar_vol_20.iloc[idx]

    # Guard against NaN in required indicators
    if any(
        pd.isna(v)
        for v in [
            sma20_today,
            sma50_today,
            sma200_today,
            rsi5_today,
            atr14_today,
            avg_dv_today,
        ]
    ):
        return None

    # --- Criteria 1: Established uptrend ---
    trend_ok = bool(close_today > sma50_today > sma200_today)
    # SMA50 rising: today's SMA50 > SMA50 `sma_rising_lookback` sessions ago
    rising_lb = cfg["sma_rising_lookback"]
    if idx < rising_lb:
        return None
    sma50_lb_ago = sma50.iloc[idx - rising_lb]
    if pd.isna(sma50_lb_ago):
        return None
    sma50_rising = bool(sma50_today > sma50_lb_ago)
    criterion_uptrend = trend_ok and sma50_rising

    # --- Criteria 2: Near highs ---
    high_252 = df["High"].iloc[max(0, idx - 251) : idx + 1].max()
    pct_off_high = (high_252 - close_today) / high_252 * 100 if high_252 > 0 else 999.0
    criterion_near_high = bool(pct_off_high <= cfg["max_pct_off_high"])

    # --- Criteria 3: Pullback in progress — tagged SMA20 after ≥5 closes above it ---
    tolerance_mult = 1 + cfg["pullback_sma_tolerance_pct"] / 100
    tagged_sma20 = bool(low_today <= sma20_today * tolerance_mult)
    # Count consecutive prior closes above SMA20 (look back up to 60 days)
    min_above = cfg["min_days_above_sma"]
    lookback_window = min(60, idx)
    consecutive_above = 0
    for k in range(idx - 1, max(idx - lookback_window - 1, -1), -1):
        if pd.isna(sma20.iloc[k]):
            break
        if df["Close"].iloc[k] > sma20.iloc[k]:
            consecutive_above += 1
        else:
            break
    criterion_pullback = tagged_sma20 and consecutive_above >= min_above

    # --- Criteria 4: Orderly pullback (depth + no close below SMA50) ---
    # Swing high: highest close in the prior 20 sessions before today
    swing_window = min(20, idx)
    swing_high = (
        df["Close"].iloc[idx - swing_window : idx].max()
        if swing_window > 0
        else close_today
    )
    pullback_depth = (
        (swing_high - close_today) / swing_high * 100 if swing_high > 0 else 0.0
    )
    depth_ok = bool(
        cfg["pullback_min_pct"] <= pullback_depth <= cfg["pullback_max_pct"]
    )
    # No close below SMA50 in the pullback window (last `swing_window` sessions including today)
    no_breakdown = True
    for k in range(idx - swing_window, idx + 1):
        if k < 0:
            continue
        if pd.isna(sma50.iloc[k]):
            continue
        if df["Close"].iloc[k] < sma50.iloc[k]:
            no_breakdown = False
            break
    criterion_orderly = depth_ok and no_breakdown

    # --- Criteria 5: Reset confirmed (RSI5 < rsi_max) ---
    criterion_rsi = bool(rsi5_today < cfg["rsi_max"])

    # --- Criteria 6: Liquidity floors ---
    criterion_liq = bool(
        avg_dv_today >= cfg["min_dollar_vol"] and close_today >= cfg["min_price"]
    )

    indicators: dict[str, Any] = {
        "close": round(close_today, 4),
        "sma20": round(sma20_today, 4),
        "sma50": round(sma50_today, 4),
        "sma200": round(sma200_today, 4),
        "rsi5": round(rsi5_today, 2),
        "pct_off_252d_high": round(pct_off_high, 2),
        "pullback_depth_pct": round(pullback_depth, 2),
        "consecutive_days_above_sma20": consecutive_above,
        "atr14": round(atr14_today, 4),
        "avg_dollar_vol_20d": round(avg_dv_today, 0),
    }

    criteria_met: dict[str, bool] = {
        "uptrend": criterion_uptrend,
        "near_high": criterion_near_high,
        "pullback_in_progress": criterion_pullback,
        "orderly_pullback": criterion_orderly,
        "rsi_reset": criterion_rsi,
        "liquidity": criterion_liq,
    }

    fired = all(criteria_met.values())
    return {
        "indicators": indicators,
        "criteria_met": criteria_met,
        "close": close_today,
        "fired": fired,
    }


async def run_trend_pullback_scan(
    tickers: list[str],
    db: Session,
    start_date: date | None = None,
    end_date: date | None = None,
    config: dict | None = None,
    diagnostics_out: dict | None = None,
) -> list[dict[str, Any]]:
    """
    Run the trend_pullback scanner over a date range.

    For each (ticker, event_date):
      1. Fetch ~300 daily bars.
      2. Compute rolling indicators (SMA20/50/200, RSI5, ATR14, avg dollar vol).
      3. Evaluate all 6 criteria.
      4. Persist ScannerEvent if all pass.
    """
    _perf_start = _time.monotonic()
    try:
        if start_date is None and end_date is None:
            start_date = end_date = get_market_today()
        elif start_date is None:
            start_date = end_date
        elif end_date is None:
            end_date = start_date

        cfg: dict[str, Any] = {**DEFAULT_CONFIG, **(config or {})}

        results: list[dict[str, Any]] = []
        counts = {
            "no_bars": 0,
            "insufficient_history": 0,
            "evaluated": 0,
            "fired": 0,
            "errors": 0,
        }

        trading_days = [
            start_date + timedelta(days=i)
            for i in range((end_date - start_date).days + 1)
            if (start_date + timedelta(days=i)).weekday() < 5
        ]

        for event_date in trading_days:
            for ticker in tickers:
                try:
                    bars = _get_daily_bars(db, ticker, event_date, _LOOKBACK_DAYS)
                    if not bars:
                        counts["no_bars"] += 1
                        continue

                    result = _evaluate_ticker(ticker, event_date, bars, cfg)
                    if result is None:
                        counts["insufficient_history"] += 1
                        continue

                    counts["evaluated"] += 1

                    if not result["fired"]:
                        continue

                    close_today = result["close"]
                    indicators = result["indicators"]
                    criteria_met = result["criteria_met"]

                    event_dict = _save_event(
                        db=db,
                        ticker=ticker,
                        event_date=event_date,
                        scanner_type="trend_pullback",
                        indicators=indicators,
                        criteria_met=criteria_met,
                        enrichment={},
                        previous_close=None,
                        closing_price=close_today,
                    )
                    results.append(event_dict)
                    counts["fired"] += 1
                    scanner_events_total.labels(scanner_type="trend_pullback").inc()

                except Exception:
                    counts["errors"] += 1
                    _LOG.exception(
                        "Error in trend_pullback scan for %s on %s", ticker, event_date
                    )

        _LOG.info(
            "trend_pullback scan complete: tickers=%d days=%d "
            "no_bars=%d insufficient_history=%d evaluated=%d fired=%d errors=%d",
            len(tickers),
            len(trading_days),
            counts["no_bars"],
            counts["insufficient_history"],
            counts["evaluated"],
            counts["fired"],
            counts["errors"],
        )

        if diagnostics_out is not None:
            diagnostics_out.update(
                {
                    "tickers": len(tickers),
                    "days": len(trading_days),
                    "start_date": start_date.isoformat(),
                    "end_date": end_date.isoformat(),
                    "no_bars": counts["no_bars"],
                    "insufficient_history": counts["insufficient_history"],
                    "evaluated": counts["evaluated"],
                    "fired": counts["fired"],
                    "errors": counts["errors"],
                }
            )

        _total_units = len(tickers) * len(trading_days)
        if _total_units == 0 or counts["errors"] < _total_units:
            scan_last_success_timestamp.labels(scanner_type="trend_pullback").set(
                _time.time()
            )
        scan_failed_tickers_ratio.labels(scanner_type="trend_pullback").set(
            counts["errors"] / max(1, len(tickers) * len(trading_days))
        )
        return results
    finally:
        scan_duration_seconds.labels(scanner_type="trend_pullback").observe(
            _time.monotonic() - _perf_start
        )


async def run_trend_pullback_scan_for_date(
    ticker: str,
    event_date: date,
    db: Session,
) -> list[dict[str, Any]]:
    """Single-ticker single-date wrapper used by run_range_scan's scanner_map."""
    return await run_trend_pullback_scan(
        [ticker], db, start_date=event_date, end_date=event_date
    )


# -- Orchestrator self-registration -------------------------------------------

from app.services.scan_orchestrator import ScannerDescriptor, register  # noqa: E402


async def _orchestrator_run(
    tickers: list,
    db: Any,
    event_date: date,
    scanner_run: Optional[Any] = None,
) -> list[dict]:
    """Adapter: maps the standard ScannerFn signature to run_trend_pullback_scan."""
    return await run_trend_pullback_scan(
        tickers=tickers,
        db=db,
        start_date=event_date,
        end_date=event_date,
    )


register(
    ScannerDescriptor(
        key="trend_pullback",
        display_name="Trend Pullback",
        description=(
            "Detects stocks in confirmed uptrends (close > SMA50 > SMA200, SMA50 rising) "
            "pulling back in an orderly way to their rising 20-day SMA. "
            "RSI(5) < 40 confirms the reset; liquidity floors apply."
        ),
        run=_orchestrator_run,
        supports_date_range=True,
    )
)
