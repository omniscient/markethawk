"""Pydantic schemas for the replay API."""

from datetime import date, datetime
from typing import Any, Dict, List, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import BatchDateRange, Ticker


class ReplayRunRequest(BatchDateRange):
    model_config = ConfigDict(extra="forbid")

    scanner_type: str
    trading_strategy_id: Optional[int] = None
    universe_id: int
    max_hold_days: int = Field(default=10, ge=1, le=252)
    exit_fidelity: Literal["intraday", "daily"] = "intraday"
    benchmark_symbol: Optional[Ticker] = "SPY"


class ReplayTradeResponse(BaseModel):
    id: int
    replay_run_id: int
    scanner_event_id: Optional[int] = None
    ticker: str
    signal_date: date
    entry_date: Optional[date] = None
    entry_price: Optional[float] = None
    direction: Optional[str] = None
    stop_price: Optional[float] = None
    target_price: Optional[float] = None
    exit_date: Optional[date] = None
    exit_price: Optional[float] = None
    exit_reason: Optional[str] = None
    return_pct: Optional[float] = None
    return_r: Optional[float] = None
    mfe_pct: Optional[float] = None
    mae_pct: Optional[float] = None
    bars_held: Optional[int] = None
    regime_trend: Optional[str] = None
    regime_vol: Optional[str] = None
    fill_source: Optional[str] = None

    model_config = {"from_attributes": True}


class ReplayTradesResponse(BaseModel):
    trades: List[ReplayTradeResponse]
    total: int
    limit: int
    offset: int


class ReplayRunResponse(BaseModel):
    id: int
    uuid: UUID
    status: str
    scanner_type: str
    scanner_config_snapshot: Dict[str, Any]
    trading_strategy_id: Optional[int] = None
    strategy_snapshot: Optional[Dict[str, Any]] = None
    universe_id: int
    universe_snapshot: Dict[str, Any]
    start_date: date
    end_date: date
    max_hold_days: int
    exit_fidelity: str
    benchmark_symbol: Optional[str] = None
    data_hash: Optional[str] = None
    metrics: Optional[Dict[str, Any]] = None
    skipped_count: Optional[int] = None
    error_message: Optional[str] = None
    celery_task_id: Optional[str] = None
    total_trades: Optional[int] = None
    hit_rate: Optional[float] = None
    expectancy_r: Optional[float] = None
    profit_factor: Optional[float] = None
    max_drawdown_r: Optional[float] = None
    avg_bars_held: Optional[float] = None
    median_bars_held: Optional[float] = None
    avg_mfe_pct: Optional[float] = None
    avg_mae_pct: Optional[float] = None
    mfe_mae_ratio: Optional[float] = None
    created_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class ReplayAnalyticsResponse(BaseModel):
    status: str
    equity_curve: List[Dict[str, Any]] = []
    calendar_decay: List[Dict[str, Any]] = []
    holding_period_decay: List[Dict[str, Any]] = []
    regime_breakdown: List[Dict[str, Any]] = []


class RunCompareEntry(BaseModel):
    uuid: UUID
    scanner_type: str
    start_date: date
    end_date: date
    status: str
    headline_metrics: Dict[str, Any]
    data_hash: Optional[str]


class RunPairComparison(BaseModel):
    a: UUID
    b: UUID
    data_hash_match: bool


class ReplayCompareResponse(BaseModel):
    runs: List[RunCompareEntry]
    comparisons: List[RunPairComparison]
    all_hashes_match: bool
