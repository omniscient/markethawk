"""
NewsArticle SQLAlchemy model.
"""

from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, JSON, Text, Uuid as UUID
import uuid

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
    tickers = Column(JSON, default=list)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
