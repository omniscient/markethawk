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

import logging
from datetime import date as date_type
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
from app.utils.db import get_or_404
from app.utils.time import utc_now

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
def list_strategies(
    active_only: bool = False,
    db: Session = Depends(get_db),
) -> List[Dict[str, Any]]:
    """Return all trading strategies ordered by creation date."""
    q = db.query(TradingStrategy)
    if active_only:
        q = q.filter(TradingStrategy.is_active == True)
    strategies = q.order_by(TradingStrategy.created_at.desc()).all()
    return [TradingStrategyResponse.from_orm_dict(s).model_dump() for s in strategies]


def _validate_live_strategy(paper_mode: bool, max_position_usd) -> None:
    """Raise HTTP 422 if a live strategy has no or non-positive max_position_usd."""
    if not paper_mode and (max_position_usd is None or float(max_position_usd) <= 0):
        raise HTTPException(
            status_code=422,
            detail="max_position_usd is required when paper_mode=False",
        )


@router.post("/strategies", status_code=201)
def create_strategy(
    payload: Dict[str, Any],
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Create a new trading strategy. Defaults to paper_mode=True for safety."""
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
    _validate_live_strategy(
        paper_mode=strategy.paper_mode, max_position_usd=strategy.max_position_usd
    )
    db.add(strategy)
    db.commit()
    db.refresh(strategy)
    logger.info(f"Created trading strategy id={strategy.id} name='{strategy.name}'")
    return TradingStrategyResponse.from_orm_dict(strategy).model_dump()


@router.get("/strategies/{strategy_id}")
def get_strategy(
    strategy_id: int,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    s = get_or_404(db, TradingStrategy, strategy_id, "Strategy")
    return TradingStrategyResponse.from_orm_dict(s).model_dump()


@router.patch("/strategies/{strategy_id}")
def update_strategy(
    strategy_id: int,
    payload: Dict[str, Any],
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Partial update of a trading strategy."""
    s = get_or_404(db, TradingStrategy, strategy_id, "Strategy")

    for key, value in payload.items():
        if key in _STRATEGY_UPDATABLE:
            setattr(s, key, value)

    _validate_live_strategy(
        paper_mode=s.paper_mode, max_position_usd=s.max_position_usd
    )
    s.updated_at = utc_now()
    db.commit()
    db.refresh(s)
    return TradingStrategyResponse.from_orm_dict(s).model_dump()


@router.delete("/strategies/{strategy_id}", status_code=204)
def delete_strategy(
    strategy_id: int,
    db: Session = Depends(get_db),
) -> None:
    """
    Soft-delete a strategy by setting is_active=False.

    We never hard-delete because AutoTradeOrders reference the strategy and
    it would break the audit trail.
    """
    s = get_or_404(db, TradingStrategy, strategy_id, "Strategy")

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
    if open_orders > 0:
        raise HTTPException(
            status_code=409,
            detail=f"Cannot delete strategy with {open_orders} open order(s). Close them first.",
        )

    s.is_active = False
    s.updated_at = utc_now()
    db.commit()
    logger.info(f"Deactivated trading strategy id={strategy_id}")


# ── Auto-Trade Orders ────────────────────────────────────────────────────────


@router.get("/orders")
def list_orders(
    status: Optional[str] = None,
    symbol: Optional[str] = None,
    strategy_id: Optional[int] = None,
    from_date: Optional[str] = None,
    limit: int = 100,
    db: Session = Depends(get_db),
) -> List[Dict[str, Any]]:
    """List AutoTradeOrders with optional filters."""
    q = db.query(AutoTradeOrder)
    if status:
        q = q.filter(AutoTradeOrder.status == status)
    if symbol:
        q = q.filter(AutoTradeOrder.symbol == symbol.upper())
    if strategy_id:
        q = q.filter(AutoTradeOrder.trading_strategy_id == strategy_id)
    if from_date:
        try:
            d = date_type.fromisoformat(from_date)
            q = q.filter(AutoTradeOrder.event_date >= d)
        except ValueError:
            raise HTTPException(
                status_code=422, detail="Invalid from_date format. Use YYYY-MM-DD."
            )

    orders = q.order_by(AutoTradeOrder.created_at.desc()).limit(min(limit, 500)).all()
    return [AutoTradeOrderResponse.from_orm_dict(o).model_dump() for o in orders]


@router.get("/orders/{order_id}")
def get_order(
    order_id: int,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    o = get_or_404(db, AutoTradeOrder, order_id, "Order")
    return AutoTradeOrderResponse.from_orm_dict(o).model_dump()


@router.post("/orders/{order_id}/approve")
@limiter.limit(TRADING_LIMIT)
def approve_order_endpoint(
    request: Request,
    order_id: int,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Approve a pending_approval order."""
    o = get_or_404(db, AutoTradeOrder, order_id, "Order")
    if o.status != "pending_approval":
        raise HTTPException(
            status_code=409,
            detail=f"Order is not pending approval (current status: {o.status}).",
        )

    strategy = get_or_404(db, TradingStrategy, o.trading_strategy_id, "Strategy")

    result = approve_order(o, strategy, db)
    return AutoTradeOrderResponse.from_orm_dict(result).model_dump()


@router.post("/orders/{order_id}/reject")
@limiter.limit(TRADING_LIMIT)
def reject_order(
    request: Request,
    order_id: int,
    payload: Dict[str, Any] = {},
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Reject a pending_approval order without submitting it."""
    o = get_or_404(db, AutoTradeOrder, order_id, "Order")
    if o.status != "pending_approval":
        raise HTTPException(
            status_code=409,
            detail=f"Order is not pending approval (current status: {o.status}).",
        )

    o.status = "rejected"
    o.rejection_reason = payload.get("reason", "Manually rejected via UI")
    o.updated_at = utc_now()
    db.commit()
    db.refresh(o)
    logger.info(f"Rejected order id={o.id} reason='{o.rejection_reason}'")
    return AutoTradeOrderResponse.from_orm_dict(o).model_dump()


@router.post("/orders/{order_id}/cancel")
@limiter.limit(TRADING_LIMIT)
def cancel_order_endpoint(
    request: Request,
    order_id: int,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Cancel an active order."""
    o = get_or_404(db, AutoTradeOrder, order_id, "Order")

    cancellable = {"submitted", "open", "pending", "pending_approval"}
    if o.status not in cancellable:
        raise HTTPException(
            status_code=409,
            detail=f"Order cannot be cancelled (current status: {o.status}).",
        )

    try:
        result = cancel_order(o, db)
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    return AutoTradeOrderResponse.from_orm_dict(result).model_dump()


# ── Account Summary ──────────────────────────────────────────────────────────


@router.get("/account")
def get_account_endpoint(db: Session = Depends(get_db)) -> Dict[str, Any]:
    """Fetch live account summary from IBKR."""
    return get_account()


# ── Stats ────────────────────────────────────────────────────────────────────


@router.get("/stats")
def get_stats_endpoint(
    days: int = 30,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Return auto-trading statistics for the last N days."""
    return get_stats(db, days=days)


# ── Config ───────────────────────────────────────────────────────────────────


@router.get("/config")
def get_trading_config(db: Session = Depends(get_db)) -> Dict[str, Any]:
    """Return current auto-trading system config values."""
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


@router.patch("/config")
def update_trading_config(
    payload: Dict[str, Any],
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Update auto-trading system config (AUTO_TRADING_ENABLED, PAPER_ACCOUNT_SIZE)."""
    allowed = {"AUTO_TRADING_ENABLED", "PAPER_ACCOUNT_SIZE"}
    now = utc_now()

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
    return get_trading_config(db)
