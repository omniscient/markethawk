"""
Stock Pydantic schemas.
"""

from datetime import date
from typing import Optional

from pydantic import BaseModel, ConfigDict


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

    model_config = ConfigDict(from_attributes=True)
