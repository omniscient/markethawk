from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship

from app.core.database import Base
from app.utils.time import utc_now


class TweetSignal(Base):
    __tablename__ = "tweet_signals"

    id = Column(Integer, primary_key=True, index=True)
    account_id = Column(
        Integer, ForeignKey("monitored_accounts.id"), nullable=False, index=True
    )
    tweet_id = Column(String(30), nullable=False, unique=True, index=True)
    tweet_url = Column(String(200), nullable=False)
    posted_at = Column(DateTime, nullable=False)
    scraped_at = Column(DateTime, default=utc_now)

    # Content
    full_text = Column(Text, nullable=False)
    media_urls = Column(JSONB, nullable=False, default=list)

    # Classification
    classification = Column(
        String(20), nullable=False
    )  # CALLOUT|CELEBRATION|UPDATE|RETWEET|UNKNOWN
    confidence = Column(Float, nullable=False)

    # Extraction
    tickers = Column(JSONB, nullable=False, default=list)
    price_levels = Column(JSONB, nullable=False, default=dict)
    direction = Column(String(10), nullable=True)  # long|short|None

    # Pipeline
    promoted = Column(Boolean, nullable=False, default=False)
    scanner_event_id = Column(Integer, ForeignKey("scanner_events.id"), nullable=True)
    promotion_reason = Column(String(30), nullable=True)

    created_at = Column(DateTime, default=utc_now)

    account = relationship("MonitoredAccount", back_populates="tweet_signals")
    scanner_event = relationship("ScannerEvent", foreign_keys=[scanner_event_id])

    __table_args__ = (
        Index("ix_tweet_signals_account_posted", "account_id", "posted_at"),
        Index(
            "ix_tweet_signals_classification_confidence", "classification", "confidence"
        ),
        Index("ix_tweet_signals_promoted_classification", "promoted", "classification"),
    )
