"""
ScannerEvent SQLAlchemy model.
"""

from datetime import datetime, timezone
import uuid
from sqlalchemy import Column, Integer, String, DateTime, Date, Numeric, Float, ForeignKey, Uuid as UUID, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship

from app.core.database import Base


class ScannerEvent(Base):
    """Represents a detected scanner event (e.g. volume spike, oversold bounce)."""
    
    __tablename__ = "scanner_events"
    
    id = Column(Integer, primary_key=True, index=True)
    uuid = Column(UUID(as_uuid=True), default=uuid.uuid4, unique=True, index=True)
    ticker = Column(String(10), nullable=False, index=True)
    event_date = Column(Date, nullable=False, index=True)
    scanner_type = Column(String(50), nullable=False, index=True)  # discriminator (pre_market_volume, oversold_bounce, etc.)
    
    # Common event envelope
    summary = Column(String(500))  # human-readable signal summary
    severity = Column(String(10), default="medium")  # low, medium, high
    previous_close = Column(Numeric)
    opening_price = Column(Numeric)
    closing_price = Column(Numeric)
    
    # Scanner-specific payload (indicators like RSI, volume ratios, etc.)
    indicators = Column(JSONB, nullable=False, default=dict)
    
    # Criteria met (booleans/flags)
    criteria_met = Column(JSONB, nullable=False, default=dict)
    
    # Enrichment metadata (catalysts, splits, float rotation, etc.)
    metadata_ = Column("metadata", JSONB, nullable=False, default=dict)
    
    signal_cluster_id = Column(
        Integer, ForeignKey("signal_clusters.id"), nullable=True, index=True
    )

    signal_quality_score = Column(Float, nullable=True)

    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None), onupdate=lambda: datetime.now(timezone.utc).replace(tzinfo=None))

    reviews = relationship("SignalReview", back_populates="event", cascade="all, delete-orphan")

    @property
    def latest_review(self):
        if not self.reviews:
            return None
        return max(self.reviews, key=lambda r: r.reviewed_at)

    __table_args__ = (
        UniqueConstraint('ticker', 'event_date', 'scanner_type', name='uq_scanner_event'),
    )
