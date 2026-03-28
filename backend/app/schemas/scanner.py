from pydantic import BaseModel, Field, ConfigDict
from typing import Optional, List, Dict, Any
from datetime import datetime
from uuid import UUID


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
    events: List[Dict[str, Any]] = []


class ScannerStatsResponse(BaseModel):
    """Schema for scanner statistics."""
    activeAlerts: int
    avgVolumeSpike: float
    totalEvents: int
    todayEvents: int

    model_config = ConfigDict(from_attributes=True)


class ScannerConfigResponse(BaseModel):
    """Schema for scanner configuration response."""
    id: int
    uuid: UUID
    name: str
    description: Optional[str] = None
    scanner_type: str
    parameters: Dict[str, Any]
    criteria: List[Dict[str, Any]]
    is_active: bool
    run_frequency: Optional[str] = None
    last_run: Optional[datetime] = None
    next_run: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)
