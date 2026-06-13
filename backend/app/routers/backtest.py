"""
Backtest router.

Endpoints:
  POST   /api/v1/backtest/runs          — enqueue a new backtest run
  GET    /api/v1/backtest/runs          — list backtest runs (paginated)
  GET    /api/v1/backtest/runs/{uuid}   — poll / retrieve a run + its trades
"""

import logging
import uuid as _uuid
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.backtest_run import BacktestRun
from app.models.trading_strategy import TradingStrategy
from app.schemas.backtest import (
    BacktestRunDetailResponse,
    BacktestRunRequest,
    BacktestRunResponse,
)
from app.utils.time import utc_now

router = APIRouter(prefix="/api/v1/backtest", tags=["backtest"])
logger = logging.getLogger(__name__)


@router.post("/runs", response_model=BacktestRunResponse, status_code=202)
def create_backtest_run(
    request: Request,
    payload: BacktestRunRequest,
    db: Session = Depends(get_db),
):
    """
    Enqueue a new backtest run.

    Returns HTTP 202 with the run record (status=queued).
    Poll GET /runs/{uuid} to track progress.
    """
    from app.models.stock_universe import StockUniverse
    from app.tasks.backtest import run_backtest

    # Validate strategy exists
    strategy = (
        db.query(TradingStrategy)
        .filter(TradingStrategy.id == payload.strategy_id)
        .first()
    )
    if not strategy:
        raise HTTPException(
            status_code=404,
            detail=f"TradingStrategy id={payload.strategy_id} not found",
        )

    # Validate universe exists
    universe = (
        db.query(StockUniverse).filter(StockUniverse.id == payload.universe_id).first()
    )
    if not universe:
        raise HTTPException(
            status_code=404, detail=f"StockUniverse id={payload.universe_id} not found"
        )

    if payload.start_date > payload.end_date:
        raise HTTPException(status_code=422, detail="start_date must be <= end_date")

    run = BacktestRun(
        uuid=_uuid.uuid4(),
        scanner_type=payload.scanner_type,
        strategy_id=payload.strategy_id,
        universe_id=payload.universe_id,
        start_date=payload.start_date,
        end_date=payload.end_date,
        max_hold_sessions=payload.max_hold_sessions,
        scanner_config_params=payload.scanner_config_params,
        status="queued",
        created_at=utc_now(),
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    async_result = run_backtest.delay(
        run_id=run.id,
        scanner_type=payload.scanner_type,
        strategy_id=payload.strategy_id,
        universe_id=payload.universe_id,
        start_date_iso=payload.start_date.isoformat(),
        end_date_iso=payload.end_date.isoformat(),
        max_hold_sessions=payload.max_hold_sessions,
    )

    run.celery_task_id = async_result.id
    db.commit()
    db.refresh(run)

    return run


@router.get("/runs", response_model=List[BacktestRunResponse])
def list_backtest_runs(
    scanner_type: Optional[str] = Query(default=None),
    strategy_id: Optional[int] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    """List backtest runs, most recent first."""
    q = db.query(BacktestRun)
    if scanner_type:
        q = q.filter(BacktestRun.scanner_type == scanner_type)
    if strategy_id is not None:
        q = q.filter(BacktestRun.strategy_id == strategy_id)
    runs = q.order_by(BacktestRun.created_at.desc()).offset(offset).limit(limit).all()
    return runs


@router.get("/runs/{run_uuid}", response_model=BacktestRunDetailResponse)
def get_backtest_run(
    run_uuid: str,
    db: Session = Depends(get_db),
):
    """
    Retrieve a backtest run by UUID, including the full trade list.

    Use this endpoint to poll for completion (check status field).
    """
    from app.models.backtest_trade import BacktestTrade

    try:
        parsed_uuid = _uuid.UUID(run_uuid)
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid UUID format")

    run = db.query(BacktestRun).filter(BacktestRun.uuid == parsed_uuid).first()
    if not run:
        raise HTTPException(status_code=404, detail="Backtest run not found")

    trades = (
        db.query(BacktestTrade)
        .filter(BacktestTrade.run_id == run.id)
        .order_by(BacktestTrade.signal_date.asc(), BacktestTrade.ticker.asc())
        .all()
    )

    from app.schemas.backtest import BacktestTradeResponse

    run_data = BacktestRunDetailResponse.model_validate(run)
    run_data.trades = [BacktestTradeResponse.model_validate(t) for t in trades]
    return run_data
