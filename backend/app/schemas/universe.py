"""
Stock Universe Pydantic schemas.
"""

import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import BoundedDict


class StockUniverseCreate(BaseModel):
    """Schema for creating a new stock universe."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., max_length=100)
    description: Optional[str] = Field(None, max_length=2048)
    criteria: BoundedDict


class StockUniverseUpdate(BaseModel):
    """Schema for updating an existing stock universe."""

    model_config = ConfigDict(extra="forbid")

    name: Optional[str] = Field(None, max_length=100)
    description: Optional[str] = Field(None, max_length=2048)
    criteria: Optional[BoundedDict] = None
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


class DataHealthResponse(BaseModel):
    """Summary data-health response for a single universe."""

    degraded: bool
    stale_pct: float
    gapped_pct: float
    worst_staleness_hours: float
    grade: str
