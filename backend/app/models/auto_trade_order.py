"""
AutoTradeOrder model — immutable audit record for every automated trade decision.

One record is created the moment the system decides to trade on an alert.
It tracks the full lifecycle: decision → submission → fill → exit.
"""

from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from app.core.database import Base

# ── Status enum values (stored as strings) ───────────────────────────────────
#
#  pending_approval  — created but waiting for human approval (requires_approval=True)
#  pending           — approved / auto-approved, queued for IBKR submission
#  submitted         — bracket order sent to IBKR, awaiting fill confirmation
#  open              — entry order filled; stop + target are live in the market
#  closed            — position exited (stop hit, target hit, or manual close)
#  cancelled         — cancelled before fill (by user or system)
#  rejected          — IBKR rejected the order (insufficient margin, outside hours, etc.)
#  error             — unexpected exception during placement
# ─────────────────────────────────────────────────────────────────────────────


class AutoTradeOrder(Base):
    """
    Represents a single automated trade decision triggered by an alert rule.

    Created synchronously when evaluate_scanner_alerts fires; never mutated
    in ways that would destroy audit history (new columns, never deleted rows).
    """

    __tablename__ = "auto_trade_orders"

    __table_args__ = (
        # One auto-trade attempt per symbol / strategy / calendar day.
        # Prevents duplicate entries when the same alert fires multiple times
        # or when multiple matching rules share the same strategy.
        UniqueConstraint(
            "symbol",
            "trading_strategy_id",
            "event_date",
            name="uq_auto_trade_symbol_strategy_date",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)

    # ── Source linkage ───────────────────────────────────────────────────
    alert_rule_id = Column(
        Integer,
        ForeignKey("alert_rules.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    scanner_event_id = Column(
        Integer,
        ForeignKey("scanner_events.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    trading_strategy_id = Column(
        Integer,
        ForeignKey("trading_strategies.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # ── Identity ─────────────────────────────────────────────────────────
    symbol = Column(String(10), nullable=False, index=True)
    side = Column(String(10), nullable=False)  # "long" | "short"
    event_date = Column(Date, nullable=False, index=True)  # used in unique constraint

    # ── Status ───────────────────────────────────────────────────────────
    status = Column(String(30), nullable=False, default="pending", index=True)
    rejection_reason = Column(Text, nullable=True)  # why the order was blocked/rejected

    # ── Decision snapshot (calculated at alert time, never changed) ──────
    trigger_price = Column(
        Numeric, nullable=True
    )  # price in event.indicators at alert moment
    entry_price_target = Column(
        Numeric, nullable=True
    )  # trigger adjusted for limit_offset_pct
    calculated_stop = Column(Numeric, nullable=True)
    calculated_target = Column(Numeric, nullable=True)
    quantity = Column(Integer, nullable=True)
    risk_amount_usd = Column(Numeric, nullable=True)

    # paper_mode snapshot: True if strategy was in paper mode when order was created
    is_paper = Column(Boolean, default=True, nullable=False)

    # ── Broker state (filled in as IBKR responds) ────────────────────────
    broker_order_id = Column(String(50), nullable=True)  # parent/entry order ID
    broker_stop_id = Column(String(50), nullable=True)  # stop-loss child order ID
    broker_target_id = Column(String(50), nullable=True)  # take-profit child order ID

    fill_price = Column(Numeric, nullable=True)
    filled_at = Column(DateTime, nullable=True)

    exit_price = Column(Numeric, nullable=True)
    exited_at = Column(DateTime, nullable=True)
    exit_reason = Column(String(30), nullable=True)  # "stop" | "target" | "manual"

    # ── Journal link ─────────────────────────────────────────────────────
    # Populated once the entry fill is confirmed; points to the Trade record
    # created automatically in the journal so PnL is tracked in one place.
    trade_id = Column(
        Integer, ForeignKey("trades.id", ondelete="SET NULL"), nullable=True, index=True
    )

    # ── Relationships ────────────────────────────────────────────────────
    trading_strategy = relationship(
        "TradingStrategy", back_populates="auto_trade_orders"
    )
    trade = relationship("Trade")

    created_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc).replace(tzinfo=None),
    )
    updated_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc).replace(tzinfo=None),
        onupdate=lambda: datetime.now(timezone.utc).replace(tzinfo=None),
    )
