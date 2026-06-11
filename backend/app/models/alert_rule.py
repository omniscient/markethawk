"""
AlertRule model — user-defined alert rules for scanner events.
"""

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship

from app.core.database import Base
from app.utils.time import utc_now


class AlertRule(Base):
    """A user-defined rule that triggers notifications when scanner events match."""

    __tablename__ = "alert_rules"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(200), nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)

    # Filter: which scanner types trigger this rule (empty list = all types)
    # e.g. ["pre_market_volume_spike", "oversold_bounce", "liquidity_hunt"]
    scanner_types = Column(JSONB, nullable=False, default=list)

    # Filter: "any", "high", "medium", "low"
    severity_filter = Column(String(10), nullable=False, default="any")

    # Minimum cooldown between repeat alerts for same ticker+rule (minutes)
    cooldown_minutes = Column(Integer, nullable=False, default=60)

    # Delivery channels: list of enabled channel names
    # Valid values: "browser_push", "email", "google_chat", "webhook"
    channels = Column(JSONB, nullable=False, default=list)

    # Per-channel configuration (JSONB)
    # {
    #   "email": "user@example.com",
    #   "google_chat_webhook": "https://chat.googleapis.com/...",
    #   "webhook_url": "https://hooks.example.com/..."
    # }
    channel_config = Column(JSONB, nullable=False, default=dict)

    # ── Auto-trading ─────────────────────────────────────────────────────
    # When True, matching scanner events automatically trigger trade execution
    # via the linked TradingStrategy (if set).
    auto_trade = Column(Boolean, default=False, nullable=False)

    # FK to the TradingStrategy that governs sizing/entry/exit for auto-trades.
    # NULL means no automatic trading even if auto_trade=True.
    trading_strategy_id = Column(
        Integer,
        ForeignKey("trading_strategies.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # Relationship back to the strategy (lazy-loaded, no cascade)
    trading_strategy = relationship("TradingStrategy", back_populates="alert_rules")

    created_at = Column(
        DateTime,
        default=utc_now,
    )
    updated_at = Column(
        DateTime,
        default=utc_now,
        onupdate=utc_now,
    )
