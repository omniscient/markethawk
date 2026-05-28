"""Pydantic response models for auto-trading, replacing ad-hoc serialiser dicts."""

from datetime import datetime, date
from decimal import Decimal
from typing import Any, List, Optional

from pydantic import BaseModel, ConfigDict


class TradingStrategyResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    description: Optional[str] = None
    is_active: bool
    paper_mode: bool
    requires_approval: bool
    risk_per_trade_pct: Optional[float] = None
    max_position_usd: Optional[float] = None
    max_trades_per_day: int
    max_concurrent_positions: int
    entry_type: Optional[str] = None
    limit_offset_pct: float = 0.0
    stop_pct: Optional[float] = None
    risk_reward_ratio: Optional[float] = None
    max_slippage_pct: Optional[float] = None
    allowed_sessions: List[str] = ["regular"]
    direction: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    @classmethod
    def from_orm_dict(cls, s: Any) -> "TradingStrategyResponse":
        return cls(
            id=s.id,
            name=s.name,
            description=s.description,
            is_active=s.is_active,
            paper_mode=s.paper_mode,
            requires_approval=s.requires_approval,
            risk_per_trade_pct=float(s.risk_per_trade_pct) if s.risk_per_trade_pct is not None else None,
            max_position_usd=float(s.max_position_usd) if s.max_position_usd is not None else None,
            max_trades_per_day=s.max_trades_per_day,
            max_concurrent_positions=s.max_concurrent_positions,
            entry_type=s.entry_type,
            limit_offset_pct=float(s.limit_offset_pct) if s.limit_offset_pct is not None else 0.0,
            stop_pct=float(s.stop_pct) if s.stop_pct is not None else None,
            risk_reward_ratio=float(s.risk_reward_ratio) if s.risk_reward_ratio is not None else None,
            max_slippage_pct=float(s.max_slippage_pct) if s.max_slippage_pct is not None else None,
            allowed_sessions=s.allowed_sessions or ["regular"],
            direction=s.direction,
            created_at=s.created_at,
            updated_at=s.updated_at,
        )


class AutoTradeOrderResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    alert_rule_id: Optional[int] = None
    scanner_event_id: Optional[int] = None
    trading_strategy_id: Optional[int] = None
    symbol: str
    side: str
    event_date: Optional[date] = None
    status: str
    rejection_reason: Optional[str] = None
    trigger_price: Optional[float] = None
    entry_price_target: Optional[float] = None
    calculated_stop: Optional[float] = None
    calculated_target: Optional[float] = None
    quantity: Optional[int] = None
    risk_amount_usd: Optional[float] = None
    is_paper: bool
    broker_order_id: Optional[str] = None
    broker_stop_id: Optional[str] = None
    broker_target_id: Optional[str] = None
    fill_price: Optional[float] = None
    filled_at: Optional[datetime] = None
    exit_price: Optional[float] = None
    exited_at: Optional[datetime] = None
    exit_reason: Optional[str] = None
    trade_id: Optional[int] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    @classmethod
    def from_orm_dict(cls, o: Any) -> "AutoTradeOrderResponse":
        return cls(
            id=o.id,
            alert_rule_id=o.alert_rule_id,
            scanner_event_id=o.scanner_event_id,
            trading_strategy_id=o.trading_strategy_id,
            symbol=o.symbol,
            side=o.side,
            event_date=o.event_date,
            status=o.status,
            rejection_reason=o.rejection_reason,
            trigger_price=float(o.trigger_price) if o.trigger_price is not None else None,
            entry_price_target=float(o.entry_price_target) if o.entry_price_target is not None else None,
            calculated_stop=float(o.calculated_stop) if o.calculated_stop is not None else None,
            calculated_target=float(o.calculated_target) if o.calculated_target is not None else None,
            quantity=o.quantity,
            risk_amount_usd=float(o.risk_amount_usd) if o.risk_amount_usd is not None else None,
            is_paper=o.is_paper,
            broker_order_id=o.broker_order_id,
            broker_stop_id=o.broker_stop_id,
            broker_target_id=o.broker_target_id,
            fill_price=float(o.fill_price) if o.fill_price is not None else None,
            filled_at=o.filled_at,
            exit_price=float(o.exit_price) if o.exit_price is not None else None,
            exited_at=o.exited_at,
            exit_reason=o.exit_reason,
            trade_id=o.trade_id,
            created_at=o.created_at,
            updated_at=o.updated_at,
        )
