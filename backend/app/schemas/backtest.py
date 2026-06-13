"""
Pydantic schemas for the backtest API.
"""

from datetime import date, datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class BacktestRunRequest(BaseModel):
    scanner_type: str
    strategy_id: int
    universe_id: int
    start_date: date
    end_date: date
    max_hold_sessions: int = Field(default=10, ge=1, le=252)
    scanner_config_params: Optional[Dict[str, Any]] = None


class BacktestTradeResponse(BaseModel):
    id: int
    run_id: int
    ticker: str
    signal_date: date
    source_event_id: Optional[int] = None
    signal_indicators: Optional[Dict[str, Any]] = None
    entry_date: Optional[date] = None
    entry_price: Optional[float] = None
    exit_date: Optional[date] = None
    exit_price: Optional[float] = None
    exit_reason: Optional[str] = None
    hold_sessions: Optional[int] = None
    result_r: Optional[float] = None
    stop_price: Optional[float] = None
    target_price: Optional[float] = None
    created_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class BacktestRunResponse(BaseModel):
    id: int
    uuid: UUID
    scanner_type: str
    strategy_id: int
    universe_id: int
    start_date: date
    end_date: date
    max_hold_sessions: int
    scanner_config_params: Optional[Dict[str, Any]] = None
    status: str
    celery_task_id: Optional[str] = None
    error_message: Optional[str] = None

    # Summary stats
    total_signals: Optional[int] = None
    total_trades: Optional[int] = None
    wins: Optional[int] = None
    losses: Optional[int] = None
    win_rate: Optional[float] = None
    profit_factor: Optional[float] = None
    expectancy_r: Optional[float] = None
    max_drawdown_r: Optional[float] = None
    avg_hold_sessions: Optional[float] = None
    median_hold_sessions: Optional[float] = None

    # Anti-bias metadata
    signals_skipped_no_data: Optional[int] = None
    trades_exited_on_data_end: Optional[int] = None
    universe_as_of: Optional[str] = None
    bars_source: Optional[str] = None
    degraded_input: Optional[bool] = None

    created_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class BacktestRunDetailResponse(BacktestRunResponse):
    trades: List[BacktestTradeResponse] = []
