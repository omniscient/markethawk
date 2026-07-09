"""ScannerQueryService — DB aggregation queries extracted from routers/scanner.py."""

from datetime import date, timedelta, timezone
from typing import Any, Optional, TypedDict

import sqlalchemy as sa
from sqlalchemy import distinct, func
from sqlalchemy.orm import Session

from app.models import MonitoredStock, ScannerEvent, ScannerRun
from app.models.scanner_outcome_summary import ScannerOutcomeSummary
from app.models.signal_review import SignalReview
from app.models.system_config import SystemConfig
from app.services.scan_orchestrator import compute_next_run


class CoverageRange(TypedDict):
    start: date
    end: date
    runs: int
    events: int


def _is_weekday(day: date) -> bool:
    return day.weekday() < 5


def _next_weekday(day: date) -> date:
    candidate = day + timedelta(days=1)
    while not _is_weekday(candidate):
        candidate += timedelta(days=1)
    return candidate


def _weekday_count(start: date, end: date) -> int:
    if end < start:
        return 0
    count = 0
    day = start
    while day <= end:
        if _is_weekday(day):
            count += 1
        day += timedelta(days=1)
    return count


def _subtract_weekdays(end: date, weekdays: int) -> date:
    if weekdays <= 1:
        return end
    remaining = weekdays - 1
    day = end
    while remaining > 0:
        day -= timedelta(days=1)
        if _is_weekday(day):
            remaining -= 1
    return day


def merge_coverage_ranges(ranges: list[CoverageRange]) -> list[CoverageRange]:
    ordered = sorted(ranges, key=lambda item: (item["start"], item["end"]))
    merged: list[CoverageRange] = []
    for item in ordered:
        if item["end"] < item["start"]:
            continue
        if not merged:
            merged.append(item.copy())
            continue
        current = merged[-1]
        if item["start"] <= _next_weekday(current["end"]):
            if item["end"] > current["end"]:
                current["end"] = item["end"]
            current["runs"] += item["runs"]
            current["events"] += item["events"]
        else:
            merged.append(item.copy())
    return merged


def _coverage_gaps(
    covered: list[CoverageRange],
    right_boundary: date,
) -> list[dict[str, Any]]:
    if not covered:
        start = _subtract_weekdays(right_boundary, 30)
        return [
            {
                "start": start,
                "end": right_boundary,
                "weekdays": _weekday_count(start, right_boundary),
            }
        ]

    gaps: list[dict[str, Any]] = []
    for previous, next_range in zip(covered, covered[1:]):
        start = previous["end"] + timedelta(days=1)
        end = next_range["start"] - timedelta(days=1)
        weekdays = _weekday_count(start, end)
        if weekdays > 0:
            gaps.append({"start": start, "end": end, "weekdays": weekdays})

    latest_covered = covered[-1]["end"]
    if latest_covered < right_boundary:
        start = latest_covered + timedelta(days=1)
        weekdays = _weekday_count(start, right_boundary)
        if weekdays > 0:
            gaps.append(
                {"start": start, "end": right_boundary, "weekdays": weekdays}
            )
    return gaps


