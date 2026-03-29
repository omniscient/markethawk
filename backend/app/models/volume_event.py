"""
VolumeEvent SQLAlchemy model.
"""

from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, Date, Numeric, JSON, Uuid as UUID
import uuid

from app.core.database import Base


class VolumeEvent(Base):
    """Represents a detected volume spike event."""
    
    __tablename__ = "volume_events"
    
    id = Column(Integer, primary_key=True, index=True)
    uuid = Column(UUID(as_uuid=True), default=uuid.uuid4, unique=True, index=True)
    ticker = Column(String(10), nullable=False, index=True)
    event_date = Column(Date, nullable=False, index=True)
    event_type = Column(String(50), nullable=False, index=True)
    pre_market_volume = Column(Numeric, nullable=False)
    regular_volume = Column(Numeric)
    avg_volume_20d = Column(Numeric, nullable=False)
    avg_volume_50d = Column(Numeric)
    relative_volume = Column(Numeric, nullable=False)
    volume_spike_ratio = Column(Numeric, nullable=False)
    previous_close = Column(Numeric, nullable=False)
    pre_market_high = Column(Numeric)
    pre_market_low = Column(Numeric)
    opening_price = Column(Numeric)
    closing_price = Column(Numeric)
    regular_high = Column(Numeric)
    regular_low = Column(Numeric)
    post_market_high = Column(Numeric)
    post_market_low = Column(Numeric)
    total_day_high = Column(Numeric)
    total_day_low = Column(Numeric)
    fade_from_high_pct = Column(Numeric)
    day_range_pct = Column(Numeric)
    gap_pct = Column(Numeric)
    price_change_pct = Column(Numeric)
    price_gap_pct = Column(Numeric)
    criteria_met = Column(JSON, nullable=False)
    news_count = Column(Integer, default=0)
    earnings_date = Column(Date)
    market_cap_at_event = Column(Numeric)
    raw_data = Column(JSON, default=dict)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
