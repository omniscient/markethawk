from sqlalchemy import Boolean, Column, DateTime, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship

from app.core.database import Base
from app.utils.time import utc_now


class MonitoredAccount(Base):
    __tablename__ = "monitored_accounts"

    id = Column(Integer, primary_key=True, index=True)
    handle = Column(String(50), nullable=False)
    display_name = Column(String(100), nullable=False)
    platform = Column(String(20), nullable=False, default="x")
    poll_interval_seconds = Column(Integer, nullable=False, default=45)
    enabled = Column(Boolean, nullable=False, default=True)
    classification_config = Column(JSONB, nullable=False, default=dict)
    last_poll_at = Column(DateTime, nullable=True)
    last_tweet_id = Column(String(30), nullable=True)
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(
        DateTime,
        default=utc_now,
        onupdate=utc_now,
    )

    tweet_signals = relationship(
        "TweetSignal", back_populates="account", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint(
            "handle", "platform", name="uq_monitored_account_handle_platform"
        ),
    )
