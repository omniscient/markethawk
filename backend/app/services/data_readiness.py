"""
DataReadinessService — checks whether required aggregate data exists for outcome tracking.
"""

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Any, List, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.scanner_config import ScannerConfig
from app.models.stock_aggregate import StockAggregate
from app.services.data_quality import DataQualityService

EVENT_WARNING_CODES = {
    "missing_required_timespan",
    "low_coverage",
    "integrity_violation",
    "continuity_gap",
    "stale_data",
    "insufficient_lookback",
}

_BARS_PER_TRADING_DAY: dict[str, int] = {
    "minute": 390,
    "hour": 7,
    "day": 1,
    "week": 1,
    "month": 1,
}

_COVERAGE_WARNING_THRESHOLD = 0.85

_AFFECTED_INPUTS_BY_TIMESPAN: dict[str, list[str]] = {
    "minute": ["minute_aggregates", "price", "volume"],
    "hour": ["hourly_aggregates", "price", "volume"],
    "day": ["daily_aggregates", "close", "volume"],
    "week": ["weekly_aggregates", "close", "volume"],
    "month": ["monthly_aggregates", "close", "volume"],
}


@dataclass
class TimespanCoverage:
    timespan: str
    multiplier: int
    required_from: date
    required_to: date
    available_from: Optional[date] = None
    available_to: Optional[date] = None
    is_ready: bool = False


@dataclass
class ReadinessReport:
    ticker: str
    scanner_type: str
    coverages: List[TimespanCoverage] = field(default_factory=list)
    is_ready: bool = False
    missing_summary: str = ""


