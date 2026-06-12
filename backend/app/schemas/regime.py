"""Pydantic schemas for regime breakdown endpoints."""

from typing import Dict, Optional

from pydantic import BaseModel


class RegimeSliceSchema(BaseModel):
    sample_size: int
    win_rate_pct: Optional[float] = None
    avg_mfe_pct: Optional[float] = None
    avg_mae_pct: Optional[float] = None


class RegimeBreakdownResponse(BaseModel):
    scanner_type: str
    total_events: int
    breakdown: Dict[str, RegimeSliceSchema]
