"""
Scanner Event Pydantic schemas.
"""

from pydantic import BaseModel, Field
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
    
    indicators: Dict[str, Any] = Field(default_factory=dict)
    criteria_met: Dict[str, Any] = Field(default_factory=dict)
    metadata: Dict[str, Any] = Field(default_factory=dict, alias="metadata_")
    
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
        populate_by_name = True


class ScannerEventSummary(BaseModel):
    """Minimal schema for list views of scanner events."""
    id: int
    uuid: uuid.UUID
    ticker: str
    event_date: date
    scanner_type: str
    summary: Optional[str] = None
    severity: Optional[str] = "medium"
    
    class Config:
        from_attributes = True
