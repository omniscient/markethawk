"""
AlertDeliveryLog model — immutable audit trail for every notification attempt.
"""

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text

from app.core.database import Base
from app.utils.time import utc_now


class AlertDeliveryLog(Base):
    """One row per notification attempt (success or failure)."""

    __tablename__ = "alert_delivery_logs"

    id = Column(Integer, primary_key=True, index=True)

    rule_id = Column(
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

    ticker = Column(String(10), nullable=True, index=True)
    scanner_type = Column(String(50), nullable=True)
    channel = Column(
        String(30), nullable=False
    )  # browser_push, email, google_chat, webhook

    # "sent" or "failed"
    status = Column(String(10), nullable=False, default="sent")
    error_message = Column(Text, nullable=True)

    delivered_at = Column(
        DateTime,
        default=utc_now,
        nullable=False,
    )
