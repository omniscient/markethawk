"""
Gate evidence generators for missing_bars and insufficient_lookback gate issues.

Wires DataQualityService bar-count analysis and ScannerConfig.data_requirements
into typed GateIssue payloads for the #492 gate policy layer.
"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional
from zoneinfo import ZoneInfo

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.scanner_config import ScannerConfig
from app.models.stock_aggregate import StockAggregate
from app.models.stock_split import StockSplit
from app.models.stock_universe_ticker import StockUniverseTicker
from app.models.universe_quality_report import UniverseQualityReport
from app.services.split_adjustment import SplitAdjustmentService
from app.utils.session import session_for_ts

_ET = ZoneInfo("America/New_York")

# Split/dividend anomaly detection defaults (overridable via scanner_config.parameters).
# Overnight return magnitude (pct) that triggers a discontinuity check.
_DEFAULT_DISCONTINUITY_FLOOR_PCT = 25.0
# Tolerance (pct) between the observed jump and the recorded split factor.
_DEFAULT_FACTOR_TOLERANCE_PCT = 5.0
# Timezone/session mismatch default (overridable via scanner_config.parameters).
_DEFAULT_SESSION_MISMATCH_THRESHOLD_PCT = 1.0

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

    The bar-count checks (missing_bars / insufficient_lookback) populate the
    numeric observed/required fields. The richer checks (split_dividend_anomaly /
    session_mismatch) carry their structured evidence — including the issue
    ``severity`` ("blocker" | "warning") and a free-form ``reason`` — in the
    optional ``context`` dict, leaving the numeric fields at their defaults.
    """

    # one of: missing_bars | insufficient_lookback | split_dividend_anomaly | session_mismatch
    issue_code: str
    ticker: Optional[str]  # None reserved for future universe-level aggregation
    timespan: str = "minute"
    multiplier: int = 1
    observed: int = 0  # actual bars available (bar-count checks)
    required: int = 0  # target bar count from config (bar-count checks)
    context: Optional[dict] = None  # structured evidence for the richer checks


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
    if not report or report.status != "complete" or not report.report_data:
        return {}
    cache: dict[tuple[str, str, int], tuple[int, int]] = {}
    for entry in report.report_data.get("tickers", []):
        t = entry.get("ticker")
        ts = entry.get("timespan")
        mult = entry.get("multiplier")
        if t and ts and mult is not None:
            exp = int(entry.get("expected_bars", 0))
            if exp > 0:
                cache[(t, ts, int(mult))] = (
                    int(entry.get("actual_bars", 0)),
                    exp,
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


# ---------------------------------------------------------------------------
# Split/dividend anomaly + timezone/session mismatch evidence (#500)
#
# Both emitters scope to equities (StockAggregate) and timespan == "minute"
# only. Daily bars and FuturesAggregate are excluded. They run at the batch
# quality cadence (POST /api/v1/universe/{id}/quality), not the latency-
# sensitive scan path, so they query stock_aggregates directly.
# ---------------------------------------------------------------------------


def _scanner_parameters(scanner_config: Optional[ScannerConfig]) -> dict:
    """Return scanner_config.parameters (a JSON dict), or {} when absent/None."""
    if scanner_config is None:
        return {}
    return getattr(scanner_config, "parameters", None) or {}


def _et_date(ts: datetime):
    """Eastern-time calendar date for a (naive-UTC or aware) bar timestamp."""
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(_ET).date()


def _load_minute_bars(db: Session, ticker: str) -> list[StockAggregate]:
    """All equity minute bars for a ticker, ordered oldest -> newest."""
    return (
        db.query(StockAggregate)
        .filter(
            StockAggregate.ticker == ticker,
            StockAggregate.timespan == "minute",
        )
        .order_by(StockAggregate.timestamp.asc())
        .all()
    )


def _load_splits(db: Session, ticker: str) -> list[StockSplit]:
    """All recorded splits for a ticker, ordered by execution_date."""
    return (
        db.query(StockSplit)
        .filter(StockSplit.ticker == ticker)
        .order_by(StockSplit.execution_date.asc())
        .all()
    )


def _is_regular(bar: StockAggregate) -> bool:
    return not bar.is_pre_market and not bar.is_after_market


def _discontinuity_issues(
    ticker: str,
    bars: list[StockAggregate],
    splits_by_date: dict,
    floor: float,
    tolerance: float,
) -> list[GateIssue]:
    """Sub-check 2: flag overnight regular-session boundary returns >= floor that
    lack a matching, correctly-factored split.
    """
    # Index the first/last regular-session bar per ET trading date.
    by_date: "OrderedDict" = OrderedDict()
    for bar in bars:
        if not _is_regular(bar):
            continue
        d = _et_date(bar.timestamp)
        slot = by_date.get(d)
        if slot is None:
            by_date[d] = {"first": bar, "last": bar}
        else:
            slot["last"] = bar

    dates = sorted(by_date.keys())
    issues: list[GateIssue] = []
    for prev_date, boundary_date in zip(dates, dates[1:]):
        last_bar = by_date[prev_date]["last"]
        first_bar = by_date[boundary_date]["first"]
        last_close = float(last_bar.close)
        first_open = float(first_bar.open)
        if last_close == 0:
            continue

        observed_ratio = first_open / last_close
        overnight_return = abs(observed_ratio - 1.0)
        if overnight_return < floor:
            continue

        last_volume = float(last_bar.volume or 0)
        first_volume = float(first_bar.volume or 0)
        volume_ratio = (first_volume / last_volume) if last_volume else None

        evidence = {
            "severity": "blocker",
            "execution_date": str(boundary_date),
            "prev_session_date": str(prev_date),
            "last_close": round(last_close, 6),
            "first_open": round(first_open, 6),
            "observed_ratio": round(observed_ratio, 6),
            "discontinuity_pct": round(overnight_return * 100, 2),
            "volume_ratio": round(volume_ratio, 4)
            if volume_ratio is not None
            else None,
        }

        split = splits_by_date.get(boundary_date)
        if split is None:
            evidence["reason"] = "unexplained_discontinuity"
            issues.append(
                GateIssue(
                    issue_code="split_dividend_anomaly", ticker=ticker, context=evidence
                )
            )
            continue

        expected_ratio = float(SplitAdjustmentService.compute_price_factor(split))
        evidence["expected_ratio"] = round(expected_ratio, 6)
        evidence["split_from"] = float(split.split_from)
        evidence["split_to"] = float(split.split_to)
        if expected_ratio == 0:
            continue
        factor_error = abs(observed_ratio - expected_ratio) / abs(expected_ratio)
        evidence["factor_error_pct"] = round(factor_error * 100, 2)
        if factor_error > tolerance:
            evidence["reason"] = "split_factor_mismatch"
            issues.append(
                GateIssue(
                    issue_code="split_dividend_anomaly", ticker=ticker, context=evidence
                )
            )
        # else: discontinuity is consistent with the recorded split — no issue.

    return issues


def generate_split_dividend_anomaly_issues(
    db: Session,
    universe_id: int,
    scanner_config: Optional[ScannerConfig],
    ticker: Optional[str] = None,
) -> list[GateIssue]:
    """Emit GateIssue(issue_code='split_dividend_anomaly') for split/dividend
    adjustment anomalies in stored equity minute bars.

    Two sub-checks per ticker (both blocker severity):
      1. Unapplied split — a StockSplit row with adjustments_applied_at IS NULL
         whose execution_date is straddled by stored minute bars.
      2. Price discontinuity — an overnight regular-session boundary return whose
         magnitude is >= split_discontinuity_floor_pct, that either has no
         matching split on the boundary date, or a recorded split whose factor
         disagrees with the observed jump by more than split_factor_tolerance_pct.

    Thresholds come from scanner_config.parameters (JSON) with defaults; a None
    scanner_config falls back to those defaults. Scope is equities + minute bars.
    """
    params = _scanner_parameters(scanner_config)
    floor = (
        float(
            params.get(
                "split_discontinuity_floor_pct", _DEFAULT_DISCONTINUITY_FLOOR_PCT
            )
        )
        / 100.0
    )
    tolerance = (
        float(params.get("split_factor_tolerance_pct", _DEFAULT_FACTOR_TOLERANCE_PCT))
        / 100.0
    )

    issues: list[GateIssue] = []
    for t in _get_tickers(db, universe_id, ticker):
        bars = _load_minute_bars(db, t)
        if not bars:
            continue
        splits = _load_splits(db, t)

        # Sub-check 1: unapplied split straddled by stored bars.
        # Straddle is decided on Eastern-time calendar dates (via _et_date), not
        # naive UTC midnight: a bar is pre-split iff its ET date < execution_date
        # and post-split iff its ET date >= execution_date. The old naive-UTC
        # boundary falsely counted a winter (EST, UTC-5) 20:00 ET post-market bar
        # the evening BEFORE the split — whose UTC timestamp rolls into
        # execution_date — as post-split, firing a false-positive blocker.
        first_et_date = _et_date(bars[0].timestamp)
        last_et_date = _et_date(bars[-1].timestamp)
        for split in splits:
            if split.adjustments_applied_at is not None:
                continue
            has_pre = first_et_date < split.execution_date
            has_post = last_et_date >= split.execution_date
            if has_pre and has_post:
                issues.append(
                    GateIssue(
                        issue_code="split_dividend_anomaly",
                        ticker=t,
                        context={
                            "severity": "blocker",
                            "reason": "unapplied_split",
                            "execution_date": str(split.execution_date),
                            "split_from": float(split.split_from),
                            "split_to": float(split.split_to),
                        },
                    )
                )

        # Sub-check 2: unexplained / mis-factored overnight discontinuity.
        splits_by_date = {s.execution_date: s for s in splits}
        issues.extend(_discontinuity_issues(t, bars, splits_by_date, floor, tolerance))

    return issues


def generate_timezone_session_mismatch_issues(
    db: Session,
    universe_id: int,
    scanner_config: Optional[ScannerConfig],
    ticker: Optional[str] = None,
) -> list[GateIssue]:
    """Emit GateIssue(issue_code='session_mismatch') when stored session flags
    disagree with the DST-correct recomputed session classification.

    For each equity minute bar the expected session is recomputed via
    session_for_ts() ("pre" | "regular" | "post" | "closed") and compared against
    the stored is_pre_market / is_after_market flags ("post" maps to
    is_after_market):
      - Any bar landing in a 'closed' window -> blocker (an ingest-time timezone
        offset error: real ticks should never fall outside 04:00-20:00 ET).
      - Flag mismatches above session_mismatch_threshold_pct -> warning.

    Threshold comes from scanner_config.parameters (JSON) with a default; a None
    scanner_config falls back to the default. Scope is equities + minute bars.
    """
    params = _scanner_parameters(scanner_config)
    threshold = (
        float(
            params.get(
                "session_mismatch_threshold_pct",
                _DEFAULT_SESSION_MISMATCH_THRESHOLD_PCT,
            )
        )
        / 100.0
    )

    issues: list[GateIssue] = []
    for t in _get_tickers(db, universe_id, ticker):
        bars = _load_minute_bars(db, t)
        total = len(bars)
        if total == 0:
            continue

        mismatch_count = 0
        closed_count = 0
        sample_mismatches: list[dict] = []

        for bar in bars:
            expected_session = session_for_ts(bar.timestamp)
            if expected_session == "closed":
                closed_count += 1
                continue
            expected_pre = expected_session == "pre"
            expected_post = expected_session == "post"
            if expected_pre != bool(bar.is_pre_market) or expected_post != bool(
                bar.is_after_market
            ):
                mismatch_count += 1
                if len(sample_mismatches) < 10:
                    sample_mismatches.append(
                        {
                            "timestamp_utc": bar.timestamp.isoformat(),
                            "stored_pre": bool(bar.is_pre_market),
                            "stored_post": bool(bar.is_after_market),
                            "expected_session": expected_session,
                        }
                    )

        if closed_count > 0:
            issues.append(
                GateIssue(
                    issue_code="session_mismatch",
                    ticker=t,
                    context={
                        "severity": "blocker",
                        "reason": "bars_in_closed_window",
                        "closed_bar_count": closed_count,
                        "total_bars": total,
                    },
                )
            )

        # Deliberate refinement over the spec draft: closed-window bars are
        # surfaced by the independent blocker above, so the warning rate is
        # measured over open-window bars only (denominator excludes closed bars).
        denom = total - closed_count
        if denom > 0:
            mismatch_rate = mismatch_count / denom
            if mismatch_rate > threshold:
                issues.append(
                    GateIssue(
                        issue_code="session_mismatch",
                        ticker=t,
                        context={
                            "severity": "warning",
                            "reason": "flag_mismatch",
                            "mismatch_count": mismatch_count,
                            "total_bars": total,
                            "open_window_bars": denom,
                            "mismatch_rate_pct": round(mismatch_rate * 100, 2),
                            "threshold_pct": round(threshold * 100, 2),
                            "sample_mismatches": sample_mismatches,
                        },
                    )
                )

    return issues
