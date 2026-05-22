"""
SignalReview SQLAlchemy model.
"""

from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship

from app.core.database import Base


class SignalReview(Base):
    __tablename__ = "signal_reviews"

    id = Column(Integer, primary_key=True, index=True)
    scanner_event_id = Column(
        Integer, ForeignKey("scanner_events.id", ondelete="CASCADE"), nullable=False, index=True
    )
    verdict = Column(String(20), nullable=False)          # confirmed | rejected | enhanced
    reject_reason = Column(String(50), nullable=True)     # noise | too_late | stale_data | split_artifact | threshold_too_loose | other
    notes = Column(String(1000), nullable=True)
    enhance_suggestion = Column(JSONB, nullable=True)     # {threshold, current_value, proposed_value, rationale, file, line_hint}
    reviewed_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc).replace(tzinfo=None),
        nullable=False,
    )
    reviewed_by = Column(String(100), nullable=True)      # reserved for future multi-user

    event = relationship("ScannerEvent", back_populates="reviews")
