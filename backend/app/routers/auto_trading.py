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
from datetime import datetime, timezone, date as date_type, timedelta
from decimal import Decimal
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.core.config import settings
from app.core.database import get_db
from app.models.auto_trade_order import AutoTradeOrder
from app.models.system_config import SystemConfig
from app.models.trading_strategy import TradingStrategy
from app.models.trade import Trade

router = APIRouter(prefix="/api/trading", tags=["auto-trading"])
logger = logging.getLogger(__name__)


# ── Serialisers ──────────────────────────────────────────────────────────────

def _strategy_to_dict(s: TradingStrategy) -> Dict[str, Any]:
    return {
        "id": s.id,
        "name": s.name,
        "description": s.description,
        "is_active": s.is_active,
        "paper_mode": s.paper_mode,
        "requires_approval": s.requires_approval,
        "risk_per_trade_pct": float(s.risk_per_trade_pct) if s.risk_per_trade_pct is not None else None,
        "max_position_usd": float(s.max_position_usd) if s.max_position_usd is not None else None,
        "max_trades_per_day": s.max_trades_per_day,
        "max_concurrent_positions": s.max_concurrent_positions,
        "entry_type": s.entry_type,
        "limit_offset_pct": float(s.limit_offset_pct) if s.limit_offset_pct is not None else 0.0,
        "stop_pct": float(s.stop_pct) if s.stop_pct is not None else None,
        "risk_reward_ratio": float(s.risk_reward_ratio) if s.risk_reward_ratio is not None else None,
        "max_slippage_pct": float(s.max_slippage_pct) if s.max_slippage_pct is not None else None,
        "allowed_sessions": s.allowed_sessions or ["regular"],
        "direction": s.direction,
        "created_at": s.created_at.isoformat() if s.created_at else None,
        "updated_at": s.updated_at.isoformat() if s.updated_at else None,
    }


def _order_to_dict(o: AutoTradeOrder) -> Dict[str, Any]:
    return {
        "id": o.id,
        "alert_rule_id": o.alert_rule_id,
        "scanner_event_id": o.scanner_event_id,
        "trading_strategy_id": o.trading_strategy_id,
        "symbol": o.symbol,
        "side": o.side,
        "event_date": o.event_date.isoformat() if o.event_date else None,
        "status": o.status,
        "rejection_reason": o.rejection_reason,
        "trigger_price": float(o.trigger_price) if o.trigger_price is not None else None,
        "entry_price_target": float(o.entry_price_target) if o.entry_price_target is not None else None,
        "calculated_stop": float(o.calculated_stop) if o.calculated_stop is not None else None,
        "calculated_target": float(o.calculated_target) if o.calculated_target is not None else None,
        "quantity": o.quantity,
        "risk_amount_usd": float(o.risk_amount_usd) if o.risk_amount_usd is not None else None,
        "is_paper": o.is_paper,
        "broker_order_id": o.broker_order_id,
        "broker_stop_id": o.broker_stop_id,
        "broker_target_id": o.broker_target_id,
        "fill_price": float(o.fill_price) if o.fill_price is not None else None,
        "filled_at": o.filled_at.isoformat() if o.filled_at else None,
        "exit_price": float(o.exit_price) if o.exit_price is not None else None,
        "exited_at": o.exited_at.isoformat() if o.exited_at else None,
        "exit_reason": o.exit_reason,
        "trade_id": o.trade_id,
        "created_at": o.created_at.isoformat() if o.created_at else None,
        "updated_at": o.updated_at.isoformat() if o.updated_at else None,
    }


# ── Trading Strategies — CRUD ────────────────────────────────────────────────

