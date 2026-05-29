"""
Auto-trading router — CRUD for trading strategies, order management, account info.

Endpoints:
  Strategies:
    GET    /api/trading/strategies
    POST   /api/trading/strategies
    GET    /api/trading/strategies/{id}
    PATCH  /api/trading/strategies/{id}
    DELETE /api/trading/strategies/{id}

  Orders:
    GET    /api/trading/orders
    GET    /api/trading/orders/{id}
    POST   /api/trading/orders/{id}/approve
    POST   /api/trading/orders/{id}/reject
    POST   /api/trading/orders/{id}/cancel

  Account / Stats:
    GET    /api/trading/account
    GET    /api/trading/stats
    PATCH  /api/trading/config
"""

import asyncio
import logging
from datetime import date as date_type
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.rate_limits import TRADING_LIMIT, limiter
from app.models.auto_trade_order import AutoTradeOrder
from app.models.system_config import SystemConfig
from app.models.trading_strategy import TradingStrategy
from app.schemas.auto_trade import AutoTradeOrderResponse, TradingStrategyResponse
from app.services.auto_trade_service import (
    approve_order,
    cancel_order,
    get_account,
    get_stats,
)

router = APIRouter(prefix="/api/v1/trading", tags=["auto-trading"])
logger = logging.getLogger(__name__)


# ── Trading Strategies — CRUD ────────────────────────────────────────────────

_STRATEGY_UPDATABLE = {
    "name",
    "description",
    "is_active",
    "paper_mode",
    "requires_approval",
    "risk_per_trade_pct",
    "max_position_usd",
    "max_trades_per_day",
    "max_concurrent_positions",
    "entry_type",
    "limit_offset_pct",
    "stop_pct",
    "risk_reward_ratio",
    "max_slippage_pct",
    "allowed_sessions",
    "direction",
}


@router.get("/strategies")
async def list_strategies(
    active_only: bool = False,
    db: Session = Depends(get_db),
) -> List[Dict[str, Any]]:
    """Return all trading strategies ordered by creation date."""
    loop = asyncio.get_running_loop()

    def _query():
        q = db.query(TradingStrategy)
        if active_only:
            q = q.filter(TradingStrategy.is_active == True)
        return q.order_by(TradingStrategy.created_at.desc()).all()

    strategies = await loop.run_in_executor(None, _query)
    return [TradingStrategyResponse.from_orm_dict(s).model_dump() for s in strategies]


