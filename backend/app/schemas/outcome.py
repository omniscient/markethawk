from pydantic import BaseModel, ConfigDict
from typing import Optional, List, Dict, Any
from datetime import datetime, date


class OutcomeSnapshotResponse(BaseModel):
    id: int
    scanner_event_id: int
    interval_key: str
    reference_price: float
    snapshot_price: Optional[float] = None
    pct_change: Optional[float] = None
    high_since_signal: Optional[float] = None
    low_since_signal: Optional[float] = None
    volume_since_signal: Optional[int] = None
    captured_at: Optional[datetime] = None
    status: str
    model_config = ConfigDict(from_attributes=True)


class OutcomeSummaryResponse(BaseModel):
    id: int
    scanner_event_id: int
    reference_price: float
    mfe_pct: Optional[float] = None
    mfe_time_minutes: Optional[int] = None
    mae_pct: Optional[float] = None
    mae_time_minutes: Optional[int] = None
    mfe_mae_ratio: Optional[float] = None
    r_multiple: Optional[float] = None
    eod_pct_change: Optional[float] = None
    follow_through: Optional[bool] = None
    gap_filled: Optional[bool] = None
    is_complete: bool
    completed_at: Optional[datetime] = None
    model_config = ConfigDict(from_attributes=True)


class EventOutcomeResponse(BaseModel):
    summary: Optional[OutcomeSummaryResponse] = None
    snapshots: List[OutcomeSnapshotResponse] = []


class IntervalBreakdown(BaseModel):
    avg_pct: float
    median_pct: float
    stddev_pct: float
    win_rate: float
    sample_size: int


class EdgeDecayPoint(BaseModel):
    period: str
    win_rate: float
    avg_mfe: float
    avg_mae: float
    sample_size: int


class ScorecardResponse(BaseModel):
    scanner_type: str
    period: str
    total_signals: int
    complete_signals: int
    win_rate_pct: Optional[float] = None
    avg_mfe_pct: Optional[float] = None
    avg_mae_pct: Optional[float] = None
    mfe_mae_ratio: Optional[float] = None
    avg_r_multiple: Optional[float] = None
    expectancy: Optional[float] = None
    profit_factor: Optional[float] = None
    follow_through_rate_pct: Optional[float] = None
    edge_decay: List[EdgeDecayPoint] = []
    interval_breakdown: Dict[str, IntervalBreakdown] = {}


class ReadinessCoverage(BaseModel):
    timespan: str
    multiplier: int
    required_from: date
    required_to: date
    available_from: Optional[date] = None
    available_to: Optional[date] = None
    is_ready: bool


class ReadinessResponse(BaseModel):
    ticker: str
    scanner_type: str
    coverages: List[ReadinessCoverage] = []
    is_ready: bool
    missing_summary: str


class BackfillRequest(BaseModel):
    scanner_type: str
    start_date: date
    end_date: date


class BackfillResponse(BaseModel):
    snapshots_created: int
    events_processed: int
    scanner_type: str


class DistributionPoint(BaseModel):
    ticker: str
    event_date: date
    value: float
    scanner_type: str
    severity: Optional[str] = None


class SignalListItem(BaseModel):
    id: int
    ticker: str
    event_date: date
    severity: Optional[str] = None
    summary: Optional[str] = None
    opening_price: Optional[float] = None
    previous_close: Optional[float] = None
    closing_price: Optional[float] = None
    reference_price: Optional[float] = None
    mfe_pct: Optional[float] = None
    mae_pct: Optional[float] = None
    eod_pct_change: Optional[float] = None
    follow_through: Optional[bool] = None
    mfe_mae_ratio: Optional[float] = None
    is_complete: Optional[bool] = None


class SignalListResponse(BaseModel):
    signals: List[SignalListItem]
    total: int
    limit: int
    offset: int
