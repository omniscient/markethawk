"""
ScannerOutcomeSummary SQLAlchemy model.
"""

from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, Numeric

from app.core.database import Base


class ScannerOutcomeSummary(Base):
    """Derived signal-quality metrics for a scanner event, computed from its snapshots."""

    __tablename__ = "scanner_outcome_summaries"

    id = Column(Integer, primary_key=True, index=True)
    scanner_event_id = Column(
        Integer,
        ForeignKey("scanner_events.id"),
        nullable=False,
        unique=True,
        index=True,
    )
    reference_price = Column(Numeric, nullable=False)
    mfe_pct = Column(Numeric, nullable=True)
    mfe_time_minutes = Column(Integer, nullable=True)
    mae_pct = Column(Numeric, nullable=True)
    mae_time_minutes = Column(Integer, nullable=True)
    mfe_mae_ratio = Column(Numeric, nullable=True)
    r_multiple = Column(Numeric, nullable=True)
    eod_pct_change = Column(Numeric, nullable=True)
    follow_through = Column(Boolean, nullable=True)
    gap_filled = Column(Boolean, nullable=True)
    is_complete = Column(Boolean, default=False, index=True)
    completed_at = Column(DateTime, nullable=True)

    created_at = Column(
        DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None)
    )
    updated_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc).replace(tzinfo=None),
        onupdate=lambda: datetime.now(timezone.utc).replace(tzinfo=None),
    )
