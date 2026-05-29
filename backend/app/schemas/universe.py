"""
Stock Universe Pydantic schemas.
"""

import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class StockUniverseCreate(BaseModel):
    """Schema for creating a new stock universe."""

    name: str = Field(..., max_length=100)
    description: Optional[str] = None
    criteria: Dict[str, Any]


class StockUniverseUpdate(BaseModel):
    """Schema for updating an existing stock universe."""

    name: Optional[str] = Field(None, max_length=100)
    description: Optional[str] = None
    criteria: Optional[Dict[str, Any]] = None
    is_active: Optional[bool] = None


class StockUniverseResponse(BaseModel):
    """Schema for stock universe API responses."""

    id: int
    uuid: uuid.UUID
    name: str
    description: Optional[str]
    criteria: Dict[str, Any]
    created_at: datetime
    is_active: bool
    ticker_count: Optional[int] = 0
    aggregate_count: Optional[int] = 0
    min_aggregate_date: Optional[datetime] = None
    max_aggregate_date: Optional[datetime] = None
    available_timespans: Optional[List[str]] = []
    stats_refreshed_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class UniverseSummary(BaseModel):
    """Minimal universe info returned for ticker membership lookups."""

    id: int
    name: str

    model_config = ConfigDict(from_attributes=True)
