"""
Scanner Event Pydantic schemas.
"""

import uuid
from datetime import date, datetime
from typing import Any, Dict, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.signal_review import SignalReviewResponse

SeverityLiteral = Literal["low", "medium", "high"]


class ScannerEventResponse(BaseModel):
    """Full detailed schema for scanner event API responses."""

    id: int
    uuid: uuid.UUID
    ticker: str
    event_date: date
    scanner_type: str

    summary: Optional[str] = None
    severity: Optional[SeverityLiteral] = "medium"

    previous_close: Optional[float] = None
    opening_price: Optional[float] = None
    closing_price: Optional[float] = None

    signal_quality_score: Optional[float] = None
    regime: Optional[str] = None

    indicators: Dict[str, Any] = Field(default_factory=dict)
    criteria_met: Dict[str, Any] = Field(default_factory=dict)
    metadata: Dict[str, Any] = Field(default_factory=dict, alias="metadata_")
    explanation: Optional[Dict[str, Any]] = None

    created_at: datetime
    updated_at: datetime

    latest_review: Optional[SignalReviewResponse] = None

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class ScannerEventSummary(BaseModel):
    """Minimal schema for list views of scanner events."""

    id: int
    uuid: uuid.UUID
    ticker: str
    event_date: date
    scanner_type: str
    summary: Optional[str] = None
    severity: Optional[SeverityLiteral] = "medium"

    model_config = ConfigDict(from_attributes=True)
