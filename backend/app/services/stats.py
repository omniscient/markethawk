"""
Stats Service - Statistical aggregation and analysis for volume events.
"""

from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import sqlalchemy as sa
from sqlalchemy import and_, cast, desc, extract, func, or_
from sqlalchemy.orm import Session

from app.models.scanner_event import ScannerEvent
from app.models.scanner_outcome_snapshot import ScannerOutcomeSnapshot
from app.models.scanner_outcome_summary import ScannerOutcomeSummary
from app.models.signal_review import SignalReview

# JSONB path to the gate tier: metadata_["quality_gate"]["tier"]
_GATE_TIER = ScannerEvent.metadata_["quality_gate"]["tier"].astext


def _build_trust_filter(include_warnings: bool = False, include_all: bool = False):
    """Return a SQLAlchemy filter expression for the quality-gate trust level.

    - include_all=True  → no filter (all tiers visible)
    - include_warnings  → trusted + warning (exclude blocked/skipped)
    - default           → trusted only (NULL tier treated as trusted for legacy events)
    """
    if include_all:
        return None
    if include_warnings:
        # Allowlist: keep NULL (legacy trusted) and explicitly trusted/warning tiers
        return or_(_GATE_TIER.is_(None), _GATE_TIER.in_(["trusted", "warning"]))
    # Default: only events explicitly trusted or without a gate record
    return or_(_GATE_TIER.is_(None), _GATE_TIER == "trusted")


