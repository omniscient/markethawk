"""
OutcomeService — creates, captures, and summarises scanner outcome data.
"""

import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import List, Optional

from sqlalchemy.orm import Session

from app.models.scanner_config import ScannerConfig
from app.models.scanner_event import ScannerEvent
from app.models.scanner_outcome_snapshot import ScannerOutcomeSnapshot
from app.models.scanner_outcome_summary import ScannerOutcomeSummary
from app.utils.time import utc_now

logger = logging.getLogger(__name__)


class OutcomeService:
    """Service for managing scanner outcome tracking."""

    @staticmethod
    def create_pending_snapshots(
        db: Session,
        event: ScannerEvent,
    ) -> List[ScannerOutcomeSnapshot]:
        config = (
            db.query(ScannerConfig)
            .filter(ScannerConfig.scanner_type == event.scanner_type)
            .first()
        )
        if not config or not config.outcome_config:
            return []

        oc = config.outcome_config
        intervals = oc.get("intervals", [])
        if not intervals:
            return []

        ref_source = oc.get("reference_price_source", "opening_price")
        reference_price = getattr(event, ref_source, None) or event.opening_price
        if reference_price is None:
            logger.warning(
                "OutcomeService: no reference price for event %s (source=%s), skipping snapshots",
                event.id,
                ref_source,
            )
            return []

        snapshots = []
        for interval_key in intervals:
            snapshot = ScannerOutcomeSnapshot(
                scanner_event_id=event.id,
                interval_key=interval_key,
                reference_price=reference_price,
                status="pending",
            )
            db.add(snapshot)
            snapshots.append(snapshot)

        db.flush()
        return snapshots

    @staticmethod
    def capture_snapshot(db: Session, snapshot: ScannerOutcomeSnapshot) -> None:
        """Fill in a pending snapshot's price metrics from stock_aggregates."""
        from app.models.stock_aggregate import StockAggregate

        event = (
            db.query(ScannerEvent)
            .filter(ScannerEvent.id == snapshot.scanner_event_id)
            .first()
        )
        if not event:
            snapshot.status = "failed"
            return

        ref_price = float(snapshot.reference_price)
        if ref_price <= 0:
            snapshot.status = "failed"
            return

        from datetime import time as _time
        from datetime import timedelta
        from zoneinfo import ZoneInfo

        _ET = ZoneInfo("America/New_York")
        day_open_et = datetime.combine(event.event_date, _time(9, 30), tzinfo=_ET)
        day_open_utc = day_open_et.astimezone(timezone.utc).replace(tzinfo=None)

        interval_map = {
            "1h": timedelta(hours=1),
            "4h": timedelta(hours=4),
            "eod": timedelta(hours=6, minutes=30),
            "1d": timedelta(days=1),
            "2d": timedelta(days=2),
            "5d": timedelta(days=5),
        }
        delta = interval_map.get(snapshot.interval_key)
        if delta is None:
            snapshot.status = "failed"
            return

        window_start = day_open_utc
        window_end = day_open_utc + delta

        bars = (
            db.query(StockAggregate)
            .filter(
                StockAggregate.ticker == event.ticker,
                StockAggregate.timespan == "minute",
                StockAggregate.timestamp >= window_start,
                StockAggregate.timestamp < window_end,
            )
            .order_by(StockAggregate.timestamp.asc())
            .all()
        )

        if not bars:
            snapshot.status = "failed"
            return

        high = max(float(b.high) for b in bars)
        low = min(float(b.low) for b in bars)
        last_close = float(bars[-1].close)
        total_volume = sum(int(b.volume) for b in bars)

        snapshot.snapshot_price = Decimal(str(round(last_close, 4)))
        snapshot.pct_change = Decimal(
            str(round((last_close - ref_price) / ref_price * 100, 4))
        )
        snapshot.high_since_signal = Decimal(str(round(high, 4)))
        snapshot.low_since_signal = Decimal(str(round(low, 4)))
        snapshot.volume_since_signal = total_volume
        snapshot.captured_at = utc_now()
        snapshot.status = "captured"

    @staticmethod
    def recompute_summary(
        db: Session, scanner_event_id: int
    ) -> Optional[ScannerOutcomeSummary]:
        """Upsert the outcome summary for an event from its captured snapshots."""
        event = (
            db.query(ScannerEvent).filter(ScannerEvent.id == scanner_event_id).first()
        )
        if not event:
            return None

        snapshots = (
            db.query(ScannerOutcomeSnapshot)
            .filter(ScannerOutcomeSnapshot.scanner_event_id == scanner_event_id)
            .all()
        )
        captured = [s for s in snapshots if s.status == "captured"]
        if not captured:
            return None

        ref_price = float(captured[0].reference_price)
        if ref_price <= 0:
            return None

        highest = max(
            float(s.high_since_signal)
            for s in captured
            if s.high_since_signal is not None
        )
        lowest = min(
            float(s.low_since_signal)
            for s in captured
            if s.low_since_signal is not None
        )
        mfe_pct = round((highest - ref_price) / ref_price * 100, 4)
        mae_pct = round((lowest - ref_price) / ref_price * 100, 4)
        mfe_mae_ratio = round(abs(mfe_pct / mae_pct), 4) if mae_pct != 0 else None

        eod_snap = next((s for s in captured if s.interval_key == "eod"), None)
        eod_pct = (
            float(eod_snap.pct_change) if eod_snap and eod_snap.pct_change else None
        )

        config = (
            db.query(ScannerConfig)
            .filter(ScannerConfig.scanner_type == event.scanner_type)
            .first()
        )
        threshold = 2.0
        if config and config.outcome_config:
            threshold = config.outcome_config.get("follow_through_threshold_pct", 2.0)
        follow_through = eod_pct is not None and eod_pct >= threshold

        all_intervals = set()
        if config and config.outcome_config:
            all_intervals = set(config.outcome_config.get("intervals", []))
        captured_intervals = {s.interval_key for s in captured}
        is_complete = (
            all_intervals.issubset(captured_intervals)
            if all_intervals
            else len(captured) > 0
        )

        summary = (
            db.query(ScannerOutcomeSummary)
            .filter(ScannerOutcomeSummary.scanner_event_id == scanner_event_id)
            .first()
        )
        if not summary:
            summary = ScannerOutcomeSummary(scanner_event_id=scanner_event_id)
            db.add(summary)

        summary.reference_price = Decimal(str(ref_price))
        summary.mfe_pct = Decimal(str(mfe_pct))
        summary.mae_pct = Decimal(str(mae_pct))
        summary.mfe_mae_ratio = (
            Decimal(str(mfe_mae_ratio)) if mfe_mae_ratio is not None else None
        )
        summary.eod_pct_change = Decimal(str(eod_pct)) if eod_pct is not None else None
        summary.follow_through = follow_through
        summary.is_complete = is_complete
        summary.completed_at = utc_now() if is_complete else None

        db.flush()
        return summary