@router.post("/strategies", status_code=201)
async def create_strategy(
    payload: Dict[str, Any],
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Create a new trading strategy. Defaults to paper_mode=True for safety."""
    loop = asyncio.get_running_loop()

    def _create():
        strategy = TradingStrategy(
            name=payload.get("name", "Untitled Strategy"),
            description=payload.get("description"),
            is_active=payload.get("is_active", True),
            paper_mode=payload.get("paper_mode", True),
            requires_approval=payload.get("requires_approval", False),
            risk_per_trade_pct=payload.get("risk_per_trade_pct", 1.0),
            max_position_usd=payload.get("max_position_usd"),
            max_trades_per_day=int(payload.get("max_trades_per_day", 3)),
            max_concurrent_positions=int(payload.get("max_concurrent_positions", 2)),
            entry_type=payload.get("entry_type", "market"),
            limit_offset_pct=payload.get("limit_offset_pct", 0.0),
            stop_pct=payload.get("stop_pct", 2.0),
            risk_reward_ratio=payload.get("risk_reward_ratio", 2.0),
            max_slippage_pct=payload.get("max_slippage_pct", 0.5),
            allowed_sessions=payload.get("allowed_sessions", ["regular"]),
            direction=payload.get("direction", "long_only"),
        )
        db.add(strategy)
        db.commit()
        db.refresh(strategy)
        logger.info(f"Created trading strategy id={strategy.id} name='{strategy.name}'")
        return strategy

    strategy = await loop.run_in_executor(None, _create)
    return TradingStrategyResponse.from_orm_dict(strategy).model_dump()


@router.get("/strategies/{strategy_id}")
async def get_strategy(
    strategy_id: int,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    loop = asyncio.get_running_loop()
    s = await loop.run_in_executor(
        None, lambda: db.query(TradingStrategy).filter(TradingStrategy.id == strategy_id).first()
    )
    if not s:
        raise HTTPException(status_code=404, detail="Strategy not found.")
    return TradingStrategyResponse.from_orm_dict(s).model_dump()


@router.patch("/strategies/{strategy_id}")
async def update_strategy(
    strategy_id: int,
    payload: Dict[str, Any],
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Partial update of a trading strategy."""
    loop = asyncio.get_running_loop()
    s = await loop.run_in_executor(
        None, lambda: db.query(TradingStrategy).filter(TradingStrategy.id == strategy_id).first()
    )
    if not s:
        raise HTTPException(status_code=404, detail="Strategy not found.")

    def _update():
        for key, value in payload.items():
            if key in _STRATEGY_UPDATABLE:
                setattr(s, key, value)
        s.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
        db.commit()
        db.refresh(s)
        return s

    s = await loop.run_in_executor(None, _update)
    return TradingStrategyResponse.from_orm_dict(s).model_dump()


@router.delete("/strategies/{strategy_id}", status_code=204)
async def delete_strategy(
    strategy_id: int,
    db: Session = Depends(get_db),
) -> None:
    """
    Soft-delete a strategy by setting is_active=False.

    We never hard-delete because AutoTradeOrders reference the strategy and
    it would break the audit trail.
    """
    loop = asyncio.get_running_loop()

    def _query():
        s = db.query(TradingStrategy).filter(TradingStrategy.id == strategy_id).first()
        if not s:
            return None, 0
        open_orders = (
            db.query(AutoTradeOrder)
            .filter(
                AutoTradeOrder.trading_strategy_id == strategy_id,
                AutoTradeOrder.status.in_(
                    ["submitted", "open", "pending", "pending_approval"]
                ),
            )
            .count()
        )
        return s, open_orders

    s, open_orders = await loop.run_in_executor(None, _query)
    if not s:
        raise HTTPException(status_code=404, detail="Strategy not found.")
    if open_orders > 0:
        raise HTTPException(
            status_code=409,
            detail=f"Cannot delete strategy with {open_orders} open order(s). Close them first.",
        )

    def _deactivate():
        s.is_active = False
        s.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
        db.commit()
        logger.info(f"Deactivated trading strategy id={strategy_id}")

    await loop.run_in_executor(None, _deactivate)


# ── Auto-Trade Orders ────────────────────────────────────────────────────────


@router.get("/orders")
async def list_orders(
    status: Optional[str] = None,
    symbol: Optional[str] = None,
    strategy_id: Optional[int] = None,
    from_date: Optional[str] = None,
    limit: int = 100,
    db: Session = Depends(get_db),
) -> List[Dict[str, Any]]:
    """List AutoTradeOrders with optional filters."""
    # Validate from_date before hitting DB
    parsed_date = None
    if from_date:
        try:
            parsed_date = date_type.fromisoformat(from_date)
        except ValueError:
            raise HTTPException(
                status_code=422, detail="Invalid from_date format. Use YYYY-MM-DD."
            )

    loop = asyncio.get_running_loop()

    def _query():
        q = db.query(AutoTradeOrder)
        if status:
            q = q.filter(AutoTradeOrder.status == status)
        if symbol:
            q = q.filter(AutoTradeOrder.symbol == symbol.upper())
        if strategy_id:
            q = q.filter(AutoTradeOrder.trading_strategy_id == strategy_id)
        if parsed_date:
            q = q.filter(AutoTradeOrder.event_date >= parsed_date)
        return q.order_by(AutoTradeOrder.created_at.desc()).limit(min(limit, 500)).all()

    orders = await loop.run_in_executor(None, _query)
    return [AutoTradeOrderResponse.from_orm_dict(o).model_dump() for o in orders]


@router.get("/orders/{order_id}")
async def get_order(
    order_id: int,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    loop = asyncio.get_running_loop()
    o = await loop.run_in_executor(
        None, lambda: db.query(AutoTradeOrder).filter(AutoTradeOrder.id == order_id).first()
    )
    if not o:
        raise HTTPException(status_code=404, detail="Order not found.")
    return AutoTradeOrderResponse.from_orm_dict(o).model_dump()


@router.post("/orders/{order_id}/approve")
@limiter.limit(TRADING_LIMIT)
async def approve_order_endpoint(
    request: Request,
    order_id: int,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Approve a pending_approval order."""
    loop = asyncio.get_running_loop()

    def _fetch():
        o = db.query(AutoTradeOrder).filter(AutoTradeOrder.id == order_id).first()
        if not o:
            return None, None
        strategy = (
            db.query(TradingStrategy)
            .filter(TradingStrategy.id == o.trading_strategy_id)
            .first()
        )
        return o, strategy

    o, strategy = await loop.run_in_executor(None, _fetch)
    if not o:
        raise HTTPException(status_code=404, detail="Order not found.")
    if o.status != "pending_approval":
        raise HTTPException(
            status_code=409,
            detail=f"Order is not pending approval (current status: {o.status}).",
        )
    if not strategy:
        raise HTTPException(status_code=404, detail="Strategy not found.")

    result = await loop.run_in_executor(None, lambda: approve_order(o, strategy, db))
    return AutoTradeOrderResponse.from_orm_dict(result).model_dump()


@router.post("/orders/{order_id}/reject")
@limiter.limit(TRADING_LIMIT)
async def reject_order(
    request: Request,
    order_id: int,
    payload: Dict[str, Any] = {},
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Reject a pending_approval order without submitting it."""
    loop = asyncio.get_running_loop()
    o = await loop.run_in_executor(
        None, lambda: db.query(AutoTradeOrder).filter(AutoTradeOrder.id == order_id).first()
    )
    if not o:
        raise HTTPException(status_code=404, detail="Order not found.")
    if o.status != "pending_approval":
        raise HTTPException(
            status_code=409,
            detail=f"Order is not pending approval (current status: {o.status}).",
        )

    def _reject():
        o.status = "rejected"
        o.rejection_reason = payload.get("reason", "Manually rejected via UI")
        o.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
        db.commit()
        db.refresh(o)
        logger.info(f"Rejected order id={o.id} reason='{o.rejection_reason}'")
        return o

    o = await loop.run_in_executor(None, _reject)
    return AutoTradeOrderResponse.from_orm_dict(o).model_dump()


@router.post("/orders/{order_id}/cancel")
@limiter.limit(TRADING_LIMIT)
async def cancel_order_endpoint(
    request: Request,
    order_id: int,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Cancel an active order."""
    loop = asyncio.get_running_loop()
    o = await loop.run_in_executor(
        None, lambda: db.query(AutoTradeOrder).filter(AutoTradeOrder.id == order_id).first()
    )
    if not o:
        raise HTTPException(status_code=404, detail="Order not found.")

    cancellable = {"submitted", "open", "pending", "pending_approval"}
    if o.status not in cancellable:
        raise HTTPException(
            status_code=409,
            detail=f"Order cannot be cancelled (current status: {o.status}).",
        )

    try:
        result = await loop.run_in_executor(None, lambda: cancel_order(o, db))
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    return AutoTradeOrderResponse.from_orm_dict(result).model_dump()


# ── Account Summary ──────────────────────────────────────────────────────────


@router.get("/account")
async def get_account_endpoint(db: Session = Depends(get_db)) -> Dict[str, Any]:
    """Fetch live account summary from IBKR."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, get_account)


# ── Stats ────────────────────────────────────────────────────────────────────


@router.get("/stats")
async def get_stats_endpoint(
    days: int = 30,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Return auto-trading statistics for the last N days."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, lambda: get_stats(db, days=days))


# ── Config ───────────────────────────────────────────────────────────────────


@router.get("/config")
async def get_trading_config(db: Session = Depends(get_db)) -> Dict[str, Any]:
    """Return current auto-trading system config values."""
    loop = asyncio.get_running_loop()

    def _query():
        keys = ["AUTO_TRADING_ENABLED", "PAPER_ACCOUNT_SIZE"]
        result: Dict[str, Any] = {
            "AUTO_TRADING_ENABLED": False,
            "PAPER_ACCOUNT_SIZE": 100000,
        }
        configs = db.query(SystemConfig).filter(SystemConfig.key.in_(keys)).all()
        for c in configs:
            if c.key == "AUTO_TRADING_ENABLED":
                result["AUTO_TRADING_ENABLED"] = c.value.lower() == "true"
            elif c.key == "PAPER_ACCOUNT_SIZE":
                try:
                    result["PAPER_ACCOUNT_SIZE"] = float(c.value)
                except ValueError:
                    pass
        return result

    return await loop.run_in_executor(None, _query)


@router.patch("/config")
async def update_trading_config(
    payload: Dict[str, Any],
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Update auto-trading system config (AUTO_TRADING_ENABLED, PAPER_ACCOUNT_SIZE)."""
    loop = asyncio.get_running_loop()

    def _update():
        allowed = {"AUTO_TRADING_ENABLED", "PAPER_ACCOUNT_SIZE"}
        now = datetime.now(timezone.utc).replace(tzinfo=None)

        for key, value in payload.items():
            if key not in allowed:
                continue

            if key == "AUTO_TRADING_ENABLED":
                str_val = "true" if bool(value) else "false"
            else:
                str_val = str(value)

            existing = db.query(SystemConfig).filter(SystemConfig.key == key).first()
            if existing:
                existing.value = str_val
                existing.updated_at = now
            else:
                db.add(SystemConfig(key=key, value=str_val))

            logger.info(f"trading config: {key} = {str_val}")

        db.commit()

    await loop.run_in_executor(None, _update)

    # Re-fetch config after update
    def _fetch_config():
        keys = ["AUTO_TRADING_ENABLED", "PAPER_ACCOUNT_SIZE"]
        result: Dict[str, Any] = {
            "AUTO_TRADING_ENABLED": False,
            "PAPER_ACCOUNT_SIZE": 100000,
        }
        configs = db.query(SystemConfig).filter(SystemConfig.key.in_(keys)).all()
        for c in configs:
            if c.key == "AUTO_TRADING_ENABLED":
                result["AUTO_TRADING_ENABLED"] = c.value.lower() == "true"
            elif c.key == "PAPER_ACCOUNT_SIZE":
                try:
                    result["PAPER_ACCOUNT_SIZE"] = float(c.value)
                except ValueError:
                    pass
        return result

    return await loop.run_in_executor(None, _fetch_config)
