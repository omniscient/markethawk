"""
Volume Event Pydantic schemas.
"""

from pydantic import BaseModel
from typing import Dict, Any, Optional
from datetime import datetime, date
import uuid


class VolumeEventResponse(BaseModel):
    """Schema for volume event API responses."""
    id: int
    uuid: uuid.UUID
    ticker: str
    event_date: date
    event_type: str
    pre_market_volume: float
    avg_volume_20d: float
    relative_volume: float
    volume_spike_ratio: float
    opening_price: Optional[float] = None
    closing_price: Optional[float] = None
    regular_high: Optional[float] = None
    regular_low: Optional[float] = None
    post_market_high: Optional[float] = None
    post_market_low: Optional[float] = None
    total_day_high: Optional[float] = None
    total_day_low: Optional[float] = None
    fade_from_high_pct: Optional[float] = None
    day_range_pct: Optional[float] = None
    gap_pct: Optional[float] = None
    price_gap_pct: Optional[float] = None
    criteria_met: Dict[str, Any]
    created_at: datetime

    class Config:
        from_attributes = True
