from datetime import date, datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, field_validator


class ScannerRunRequest(BaseModel):
    """Schema for scanner run requests."""

    universe_id: Optional[int] = None
    tickers: Optional[List[str]] = None
    scanner_type: str = "pre_market_volume"
    dry_run: bool = False
    start_date: Optional[date] = None
    end_date: Optional[date] = None

    @field_validator("end_date")
    @classmethod
    def end_date_not_before_start(cls, v, info):
        start = info.data.get("start_date")
        if v is not None and start is not None and v < start:
            raise ValueError("end_date must not be before start_date")
        return v


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
    scan_start_date: Optional[date] = None
    scan_end_date: Optional[date] = None
    diagnostics: Optional[Dict[str, Any]] = None

    model_config = ConfigDict(from_attributes=True)


class ScannerRunAsyncResponse(BaseModel):
    """Returned when a scan is queued; the result is delivered via WS / status endpoint."""

    scan_id: str
    task_id: str
    started_at: datetime
    scanner_type: str
    universe_id: Optional[int] = None
    scan_start_date: Optional[date] = None
    scan_end_date: Optional[date] = None
    status: str = "queued"

    model_config = ConfigDict(from_attributes=True)


class ScannerRunStatusResponse(BaseModel):
    """Snapshot of an in-flight or finished scan."""

    scan_id: str
    task_id: Optional[str] = None
    status: str  # queued | running | completed | failed | cancelled
    scanner_type: str
    universe_id: Optional[int] = None
    scan_start_date: Optional[date] = None
    scan_end_date: Optional[date] = None
    stocks_scanned: int = 0
    events_detected: int = 0
    execution_time_ms: int = 0
    error_message: Optional[str] = None
    started_at: Optional[datetime] = None
    # Live progress, only present while running. Cleared on completion.
    progress: Optional[Dict[str, Any]] = None

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


class ScannerLastRunInfo(BaseModel):
    timestamp: Optional[datetime] = None
    status: str
    events_detected: int = 0
    duration_ms: int = 0


class ScannerSparklinePoint(BaseModel):
    created_at: Optional[str] = None
    events_detected: int = 0
    status: str


class ScannerStatusBlockResponse(BaseModel):
    scanner_type: str
    universe_id: Optional[int] = None
    last_run: Optional[ScannerLastRunInfo] = None
    next_run: Optional[datetime] = None
    total_events: int = 0
    success_rate: Optional[float] = None
    avg_events_per_scan: Optional[float] = None
    sparkline: List[ScannerSparklinePoint] = []

    model_config = ConfigDict(from_attributes=True)


class ClearEventsResponse(BaseModel):
    ticker: str
    deleted_count: int


class ScannerRangeRequest(BaseModel):
    """Schema for a date-range scanner run against a single ticker."""

    ticker: str
    scanner_types: List[str]
    start_date: date
    end_date: date
    fetch_missing_data: bool = True

    @field_validator("scanner_types")
    @classmethod
    def scanner_types_not_empty(cls, v):
        if not v:
            raise ValueError("At least one scanner type must be selected")
        return v
