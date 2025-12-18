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
    price_gap_pct: Optional[float] = None
    criteria_met: Dict[str, Any]
    created_at: datetime

    class Config:
        from_attributes = True
