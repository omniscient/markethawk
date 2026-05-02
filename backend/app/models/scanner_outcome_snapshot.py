"""
ScannerOutcomeSnapshot SQLAlchemy model.
"""

from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, DateTime, Numeric, BigInteger, ForeignKey, UniqueConstraint
from sqlalchemy.schema import Index

from app.core.database import Base


class ScannerOutcomeSnapshot(Base):
    """Captures price action at a specific time offset from a scanner signal."""

    __tablename__ = "scanner_outcome_snapshots"

    id = Column(Integer, primary_key=True, index=True)
    scanner_event_id = Column(Integer, ForeignKey("scanner_events.id"), nullable=False, index=True)
    interval_key = Column(String(10), nullable=False)
    reference_price = Column(Numeric, nullable=False)
    snapshot_price = Column(Numeric, nullable=True)
    pct_change = Column(Numeric, nullable=True)
    high_since_signal = Column(Numeric, nullable=True)
    low_since_signal = Column(Numeric, nullable=True)
    volume_since_signal = Column(BigInteger, nullable=True)
    captured_at = Column(DateTime, nullable=True)
    status = Column(String(20), nullable=False, default="pending", index=True)

    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None))

    __table_args__ = (
        UniqueConstraint("scanner_event_id", "interval_key", name="uq_outcome_snapshot_event_interval"),
    )
