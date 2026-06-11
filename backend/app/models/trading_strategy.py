"""
TradingStrategy model — defines how auto-trades are sized, entered, and exited.

Decoupled from AlertRule so the same strategy can be reused across many rules,
and R:R / sizing tweaks apply everywhere without touching alert configuration.
"""

from sqlalchemy import Boolean, Column, DateTime, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship

from app.core.database import Base
from app.utils.time import utc_now


class TradingStrategy(Base):
    """
    Defines risk/reward parameters for automated trade execution.

    One strategy can be referenced by many AlertRules.  When an alert fires
    on a rule that has auto_trade=True, the linked strategy controls:
      - How much capital to risk per trade
      - Where to place the stop-loss and take-profit
      - Whether to use a market or limit entry
      - Which sessions are eligible for trading
    """

    __tablename__ = "trading_strategies"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(200), nullable=False, unique=True)
    description = Column(Text, nullable=True)

    # ── Lifecycle flags ──────────────────────────────────────────────────
    is_active = Column(Boolean, default=True, nullable=False)

    # paper_mode=True: full decision logic runs but NO real orders are sent
    # to IBKR. Flip to False only when you want live execution.
    paper_mode = Column(Boolean, default=True, nullable=False)

    # requires_approval=True: AutoTradeOrder is created with
    # status="pending_approval" and waits for manual UI approval before
    # being submitted to the broker.
    requires_approval = Column(Boolean, default=False, nullable=False)

    # ── Risk / sizing ────────────────────────────────────────────────────
    # Percentage of account net liquidation to risk on this trade.
    # e.g. 1.0 = risk 1 % of account on each trade
    risk_per_trade_pct = Column(Numeric, default=1.0, nullable=False)

    # Hard cap on position notional value in USD (overrides pct sizing when hit)
    max_position_usd = Column(Numeric, nullable=True)

    # Safety limits
    max_trades_per_day = Column(Integer, default=3, nullable=False)
    max_concurrent_positions = Column(Integer, default=2, nullable=False)

    # ── Entry ────────────────────────────────────────────────────────────
    # "market" → MKT order at alert time
    # "limit"  → LMT order at (trigger_price * (1 ± limit_offset_pct/100))
    entry_type = Column(String(20), default="market", nullable=False)

    # For limit entries: % offset from trigger price.
    # Positive = buy above trigger (chase); negative = buy below (wait for pull-back)
    limit_offset_pct = Column(Numeric, default=0.0, nullable=False)

    # ── Stop & target ────────────────────────────────────────────────────
    # Stop-loss distance from entry as a percentage.
    # e.g. 2.0 = stop placed 2 % below entry (long) / 2 % above entry (short)
    stop_pct = Column(Numeric, default=2.0, nullable=False)

    # Target = entry + (stop_distance_dollars * risk_reward_ratio)
    # e.g. 2.0 with stop_pct=2 → target is 4 % from entry  →  2:1 R:R
    risk_reward_ratio = Column(Numeric, default=2.0, nullable=False)

    # Abort an order if the actual fill price deviates more than this %
    # from the trigger price (protects against gap fills on market orders)
    max_slippage_pct = Column(Numeric, default=0.5, nullable=False)

    # ── Eligibility ──────────────────────────────────────────────────────
    # Which sessions this strategy may trade in.
    # Valid values: "pre", "regular", "post"
    allowed_sessions = Column(JSONB, nullable=False, default=lambda: ["regular"])

    # Trade direction: "long_only" | "short_only" | "both"
    direction = Column(String(20), default="long_only", nullable=False)

    # ── Relationships ────────────────────────────────────────────────────
    alert_rules = relationship("AlertRule", back_populates="trading_strategy")
    auto_trade_orders = relationship(
        "AutoTradeOrder", back_populates="trading_strategy"
    )

    created_at = Column(
        DateTime,
        default=utc_now,
    )
    updated_at = Column(
        DateTime,
        default=utc_now,
        onupdate=utc_now,
    )