class DataReadinessService:
    @staticmethod
    def _normalize_timespan_requirements(data_requirements: dict | None) -> list[dict]:
        if not data_requirements:
            return []
        timespans = data_requirements.get("timespans")
        if isinstance(timespans, list):
            return [dict(req) for req in timespans if isinstance(req, dict)]
        if "timespan" in data_requirements or "min_bars" in data_requirements:
            return [dict(data_requirements)]
        return []

    @staticmethod
    def _scanner_type_candidates(scanner_type: str) -> list[str]:
        candidates = [scanner_type]
        if scanner_type in {"liquidity_hunt_pre", "liquidity_hunt_post"}:
            candidates.append("liquidity_hunt")
        return candidates

    @staticmethod
    def _affected_inputs(req: dict) -> list[str]:
        configured = req.get("affected_inputs")
        if isinstance(configured, list) and configured:
            return [str(value) for value in configured]
        timespan = str(req.get("timespan", "minute"))
        return list(
            _AFFECTED_INPUTS_BY_TIMESPAN.get(
                timespan, [f"{timespan}_aggregates", "price", "volume"]
            )
        )

    @staticmethod
    def _expected_bars(req: dict) -> Optional[int]:
        if req.get("expected_bars") is not None:
            return int(req["expected_bars"])
        lookback_days = req.get("lookback_days")
        if not lookback_days:
            return None
        timespan = str(req.get("timespan", "minute"))
        multiplier = max(1, int(req.get("multiplier", 1)))
        bars_per_day = max(1, _BARS_PER_TRADING_DAY.get(timespan, 60) // multiplier)
        return int(lookback_days) * bars_per_day

    @staticmethod
    def _warning(
        code: str,
        *,
        ticker: str,
        scanner_type: str,
        event_date: date,
        req: dict,
        severity: str = "medium",
        message: str,
        detail: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        return {
            "code": code,
            "severity": severity,
            "message": message,
            "affected_inputs": DataReadinessService._affected_inputs(req),
            "detail": {
                "ticker": ticker,
                "scanner_type": scanner_type,
                "event_date": event_date.isoformat(),
                "timespan": str(req.get("timespan", "minute")),
                "multiplier": int(req.get("multiplier", 1)),
                **(detail or {}),
            },
        }

    @staticmethod
    def _load_event_rows(
        db: Session,
        ticker: str,
        event_date: date,
        req: dict,
    ) -> list[Any]:
        timespan = str(req.get("timespan", "minute"))
        multiplier = int(req.get("multiplier", 1))
        query = db.query(
            StockAggregate.timestamp,
            StockAggregate.open,
            StockAggregate.high,
            StockAggregate.low,
            StockAggregate.close,
            StockAggregate.volume,
        ).filter(
            StockAggregate.ticker == ticker,
            StockAggregate.timespan == timespan,
            StockAggregate.multiplier == multiplier,
            StockAggregate.timestamp
            < datetime.combine(event_date + timedelta(days=1), time.min),
        )
        lookback_days = req.get("lookback_days")
        if lookback_days:
            query = query.filter(
                StockAggregate.timestamp
                >= datetime.combine(
                    event_date - timedelta(days=int(lookback_days)), time.min
                )
            )
        return query.order_by(StockAggregate.timestamp.asc()).all()

    @staticmethod
    def event_warnings(
        db: Session,
        ticker: str,
        scanner_type: str,
        event_date: date,
        data_requirements: Optional[dict] = None,
    ) -> list[dict[str, Any]]:
        """Return scanner-explanation-ready warnings scoped to one event."""
        if data_requirements is None:
            for candidate in DataReadinessService._scanner_type_candidates(
                scanner_type
            ):
                config = (
                    db.query(ScannerConfig)
                    .filter(ScannerConfig.scanner_type == candidate)
                    .first()
                )
                config_requirements = getattr(config, "data_requirements", None)
                if config_requirements:
                    data_requirements = config_requirements
                    break

        reqs = DataReadinessService._normalize_timespan_requirements(
            data_requirements
        )
        if not reqs:
            return []

        warnings: list[dict[str, Any]] = []
        for req in reqs:
            timespan = str(req.get("timespan", "minute"))
            multiplier = int(req.get("multiplier", 1))
            rows = DataReadinessService._load_event_rows(db, ticker, event_date, req)
            affected = f"{timespan}x{multiplier}"

            if not rows:
                warnings.append(
                    DataReadinessService._warning(
                        "missing_required_timespan",
                        ticker=ticker,
                        scanner_type=scanner_type,
                        event_date=event_date,
                        req=req,
                        severity="high",
                        message=(
                            f"{ticker} has no {affected} aggregate data available"
                            f" for the {event_date.isoformat()} explanation window."
                        ),
                        detail={"observed_bars": 0},
                    )
                )
                continue

            observed_bars = len(rows)
            expected_bars = DataReadinessService._expected_bars(req)
            if (
                expected_bars
                and observed_bars < expected_bars * _COVERAGE_WARNING_THRESHOLD
            ):
                coverage_pct = round(observed_bars / expected_bars * 100, 1)
                warnings.append(
                    DataReadinessService._warning(
                        "low_coverage",
                        ticker=ticker,
                        scanner_type=scanner_type,
                        event_date=event_date,
                        req=req,
                        message=(
                            f"{ticker} {affected} coverage is {coverage_pct:.1f}%"
                            " of the expected event window."
                        ),
                        detail={
                            "observed_bars": observed_bars,
                            "expected_bars": expected_bars,
                            "coverage_pct": coverage_pct,
                        },
                    )
                )

            min_bars = req.get("min_bars")
            if min_bars is not None and observed_bars < int(min_bars):
                warnings.append(
                    DataReadinessService._warning(
                        "insufficient_lookback",
                        ticker=ticker,
                        scanner_type=scanner_type,
                        event_date=event_date,
                        req=req,
                        message=(
                            f"{ticker} has {observed_bars} {affected} bars but"
                            f" {int(min_bars)} are required for the scanner lookback."
                        ),
                        detail={
                            "observed_bars": observed_bars,
                            "required_bars": int(min_bars),
                        },
                    )
                )

            quality_summary = DataQualityService.summarize_event_bars(
                rows, timespan, multiplier
            )
            bad_bar_count = quality_summary["bad_bar_count"]
            if bad_bar_count:
                warnings.append(
                    DataReadinessService._warning(
                        "integrity_violation",
                        ticker=ticker,
                        scanner_type=scanner_type,
                        event_date=event_date,
                        req=req,
                        severity="high",
                        message=(
                            f"{ticker} has {bad_bar_count} invalid {affected}"
                            " OHLCV bar(s) in the explanation window."
                        ),
                        detail={"bad_bar_count": bad_bar_count},
                    )
                )

            timestamps = [row.timestamp for row in rows]
            duplicate_count = quality_summary["duplicate_count"]
            gap_count = quality_summary["gap_count"]
            if duplicate_count or gap_count:
                warnings.append(
                    DataReadinessService._warning(
                        "continuity_gap",
                        ticker=ticker,
                        scanner_type=scanner_type,
                        event_date=event_date,
                        req=req,
                        message=(
                            f"{ticker} {affected} data has {gap_count} gap(s)"
                            f" and {duplicate_count} duplicate timestamp(s)."
                        ),
                        detail={
                            "gap_count": gap_count,
                            "duplicate_count": duplicate_count,
                        },
                    )
                )

            last_bar_date = max(timestamps).date()
            stale_tolerance_days = int(
                req.get("max_stale_days", 1 if timespan == "day" else 0)
            )
            stale_after = event_date - timedelta(days=stale_tolerance_days)
            if last_bar_date < stale_after:
                warnings.append(
                    DataReadinessService._warning(
                        "stale_data",
                        ticker=ticker,
                        scanner_type=scanner_type,
                        event_date=event_date,
                        req=req,
                        message=(
                            f"{ticker} latest {affected} bar is {last_bar_date},"
                            f" stale for the {event_date.isoformat()} event."
                        ),
                        detail={
                            "last_bar": last_bar_date.isoformat(),
                            "max_stale_days": stale_tolerance_days,
                        },
                    )
                )

        return warnings

    @staticmethod
    def event_warning_metadata(
        base_metadata: Optional[dict[str, Any]],
        warnings: list[dict[str, Any]],
    ) -> Optional[dict[str, Any]]:
        """Merge event-scoped warnings into existing quality_gate metadata."""
        if not warnings:
            return base_metadata

        merged = dict(base_metadata or {})
        merged.setdefault("tier", "warning")
        merged.setdefault("schema_version", "quality_gate.v1")
        existing = list(merged.get("warnings") or [])
        seen = {
            (
                warning.get("code"),
                tuple(warning.get("affected_inputs") or []),
                str(warning.get("message")),
            )
            for warning in existing
        }
        for warning in warnings:
            key = (
                warning.get("code"),
                tuple(warning.get("affected_inputs") or []),
                str(warning.get("message")),
            )
            if key in seen:
                continue
            existing.append(warning)
            seen.add(key)
        merged["warnings"] = existing
        return merged

    @staticmethod
    def event_quality_gate_metadata(
        db: Session,
        ticker: str,
        scanner_type: str,
        event_date: date,
        base_metadata: Optional[dict[str, Any]],
        data_requirements: Optional[dict] = None,
    ) -> Optional[dict[str, Any]]:
        warnings = DataReadinessService.event_warnings(
            db,
            ticker=ticker,
            scanner_type=scanner_type,
            event_date=event_date,
            data_requirements=data_requirements,
        )
        return DataReadinessService.event_warning_metadata(base_metadata, warnings)

    @staticmethod
    def check(db: Session, ticker: str, scanner_type: str) -> ReadinessReport:
        config = (
            db.query(ScannerConfig)
            .filter(ScannerConfig.scanner_type == scanner_type)
            .first()
        )
        report = ReadinessReport(ticker=ticker, scanner_type=scanner_type)

        if not config or not config.data_requirements:
            report.is_ready = True
            report.missing_summary = "No data requirements configured"
            return report

        reqs = config.data_requirements.get("timespans", [])
        today = date.today()
        all_ready = True

        for req in reqs:
            ts = req.get("timespan", "minute")
            mult = req.get("multiplier", 1)
            lookback = req.get("lookback_days", 10)
            req_from = today - timedelta(days=lookback)
            req_to = today

            row = (
                db.query(
                    func.min(func.date(StockAggregate.timestamp)).label("first"),
                    func.max(func.date(StockAggregate.timestamp)).label("last"),
                )
                .filter(
                    StockAggregate.ticker == ticker,
                    StockAggregate.timespan == ts,
                    StockAggregate.multiplier == mult,
                )
                .first()
            )

            avail_from = row.first if row else None
            avail_to = row.last if row else None
            ready = (
                avail_from is not None
                and avail_to is not None
                and avail_from <= req_from
                and avail_to >= req_to - timedelta(days=1)
            )
            if not ready:
                all_ready = False

            report.coverages.append(
                TimespanCoverage(
                    timespan=ts,
                    multiplier=mult,
                    required_from=req_from,
                    required_to=req_to,
                    available_from=avail_from,
                    available_to=avail_to,
                    is_ready=ready,
                )
            )

        report.is_ready = all_ready
        if not all_ready:
            missing = [c for c in report.coverages if not c.is_ready]
            report.missing_summary = ", ".join(
                f"{c.timespan}x{c.multiplier}" for c in missing
            )
        else:
            report.missing_summary = ""

        return report