class ScannerQueryService:
    @staticmethod
    def get_scan_status_block(
        db: Session,
        scanner_type: str,
        universe_id: Optional[int] = None,
    ) -> dict[str, Any]:
        base_q = db.query(ScannerRun).filter(ScannerRun.scanner_type == scanner_type)
        if universe_id is not None:
            base_q = base_q.filter(ScannerRun.universe_id == universe_id)

        last_run_record: Optional[ScannerRun] = base_q.order_by(
            ScannerRun.created_at.desc()
        ).first()
        last_run_info = None
        if last_run_record is not None:
            ts = last_run_record.created_at
            if ts is not None and ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            last_run_info = {
                "timestamp": ts,
                "status": last_run_record.status,
                "events_detected": last_run_record.events_detected or 0,
                "duration_ms": last_run_record.execution_time_ms or 0,
            }

        recent_20 = base_q.order_by(ScannerRun.created_at.desc()).limit(20).all()
        success_rate: Optional[float] = None
        avg_events: Optional[float] = None
        if recent_20:
            completed = [r for r in recent_20 if r.status == "completed"]
            success_rate = round(len(completed) / len(recent_20) * 100, 1)
            if completed:
                avg_events = round(
                    sum(r.events_detected or 0 for r in completed) / len(completed), 1
                )

        sparkline_rows = base_q.order_by(ScannerRun.created_at.desc()).limit(10).all()
        sparkline = [
            {
                "created_at": (
                    r.created_at.replace(tzinfo=timezone.utc).isoformat()
                    if r.created_at and r.created_at.tzinfo is None
                    else r.created_at.isoformat()
                    if r.created_at
                    else None
                ),
                "events_detected": r.events_detected or 0,
                "status": r.status,
            }
            for r in reversed(sparkline_rows)
        ]

        type_variants = [scanner_type]
        if scanner_type == "liquidity_hunt":
            type_variants = [
                "liquidity_hunt",
                "liquidity_hunt_pre",
                "liquidity_hunt_post",
            ]

        event_q = db.query(func.count(ScannerEvent.id)).filter(
            ScannerEvent.scanner_type.in_(type_variants)
        )
        if universe_id is not None:
            event_q = event_q.join(
                MonitoredStock,
                sa.and_(
                    ScannerEvent.ticker == MonitoredStock.ticker,
                    MonitoredStock.universe_id == universe_id,
                    MonitoredStock.is_active.is_(True),
                ),
            )
        total_events: int = event_q.scalar() or 0

        return {
            "scanner_type": scanner_type,
            "universe_id": universe_id,
            "last_run": last_run_info,
            "next_run": compute_next_run(scanner_type),
            "total_events": total_events,
            "success_rate": success_rate,
            "avg_events_per_scan": avg_events,
            "sparkline": sparkline,
        }

    @staticmethod
    def get_coverage(
        db: Session,
        scanner_type: str,
        universe_id: int,
        latest_trading_day: Optional[date] = None,
    ) -> dict[str, Any]:
        latest_trading_day = latest_trading_day or date.today()
        rows = (
            db.query(ScannerRun)
            .filter(
                ScannerRun.scanner_type == scanner_type,
                ScannerRun.universe_id == universe_id,
                ScannerRun.status == "completed",
                ScannerRun.scan_start_date.isnot(None),
                ScannerRun.scan_end_date.isnot(None),
            )
            .order_by(ScannerRun.scan_start_date.asc(), ScannerRun.scan_end_date.asc())
            .all()
        )
        ranges: list[CoverageRange] = [
            {
                "start": row.scan_start_date,
                "end": min(row.scan_end_date, latest_trading_day),
                "runs": 1,
                "events": row.events_detected or 0,
            }
            for row in rows
            if row.scan_start_date <= latest_trading_day
        ]
        covered = merge_coverage_ranges(ranges)
        latest_covered = covered[-1]["end"] if covered else None
        return {
            "scanner_type": scanner_type,
            "universe_id": universe_id,
            "latest_covered": latest_covered,
            "latest_trading_day": latest_trading_day,
            "covered": covered,
            "gaps": _coverage_gaps(covered, latest_trading_day),
        }

    @staticmethod
    def get_signal_quality_distribution(
        db: Session,
        scanner_type: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> dict[str, Any]:
        ranker_version_row = (
            db.query(SystemConfig)
            .filter(SystemConfig.key == "signal_ranker_version")
            .first()
        )
        version = ranker_version_row.value if ranker_version_row else "unknown"

        query = (
            db.query(
                ScannerEvent.signal_quality_score,
                ScannerOutcomeSummary.eod_pct_change,
                ScannerOutcomeSummary.follow_through,
            )
            .join(
                ScannerOutcomeSummary,
                ScannerOutcomeSummary.scanner_event_id == ScannerEvent.id,
            )
            .filter(ScannerEvent.signal_quality_score.isnot(None))
        )
        if scanner_type:
            query = query.filter(ScannerEvent.scanner_type == scanner_type)
        if start_date:
            query = query.filter(ScannerEvent.event_date >= start_date)
        if end_date:
            query = query.filter(ScannerEvent.event_date <= end_date)

        rows = query.all()
        buckets: dict[str, dict] = {
            f"{i / 10:.1f}-{(i + 1) / 10:.1f}": {
                "count": 0,
                "eod_sum": 0.0,
                "ft_sum": 0,
                "eod_count": 0,
                "ft_count": 0,
            }
            for i in range(10)
        }
        for score, eod_pct, follow_through in rows:
            idx = min(int(float(score) * 10), 9)
            label = f"{idx / 10:.1f}-{(idx + 1) / 10:.1f}"
            b = buckets[label]
            b["count"] += 1
            if eod_pct is not None:
                b["eod_sum"] += float(eod_pct)
                b["eod_count"] += 1
            if follow_through is not None:
                b["ft_sum"] += int(follow_through)
                b["ft_count"] += 1

        deciles = [
            {
                "decile": label,
                "count": b["count"],
                "avg_eod_pct": round(b["eod_sum"] / b["eod_count"], 3)
                if b["eod_count"] > 0
                else None,
                "follow_through_rate": round(b["ft_sum"] / b["ft_count"], 3)
                if b["ft_count"] > 0
                else None,
            }
            for label, b in buckets.items()
        ]
        return {"deciles": deciles, "signal_ranker_version": version}

    @staticmethod
    def get_review_stats(
        db: Session,
        scanner_type: Optional[str] = None,
        start_date: Optional[Any] = None,
        end_date: Optional[Any] = None,
    ) -> dict[str, Any]:
        event_q = db.query(func.count(ScannerEvent.id))
        review_q = db.query(SignalReview).join(
            ScannerEvent, SignalReview.scanner_event_id == ScannerEvent.id
        )

        if scanner_type:
            if scanner_type == "liquidity_hunt":
                variants = [
                    "liquidity_hunt",
                    "liquidity_hunt_pre",
                    "liquidity_hunt_post",
                ]
                event_q = event_q.filter(ScannerEvent.scanner_type.in_(variants))
                review_q = review_q.filter(ScannerEvent.scanner_type.in_(variants))
            else:
                event_q = event_q.filter(ScannerEvent.scanner_type == scanner_type)
                review_q = review_q.filter(ScannerEvent.scanner_type == scanner_type)
        if start_date:
            event_q = event_q.filter(ScannerEvent.event_date >= start_date)
            review_q = review_q.filter(ScannerEvent.event_date >= start_date)
        if end_date:
            event_q = event_q.filter(ScannerEvent.event_date <= end_date)
            review_q = review_q.filter(ScannerEvent.event_date <= end_date)

        total_events = event_q.scalar() or 0
        reviewed_count = (
            review_q.with_entities(
                func.count(distinct(SignalReview.scanner_event_id))
            ).scalar()
            or 0
        )

        confirmed_count = review_q.filter(SignalReview.verdict == "confirmed").count()
        rejected_count = review_q.filter(SignalReview.verdict == "rejected").count()
        denominator = confirmed_count + rejected_count
        acceptance_rate = (
            round(confirmed_count / denominator, 3) if denominator > 0 else 0.0
        )

        by_type_rows = (
            review_q.with_entities(
                ScannerEvent.scanner_type,
                SignalReview.verdict,
                func.count(SignalReview.id),
            )
            .group_by(ScannerEvent.scanner_type, SignalReview.verdict)
            .all()
        )
        type_map: dict = {}
        for stype, v, cnt in by_type_rows:
            if stype not in type_map:
                type_map[stype] = {
                    "scanner_type": stype,
                    "total": 0,
                    "confirmed": 0,
                    "rejected": 0,
                    "uncertain": 0,
                    "enhanced": 0,
                }
            type_map[stype]["total"] += cnt
            if v in type_map[stype]:
                type_map[stype][v] += cnt

        reason_rows = (
            review_q.filter(SignalReview.reject_reason.isnot(None))
            .with_entities(SignalReview.reject_reason, func.count(SignalReview.id))
            .group_by(SignalReview.reject_reason)
            .order_by(func.count(SignalReview.id).desc())
            .limit(5)
            .all()
        )

        return {
            "total_events": total_events,
            "reviewed_count": reviewed_count,
            "acceptance_rate": acceptance_rate,
            "by_scanner_type": list(type_map.values()),
            "top_rejection_reasons": [
                {"reason": r, "count": c} for r, c in reason_rows
            ],
        }
