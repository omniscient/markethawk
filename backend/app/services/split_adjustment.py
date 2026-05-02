"""
SplitAdjustmentService — detects and applies price adjustments when stock splits occur.
"""

import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import List

from sqlalchemy import update
from sqlalchemy.orm import Session

from app.models.stock_split import StockSplit
from app.models.stock_aggregate import StockAggregate
from app.models.scanner_event import ScannerEvent
from app.models.scanner_outcome_snapshot import ScannerOutcomeSnapshot
from app.models.scanner_outcome_summary import ScannerOutcomeSummary

logger = logging.getLogger(__name__)

BATCH_SIZE = 5000


class SplitAdjustmentService:

    @staticmethod
    def get_unapplied_splits(db: Session) -> List[StockSplit]:
        return (
            db.query(StockSplit)
            .filter(StockSplit.adjustments_applied_at.is_(None))
            .order_by(StockSplit.execution_date.asc())
            .all()
        )

    @staticmethod
    def compute_price_factor(split: StockSplit) -> Decimal:
        """Price factor to adjust old prices to post-split basis.
        Reverse 10:1 (from=10, to=1) → factor 10 (old $0.40 → $4.00).
        Forward 1:2 (from=1, to=2) → factor 0.5 (old $100 → $50).
        Volume gets the inverse factor.
        """
        return Decimal(str(split.split_from)) / Decimal(str(split.split_to))

    @staticmethod
    def adjust_stock_aggregates(db: Session, ticker: str, execution_date, factor: Decimal) -> int:
        f = float(factor)
        vol_factor = 1.0 / f
        stmt = (
            update(StockAggregate)
            .where(
                StockAggregate.ticker == ticker,
                StockAggregate.timestamp < datetime.combine(execution_date, datetime.min.time()),
            )
            .values(
                open=StockAggregate.open * f,
                high=StockAggregate.high * f,
                low=StockAggregate.low * f,
                close=StockAggregate.close * f,
                vwap=StockAggregate.vwap * f,
                volume=StockAggregate.volume * vol_factor,
            )
        )
        result = db.execute(stmt)
        return result.rowcount

    @staticmethod
    def adjust_scanner_events(db: Session, ticker: str, execution_date, factor: Decimal) -> int:
        f = float(factor)
        stmt = (
            update(ScannerEvent)
            .where(
                ScannerEvent.ticker == ticker,
                ScannerEvent.event_date < execution_date,
            )
            .values(
                opening_price=ScannerEvent.opening_price * f,
                previous_close=ScannerEvent.previous_close * f,
                closing_price=ScannerEvent.closing_price * f,
            )
        )
        result = db.execute(stmt)
        return result.rowcount

    @staticmethod
    def adjust_outcome_snapshots(db: Session, ticker: str, execution_date, factor: Decimal) -> int:
        f = float(factor)
        event_ids = (
            db.query(ScannerEvent.id)
            .filter(
                ScannerEvent.ticker == ticker,
                ScannerEvent.event_date < execution_date,
            )
            .subquery()
        )
        stmt = (
            update(ScannerOutcomeSnapshot)
            .where(ScannerOutcomeSnapshot.scanner_event_id.in_(event_ids.select()))
            .values(
                reference_price=ScannerOutcomeSnapshot.reference_price * f,
                snapshot_price=ScannerOutcomeSnapshot.snapshot_price * f,
                high_since_signal=ScannerOutcomeSnapshot.high_since_signal * f,
                low_since_signal=ScannerOutcomeSnapshot.low_since_signal * f,
            )
        )
        result = db.execute(stmt)
        return result.rowcount

    @staticmethod
    def adjust_outcome_summaries(db: Session, ticker: str, execution_date, factor: Decimal) -> int:
        event_ids = (
            db.query(ScannerEvent.id)
            .filter(
                ScannerEvent.ticker == ticker,
                ScannerEvent.event_date < execution_date,
            )
            .subquery()
        )
        f = float(factor)
        stmt = (
            update(ScannerOutcomeSummary)
            .where(ScannerOutcomeSummary.scanner_event_id.in_(event_ids.select()))
            .values(reference_price=ScannerOutcomeSummary.reference_price * f)
        )
        result = db.execute(stmt)
        return result.rowcount

    @staticmethod
    def apply_split(db: Session, split: StockSplit) -> dict:
        if split.adjustments_applied_at is not None:
            return {"skipped": True, "reason": "already applied"}

        factor = SplitAdjustmentService.compute_price_factor(split)
        ticker = split.ticker
        exec_date = split.execution_date

        has_events = db.query(ScannerEvent.id).filter(
            ScannerEvent.ticker == ticker,
            ScannerEvent.event_date < exec_date,
        ).first() is not None

        if not has_events:
            split.adjustments_applied_at = datetime.now(timezone.utc).replace(tzinfo=None)
            return {"skipped": True, "reason": "no scanner events for ticker"}

        event_count = SplitAdjustmentService.adjust_scanner_events(db, ticker, exec_date, factor)
        summary_count = SplitAdjustmentService.adjust_outcome_summaries(db, ticker, exec_date, factor)

        split.adjustments_applied_at = datetime.now(timezone.utc).replace(tzinfo=None)

        logger.info(
            "Split adjustment applied: %s %s (factor=%.4f) — events=%d, summaries=%d",
            ticker, exec_date, float(factor), event_count, summary_count,
        )

        return {
            "ticker": ticker,
            "execution_date": str(exec_date),
            "factor": float(factor),
            "events_adjusted": event_count,
            "summaries_adjusted": summary_count,
        }

    @staticmethod
    def apply_all_pending(db: Session) -> List[dict]:
        splits = SplitAdjustmentService.get_unapplied_splits(db)
        results = []
        for split in splits:
            result = SplitAdjustmentService.apply_split(db, split)
            results.append(result)
        db.commit()
        return results
