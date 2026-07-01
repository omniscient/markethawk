"""Replay API router."""

from __future__ import annotations

import itertools
import uuid as _uuid
from decimal import Decimal
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.scanner_config import ScannerConfig
from app.models.replay_run import ReplayRun
from app.models.replay_trade import ReplayTrade
from app.models.stock_universe import StockUniverse
from app.models.stock_universe_ticker import StockUniverseTicker
from app.models.trading_strategy import TradingStrategy
from app.schemas.replay import (
    ReplayAnalyticsResponse,
    ReplayCompareResponse,
    ReplayRunRequest,
    ReplayRunResponse,
    ReplayTradesResponse,
    RunCompareEntry,
    RunPairComparison,
)
from app.tasks.replay import run_signal_replay
from app.utils.time import utc_now

router = APIRouter(prefix="/api/v1/replay", tags=["replay"])


def _decimal_str(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return str(value)
    return str(value)


def _strategy_snapshot(strategy: TradingStrategy | None) -> dict | None:
    if strategy is None:
        return None
    return {
        "direction": strategy.direction,
        "entry_type": strategy.entry_type,
        "limit_offset_pct": _decimal_str(strategy.limit_offset_pct),
        "stop_pct": _decimal_str(strategy.stop_pct),
        "risk_reward_ratio": _decimal_str(strategy.risk_reward_ratio),
        "max_slippage_pct": _decimal_str(strategy.max_slippage_pct),
        "allowed_sessions": strategy.allowed_sessions,
        "risk_per_trade_pct": _decimal_str(strategy.risk_per_trade_pct),
        "max_position_usd": _decimal_str(strategy.max_position_usd),
        "max_trades_per_day": strategy.max_trades_per_day,
        "max_concurrent_positions": strategy.max_concurrent_positions,
    }


def _parse_uuid(value: str) -> _uuid.UUID:
    try:
        return _uuid.UUID(value)
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid UUID format")


def _run_by_uuid(db: Session, run_uuid: str) -> ReplayRun:
    parsed = _parse_uuid(run_uuid)
    run = db.query(ReplayRun).filter(ReplayRun.uuid == parsed).first()
    if run is None:
        raise HTTPException(status_code=404, detail="Replay run not found")
    return run


@router.post("/runs", response_model=ReplayRunResponse, status_code=202)
def create_replay_run(payload: ReplayRunRequest, db: Session = Depends(get_db)):
    strategy = None
    if payload.trading_strategy_id is not None:
        strategy = (
            db.query(TradingStrategy)
            .filter(TradingStrategy.id == payload.trading_strategy_id)
            .first()
        )
        if strategy is None:
            raise HTTPException(
                status_code=404,
                detail=f"TradingStrategy id={payload.trading_strategy_id} not found",
            )
    universe = (
        db.query(StockUniverse).filter(StockUniverse.id == payload.universe_id).first()
    )
    if universe is None:
        raise HTTPException(
            status_code=404, detail=f"StockUniverse id={payload.universe_id} not found"
        )
    scanner_config = (
        db.query(ScannerConfig)
        .filter(
            ScannerConfig.scanner_type == payload.scanner_type,
            ScannerConfig.universe_id == payload.universe_id,
        )
        .order_by(ScannerConfig.is_active.desc(), ScannerConfig.id.asc())
        .first()
    )
    if scanner_config is None:
        scanner_config_snapshot = {"scanner_type": payload.scanner_type}
    else:
        scanner_config_snapshot = {
            "scanner_type": scanner_config.scanner_type,
            "parameters": scanner_config.parameters or {},
            "criteria": scanner_config.criteria or [],
            "outcome_config": scanner_config.outcome_config,
            "data_requirements": scanner_config.data_requirements,
        }
    tickers = sorted(
        row[0]
        for row in db.query(StockUniverseTicker.ticker)
        .filter(StockUniverseTicker.universe_id == payload.universe_id)
        .all()
    )

    run = ReplayRun(
        uuid=_uuid.uuid4(),
        status="queued",
        scanner_type=payload.scanner_type,
        scanner_config_snapshot=scanner_config_snapshot,
        trading_strategy_id=payload.trading_strategy_id,
        strategy_snapshot=_strategy_snapshot(strategy),
        universe_id=payload.universe_id,
        universe_snapshot={"universe_id": payload.universe_id, "tickers": tickers},
        start_date=payload.start_date,
        end_date=payload.end_date,
        max_hold_days=payload.max_hold_days,
        exit_fidelity=payload.exit_fidelity,
        benchmark_symbol=payload.benchmark_symbol or "SPY",
        created_at=utc_now(),
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    async_result = run_signal_replay.delay(run.id)
    run.celery_task_id = async_result.id
    db.commit()
    db.refresh(run)
    return run


@router.get("/runs", response_model=List[ReplayRunResponse])
def list_replay_runs(
    scanner_type: Optional[str] = Query(default=None),
    trading_strategy_id: Optional[int] = Query(default=None),
    status: Optional[str] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    query = db.query(ReplayRun)
    if scanner_type:
        query = query.filter(ReplayRun.scanner_type == scanner_type)
    if trading_strategy_id is not None:
        query = query.filter(ReplayRun.trading_strategy_id == trading_strategy_id)
    if status:
        query = query.filter(ReplayRun.status == status)
    return query.order_by(ReplayRun.created_at.desc()).offset(offset).limit(limit).all()


@router.get("/runs/compare", response_model=ReplayCompareResponse)
def compare_replay_runs(ids: str = Query(...), db: Session = Depends(get_db)):
    raw_ids = [item.strip() for item in ids.split(",") if item.strip()]
    if len(raw_ids) < 2 or len(raw_ids) > 5:
        raise HTTPException(status_code=422, detail="compare requires 2 to 5 run IDs")
    parsed_ids = [_parse_uuid(item) for item in raw_ids]
    runs = db.query(ReplayRun).filter(ReplayRun.uuid.in_(parsed_ids)).all()
    by_uuid = {run.uuid: run for run in runs}
    missing = [str(run_uuid) for run_uuid in parsed_ids if run_uuid not in by_uuid]
    if missing:
        raise HTTPException(status_code=404, detail=f"Replay run not found: {missing[0]}")
    ordered = [by_uuid[run_uuid] for run_uuid in parsed_ids]
    comparisons = [
        RunPairComparison(
            a=a.uuid,
            b=b.uuid,
            data_hash_match=bool(a.data_hash and a.data_hash == b.data_hash),
        )
        for a, b in itertools.combinations(ordered, 2)
    ]
    return ReplayCompareResponse(
        runs=[
            RunCompareEntry(
                uuid=run.uuid,
                scanner_type=run.scanner_type,
                start_date=run.start_date,
                end_date=run.end_date,
                status=run.status,
                headline_metrics={
                    "hit_rate": run.hit_rate,
                    "expectancy_r": run.expectancy_r,
                    "profit_factor": run.profit_factor,
                    "max_drawdown_r": run.max_drawdown_r,
                    "avg_bars_held": run.avg_bars_held,
                    "total_trades": run.total_trades,
                    "skipped_count": run.skipped_count,
                },
                data_hash=run.data_hash,
            )
            for run in ordered
        ],
        comparisons=comparisons,
        all_hashes_match=all(item.data_hash_match for item in comparisons),
    )


@router.get("/runs/{run_uuid}", response_model=ReplayRunResponse)
def get_replay_run(run_uuid: str, db: Session = Depends(get_db)):
    return _run_by_uuid(db, run_uuid)


@router.get("/runs/{run_uuid}/trades", response_model=ReplayTradesResponse)
def get_replay_trades(
    run_uuid: str,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    sort: str = Query(default="signal_date"),
    direction: str = Query(default="asc"),
    db: Session = Depends(get_db),
):
    run = _run_by_uuid(db, run_uuid)
    sort_columns = {
        "signal_date": ReplayTrade.signal_date,
        "return_r": ReplayTrade.return_r,
        "ticker": ReplayTrade.ticker,
        "return_pct": ReplayTrade.return_pct,
    }
    column = sort_columns.get(sort, ReplayTrade.signal_date)
    query = db.query(ReplayTrade).filter(ReplayTrade.replay_run_id == run.id)
    total = query.count()
    order_by = column.desc() if direction == "desc" else column.asc()
    trades = query.order_by(order_by).offset(offset).limit(limit).all()
    return ReplayTradesResponse(trades=trades, total=total, limit=limit, offset=offset)


@router.get("/runs/{run_uuid}/analytics", response_model=ReplayAnalyticsResponse)
def get_replay_analytics(run_uuid: str, db: Session = Depends(get_db)):
    run = _run_by_uuid(db, run_uuid)
    if run.status != "completed":
        return ReplayAnalyticsResponse(status=run.status)
    metrics = run.metrics or {}
    if not metrics:
        from app.services.replay.metrics import MetricsComputer

        metrics = MetricsComputer(db).compute(run.id).as_metrics_json()
    return ReplayAnalyticsResponse(
        status=run.status,
        equity_curve=metrics.get("equity_curve", []),
        calendar_decay=metrics.get("calendar_decay", []),
        holding_period_decay=metrics.get("holding_period_decay", []),
        regime_breakdown=metrics.get("regime_breakdown", []),
    )