class StatsService:
    """Service for calculating statistical edge data from volume events."""

    @staticmethod
    def get_edge_stats(
        db: Session,
        ticker: Optional[str] = None,
        scanner_type: Optional[str] = None,
        period: str = "monthly",  # weekly, monthly, quarterly
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
    ) -> List[Dict[str, Any]]:
        """Get aggregated statistics for stock gap events."""

        # Select grouping based on period
        if period == "weekly":
            group_by = [
                sa.extract("year", ScannerEvent.event_date).label("year"),
                sa.extract("week", ScannerEvent.event_date).label("group_val"),
            ]
        elif period == "quarterly":
            group_by = [
                sa.extract("year", ScannerEvent.event_date).label("year"),
                sa.extract("quarter", ScannerEvent.event_date).label("group_val"),
            ]
        else:  # monthly
            group_by = [
                sa.extract("year", ScannerEvent.event_date).label("year"),
                sa.extract("month", ScannerEvent.event_date).label("group_val"),
            ]

        # Helper for JSON extraction
        def json_col(field_name):
            return cast(ScannerEvent.indicators[field_name].astext, sa.Numeric)

        query = db.query(
            *group_by,
            func.count(ScannerEvent.id).label("event_count"),
            func.avg(json_col("gap_pct")).label("avg_gap_pct"),
            func.avg(json_col("fade_from_high_pct")).label("avg_fade_pct"),
            func.avg(json_col("day_range_pct")).label("avg_day_range_pct"),
            func.avg(json_col("relative_volume")).label("avg_rel_vol"),
        )

        if ticker:
            query = query.filter(ScannerEvent.ticker == ticker.upper())
        if scanner_type:
            query = query.filter(ScannerEvent.scanner_type == scanner_type)
        if start_date:
            query = query.filter(ScannerEvent.event_date >= start_date)
        if end_date:
            query = query.filter(ScannerEvent.event_date <= end_date)

        stats = (
            query.group_by(*group_by)
            .order_by(sa_desc("year"), sa_desc("group_val"))
            .all()
        )

        results = []
        for s in stats:
            results.append(
                {
                    "period": period,
                    "label": f"{int(s.year)}-{int(s.group_val)}",
                    "event_count": s.event_count,
                    "avg_gap_pct": round(float(s.avg_gap_pct or 0), 2),
                    "avg_fade_pct": round(float(s.avg_fade_pct or 0), 2),
                    "avg_day_range_pct": round(float(s.avg_day_range_pct or 0), 2),
                    "avg_rel_vol": round(float(s.avg_rel_vol or 0), 2),
                }
            )

        return results

    @staticmethod
    def get_distribution_data(
        db: Session, ticker: Optional[str] = None, scanner_type: Optional[str] = None
    ) -> Dict[str, Any]:
        """Get distribution data for scatter plots and histograms."""
        query = db.query(
            ScannerEvent.indicators, ScannerEvent.ticker, ScannerEvent.event_date
        )

        if ticker:
            query = query.filter(ScannerEvent.ticker == ticker.upper())
        if scanner_type:
            query = query.filter(ScannerEvent.scanner_type == scanner_type)

        events = query.all()

        data = []
        for e in events:
            # Safely extract from indicators
            ind = e.indicators or {}
            gap_pct = ind.get("gap_pct")
            fade_pct = ind.get("fade_from_high_pct")

            if gap_pct is not None and fade_pct is not None:
                data.append(
                    {
                        "ticker": e.ticker,
                        "date": e.event_date.isoformat(),
                        "gap_pct": float(gap_pct),
                        "fade_pct": float(fade_pct),
                        "day_range_pct": float(ind.get("day_range_pct") or 0),
                    }
                )

        return {"events": data}

    @staticmethod
    def _get_review_fields(
        db: Session,
        scanner_type: str,
        total_signals: int,
        review_window_days: int = 90,
    ) -> Dict[str, Any]:
        """Aggregate SignalReview rows for a scanner type within the trailing window.

        Returns a dict of review-side fields that can be merged into any scorecard
        response. All fields are null/empty when no reviews exist in the window.
        precision_pct = confirmed / (confirmed + rejected) * 100 (null when denominator=0).
        review_coverage_pct uses trust-filtered outcome total_signals as denominator.
        """
        cutoff = datetime.utcnow() - timedelta(days=review_window_days)
        rows = (
            db.query(
                SignalReview.verdict,
                SignalReview.reject_reason,
                func.count(SignalReview.id).label("n"),
            )
            .join(ScannerEvent, ScannerEvent.id == SignalReview.scanner_event_id)
            .filter(
                ScannerEvent.scanner_type == scanner_type,
                SignalReview.reviewed_at >= cutoff,
            )
            .group_by(SignalReview.verdict, SignalReview.reject_reason)
            .all()
        )

        verdict_counts: Dict[str, int] = {"confirmed": 0, "rejected": 0, "enhanced": 0}
        reject_reason_counts: Dict[str, int] = {}

        for row in rows:
            v = row.verdict
            n = int(row.n)
            if v in verdict_counts:
                verdict_counts[v] += n
            if v == "rejected" and row.reject_reason:
                reject_reason_counts[row.reject_reason] = (
                    reject_reason_counts.get(row.reject_reason, 0) + n
                )

        sample_n = verdict_counts["confirmed"] + verdict_counts["rejected"]
        precision_pct = (
            round(verdict_counts["confirmed"] / sample_n * 100, 1)
            if sample_n > 0
            else None
        )
        coverage_pct = (
            round(sample_n / total_signals * 100, 1) if total_signals > 0 else None
        )
        top_reasons = sorted(reject_reason_counts.items(), key=lambda x: -x[1])[:3]
        top_reject_reasons = [{"reject_reason": r, "count": c} for r, c in top_reasons]

        return {
            "precision_pct": precision_pct,
            "review_coverage_pct": coverage_pct,
            "verdict_counts": verdict_counts,
            "top_reject_reasons": top_reject_reasons,
            "review_sample_n": sample_n,
        }

    @staticmethod
    def get_scorecard(
        db: Session,
        scanner_type: str,
        start_date=None,
        end_date=None,
        severity: Optional[str] = None,
        regime: Optional[str] = None,
        include_warnings: bool = False,
        include_all: bool = False,
        review_window_days: int = 90,
    ) -> Dict[str, Any]:
        base_filters = [ScannerEvent.scanner_type == scanner_type]
        if start_date:
            base_filters.append(ScannerEvent.event_date >= start_date)
        if end_date:
            base_filters.append(ScannerEvent.event_date <= end_date)
        if severity:
            base_filters.append(ScannerEvent.severity == severity)
        if regime:
            base_filters.append(ScannerEvent.regime == regime)

        # Gate status counts — query ScannerEvent directly so events without a
        # summary (no inner join) are still reflected in the tier counts.
        tier_count_rows = (
            db.query(_GATE_TIER.label("tier"), func.count().label("n"))
            .filter(*base_filters)
            .group_by(_GATE_TIER)
            .all()
        )
        gate_status: Dict[str, int] = {
            "trusted": 0,
            "warning": 0,
            "blocked": 0,
            "skipped": 0,
            "unknown": 0,
        }
        for row in tier_count_rows:
            # A NULL tier means a legacy event with no gate record — treated as
            # trusted, consistent with _build_trust_filter (which keeps _GATE_TIER IS NULL
            # in the default trusted filter). Only genuinely unexpected non-NULL tiers
            # fall through to "unknown".
            if row.tier is None:
                key = "trusted"
            elif row.tier in gate_status:
                key = row.tier
            else:
                key = "unknown"
            gate_status[key] += int(row.n)

        # Determine gate_filter label for response
        if include_all:
            gate_filter = "all"
        elif include_warnings:
            gate_filter = "trusted+warning"
        else:
            gate_filter = "trusted"

        query = (
            db.query(ScannerOutcomeSummary)
            .join(
                ScannerEvent, ScannerEvent.id == ScannerOutcomeSummary.scanner_event_id
            )
            .filter(*base_filters)
        )
        trust_filter = _build_trust_filter(
            include_warnings=include_warnings, include_all=include_all
        )
        if trust_filter is not None:
            query = query.filter(trust_filter)

        summaries = query.all()
        # trust-filtered total (see gate_status for all-tier counts)
        total = len(summaries)
        complete = [s for s in summaries if s.is_complete]
        complete_count = len(complete)

        review_fields = StatsService._get_review_fields(
            db, scanner_type, total, review_window_days
        )

        if not complete:
            return {
                "scanner_type": scanner_type,
                "period": "custom",
                "total_signals": total,
                "complete_signals": 0,
                "win_rate_pct": None,
                "avg_mfe_pct": None,
                "avg_mae_pct": None,
                "mfe_mae_ratio": None,
                "avg_r_multiple": None,
                "expectancy": None,
                "profit_factor": None,
                "follow_through_rate_pct": None,
                "edge_decay": [],
                "interval_breakdown": {},
                "gate_status": gate_status,
                "gate_filter": gate_filter,
                **review_fields,
            }

        wins = [
            s
            for s in complete
            if s.eod_pct_change is not None and float(s.eod_pct_change) > 0
        ]
        win_rate = (
            round(len(wins) / complete_count * 100, 2) if complete_count else None
        )

        mfe_vals = [float(s.mfe_pct) for s in complete if s.mfe_pct is not None]
        mae_vals = [float(s.mae_pct) for s in complete if s.mae_pct is not None]
        r_vals = [float(s.r_multiple) for s in complete if s.r_multiple is not None]
        eod_vals = [
            float(s.eod_pct_change) for s in complete if s.eod_pct_change is not None
        ]

        avg_mfe = round(sum(mfe_vals) / len(mfe_vals), 4) if mfe_vals else None
        avg_mae = round(sum(mae_vals) / len(mae_vals), 4) if mae_vals else None
        ratio = (
            round(abs(avg_mfe / avg_mae), 4)
            if avg_mfe and avg_mae and avg_mae != 0
            else None
        )
        avg_r = round(sum(r_vals) / len(r_vals), 4) if r_vals else None

        avg_win = (
            sum(v for v in eod_vals if v > 0)
            / max(len([v for v in eod_vals if v > 0]), 1)
            if eod_vals
            else 0
        )
        avg_loss = (
            abs(
                sum(v for v in eod_vals if v < 0)
                / max(len([v for v in eod_vals if v < 0]), 1)
            )
            if eod_vals
            else 0
        )
        wr_frac = len(wins) / complete_count if complete_count else 0
        expectancy = (
            round(wr_frac * avg_win - (1 - wr_frac) * avg_loss, 4) if eod_vals else None
        )
        profit_factor = (
            round(
                sum(v for v in eod_vals if v > 0)
                / abs(sum(v for v in eod_vals if v < 0)),
                4,
            )
            if eod_vals and sum(v for v in eod_vals if v < 0) != 0
            else None
        )

        ft_count = sum(1 for s in complete if s.follow_through)
        ft_rate = round(ft_count / complete_count * 100, 2) if complete_count else None

        return {
            "scanner_type": scanner_type,
            "period": "custom",
            "total_signals": total,
            "complete_signals": complete_count,
            "win_rate_pct": win_rate,
            "avg_mfe_pct": avg_mfe,
            "avg_mae_pct": avg_mae,
            "mfe_mae_ratio": ratio,
            "avg_r_multiple": avg_r,
            "expectancy": expectancy,
            "profit_factor": profit_factor,
            "follow_through_rate_pct": ft_rate,
            "edge_decay": [],
            "interval_breakdown": {},
            "gate_status": gate_status,
            "gate_filter": gate_filter,
            **review_fields,
        }

    @staticmethod
    def get_edge_decay(
        db: Session,
        scanner_type: str,
        start_date=None,
        end_date=None,
        period: str = "weekly",
    ) -> List[Dict[str, Any]]:
        if period == "weekly":
            grp = [
                extract("isoyear", ScannerEvent.event_date).label("yr"),
                extract("week", ScannerEvent.event_date).label("p"),
            ]
        elif period == "quarterly":
            grp = [
                extract("year", ScannerEvent.event_date).label("yr"),
                extract("quarter", ScannerEvent.event_date).label("p"),
            ]
        else:
            grp = [
                extract("year", ScannerEvent.event_date).label("yr"),
                extract("month", ScannerEvent.event_date).label("p"),
            ]

        query = (
            db.query(
                *grp,
                func.count(ScannerOutcomeSummary.id).label("n"),
                func.avg(ScannerOutcomeSummary.mfe_pct).label("avg_mfe"),
                func.avg(ScannerOutcomeSummary.mae_pct).label("avg_mae"),
                func.sum(
                    sa.case(
                        (
                            and_(
                                ScannerOutcomeSummary.eod_pct_change != None,
                                ScannerOutcomeSummary.eod_pct_change > 0,
                            ),
                            1,
                        ),
                        else_=0,
                    )
                ).label("wins"),
            )
            .join(
                ScannerEvent, ScannerEvent.id == ScannerOutcomeSummary.scanner_event_id
            )
            .filter(
                ScannerEvent.scanner_type == scanner_type,
                ScannerOutcomeSummary.is_complete == True,
            )
        )
        if start_date:
            query = query.filter(ScannerEvent.event_date >= start_date)
        if end_date:
            query = query.filter(ScannerEvent.event_date <= end_date)

        rows = query.group_by(*grp).order_by(desc("yr"), desc("p")).all()

        result = []
        for r in rows:
            n = int(r.n)
            result.append(
                {
                    "period": f"{int(r.yr)}-{int(r.p):02d}",
                    "win_rate": round(int(r.wins) / n * 100, 2) if n else 0,
                    "avg_mfe": round(float(r.avg_mfe or 0), 4),
                    "avg_mae": round(float(r.avg_mae or 0), 4),
                    "sample_size": n,
                }
            )
        return result

    @staticmethod
    def get_interval_performance(
        db: Session,
        scanner_type: str,
        interval_key: Optional[str] = None,
    ) -> Dict[str, Any]:
        query = (
            db.query(
                ScannerOutcomeSnapshot.interval_key,
                func.avg(ScannerOutcomeSnapshot.pct_change).label("avg_pct"),
                func.count(ScannerOutcomeSnapshot.id).label("n"),
                func.stddev(ScannerOutcomeSnapshot.pct_change).label("stddev_pct"),
                func.sum(
                    sa.case(
                        (
                            and_(
                                ScannerOutcomeSnapshot.pct_change != None,
                                ScannerOutcomeSnapshot.pct_change > 0,
                            ),
                            1,
                        ),
                        else_=0,
                    )
                ).label("wins"),
            )
            .join(
                ScannerEvent, ScannerEvent.id == ScannerOutcomeSnapshot.scanner_event_id
            )
            .filter(
                ScannerEvent.scanner_type == scanner_type,
                ScannerOutcomeSnapshot.status == "captured",
            )
        )
        if interval_key:
            query = query.filter(ScannerOutcomeSnapshot.interval_key == interval_key)

        rows = query.group_by(ScannerOutcomeSnapshot.interval_key).all()

        result = {}
        for r in rows:
            n = int(r.n)
            pcts = (
                db.query(ScannerOutcomeSnapshot.pct_change)
                .join(
                    ScannerEvent,
                    ScannerEvent.id == ScannerOutcomeSnapshot.scanner_event_id,
                )
                .filter(
                    ScannerEvent.scanner_type == scanner_type,
                    ScannerOutcomeSnapshot.interval_key == r.interval_key,
                    ScannerOutcomeSnapshot.status == "captured",
                    ScannerOutcomeSnapshot.pct_change != None,
                )
                .order_by(ScannerOutcomeSnapshot.pct_change)
                .all()
            )
            vals = [float(p[0]) for p in pcts]
            median = vals[len(vals) // 2] if vals else 0

            result[r.interval_key] = {
                "avg_pct": round(float(r.avg_pct or 0), 4),
                "median_pct": round(median, 4),
                "stddev_pct": round(float(r.stddev_pct or 0), 4),
                "win_rate": round(int(r.wins) / n * 100, 2) if n else 0,
                "sample_size": n,
            }
        return result

    @staticmethod
    def get_distribution(
        db: Session,
        scanner_type: str,
        metric: str = "mfe_pct",
    ) -> List[Dict[str, Any]]:
        allowed = {
            "mfe_pct",
            "mae_pct",
            "r_multiple",
            "eod_pct_change",
            "mfe_mae_ratio",
        }
        if metric not in allowed:
            metric = "mfe_pct"

        col = getattr(ScannerOutcomeSummary, metric, ScannerOutcomeSummary.mfe_pct)

        rows = (
            db.query(
                ScannerEvent.ticker,
                ScannerEvent.event_date,
                ScannerEvent.severity,
                col.label("value"),
            )
            .join(
                ScannerEvent, ScannerEvent.id == ScannerOutcomeSummary.scanner_event_id
            )
            .filter(
                ScannerEvent.scanner_type == scanner_type,
                ScannerOutcomeSummary.is_complete == True,
                col != None,
            )
            .order_by(col)
            .all()
        )

        return [
            {
                "ticker": r.ticker,
                "event_date": r.event_date.isoformat(),
                "value": round(float(r.value), 4),
                "scanner_type": scanner_type,
                "severity": r.severity,
            }
            for r in rows
        ]

    @staticmethod
    def get_signals(
        db: Session,
        scanner_type: str,
        start_date=None,
        end_date=None,
        severity: Optional[str] = None,
        sort_by: str = "event_date",
        sort_order: str = "desc",
        limit: int = 100,
        offset: int = 0,
    ) -> Dict[str, Any]:
        base = (
            db.query(ScannerEvent, ScannerOutcomeSummary)
            .outerjoin(
                ScannerOutcomeSummary,
                ScannerEvent.id == ScannerOutcomeSummary.scanner_event_id,
            )
            .filter(ScannerEvent.scanner_type == scanner_type)
        )
        if start_date:
            base = base.filter(ScannerEvent.event_date >= start_date)
        if end_date:
            base = base.filter(ScannerEvent.event_date <= end_date)
        if severity:
            base = base.filter(ScannerEvent.severity == severity)

        total = base.count()

        sort_col_map = {
            "event_date": ScannerEvent.event_date,
            "ticker": ScannerEvent.ticker,
            "mfe_pct": ScannerOutcomeSummary.mfe_pct,
            "mae_pct": ScannerOutcomeSummary.mae_pct,
            "eod_pct_change": ScannerOutcomeSummary.eod_pct_change,
        }
        col = sort_col_map.get(sort_by, ScannerEvent.event_date)
        order = desc(col) if sort_order == "desc" else col.asc()

        rows = base.order_by(order).limit(limit).offset(offset).all()

        signals = []
        for event, summary in rows:
            gate_meta = (event.metadata_ or {}).get("quality_gate") or {}
            signals.append(
                {
                    "id": event.id,
                    "ticker": event.ticker,
                    "event_date": event.event_date.isoformat(),
                    "severity": event.severity,
                    "summary": event.summary,
                    # gate_tier is label-only; trust filtering is intentionally left
                    # to the client (UI filters client-side). If server-side exclusion
                    # is needed in future, add include_warnings/include_all params here.
                    "gate_tier": gate_meta.get("tier"),
                    "opening_price": float(event.opening_price)
                    if event.opening_price
                    else None,
                    "previous_close": float(event.previous_close)
                    if event.previous_close
                    else None,
                    "closing_price": float(event.closing_price)
                    if event.closing_price
                    else None,
                    "reference_price": float(summary.reference_price)
                    if summary and summary.reference_price
                    else None,
                    "mfe_pct": float(summary.mfe_pct)
                    if summary and summary.mfe_pct is not None
                    else None,
                    "mae_pct": float(summary.mae_pct)
                    if summary and summary.mae_pct is not None
                    else None,
                    "eod_pct_change": float(summary.eod_pct_change)
                    if summary and summary.eod_pct_change is not None
                    else None,
                    "follow_through": summary.follow_through if summary else None,
                    "mfe_mae_ratio": float(summary.mfe_mae_ratio)
                    if summary and summary.mfe_mae_ratio is not None
                    else None,
                    "is_complete": summary.is_complete if summary else None,
                }
            )

        return {
            "signals": signals,
            "total": total,
            "limit": limit,
            "offset": offset,
        }

    @staticmethod
    def get_regime_breakdown(
        db: Session,
        scanner_type: str,
        start_date=None,
        end_date=None,
    ) -> Dict[str, Any]:
        """Per-regime win-rate, avg MFE, avg MAE, and sample size for a scanner type."""
        from collections import defaultdict

        query = (
            db.query(ScannerOutcomeSummary, ScannerEvent.regime)
            .join(
                ScannerEvent, ScannerEvent.id == ScannerOutcomeSummary.scanner_event_id
            )
            .filter(
                ScannerEvent.scanner_type == scanner_type,
                ScannerEvent.regime.isnot(None),
            )
        )
        if start_date:
            query = query.filter(ScannerEvent.event_date >= start_date)
        if end_date:
            query = query.filter(ScannerEvent.event_date <= end_date)

        rows = query.all()

        total_events = (
            db.query(ScannerEvent)
            .filter(ScannerEvent.scanner_type == scanner_type)
            .count()
        )

        by_regime: Dict[str, list] = defaultdict(list)
        for summary, regime_label in rows:
            if summary.is_complete:
                by_regime[regime_label].append(summary)

        breakdown = {}
        for regime_label, summaries in by_regime.items():
            n = len(summaries)
            wins = [
                s
                for s in summaries
                if s.eod_pct_change is not None and float(s.eod_pct_change) > 0
            ]
            mfe_vals = [float(s.mfe_pct) for s in summaries if s.mfe_pct is not None]
            mae_vals = [float(s.mae_pct) for s in summaries if s.mae_pct is not None]
            breakdown[regime_label] = {
                "sample_size": n,
                "win_rate_pct": round(len(wins) / n * 100, 2) if n else None,
                "avg_mfe_pct": round(sum(mfe_vals) / len(mfe_vals), 4)
                if mfe_vals
                else None,
                "avg_mae_pct": round(sum(mae_vals) / len(mae_vals), 4)
                if mae_vals
                else None,
            }

        return {
            "scanner_type": scanner_type,
            "total_events": total_events,
            "breakdown": breakdown,
        }


# Helper for descending sort in SQLAlchemy
def sa_desc(field):
    from sqlalchemy import desc

    return desc(field)
