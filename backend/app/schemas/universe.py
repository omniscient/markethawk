"""
Stock Universe Pydantic schemas.
"""

from pydantic import BaseModel, Field
from typing import Optional, Dict, Any
from datetime import datetime
import uuid


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

    class Config:
        from_attributes = True
