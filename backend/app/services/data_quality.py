"""
Data Quality Service.

Analyses the completeness, integrity, and continuity of aggregate (OHLCV) bars
stored for a universe.  Results are persisted in UniverseQualityReport.

Scoring dimensions
──────────────────
  Coverage    60% — what fraction of expected bars are present
  Integrity   30% — what fraction of bars pass OHLCV sanity checks
  Continuity  10% — absence of intra-session data gaps

Grade scale
───────────
  A  95–100   production-ready
  B  85–94    minor gaps, usable
  C  70–84    significant gaps, use with caution
  D  50–69    major holes, scanner results unreliable
  F  <50      severely incomplete
"""

import logging
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.services.quality_helpers import (  # noqa: F401
    _count_weekdays_between,
    _detect_gaps,
)

logger = logging.getLogger(__name__)

# Maximum number of gap entries kept in the stored report per ticker (saves space)
MAX_GAPS_STORED = 50


# ── helpers ──────────────────────────────────────────────────────────────────


def _score_to_grade(score: float) -> str:
    if score >= 95:
        return "A"
    if score >= 85:
        return "B"
    if score >= 70:
        return "C"
    if score >= 50:
        return "D"
    return "F"


def _grade_color(grade: str) -> str:
    return {"A": "green", "B": "green", "C": "yellow", "D": "orange", "F": "red"}.get(
        grade, "gray"
    )


def _estimate_expected_bars(
    timestamps: List[datetime],
    timespan: str,
    multiplier: int,
    holiday_map: Optional[Dict] = None,
    is_futures: bool = False,
):
    """
    Empirical P90 approach: group by date, take the 90th-percentile bar count
    per active day, multiply by number of active days.  Self-calibrates to
    whatever session type was originally requested (pre-market, full day, etc.).

    Asset-class correction
    ──────────────────────
    The P90 yardstick only makes sense when sessions produce a uniform bar
    count — true for futures (continuous CME sessions), false for stocks:
    an illiquid ticker emits intraday bars only for periods with trades, so
    day-to-day bar-count variation is organic trading activity, not missing
    data (verified bar-for-bar against the provider).  For stocks every day
    with data therefore counts as complete (expected = actual); shortfalls
    surface via gap detection, integrity checks, and the staleness sweep.

    Stub-day correction (futures)
    ─────────────────────────────
    Some calendar dates naturally hold far fewer bars than a full session:
      • Sunday opens: the CME session starts at 18:00 ET Sunday but the UTC
        date only captures 1–2 hours of bars before rolling to Monday.
        (EST: 23:00–23:59 UTC = 60 bars; EDT: 22:00–23:59 UTC = 120 bars)

    Fix: for any date whose bar count is < 50 % of P90 ("stub day"), set
    expected = actual.  Full days still use P90 as the yardstick.

    Holiday-calendar correction
    ───────────────────────────
    holiday_map maps date → event_type ('full_close' | 'early_close' | 'late_open').
      full_close  — market was closed; any bars present are anomalous.
                    The date is excluded from the expected calculation entirely
                    so it does not create a phantom coverage shortfall.
      early_close / late_open — abbreviated session; whatever bars are present
                    are correct.  Treated like a stub (actual = expected).

    Returns (expected_bars, coverage_detail) where coverage_detail explains
    how the expected count was computed (useful for UI explanation).
    """
    empty_detail: Dict[str, Any] = {
        "p90_bars_per_day": 0,
        "full_day_count": 0,
        "stub_day_count": 0,
        "partial_day_count": 0,
        "holiday_day_count": 0,
        "partial_days": [],
    }
    if not timestamps:
        return 0, empty_detail

    by_date: Dict[Any, int] = defaultdict(int)
    for ts in timestamps:
        by_date[ts.date()] += 1

    counts = sorted(by_date.values())
    p90_idx = min(int(len(counts) * 0.90), len(counts) - 1)
    p90 = counts[p90_idx]

    stub_threshold = p90 * 0.5

    full_days = 0
    stub_days = 0
    holiday_days = 0
    partial_days: List[Dict] = []
    expected = 0

    for d, cnt in by_date.items():
        holiday_type = holiday_map.get(d) if holiday_map else None

        if holiday_type == "full_close":
            # Market was fully closed — skip entirely; any bars are anomalous
            holiday_days += 1

        elif holiday_type in ("early_close", "late_open"):
            # Abbreviated session — whatever bars exist are correct, no penalty
            expected += cnt
            holiday_days += 1

        elif not is_futures:
            # Stocks: intraday bars only exist for periods with trades, so a
            # below-P90 day is organic activity, not missing data — no penalty
            expected += cnt
            full_days += 1

        elif cnt < stub_threshold:
            # Organic stub (Sunday open boundary, single-day holiday without a
            # calendar entry, etc.) — actual = expected, no penalty
            expected += cnt
            stub_days += 1

        elif cnt < p90:
            # Partial day — below the P90 baseline without a known explanation;
            # this is a genuine coverage shortfall
            expected += p90
            partial_days.append(
                {
                    "date": str(d),
                    "actual_bars": cnt,
                    "expected_bars": p90,
                    "shortfall": p90 - cnt,
                }
            )

        else:
            expected += p90
            full_days += 1

    # Sort partial days worst-first and cap stored list to save space
    partial_days.sort(key=lambda x: x["shortfall"], reverse=True)

    detail: Dict[str, Any] = {
        "p90_bars_per_day": p90,
        "full_day_count": full_days,
        "stub_day_count": stub_days,
        "partial_day_count": len(partial_days),
        "holiday_day_count": holiday_days,
        "partial_days": partial_days[:30],
    }

    return expected, detail