_STRATEGY_UPDATABLE = {
    "name", "description", "is_active", "paper_mode", "requires_approval",
    "risk_per_trade_pct", "max_position_usd", "max_trades_per_day",
    "max_concurrent_positions", "entry_type", "limit_offset_pct",
    "stop_pct", "risk_reward_ratio", "max_slippage_pct",
    "allowed_sessions", "direction",
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
    return [_strategy_to_dict(s) for s in strategies]


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
    db.add(strategy)
    db.commit()
    db.refresh(strategy)
    logger.info(f"Created trading strategy id={strategy.id} name='{strategy.name}'")
    return _strategy_to_dict(strategy)


@router.get("/strategies/{strategy_id}")
def get_strategy(
    strategy_id: int,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    s = db.query(TradingStrategy).filter(TradingStrategy.id == strategy_id).first()
    if not s:
        raise HTTPException(status_code=404, detail="Strategy not found.")
    return _strategy_to_dict(s)


@router.patch("/strategies/{strategy_id}")
def update_strategy(
    strategy_id: int,
    payload: Dict[str, Any],
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Partial update of a trading strategy."""
    s = db.query(TradingStrategy).filter(TradingStrategy.id == strategy_id).first()
    if not s:
        raise HTTPException(status_code=404, detail="Strategy not found.")

    for key, value in payload.items():
        if key in _STRATEGY_UPDATABLE:
            setattr(s, key, value)

    s.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
    db.commit()
    db.refresh(s)
    return _strategy_to_dict(s)


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
    s = db.query(TradingStrategy).filter(TradingStrategy.id == strategy_id).first()
    if not s:
        raise HTTPException(status_code=404, detail="Strategy not found.")

    # Refuse to delete if there are open orders on this strategy
    open_orders = (
        db.query(AutoTradeOrder)
        .filter(
            AutoTradeOrder.trading_strategy_id == strategy_id,
            AutoTradeOrder.status.in_(["submitted", "open", "pending", "pending_approval"]),
        )
        .count()
    )
    if open_orders > 0:
        raise HTTPException(
            status_code=409,
            detail=f"Cannot delete strategy with {open_orders} open order(s). Close them first.",
        )

    s.is_active = False
    s.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
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
            raise HTTPException(status_code=422, detail="Invalid from_date format. Use YYYY-MM-DD.")

    orders = (
        q.order_by(AutoTradeOrder.created_at.desc())
        .limit(min(limit, 500))
        .all()
    )
    return [_order_to_dict(o) for o in orders]


@router.get("/orders/{order_id}")
def get_order(
    order_id: int,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    o = db.query(AutoTradeOrder).filter(AutoTradeOrder.id == order_id).first()
    if not o:
        raise HTTPException(status_code=404, detail="Order not found.")
    return _order_to_dict(o)


@router.post("/orders/{order_id}/approve")
def approve_order(
    order_id: int,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """
    Approve a pending_approval order.

    Moves the order to 'pending' then immediately submits it to IBKR
    (or marks as submitted for paper orders).
    """
    o = db.query(AutoTradeOrder).filter(AutoTradeOrder.id == order_id).first()
    if not o:
        raise HTTPException(status_code=404, detail="Order not found.")
    if o.status != "pending_approval":
        raise HTTPException(
            status_code=409,
            detail=f"Order is not pending approval (current status: {o.status}).",
        )

    # Fetch strategy to decide paper vs live
    strategy = db.query(TradingStrategy).filter(
        TradingStrategy.id == o.trading_strategy_id
    ).first()
    if not strategy:
        raise HTTPException(status_code=404, detail="Strategy not found.")

    if strategy.paper_mode:
        o.status = "submitted"
        o.broker_order_id = f"PAPER-{o.id}"
        o.broker_stop_id = f"PAPER-STOP-{o.id}"
        o.broker_target_id = f"PAPER-TGT-{o.id}"
        db.commit()
        logger.info(f"Approved paper order id={o.id}")
    else:
        # Queue IBKR submission via Celery to avoid blocking the HTTP request.
        # We submit the existing order directly — do NOT re-queue execute_auto_trade,
        # which would hit the idempotency guard and silently skip.
        from app.core.celery_app import celery_app as _celery

        o.status = "pending"
        db.commit()

        _celery.send_task(
            "app.tasks.submit_approved_order",
            kwargs={"order_id": o.id},
        )
        logger.info(f"Approved live order id={o.id}, queued for IBKR submission")

    db.refresh(o)
    return _order_to_dict(o)


@router.post("/orders/{order_id}/reject")
def reject_order(
    order_id: int,
    payload: Dict[str, Any] = {},
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Reject a pending_approval order without submitting it."""
    o = db.query(AutoTradeOrder).filter(AutoTradeOrder.id == order_id).first()
    if not o:
        raise HTTPException(status_code=404, detail="Order not found.")
    if o.status != "pending_approval":
        raise HTTPException(
            status_code=409,
            detail=f"Order is not pending approval (current status: {o.status}).",
        )

    o.status = "rejected"
    o.rejection_reason = payload.get("reason", "Manually rejected via UI")
    o.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
    db.commit()
    db.refresh(o)
    logger.info(f"Rejected order id={o.id} reason='{o.rejection_reason}'")
    return _order_to_dict(o)


@router.post("/orders/{order_id}/cancel")
def cancel_order(
    order_id: int,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """
    Cancel an active order.

    For paper orders: immediately sets status=cancelled.
    For live orders: sends cancel to IBKR and sets status=cancelled.
    """
    o = db.query(AutoTradeOrder).filter(AutoTradeOrder.id == order_id).first()
    if not o:
        raise HTTPException(status_code=404, detail="Order not found.")

    cancellable = {"submitted", "open", "pending", "pending_approval"}
    if o.status not in cancellable:
        raise HTTPException(
            status_code=409,
            detail=f"Order cannot be cancelled (current status: {o.status}).",
        )

    if not o.is_paper and o.broker_order_id and o.status in ("submitted", "open"):
        # Live cancel via IBKR
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            from app.providers.ibkr_orders import IBKROrderManager
            manager = IBKROrderManager()
            loop.run_until_complete(
                manager.cancel_bracket(
                    parent_order_id=int(o.broker_order_id),
                    stop_order_id=int(o.broker_stop_id or 0),
                    target_order_id=int(o.broker_target_id or 0),
                )
            )
        except Exception as exc:
            logger.error(f"IBKR cancel failed for order {o.id}: {exc}")
            raise HTTPException(status_code=502, detail=f"IBKR cancel failed: {exc}")
        finally:
            loop.close()

    o.status = "cancelled"
    o.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
    db.commit()
    db.refresh(o)
    logger.info(f"Cancelled order id={o.id}")
    return _order_to_dict(o)


# ── Account Summary ──────────────────────────────────────────────────────────

@router.get("/account")
def get_account(db: Session = Depends(get_db)) -> Dict[str, Any]:
    """
    Fetch live account summary from IBKR.

    Returns net_liquidation, available_funds, buying_power plus a list of
    current open AutoTradeOrders that are in the 'open' state.
    """
    try:
        from app.providers.ibkr_orders import IBKROrderManager
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            manager = IBKROrderManager()
            account = loop.run_until_complete(manager.get_account_summary())
            open_broker_orders = loop.run_until_complete(manager.get_open_orders())
        finally:
            loop.close()

        return {
            "net_liquidation": account.net_liquidation,
            "available_funds": account.available_funds,
            "buying_power": account.buying_power,
            "currency": account.currency,
            "connected": True,
            "open_broker_orders": [
                {
                    "order_id": o.order_id,
                    "symbol": o.symbol,
                    "action": o.action,
                    "order_type": o.order_type,
                    "quantity": o.total_qty,
                    "status": o.status,
                    "filled": o.filled,
                    "avg_fill_price": o.avg_fill_price,
                }
                for o in open_broker_orders
            ],
        }
    except Exception as exc:
        logger.warning(f"get_account: IBKR unavailable: {exc}")
        return {
            "net_liquidation": None,
            "available_funds": None,
            "buying_power": None,
            "currency": "USD",
            "connected": False,
            "error": str(exc),
            "open_broker_orders": [],
        }


# ── Stats ────────────────────────────────────────────────────────────────────

@router.get("/stats")
def get_stats(
    days: int = 30,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """
    Return auto-trading statistics for the last N days.

    Counts by status, total risk deployed, closed P&L, win rate.
    """
    since = date_type.today() - timedelta(days=days)
    orders = (
        db.query(AutoTradeOrder)
        .filter(AutoTradeOrder.event_date >= since)
        .all()
    )

    total = len(orders)
    by_status: Dict[str, int] = {}
    for o in orders:
        by_status[o.status] = by_status.get(o.status, 0) + 1

    closed = [o for o in orders if o.status == "closed"]
    wins   = [o for o in closed if o.exit_price and o.fill_price and (
        (o.side == "long"  and float(o.exit_price) > float(o.fill_price)) or
        (o.side == "short" and float(o.exit_price) < float(o.fill_price))
    )]

    # P&L from linked Trade records
    trade_ids = [o.trade_id for o in closed if o.trade_id]
    total_pnl = 0.0
    if trade_ids:
        trades = db.query(Trade).filter(Trade.id.in_(trade_ids)).all()
        total_pnl = sum(float(t.gross_pnl or 0) for t in trades)

    return {
        "period_days": days,
        "total_orders": total,
        "by_status": by_status,
        "closed_count": len(closed),
        "win_count": len(wins),
        "win_rate": round(len(wins) / len(closed) * 100, 1) if closed else None,
        "total_pnl": round(total_pnl, 2),
        "avg_pnl_per_trade": round(total_pnl / len(closed), 2) if closed else None,
    }


# ── Config ───────────────────────────────────────────────────────────────────

@router.get("/config")
def get_trading_config(db: Session = Depends(get_db)) -> Dict[str, Any]:
    """Return current auto-trading system config values."""
    keys = ["AUTO_TRADING_ENABLED", "PAPER_ACCOUNT_SIZE"]
    result: Dict[str, Any] = {"AUTO_TRADING_ENABLED": False, "PAPER_ACCOUNT_SIZE": 100000}
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
    """
    Update auto-trading system config.

    Accepted keys:
      - AUTO_TRADING_ENABLED (bool)
      - PAPER_ACCOUNT_SIZE   (float)
    """
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
    return get_trading_config(db)
