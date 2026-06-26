"""
Gate evidence generators for missing_bars and insufficient_lookback gate issues.

Wires DataQualityService bar-count analysis and ScannerConfig.data_requirements
into typed GateIssue payloads for the #492 gate policy layer.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.scanner_config import ScannerConfig
from app.models.stock_aggregate import StockAggregate
from app.models.stock_universe_ticker import StockUniverseTicker
from app.models.universe_quality_report import UniverseQualityReport

# Approximate bars per trading day for each timespan unit (multiplier=1).
# Used only in the fallback path when no cached report_data is available.
_BARS_PER_TRADING_DAY: dict[str, int] = {
    "minute": 390,
    "hour": 7,
    "day": 1,
    "week": 1,
    "month": 1,
}


@dataclass
class GateIssue:
    """Stable payload shape consumed by the #492 gate policy layer.

    Replace this stub with #492's canonical QualityIssue import when that
    ticket lands and the field names align.
    """
    issue_code: str        # "missing_bars" | "insufficient_lookback"
    ticker: Optional[str]  # None reserved for future universe-level aggregation
    timespan: str
    multiplier: int
    observed: int          # actual bars available
    required: int          # target bar count from config


def _get_tickers(db: Session, universe_id: int, ticker: Optional[str]) -> list[str]:
    if ticker is not None:
        return [ticker]
    rows = (
        db.query(StockUniverseTicker)
        .filter(StockUniverseTicker.universe_id == universe_id)
        .all()
    )
    return [r.ticker for r in rows]


def _load_report_cache(
    db: Session, universe_id: int
) -> dict[tuple[str, str, int], tuple[int, int]]:
    """Return {(ticker, timespan, multiplier): (actual_bars, expected_bars)} from cache."""
    report = (
        db.query(UniverseQualityReport)
        .filter(UniverseQualityReport.universe_id == universe_id)
        .first()
    )
    if not report or not report.report_data:
        return {}
    cache: dict[tuple[str, str, int], tuple[int, int]] = {}
    for entry in report.report_data.get("tickers", []):
        t = entry.get("ticker")
        ts = entry.get("timespan")
        mult = entry.get("multiplier")
        if t and ts and mult is not None:
            cache[(t, ts, int(mult))] = (
                int(entry.get("actual_bars", 0)),
                int(entry.get("expected_bars", 0)),
            )
    return cache


def _count_bars(db: Session, ticker: str, timespan: str, multiplier: int) -> int:
    return (
        db.query(func.count(StockAggregate.id))
        .filter(
            StockAggregate.ticker == ticker,
            StockAggregate.timespan == timespan,
            StockAggregate.multiplier == multiplier,
        )
        .scalar()
        or 0
    )


def generate_missing_bars_issues(
    db: Session,
    universe_id: int,
    scanner_config: ScannerConfig,
    ticker: Optional[str] = None,
) -> list[GateIssue]:
    """Emit GateIssue(issue_code='missing_bars') for each ticker x timespan where
    actual bar count is below the expected count derived from lookback_days.

    Prefers UniverseQualityReport.report_data cache; falls back to a direct
    SELECT count(*) FROM stock_aggregates when no report exists or is absent.
    Returns [] when data_requirements has no timespans[] key.
    """
    timespans = (scanner_config.data_requirements or {}).get("timespans", [])
    if not timespans:
        return []

    tickers_to_check = _get_tickers(db, universe_id, ticker)
    cache = _load_report_cache(db, universe_id)

    issues: list[GateIssue] = []
    for t in tickers_to_check:
        for ts_cfg in timespans:
            ts = ts_cfg.get("timespan", "minute")
            mult = int(ts_cfg.get("multiplier", 1))
            lookback_days = ts_cfg.get("lookback_days")
            if not lookback_days:
                continue

            cache_key = (t, ts, mult)
            if cache_key in cache:
                actual_bars, expected_bars = cache[cache_key]
            else:
                actual_bars = _count_bars(db, t, ts, mult)
                # Simplified estimate for fallback: lookback_days x bars per trading day.
                # The cache path uses the P90-based expected_bars from DataQualityService.
                bars_per_day = max(1, _BARS_PER_TRADING_DAY.get(ts, 60) // mult)
                expected_bars = lookback_days * bars_per_day

            if actual_bars < expected_bars:
                issues.append(
                    GateIssue(
                        issue_code="missing_bars",
                        ticker=t,
                        timespan=ts,
                        multiplier=mult,
                        observed=actual_bars,
                        required=expected_bars,
                    )
                )

    return issues


def generate_insufficient_lookback_issues(
    db: Session,
    universe_id: int,
    scanner_config: ScannerConfig,
    ticker: Optional[str] = None,
) -> list[GateIssue]:
    """Emit GateIssue(issue_code='insufficient_lookback') for each ticker x timespan
    where actual bar count is below min_bars from data_requirements.

    Only emits issues for timespans that carry a min_bars field.
    Always queries stock_aggregates directly — report_data does not store
    the timespan-filtered count against min_bars.
    Returns [] when data_requirements has no timespans[] key, or when no
    timespans have min_bars configured.
    """
    timespans = (scanner_config.data_requirements or {}).get("timespans", [])
    if not timespans:
        return []

    tickers_to_check = _get_tickers(db, universe_id, ticker)

    issues: list[GateIssue] = []
    for t in tickers_to_check:
        for ts_cfg in timespans:
            min_bars = ts_cfg.get("min_bars")
            if min_bars is None:
                continue
            ts = ts_cfg.get("timespan", "minute")
            mult = int(ts_cfg.get("multiplier", 1))

            actual_bars = _count_bars(db, t, ts, mult)

            if actual_bars < int(min_bars):
                issues.append(
                    GateIssue(
                        issue_code="insufficient_lookback",
                        ticker=t,
                        timespan=ts,
                        multiplier=mult,
                        observed=actual_bars,
                        required=int(min_bars),
                    )
                )

    return issues