# ── per-ticker analysis ───────────────────────────────────────────────────────


def _analyze_ticker_timespan(
    db: Session,
    ticker: str,
    timespan: str,
    multiplier: int,
    is_futures: bool,
    exchange: str = "NYSE",
) -> Dict:
    from app.models.futures_aggregate import FuturesAggregate
    from app.models.stock_aggregate import StockAggregate

    if is_futures:
        rows = (
            db.query(
                FuturesAggregate.timestamp,
                FuturesAggregate.open,
                FuturesAggregate.high,
                FuturesAggregate.low,
                FuturesAggregate.close,
                FuturesAggregate.volume,
            )
            .filter(
                FuturesAggregate.symbol == ticker,
                FuturesAggregate.timespan == timespan,
                FuturesAggregate.multiplier == multiplier,
            )
            .order_by(FuturesAggregate.timestamp.asc())
            .all()
        )
    else:
        rows = (
            db.query(
                StockAggregate.timestamp,
                StockAggregate.open,
                StockAggregate.high,
                StockAggregate.low,
                StockAggregate.close,
                StockAggregate.volume,
            )
            .filter(
                StockAggregate.ticker == ticker,
                StockAggregate.timespan == timespan,
                StockAggregate.multiplier == multiplier,
            )
            .order_by(StockAggregate.timestamp.asc())
            .all()
        )

    empty_result = {
        "ticker": ticker,
        "asset_class": "futures" if is_futures else "stocks",
        "timespan": timespan,
        "multiplier": multiplier,
        "grade": "F",
        "score": 0.0,
        "actual_bars": 0,
        "expected_bars": 0,
        "coverage_pct": 0.0,
        "integrity_pct": 100.0,
        "continuity_score": 100.0,
        "gap_count": 0,
        "bad_bar_count": 0,
        "duplicate_count": 0,
        "first_bar": None,
        "last_bar": None,
        "gaps": [],
        "coverage_detail": None,
    }

    if not rows:
        return empty_result

    timestamps = [r.timestamp for r in rows]
    actual_bars = len(rows)

    # ── Holiday calendar ──────────────────────────────────────────────────────
    from app.models.market_holiday import MarketHoliday

    try:
        min_date = timestamps[0].date()
        max_date = timestamps[-1].date()
        holiday_rows = (
            db.query(MarketHoliday)
            .filter(
                MarketHoliday.exchange == exchange,
                MarketHoliday.date >= min_date,
                MarketHoliday.date <= max_date,
            )
            .all()
        )
        holiday_map = {h.date: h.event_type for h in holiday_rows}
    except Exception:
        holiday_map = {}

    # ── Coverage ──────────────────────────────────────────────────────────────
    expected_bars, coverage_detail = _estimate_expected_bars(
        timestamps, timespan, multiplier, holiday_map, is_futures=is_futures
    )
    coverage_pct = min(
        100.0, (actual_bars / expected_bars * 100) if expected_bars > 0 else 100.0
    )

    # ── Integrity ─────────────────────────────────────────────────────────────
    bad_bars = 0
    for r in rows:
        h = float(r.high)
        lo = float(r.low)
        o = float(r.open)
        c = float(r.close)
        if (
            h < lo
            or h < o
            or h < c
            or lo > o
            or lo > c
            or o <= 0
            or c <= 0
            or h <= 0
            or lo <= 0
        ):
            bad_bars += 1
    integrity_pct = (
        ((actual_bars - bad_bars) / actual_bars * 100) if actual_bars > 0 else 100.0
    )

    # ── Continuity ────────────────────────────────────────────────────────────
    gaps = _detect_gaps(timestamps, timespan, multiplier)
    gap_count = len(gaps)
    # 5-point penalty per gap, floor at 0
    continuity_score = max(0.0, 100.0 - gap_count * 5)

    # ── Duplicates ────────────────────────────────────────────────────────────
    duplicate_count = actual_bars - len(set(timestamps))

    # ── Overall ───────────────────────────────────────────────────────────────
    score = coverage_pct * 0.60 + integrity_pct * 0.30 + continuity_score * 0.10
    grade = _score_to_grade(score)

    return {
        "ticker": ticker,
        "asset_class": "futures" if is_futures else "stocks",
        "timespan": timespan,
        "multiplier": multiplier,
        "grade": grade,
        "score": round(score, 1),
        "actual_bars": actual_bars,
        "expected_bars": expected_bars,
        "coverage_pct": round(coverage_pct, 1),
        "integrity_pct": round(integrity_pct, 1),
        "continuity_score": round(continuity_score, 1),
        "gap_count": gap_count,
        "bad_bar_count": bad_bars,
        "duplicate_count": duplicate_count,
        "first_bar": timestamps[0].isoformat() if timestamps else None,
        "last_bar": timestamps[-1].isoformat() if timestamps else None,
        "gaps": [
            {
                "from": g["from"].isoformat(),
                "to": g["to"].isoformat(),
                "duration_hours": g["duration_hours"],
                "missing_bars": g["missing_bars"],
            }
            for g in gaps[:MAX_GAPS_STORED]
        ],
        "coverage_detail": coverage_detail,
    }


