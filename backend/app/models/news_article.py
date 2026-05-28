"""
NewsArticle SQLAlchemy model.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, Column, DateTime, Integer, String, Text
from sqlalchemy import Uuid as UUID
from sqlalchemy.dialects.postgresql import JSONB

from app.core.database import Base


class NewsArticle(Base):
    """Represents a news article fetched from a data provider."""

    __tablename__ = "news_articles"

    id = Column(Integer, primary_key=True, index=True)
    uuid = Column(UUID(as_uuid=True), default=uuid.uuid4, unique=True, index=True)
    title = Column(String(500), nullable=False)
    author = Column(String(200))
    published_utc = Column(DateTime, nullable=False, index=True)
    article_url = Column(String(1000), nullable=False, unique=True)
    image_url = Column(String(1000))
    description = Column(Text)
    provider = Column(String(100))
    # JSON list of ticker strings that this article is about
    # Using JSONB for Postgres to support indexed contains() checks
    tickers = Column(JSON().with_variant(JSONB, "postgresql"), default=list)
    created_at = Column(
        DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None)
    )
    updated_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc).replace(tzinfo=None),
        onupdate=lambda: datetime.now(timezone.utc).replace(tzinfo=None),
    )
