"""
NewsPreference SQLAlchemy model.
"""

import uuid

from sqlalchemy import JSON, Column, DateTime, Integer
from sqlalchemy import Uuid as UUID

from app.core.database import Base
from app.utils.time import utc_now


class NewsPreference(Base):
    """Represents a global or user configuration for news fetching."""

    __tablename__ = "news_preferences"

    id = Column(Integer, primary_key=True, index=True)
    uuid = Column(UUID, default=uuid.uuid4, index=True, unique=True)

    # Filtering settings
    tracked_tickers = Column(
        JSON, default=list
    )  # List of strings e.g. ["AAPL", "NVDA"]
    tracked_universes = Column(JSON, default=list)  # List of universe IDs e.g. [1, 2]

    refresh_interval_minutes = Column(Integer, default=5)
    last_polled_at = Column(DateTime)

    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(
        DateTime,
        default=utc_now,
        onupdate=utc_now,
    )
