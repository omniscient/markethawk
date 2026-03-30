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
    events: Optional[List[Dict[str, Any]]] = None
    scanner_type: str
    error_message: Optional[str] = None
    created_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


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


class PreMarketMover(BaseModel):
    """Schema for a single pre-market mover."""
    ticker: str
    name: Optional[str] = None
    price: float
    change_percent: float
    change_value: float
    volume: int
    prev_close: float
    sector: Optional[str] = None
    market_cap: Optional[float] = None


class PreMarketMoversResponse(BaseModel):
    """Schema for the pre-market movers list response."""
    status: str
    movers: List[PreMarketMover]
    timestamp: datetime