# ── main entry point ──────────────────────────────────────────────────────────


class DataQualityService:
    @staticmethod
    def summarize_event_bars(rows: List[Any], timespan: str, multiplier: int) -> Dict:
        """Return event-scoped integrity/continuity counts for aggregate rows."""
        bad_bar_count = 0
        timestamps = []
        for row in rows:
            timestamps.append(row.timestamp)
            high = Decimal(row.high)
            low = Decimal(row.low)
            open_ = Decimal(row.open)
            close = Decimal(row.close)
            volume = int(row.volume)
            if (
                high < low
                or high < open_
                or high < close
                or low > open_
                or low > close
                or open_ <= 0
                or close <= 0
                or high <= 0
                or low <= 0
                or volume < 0
            ):
                bad_bar_count += 1

        duplicate_count = len(timestamps) - len(set(timestamps))
        gaps = _detect_gaps(timestamps, timespan, multiplier)
        return {
            "bad_bar_count": bad_bar_count,
            "duplicate_count": duplicate_count,
            "gap_count": len(gaps),
        }

    @staticmethod
    def analyze_universe(db: Session, universe_id: int) -> Dict:
        """
        Run a full quality analysis for every ticker × timespan combination
        in the universe.  Returns the complete report dict (also persisted by
        the caller / Celery task).
        """
        from app.models.futures_aggregate import FuturesAggregate
        from app.models.stock_aggregate import StockAggregate
        from app.models.stock_universe_ticker import StockUniverseTicker

        tickers = (
            db.query(StockUniverseTicker)
            .filter(StockUniverseTicker.universe_id == universe_id)
            .all()
        )

        futures_set = {t.ticker for t in tickers if t.asset_class == "futures"}

        ticker_results: List[Dict] = []

        for ticker_obj in tickers:
            ticker = ticker_obj.ticker
            is_futures = ticker in futures_set

            # Resolve exchange for holiday-calendar lookup
            if is_futures:
                exch_row = (
                    db.query(FuturesAggregate.exchange)
                    .filter(FuturesAggregate.symbol == ticker)
                    .first()
                )
                exchange = exch_row.exchange.upper() if exch_row else "CME"
            else:
                exchange = "NYSE"

            # Discover which (timespan, multiplier) combos exist for this ticker
            if is_futures:
                combos = (
                    db.query(FuturesAggregate.timespan, FuturesAggregate.multiplier)
                    .filter(FuturesAggregate.symbol == ticker)
                    .distinct()
                    .all()
                )
            else:
                combos = (
                    db.query(StockAggregate.timespan, StockAggregate.multiplier)
                    .filter(StockAggregate.ticker == ticker)
                    .distinct()
                    .all()
                )

            if not combos:
                # Ticker has no data at all — F grade
                ticker_results.append(
                    {
                        "ticker": ticker,
                        "asset_class": "futures" if is_futures else "stocks",
                        "timespan": None,
                        "multiplier": None,
                        "grade": "F",
                        "score": 0.0,
                        "actual_bars": 0,
                        "expected_bars": 0,
                        "coverage_pct": 0.0,
                        "integrity_pct": 100.0,
                        "continuity_score": 100.0,
                        "gap_count": 0,
                        "bad_bar_count": 0,
                        "duplicate_count": 0,
                        "first_bar": None,
                        "last_bar": None,
                        "gaps": [],
                        "coverage_detail": None,
                    }
                )
                continue

            for combo in combos:
                try:
                    result = _analyze_ticker_timespan(
                        db,
                        ticker,
                        combo.timespan,
                        combo.multiplier,
                        is_futures,
                        exchange=exchange,
                    )
                    ticker_results.append(result)
                except Exception as e:
                    logger.error(
                        f"DataQualityService: error analysing {ticker} "
                        f"{combo.timespan}×{combo.multiplier}: {e}"
                    )

        # ── Universe-level aggregation ────────────────────────────────────────
        # Weight by actual bar count so large tickers drive the score more
        total_weight = sum(
            r["actual_bars"] for r in ticker_results if r.get("actual_bars")
        )
        if total_weight > 0:
            overall_score = (
                sum(
                    r["score"] * r["actual_bars"]
                    for r in ticker_results
                    if r.get("actual_bars")
                )
                / total_weight
            )
        elif ticker_results:
            # All tickers have 0 bars → F
            overall_score = 0.0
        else:
            overall_score = 0.0

        overall_grade = _score_to_grade(overall_score)

        timespans_analyzed = sorted(
            {
                f"{r['multiplier']}{r['timespan']}"
                if r.get("multiplier", 1) != 1
                else r["timespan"]
                for r in ticker_results
                if r.get("timespan")
            }
        )

        # Grade distribution
        grade_dist = defaultdict(int)
        for r in ticker_results:
            grade_dist[r["grade"]] += 1

        return {
            "status": "complete",
            "overall_score": round(overall_score, 1),
            "overall_grade": overall_grade,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "ticker_count": len(set(t.ticker for t in tickers)),
            "analyzed_count": len(ticker_results),
            "timespans_analyzed": timespans_analyzed,
            "grade_distribution": dict(grade_dist),
            "tickers": ticker_results,
        }
