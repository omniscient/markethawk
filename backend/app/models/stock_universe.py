"""
StockUniverse SQLAlchemy model.
"""

import uuid

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Column,
    DateTime,
    Integer,
    String,
    Text,
)
from sqlalchemy import Uuid as UUID

from app.core.database import Base
from app.utils.time import utc_now


class StockUniverse(Base):
    """Represents a collection of stocks grouped by defined criteria."""

    __tablename__ = "stock_universes"

    id = Column(Integer, primary_key=True, index=True)
    uuid = Column(UUID(as_uuid=True), default=uuid.uuid4, unique=True, index=True)
    name = Column(String(100), nullable=False)
    description = Column(Text)
    criteria = Column(JSON, nullable=False)
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(
        DateTime,
        default=utc_now,
        onupdate=utc_now,
    )
    is_active = Column(Boolean, default=True)

    # Cached aggregate stats — refreshed on demand via POST /{id}/refresh-stats
    cached_ticker_count = Column(Integer, nullable=True)
    cached_aggregate_count = Column(BigInteger, nullable=True)
    cached_min_date = Column(DateTime, nullable=True)
    cached_max_date = Column(DateTime, nullable=True)
    cached_timespans = Column(JSON, nullable=True)  # List[str]
    stats_refreshed_at = Column(DateTime, nullable=True)
