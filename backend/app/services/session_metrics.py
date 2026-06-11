"""Session and day metrics computation — extracted from ScannerService."""

from datetime import date, datetime
from typing import Any, Dict, List
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.models.stock_aggregate import StockAggregate
from app.utils.time import to_utc_naive

_ET = ZoneInfo("America/New_York")


def calculate_day_metrics_from_aggs(aggs: List[StockAggregate]) -> Dict[str, Any]:
    """Calculate detailed price metrics from a list of minute aggregates."""
    metrics = {
        "pre_market_high": 0.0,
        "pre_market_low": 0.0,
        "pre_market_open": 0.0,
        "pre_market_close": 0.0,
        "regular_high": 0.0,
        "regular_low": 0.0,
        "opening_price": 0.0,
        "closing_price": 0.0,
        "post_market_high": 0.0,
        "post_market_low": 0.0,
        "post_market_open": 0.0,
        "post_market_close": 0.0,
        "total_day_high": 0.0,
        "total_day_low": 0.0,
        "total_volume": 0,
    }

    if not aggs:
        return metrics

    pre_aggs = [a for a in aggs if a.is_pre_market]
    reg_aggs = [a for a in aggs if not a.is_pre_market and not a.is_after_market]
    post_aggs = [a for a in aggs if a.is_after_market]

    # Total Day
    metrics["total_day_high"] = float(max(a.high for a in aggs))
    metrics["total_day_low"] = float(min(a.low for a in aggs))
    metrics["total_volume"] = sum(a.volume for a in aggs)

    # Pre Market
    if pre_aggs:
        metrics["pre_market_high"] = float(max(a.high for a in pre_aggs))
        metrics["pre_market_low"] = float(min(a.low for a in pre_aggs))
        metrics["pre_market_open"] = float(pre_aggs[0].open)
        metrics["pre_market_close"] = float(pre_aggs[-1].close)

    # Regular Market
    if reg_aggs:
        metrics["regular_high"] = float(max(a.high for a in reg_aggs))
        metrics["regular_low"] = float(min(a.low for a in reg_aggs))
        metrics["opening_price"] = float(reg_aggs[0].open)
        metrics["closing_price"] = float(reg_aggs[-1].close)

    # Post Market
    if post_aggs:
        metrics["post_market_high"] = float(max(a.high for a in post_aggs))
        metrics["post_market_low"] = float(min(a.low for a in post_aggs))
        metrics["post_market_open"] = float(post_aggs[0].open)
        metrics["post_market_close"] = float(post_aggs[-1].close)

    return metrics


def calculate_day_metrics(ticker: str, event_date: date, db: Session) -> Dict[str, Any]:
    """Calculate detailed price metrics for different sessions of a given day."""
    metrics = {
        "pre_market_high": 0.0,
        "pre_market_low": 0.0,
        "pre_market_open": 0.0,
        "pre_market_close": 0.0,
        "regular_high": 0.0,
        "regular_low": 0.0,
        "opening_price": 0.0,
        "closing_price": 0.0,
        "post_market_high": 0.0,
        "post_market_low": 0.0,
        "post_market_open": 0.0,
        "post_market_close": 0.0,
        "total_day_high": 0.0,
        "total_day_low": 0.0,
        "total_volume": 0,
    }

    # Get all minute aggregates for the day
    _ET = ZoneInfo("America/New_York")
    day_start_et = datetime.combine(event_date, datetime.min.time(), tzinfo=_ET)
    day_end_et = datetime.combine(event_date, datetime.max.time(), tzinfo=_ET)

    # Convert to UTC and strip tzinfo for DB comparison (since DB stores naive UTC)
    day_start_utc = to_utc_naive(day_start_et)
    day_end_utc = to_utc_naive(day_end_et)

    aggs = (
        db.query(StockAggregate)
        .filter(
            StockAggregate.ticker == ticker,
            StockAggregate.timestamp >= day_start_utc,
            StockAggregate.timestamp <= day_end_utc,
            StockAggregate.timespan == "minute",
        )
        .order_by(StockAggregate.timestamp.asc())
        .all()
    )

    if not aggs:
        return metrics

    pre_aggs = [a for a in aggs if a.is_pre_market]
    reg_aggs = [a for a in aggs if not a.is_pre_market and not a.is_after_market]
    post_aggs = [a for a in aggs if a.is_after_market]

    # Total Day
    metrics["total_day_high"] = float(max(a.high for a in aggs))
    metrics["total_day_low"] = float(min(a.low for a in aggs))
    metrics["total_volume"] = sum(a.volume for a in aggs)

    # Pre Market
    if pre_aggs:
        metrics["pre_market_high"] = float(max(a.high for a in pre_aggs))
        metrics["pre_market_low"] = float(min(a.low for a in pre_aggs))
        metrics["pre_market_open"] = float(pre_aggs[0].open)
        metrics["pre_market_close"] = float(pre_aggs[-1].close)

    # Regular Market
    if reg_aggs:
        metrics["regular_high"] = float(max(a.high for a in reg_aggs))
        metrics["regular_low"] = float(min(a.low for a in reg_aggs))
        metrics["opening_price"] = float(reg_aggs[0].open)
        metrics["closing_price"] = float(reg_aggs[-1].close)

    # Post Market
    if post_aggs:
        metrics["post_market_high"] = float(max(a.high for a in post_aggs))
        metrics["post_market_low"] = float(min(a.low for a in post_aggs))
        metrics["post_market_open"] = float(post_aggs[0].open)
        metrics["post_market_close"] = float(post_aggs[-1].close)

    return metrics
