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
import math
import time as _time
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
from app.services.alert_service import save_event as _save_event
from app.utils.session import get_market_today
from app.core.metrics import scanner_events_total, scan_duration_seconds

_ET = ZoneInfo("America/New_York")
_LOG = logging.getLogger(__name__)

DEFAULT_CONFIG: dict[str, Any] = {
    "volume_ratio_min": 4.0,           # criterion 1: session vol / 20d avg session vol
    "volume_pct_of_daily_min": 0.30,   # criterion 2: session vol / 20d avg total daily vol
    "spike_pct_min": 0.10,             # criterion 3: (session_high / reference_close) - 1
    # criterion 4: regular vol / 20d avg regular vol. Effectively disabled (1000.0) —
    # criterion 5 (regular range ratio) is the meaningful "orderly regular session"
    # filter. Tracking high regular volume actively excludes the canonical liquidity
    # hunt pattern where retail piles in after a pre-market spike but price stays
    # range-bound. Kept in the indicators dict for inspection.
    "regular_vol_ratio_max": 1000.0,
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
        "regular_volume_ratio": round(regular_vol_ratio, 4) if math.isfinite(regular_vol_ratio) else None,
        "regular_range_pct": round(regular_range_pct, 4),
        "avg_regular_range_pct_20d": round(avg_range_pct, 4),
        "regular_range_ratio": round(regular_range_ratio, 4) if math.isfinite(regular_range_ratio) else None,
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


def _get_session_metrics(
    db: Session, ticker: str, event_date: date
) -> dict[str, Any] | None:
    """
    Query all minute bars for event_date. Return per-session aggregates.
    Returns None if no regular-session bars exist (e.g. market holiday).
    """
    day_start_utc = (
        datetime.combine(event_date, time.min, tzinfo=_ET)
        .astimezone(timezone.utc)
        .replace(tzinfo=None)
    )
    day_end_utc = (
        datetime.combine(event_date + timedelta(days=1), time.min, tzinfo=_ET)
        .astimezone(timezone.utc)
        .replace(tzinfo=None)
    )

    rows = (
        db.query(StockAggregate)
        .filter(
            StockAggregate.ticker == ticker,
            StockAggregate.timespan == "minute",
            StockAggregate.timestamp >= day_start_utc,
            StockAggregate.timestamp < day_end_utc,
        )
        .order_by(StockAggregate.timestamp)
        .all()
    )

    pre = [r for r in rows if r.is_pre_market]
    regular = [r for r in rows if not r.is_pre_market and not r.is_after_market]
    post = [r for r in rows if r.is_after_market]

    if not regular:
        return None

    return {
        "pre_vol": float(sum(r.volume for r in pre)),
        "pre_high": float(max((r.high for r in pre), default=0)),
        "regular_vol": float(sum(r.volume for r in regular)),
        "regular_high": float(max(r.high for r in regular)),
        "regular_low": float(min(r.low for r in regular)),
        "regular_open": float(regular[0].open),
        "regular_close": float(regular[-1].close),
        "post_vol": float(sum(r.volume for r in post)),
        "post_high": float(max((r.high for r in post), default=0)),
    }


def _get_prior_day_close(db: Session, ticker: str, event_date: date) -> float | None:
    """
    Return the regular close of the most recent trading day before event_date.
    Tries timespan='day' bars first; falls back to the last regular minute bar.
    """
    day_start_utc = (
        datetime.combine(event_date, time.min, tzinfo=_ET)
        .astimezone(timezone.utc)
        .replace(tzinfo=None)
    )

    row = (
        db.query(StockAggregate.close)
        .filter(
            StockAggregate.ticker == ticker,
            StockAggregate.timespan == "day",
            StockAggregate.timestamp < day_start_utc,
        )
        .order_by(desc(StockAggregate.timestamp))
        .limit(1)
        .first()
    )
    if row:
        return float(row[0])

    row = (
        db.query(StockAggregate.close)
        .filter(
            StockAggregate.ticker == ticker,
            StockAggregate.timespan == "minute",
            StockAggregate.is_pre_market.is_(False),
            StockAggregate.is_after_market.is_(False),
            StockAggregate.timestamp < day_start_utc,
        )
        .order_by(desc(StockAggregate.timestamp))
        .limit(1)
        .first()
    )
    return float(row[0]) if row else None


def _get_event_date_regular_close(
    db: Session, ticker: str, event_date: date
) -> float | None:
    """
    Return the last regular-session minute close on event_date itself.
    Used as the reference close for the post-market variant.
    """
    day_start_utc = (
        datetime.combine(event_date, time.min, tzinfo=_ET)
        .astimezone(timezone.utc)
        .replace(tzinfo=None)
    )
    reg_end_utc = (
        datetime.combine(event_date, time(16, 0), tzinfo=_ET)  # 4:00 PM ET (regular close)
        .astimezone(timezone.utc)
        .replace(tzinfo=None)
    )

    row = (
        db.query(StockAggregate.close)
        .filter(
            StockAggregate.ticker == ticker,
            StockAggregate.timespan == "minute",
            StockAggregate.is_pre_market.is_(False),
            StockAggregate.is_after_market.is_(False),
            StockAggregate.timestamp >= day_start_utc,
            StockAggregate.timestamp < reg_end_utc,
        )
        .order_by(desc(StockAggregate.timestamp))
        .limit(1)
        .first()
    )
    return float(row[0]) if row else None


def _get_rolling_baselines(
    db: Session, ticker: str, event_date: date
) -> dict[str, Any] | None:
    """
    Compute 20-day rolling session averages from minute bars prior to event_date.
    Returns None if fewer than 10 trading days of data are available.
    """
    day_start_utc = (
        datetime.combine(event_date, time.min, tzinfo=_ET)
        .astimezone(timezone.utc)
        .replace(tzinfo=None)
    )
    lookback_start_utc = (
        datetime.combine(event_date - timedelta(days=45), time.min, tzinfo=_ET)
        .astimezone(timezone.utc)
        .replace(tzinfo=None)
    )

    rows = (
        db.query(StockAggregate)
        .filter(
            StockAggregate.ticker == ticker,
            StockAggregate.timespan == "minute",
            StockAggregate.timestamp >= lookback_start_utc,
            StockAggregate.timestamp < day_start_utc,
        )
        .order_by(StockAggregate.timestamp)
        .all()
    )

    if not rows:
        return None

    # Group rows by ET calendar date
    daily: dict[date, dict[str, list]] = defaultdict(
        lambda: {"pre": [], "post": [], "regular": []}
    )
    for r in rows:
        ts_et = r.timestamp.replace(tzinfo=timezone.utc).astimezone(_ET)
        d = ts_et.date()
        if r.is_pre_market:
            daily[d]["pre"].append(r)
        elif r.is_after_market:
            daily[d]["post"].append(r)
        else:
            daily[d]["regular"].append(r)

    # Keep only days that have regular-session bars; take the 20 most recent
    trading_days = sorted(
        [d for d, sess in daily.items() if sess["regular"]]
    )[-20:]

    if len(trading_days) < 10:
        return None

    pre_vols, post_vols, regular_vols, total_vols, range_pcts = [], [], [], [], []

    for d in trading_days:
        sess = daily[d]
        pv = float(sum(r.volume for r in sess["pre"]))
        rv = float(sum(r.volume for r in sess["regular"]))
        ov = float(sum(r.volume for r in sess["post"]))
        pre_vols.append(pv)
        post_vols.append(ov)
        regular_vols.append(rv)
        total_vols.append(pv + rv + ov)

        reg = sess["regular"]
        if reg:
            h = float(max(r.high for r in reg))
            l = float(min(r.low for r in reg))
            o = float(reg[0].open)
            if o > 0:
                range_pcts.append((h - l) / o)

    n = len(trading_days)
    return {
        "avg_pre_vol_20d": sum(pre_vols) / n,
        "avg_post_vol_20d": sum(post_vols) / n,
        "avg_regular_vol_20d": sum(regular_vols) / n,
        "avg_total_daily_vol_20d": sum(total_vols) / n,
        "avg_regular_range_pct_20d": sum(range_pcts) / len(range_pcts) if range_pcts else 0.0,
        "days_available": n,
    }


def _get_enrichment(
    db: Session, ticker: str, event_date: date
) -> dict[str, Any]:
    """Fetch catalyst, split, market-cap, and float enrichment for one ticker."""
    monitored = db.query(MonitoredStock).filter(MonitoredStock.ticker == ticker).first()
    ref = db.query(TickerReference).filter(TickerReference.ticker == ticker).first()
    six_months_prior = event_date - timedelta(days=180)
    recent_split = (
        db.query(StockSplit)
        .filter(
            StockSplit.ticker == ticker,
            StockSplit.execution_date <= event_date,
            StockSplit.execution_date >= six_months_prior,
        )
        .order_by(desc(StockSplit.execution_date))
        .first()
    )
    cat = CatalystParser.analyze(ticker, event_date, db)
    outstanding = float(ref.share_class_shares_outstanding) if ref and ref.share_class_shares_outstanding else None
    return {
        "market_cap": float(monitored.market_cap) if monitored and monitored.market_cap else None,
        "outstanding_shares": outstanding,
        "recent_split_date": recent_split.execution_date.isoformat() if recent_split else None,
        "catalyst_tags": cat.get("tags", []),
        "catalyst_summary": cat.get("summary"),
    }


def _build_indicators(
    session: str,
    base_indicators: dict[str, Any],
    regular_open: float,
    regular_close: float,
    enrichment: dict[str, Any],
    event_date: date,
    session_vol: float,
) -> dict[str, Any]:
    """Merge base indicators with opening/closing prices, float rotation, and split flag."""
    indicators = {
        **base_indicators,
        "opening_price": regular_open,
        "closing_price": regular_close,
        "split_in_lookback": False,
    }

    if enrichment.get("recent_split_date"):
        split_dt = date.fromisoformat(enrichment["recent_split_date"])
        # 28 calendar days ≈ 20 trading days (4 weekday weeks), matching the baseline window
        if (event_date - split_dt).days <= 28:
            indicators["split_in_lookback"] = True

    if enrichment.get("outstanding_shares") and enrichment["outstanding_shares"] > 0:
        indicators["float_rotation_pct"] = round(
            session_vol / enrichment["outstanding_shares"] * 100, 4
        )

    return indicators


async def run_liquidity_hunt_scan(
    tickers: list[str],
    db: Session,
    start_date: date | None = None,
    end_date: date | None = None,
    config: dict | None = None,
    diagnostics_out: dict | None = None,
) -> list[dict[str, Any]]:
    """
    Run liquidity_hunt_pre and liquidity_hunt_post scans over a date range.

    For each (ticker, date):
      1. Fetch today's session metrics from minute bars.
      2. Fetch reference closes (prior day + today's regular close).
      3. Compute 20-day rolling baselines.
      4. Evaluate pre-market criteria → save event if fires.
      5. Evaluate post-market criteria → save event if fires.

    When ``diagnostics_out`` is supplied it is populated with per-bucket counts
    (no_data / no_prior_close / no_baseline / evaluated / fired_pre / fired_post /
    errors) plus the resolved start/end dates and ticker count.
    """
    _start = _time.monotonic()
    # The pre/post variants need a *completed* regular session as a baseline,
    # so the no-args default rolls back to the previous trading day. This makes
    # the "Run Scanner" button always produce something pre-open instead of
    # silently dropping every ticker as no_data.
    if start_date is None and end_date is None:
        d = get_market_today() - timedelta(days=1)
        while d.weekday() >= 5:  # Saturday=5, Sunday=6
            d -= timedelta(days=1)
        start_date = end_date = d
    elif start_date is None:
        start_date = end_date
    elif end_date is None:
        end_date = start_date

    results: list[dict[str, Any]] = []
    counts = {
        "no_session_metrics": 0,
        "no_prior_close": 0,
        "no_baseline": 0,
        "evaluated": 0,
        "fired_pre": 0,
        "fired_post": 0,
        "errors": 0,
    }

    trading_days = [
        start_date + timedelta(days=i)
        for i in range((end_date - start_date).days + 1)
        if (start_date + timedelta(days=i)).weekday() < 5
    ]
    # Note: weekday() < 5 excludes weekends; market holidays pass through and are
    # filtered naturally when _get_session_metrics returns None (no regular bars).

    for event_date in trading_days:
        for ticker in tickers:
            try:
                session_metrics = _get_session_metrics(db, ticker, event_date)
                if session_metrics is None:
                    counts["no_session_metrics"] += 1
                    continue

                prior_day_close = _get_prior_day_close(db, ticker, event_date)
                if prior_day_close is None:
                    counts["no_prior_close"] += 1
                    continue

                event_date_regular_close = _get_event_date_regular_close(db, ticker, event_date)

                baselines = _get_rolling_baselines(db, ticker, event_date)
                if baselines is None:
                    counts["no_baseline"] += 1
                    continue

                counts["evaluated"] += 1

                try:
                    enrichment = _get_enrichment(db, ticker, event_date)
                except Exception:
                    _LOG.warning(
                        "Enrichment failed for %s on %s; proceeding with empty enrichment",
                        ticker, event_date, exc_info=True,
                    )
                    enrichment = {
                        "market_cap": None, "outstanding_shares": None,
                        "recent_split_date": None, "catalyst_tags": [], "catalyst_summary": None,
                    }

                # Pre-market variant
                fires_pre, base_ind_pre, criteria_pre = _evaluate_criteria(
                    session="pre",
                    session_vol=session_metrics["pre_vol"],
                    session_high=session_metrics["pre_high"],
                    reference_close=prior_day_close,
                    regular_vol=session_metrics["regular_vol"],
                    regular_high=session_metrics["regular_high"],
                    regular_low=session_metrics["regular_low"],
                    regular_open=session_metrics["regular_open"],
                    baselines=baselines,
                    config=config,
                )
                if fires_pre:
                    indicators_pre = _build_indicators(
                        "pre", base_ind_pre,
                        session_metrics["regular_open"],
                        session_metrics["regular_close"],
                        enrichment, event_date,
                        session_metrics["pre_vol"],
                    )
                    event_dict = _save_event(
                        db=db,
                        ticker=ticker,
                        event_date=event_date,
                        scanner_type="liquidity_hunt_pre",
                        indicators=indicators_pre,
                        criteria_met=criteria_pre,
                        enrichment=enrichment,
                        previous_close=prior_day_close,
                        opening_price=session_metrics["regular_open"],
                        closing_price=session_metrics["regular_close"],
                    )
                    results.append(event_dict)
                    counts["fired_pre"] += 1
                    scanner_events_total.labels(scanner_type="liquidity_hunt_pre").inc()

                # Post-market variant (skip if no event_date regular close)
                if event_date_regular_close is not None:
                    fires_post, base_ind_post, criteria_post = _evaluate_criteria(
                        session="post",
                        session_vol=session_metrics["post_vol"],
                        session_high=session_metrics["post_high"],
                        reference_close=event_date_regular_close,
                        regular_vol=session_metrics["regular_vol"],
                        regular_high=session_metrics["regular_high"],
                        regular_low=session_metrics["regular_low"],
                        regular_open=session_metrics["regular_open"],
                        baselines=baselines,
                        config=config,
                    )
                    if fires_post:
                        indicators_post = _build_indicators(
                            "post", base_ind_post,
                            session_metrics["regular_open"],
                            session_metrics["regular_close"],
                            enrichment, event_date,
                            session_metrics["post_vol"],
                        )
                        event_dict = _save_event(
                            db=db,
                            ticker=ticker,
                            event_date=event_date,
                            scanner_type="liquidity_hunt_post",
                            indicators=indicators_post,
                            criteria_met=criteria_post,
                            enrichment=enrichment,
                            previous_close=event_date_regular_close,
                            opening_price=session_metrics["regular_open"],
                            closing_price=session_metrics["regular_close"],
                        )
                        results.append(event_dict)
                        counts["fired_post"] += 1
                        scanner_events_total.labels(scanner_type="liquidity_hunt_post").inc()

            except Exception:
                counts["errors"] += 1
                _LOG.exception("Error in liquidity_hunt scan for %s on %s", ticker, event_date)

    _LOG.info(
        "liquidity_hunt scan complete: tickers=%d days=%d "
        "dropped=(no_data:%d no_prior_close:%d no_baseline:%d) "
        "evaluated=%d fired=(pre:%d post:%d) errors=%d",
        len(tickers), len(trading_days),
        counts["no_session_metrics"], counts["no_prior_close"], counts["no_baseline"],
        counts["evaluated"], counts["fired_pre"], counts["fired_post"], counts["errors"],
    )

    if diagnostics_out is not None:
        diagnostics_out.update({
            "tickers": len(tickers),
            "days": len(trading_days),
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "no_data": counts["no_session_metrics"],
            "no_prior_close": counts["no_prior_close"],
            "no_baseline": counts["no_baseline"],
            "evaluated": counts["evaluated"],
            "fired_pre": counts["fired_pre"],
            "fired_post": counts["fired_post"],
            "errors": counts["errors"],
        })

    scan_duration_seconds.labels(scanner_type="liquidity_hunt").observe(_time.monotonic() - _start)
    return results


async def run_liquidity_hunt_scan_for_date(
    ticker: str,
    event_date: date,
    db: Session,
) -> list[dict[str, Any]]:
    """Single-ticker single-date wrapper (used by tasks scanner_map)."""
    return await run_liquidity_hunt_scan(
        [ticker], db, start_date=event_date, end_date=event_date
    )


# ── Orchestrator self-registration ────────────────────────────────────────────

from app.services.scan_orchestrator import ScannerDescriptor, register


async def _orchestrator_run(tickers: list, db: Any, event_date: date) -> list[dict]:
    """Adapter: maps the standard ScannerFn signature to run_liquidity_hunt_scan."""
    return await run_liquidity_hunt_scan(
        tickers=tickers,
        db=db,
        start_date=event_date,
        end_date=event_date,
    )


for _key, _display, _desc in [
    ("liquidity_hunt", "Liquidity Hunt", "Intraday liquidity concentration scanner."),
    ("liquidity_hunt_pre", "Liquidity Hunt (Pre-Market)", "Pre-market liquidity concentration scanner."),
    ("liquidity_hunt_post", "Liquidity Hunt (Post-Market)", "Post-market liquidity concentration scanner."),
]:
    # All three keys share the same _orchestrator_run — run_liquidity_hunt_scan emits all variant types.
    register(ScannerDescriptor(key=_key, display_name=_display, description=_desc, run=_orchestrator_run, supports_date_range=True))
