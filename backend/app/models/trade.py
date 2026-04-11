"""
Trade Journaling SQLAlchemy models.
"""

from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, DateTime, Numeric, Text, ForeignKey, Table, Date
from sqlalchemy.orm import relationship
import uuid
from sqlalchemy.dialects.postgresql import UUID

from app.core.database import Base

# Junction table for Trade <-> Tag many-to-many relationship
trade_tags = Table(
    "trade_tags",
    Base.metadata,
    Column("trade_id", Integer, ForeignKey("trades.id", ondelete="CASCADE"), primary_key=True),
    Column("tag_id", Integer, ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True),
)

class Tag(Base):
    """Represents a custom tag for categorizing trades."""
    __tablename__ = "tags"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(50), unique=True, nullable=False, index=True)
    color = Column(String(20)) # Hex code for UI
    
    def __repr__(self):
        return f"<Tag(name='{self.name}')>"

class Trade(Base):
    """Represents a complete or ongoing trade unit (possibly multiple executions)."""
    __tablename__ = "trades"
    
    id = Column(Integer, primary_key=True, index=True)
    symbol = Column(String(10), nullable=False, index=True)
    status = Column(String(20), default="open", index=True)  # "open", "closed"
    side = Column(String(10), index=True)  # "long", "short"
    
    open_date = Column(DateTime, index=True)
    close_date = Column(DateTime, index=True)
    
    quantity = Column(Numeric)
    avg_entry_price = Column(Numeric)
    avg_exit_price = Column(Numeric)
    
    gross_pnl = Column(Numeric)
    net_pnl = Column(Numeric)
    commissions = Column(Numeric, default=0)
    return_pct = Column(Numeric)
    
    # Relationships
    executions = relationship("TradeExecution", back_populates="trade", cascade="all, delete-orphan")
    tags = relationship("Tag", secondary=trade_tags)
    notes = Column(Text)
    
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None), onupdate=lambda: datetime.now(timezone.utc).replace(tzinfo=None))

class TradeExecution(Base):
    """Represents an individual buy or sell order within a trade."""
    __tablename__ = "trade_executions"
    
    id = Column(Integer, primary_key=True, index=True)
    trade_id = Column(Integer, ForeignKey("trades.id", ondelete="CASCADE"), index=True)
    
    timestamp = Column(DateTime, nullable=False, index=True)
    side = Column(String(10), nullable=False)  # "buy", "sell", "sshort", "scover"
    price = Column(Numeric, nullable=False)
    quantity = Column(Numeric, nullable=False)
    commission = Column(Numeric, default=0)
    
    # Reference to original broker data if imported
    external_id = Column(String(100), index=True)
    
    trade = relationship("Trade", back_populates="executions")

class JournalEntry(Base):
    """Represents a daily journal entry or general note not tied to a specific trade."""
    __tablename__ = "journal_entries"
    
    id = Column(Integer, primary_key=True, index=True)
    entry_date = Column(Date, unique=True, nullable=False, index=True)
    content = Column(Text, nullable=False)
    sentiment = Column(String(20)) # "bullish", "bearish", "neutral"
    
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None), onupdate=lambda: datetime.now(timezone.utc).replace(tzinfo=None))
