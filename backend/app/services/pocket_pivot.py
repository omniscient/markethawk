"""
Pocket Pivot Scanner

Detects up-days where session volume exceeds the highest down-day volume
in the prior 10 trading days (classic Morales/Kacher pocket pivot).

Runs nightly at 02:00 UTC Mon-Fri via Celery beat (same slot as liquidity_hunt).
Self-registers with the scan orchestrator at import time.
"""

from __future__ import annotations

import logging
import time as _time
from datetime import date, datetime, time, timedelta
from typing import Any, Optional
from zoneinfo import ZoneInfo

from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.core.metrics import (
    scan_duration_seconds,
    scan_failed_tickers_ratio,
    scan_last_success_timestamp,
    scanner_events_total,
)
from app.models.monitored_stock import MonitoredStock
from app.models.stock_aggregate import StockAggregate
from app.models.stock_split import StockSplit
from app.models.ticker_reference import TickerReference
from app.services.alert_service import save_event as _save_event
from app.services.catalyst_parser import CatalystParser
from app.utils.session import get_market_today
from app.utils.time import to_utc_naive

_ET = ZoneInfo("America/New_York")
_LOG = logging.getLogger(__name__)

DEFAULT_CONFIG: dict[str, Any] = {
    "lookback_days": 10,
    "min_lookback_days": 5,
    "price_floor": 5.00,
    "volume_floor": 100_000,
}


def _get_today_bar(db: Session, ticker: str, event_date: date) -> dict[str, Any] | None:
    """Fetch the daily bar for ticker on event_date. Returns None if not found."""
    day_start_utc = to_utc_naive(datetime.combine(event_date, time.min, tzinfo=_ET))
    day_end_utc = to_utc_naive(
        datetime.combine(event_date + timedelta(days=1), time.min, tzinfo=_ET)
    )
    row = (
        db.query(StockAggregate)
        .filter(
            StockAggregate.ticker == ticker,
            StockAggregate.timespan == "day",
            StockAggregate.timestamp >= day_start_utc,
            StockAggregate.timestamp < day_end_utc,
        )
        .first()
    )
    if row is None:
        return None
    return {"close": float(row.close), "volume": int(row.volume)}


def _get_prior_close(db: Session, ticker: str, event_date: date) -> float | None:
    """Fetch the most recent daily-bar close strictly before event_date."""
    day_start_utc = to_utc_naive(datetime.combine(event_date, time.min, tzinfo=_ET))
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
    return float(row[0]) if row else None


def _get_lookback_bars(
    db: Session, ticker: str, event_date: date, lookback_days: int
) -> list:
    """
    Fetch up to lookback_days+1 daily bars before event_date (ascending).
    The first bar provides a prior-close for classifying the oldest lookback day.
    """
    day_start_utc = to_utc_naive(datetime.combine(event_date, time.min, tzinfo=_ET))
    rows = (
        db.query(StockAggregate)
        .filter(
            StockAggregate.ticker == ticker,
            StockAggregate.timespan == "day",
            StockAggregate.timestamp < day_start_utc,
        )
        .order_by(desc(StockAggregate.timestamp))
        .limit(lookback_days + 1)
        .all()
    )
    rows.reverse()
    return rows


def _classify_down_days(bars: list, lookback_days: int) -> list[int]:
    """
    Return volumes of down days within the lookback window.

    bars is in ascending order (oldest first). The function takes the last
    lookback_days bars as the window. Each bar is compared to its immediate
    predecessor in the full bars list. Bars with no predecessor are skipped.
    """
    if len(bars) < 2:
        return []
    lookback_bars = bars[-lookback_days:]
    down_volumes: list[int] = []
    for i, bar in enumerate(lookback_bars):
        preceding_idx = len(bars) - len(lookback_bars) + i - 1
        if preceding_idx < 0:
            continue
        preceding_close = float(bars[preceding_idx].close)
        if float(bar.close) < preceding_close:
            down_volumes.append(int(bar.volume))
    return down_volumes


def _get_enrichment(db: Session, ticker: str, event_date: date) -> dict[str, Any]:
    """Fetch split, market-cap, float, and catalyst enrichment. Mirrors liquidity_hunt."""
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
    outstanding = (
        float(ref.share_class_shares_outstanding)
        if ref and ref.share_class_shares_outstanding
        else None
    )
    return {
        "market_cap": float(monitored.market_cap)
        if monitored and monitored.market_cap
        else None,
        "outstanding_shares": outstanding,
        "recent_split_date": recent_split.execution_date.isoformat()
        if recent_split
        else None,
        "catalyst_tags": cat.get("tags", []),
        "catalyst_summary": cat.get("summary"),
    }


