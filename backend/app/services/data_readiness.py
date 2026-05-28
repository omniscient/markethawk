"""
DataReadinessService — checks whether required aggregate data exists for outcome tracking.
"""

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import List, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.scanner_config import ScannerConfig
from app.models.stock_aggregate import StockAggregate


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
