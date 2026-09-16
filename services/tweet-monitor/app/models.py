"""
Local SQLAlchemy model definitions for the tweet-monitor service.

These mirror the models in backend/app/models/ — the main backend's Alembic
owns the migration. The tweet-monitor service connects to the same DB and
defines its own Table bindings for writes.
"""
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean, Column, DateTime, Float, ForeignKey, Index, Integer,
    String, Text, UniqueConstraint
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


class MonitoredAccount(Base):
    __tablename__ = "monitored_accounts"

    id = Column(Integer, primary_key=True)
    handle = Column(String(50), nullable=False)
    display_name = Column(String(100), nullable=False)
    platform = Column(String(20), nullable=False, default="x")
    poll_interval_seconds = Column(Integer, nullable=False, default=45)
    enabled = Column(Boolean, nullable=False, default=True)
    classification_config = Column(JSONB, nullable=False, default=dict)
    last_poll_at = Column(DateTime, nullable=True)
    last_tweet_id = Column(String(30), nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None),
                        onupdate=lambda: datetime.now(timezone.utc).replace(tzinfo=None))

    tweet_signals = relationship("TweetSignal", back_populates="account", cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint("handle", "platform", name="uq_monitored_account_handle_platform"),
    )


class TweetSignal(Base):
    __tablename__ = "tweet_signals"

    id = Column(Integer, primary_key=True)
    account_id = Column(Integer, ForeignKey("monitored_accounts.id"), nullable=False)
    tweet_id = Column(String(30), nullable=False, unique=True)
    tweet_url = Column(String(200), nullable=False)
    posted_at = Column(DateTime, nullable=False)
    scraped_at = Column(DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None))

    full_text = Column(Text, nullable=False)
    media_urls = Column(JSONB, nullable=False, default=list)

    classification = Column(String(20), nullable=False)
    confidence = Column(Float, nullable=False)

    tickers = Column(JSONB, nullable=False, default=list)
    price_levels = Column(JSONB, nullable=False, default=dict)
    direction = Column(String(10), nullable=True)

    promoted = Column(Boolean, nullable=False, default=False)
    scanner_event_id = Column(Integer, ForeignKey("scanner_events.id"), nullable=True)
    promotion_reason = Column(String(30), nullable=True)

    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None))

    account = relationship("MonitoredAccount", back_populates="tweet_signals")

    __table_args__ = (
        Index("ix_tweet_signals_account_posted", "account_id", "posted_at"),
        Index("ix_tweet_signals_classification_confidence", "classification", "confidence"),
        Index("ix_tweet_signals_promoted_classification", "promoted", "classification"),
    )


class ScannerEvent(Base):
    """Minimal binding — tweet-monitor only writes to scanner_events, never reads structure."""
    __tablename__ = "scanner_events"

    id = Column(Integer, primary_key=True)
    uuid = Column(String(36))
    ticker = Column(String(10))
    event_date = Column(DateTime)
    scanner_type = Column(String(50))
    summary = Column(String(500))
    severity = Column(String(10))
    previous_close = Column(Float, nullable=True)
    opening_price = Column(Float, nullable=True)
    closing_price = Column(Float, nullable=True)
    indicators = Column(JSONB, default=dict)
    criteria_met = Column(JSONB, default=dict)
    metadata_ = Column("metadata", JSONB, default=dict)
    explanation = Column(JSONB, nullable=True)
    signal_quality_score = Column(Float, nullable=True)
    created_at = Column(DateTime)
    updated_at = Column(DateTime)
