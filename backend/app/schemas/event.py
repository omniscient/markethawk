"""
Scanner Event Pydantic schemas.
"""

from pydantic import BaseModel, ConfigDict, Field
from typing import Dict, Any, Optional, List
from datetime import datetime, date
import uuid


class ScannerEventResponse(BaseModel):
    """Full detailed schema for scanner event API responses."""
    id: int
    uuid: uuid.UUID
    ticker: str
    event_date: date
    scanner_type: str
    
    summary: Optional[str] = None
    severity: Optional[str] = "medium"
    
    previous_close: Optional[float] = None
    opening_price: Optional[float] = None
    closing_price: Optional[float] = None

    signal_quality_score: Optional[float] = None

    indicators: Dict[str, Any] = Field(default_factory=dict)
    criteria_met: Dict[str, Any] = Field(default_factory=dict)
    metadata: Dict[str, Any] = Field(default_factory=dict, alias="metadata_")
    
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class ScannerEventSummary(BaseModel):
    """Minimal schema for list views of scanner events."""
    id: int
    uuid: uuid.UUID
    ticker: str
    event_date: date
    scanner_type: str
    summary: Optional[str] = None
    severity: Optional[str] = "medium"
    
    model_config = ConfigDict(from_attributes=True)