async def run_pocket_pivot_scan(
    tickers: list[str],
    db: Session,
    start_date: date | None = None,
    end_date: date | None = None,
    config: dict | None = None,
    diagnostics_out: dict | None = None,
) -> list[dict[str, Any]]:
    """
    Run the pocket pivot scanner over a date range.

    For each (ticker, event_date):
      1. Fetch today's daily bar (close, volume).
      2. Fetch prior day's close; check up-day condition.
      3. Fetch lookback bars; classify down days.
      4. Check volume criterion (today_vol > max_down_day_vol, strict).
      5. Apply materiality floors (price, volume).
      6. Persist ScannerEvent if all criteria pass.
    """
    _perf_start = _time.monotonic()

    if start_date is None and end_date is None:
        start_date = end_date = get_market_today()
    elif start_date is None:
        start_date = end_date
    elif end_date is None:
        end_date = start_date

    cfg: dict[str, Any] = {**DEFAULT_CONFIG, **(config or {})}
    lookback_days: int = int(cfg["lookback_days"])
    min_lookback_days: int = int(cfg["min_lookback_days"])
    price_floor: float = float(cfg["price_floor"])
    volume_floor: int = int(cfg["volume_floor"])

    results: list[dict[str, Any]] = []
    counts = {
        "no_today_bar": 0,
        "no_prior_close": 0,
        "no_baseline": 0,
        "no_down_days": 0,
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
                today = _get_today_bar(db, ticker, event_date)
                if today is None:
                    counts["no_today_bar"] += 1
                    continue

                prior_close = _get_prior_close(db, ticker, event_date)
                if prior_close is None:
                    counts["no_prior_close"] += 1
                    continue

                # Up-day check
                if today["close"] < prior_close:
                    continue

                # Lookback bars: need min_lookback_days classifiable bars (+1 context)
                lookback_bars = _get_lookback_bars(
                    db, ticker, event_date, lookback_days
                )
                if len(lookback_bars) < min_lookback_days + 1:
                    counts["no_baseline"] += 1
                    continue

                down_volumes = _classify_down_days(lookback_bars, lookback_days)
                if not down_volumes:
                    counts["no_down_days"] += 1
                    continue

                # All required data confirmed — count as evaluated before criteria checks
                counts["evaluated"] += 1

                max_down_day_vol = max(down_volumes)

                # Volume criterion (strict) and materiality floors
                if today["volume"] <= max_down_day_vol:
                    continue
                if today["close"] < price_floor:
                    continue
                if today["volume"] < volume_floor:
                    continue

                try:
                    enrichment = _get_enrichment(db, ticker, event_date)
                except Exception:
                    _LOG.warning(
                        "Enrichment failed for %s on %s; proceeding with empty enrichment",
                        ticker,
                        event_date,
                        exc_info=True,
                    )
                    enrichment = {
                        "market_cap": None,
                        "outstanding_shares": None,
                        "recent_split_date": None,
                        "catalyst_tags": [],
                        "catalyst_summary": None,
                    }

                lookback_days_available = min(len(lookback_bars) - 1, lookback_days)

                split_in_lookback = False
                if enrichment.get("recent_split_date"):
                    split_dt = date.fromisoformat(enrichment["recent_split_date"])
                    if (event_date - split_dt).days <= 28:
                        split_in_lookback = True

                up_day_pct = (
                    round((today["close"] - prior_close) / prior_close, 4)
                    if prior_close > 0
                    else 0.0
                )
                volume_over_max_down_pct = round(
                    today["volume"] / max_down_day_vol - 1.0, 4
                )

                indicators: dict[str, Any] = {
                    "today_close": today["close"],
                    "prior_close": prior_close,
                    "up_day_pct": up_day_pct,
                    "today_volume": today["volume"],
                    "max_down_day_vol": max_down_day_vol,
                    "volume_over_max_down_pct": volume_over_max_down_pct,
                    "down_days_in_lookback": len(down_volumes),
                    "lookback_days_available": lookback_days_available,
                    "volume_floor": volume_floor,
                    "price_floor": price_floor,
                    "split_in_lookback": split_in_lookback,
                }

                criteria_met: dict[str, bool] = {
                    "up_day": True,
                    "volume_over_max_down": True,
                    "price_floor": True,
                    "volume_floor": True,
                }

                event_dict = _save_event(
                    db=db,
                    ticker=ticker,
                    event_date=event_date,
                    scanner_type="pocket_pivot",
                    indicators=indicators,
                    criteria_met=criteria_met,
                    enrichment=enrichment,
                    previous_close=prior_close,
                    closing_price=today["close"],
                )
                results.append(event_dict)
                counts["fired"] += 1
                scanner_events_total.labels(scanner_type="pocket_pivot").inc()

            except Exception:
                counts["errors"] += 1
                _LOG.exception(
                    "Error in pocket_pivot scan for %s on %s", ticker, event_date
                )

    _LOG.info(
        "pocket_pivot scan complete: tickers=%d days=%d "
        "dropped=(no_today_bar:%d no_prior_close:%d no_baseline:%d no_down_days:%d) "
        "evaluated=%d fired=%d errors=%d",
        len(tickers),
        len(trading_days),
        counts["no_today_bar"],
        counts["no_prior_close"],
        counts["no_baseline"],
        counts["no_down_days"],
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
                "no_today_bar": counts["no_today_bar"],
                "no_prior_close": counts["no_prior_close"],
                "no_baseline": counts["no_baseline"],
                "no_down_days": counts["no_down_days"],
                "evaluated": counts["evaluated"],
                "fired": counts["fired"],
                "errors": counts["errors"],
            }
        )

    scan_last_success_timestamp.labels(scanner_type="pocket_pivot").set(_time.time())
    scan_failed_tickers_ratio.labels(scanner_type="pocket_pivot").set(
        counts["errors"] / max(1, len(tickers) * len(trading_days))
    )
    scan_duration_seconds.labels(scanner_type="pocket_pivot").observe(
        _time.monotonic() - _perf_start
    )
    return results


async def run_pocket_pivot_scan_for_date(
    ticker: str,
    event_date: date,
    db: Session,
) -> list[dict[str, Any]]:
    """Single-ticker single-date wrapper used by run_range_scan's scanner_map."""
    return await run_pocket_pivot_scan(
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
    """Adapter: maps the standard ScannerFn signature to run_pocket_pivot_scan."""
    return await run_pocket_pivot_scan(
        tickers=tickers,
        db=db,
        start_date=event_date,
        end_date=event_date,
    )


register(
    ScannerDescriptor(
        key="pocket_pivot",
        display_name="Pocket Pivot",
        description=(
            "Detects up-days where session volume exceeds the highest "
            "down-day volume in the prior 10 trading days "
            "(classic Morales/Kacher pocket pivot)."
        ),
        run=_orchestrator_run,
        supports_date_range=True,
    )
)
