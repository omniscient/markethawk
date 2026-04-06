"""
Stock Pydantic schemas.
"""

from pydantic import BaseModel
from typing import Optional
from datetime import date


class MonitoredStockResponse(BaseModel):
    """Schema for monitored stock API responses."""
    id: int
    ticker: str
    company_name: Optional[str]
    sector: Optional[str]
    market_cap: Optional[float]
    added_date: date
    is_active: bool
    asset_class: str = "stocks"
    data_source: str = "massive"

    class Config:
        from_attributes = True
