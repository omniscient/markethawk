"""
StockUniverse SQLAlchemy model.
"""

from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, Boolean, JSON, Text
from sqlalchemy.dialects.postgresql import UUID
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
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    is_active = Column(Boolean, default=True)
