"""
AlertRule model — user-defined alert rules for scanner events.
"""

from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, Boolean, DateTime
from sqlalchemy.dialects.postgresql import JSONB

from app.core.database import Base


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

    created_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc).replace(tzinfo=None),
    )
    updated_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc).replace(tzinfo=None),
        onupdate=lambda: datetime.now(timezone.utc).replace(tzinfo=None),
    )
