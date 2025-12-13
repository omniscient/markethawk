"""
Scanner Pydantic schemas.
"""

from pydantic import BaseModel
from typing import Optional, List


class ScannerRunRequest(BaseModel):
    """Schema for scanner run requests."""
    universe_id: Optional[int] = None
    tickers: Optional[List[str]] = None
    scanner_type: str = "pre_market_volume"
    dry_run: bool = False


class ScannerRunResponse(BaseModel):
    """Schema for scanner run responses."""
    scan_id: str
    status: str
    stocks_scanned: int
    events_detected: int
    execution_time_ms: int
