"""
StockUniverse SQLAlchemy model.
"""

from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, DateTime, Boolean, JSON, Text, Uuid as UUID
import uuid

from app.core.database import Base


class StockUniverse(Base):
    """Represents a collection of stocks grouped by defined criteria."""
    
    __tablename__ = "stock_universes"
    
    id = Column(Integer, primary_key=True, index=True)
    uuid = Column(UUID(as_uuid=True), default=uuid.uuid4, unique=True, index=True)
    name = Column(String(100), nullable=False)
    description = Column(Text)
    criteria = Column(JSON, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None), onupdate=lambda: datetime.now(timezone.utc).replace(tzinfo=None))
    is_active = Column(Boolean, default=True)
