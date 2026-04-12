from pydantic import BaseModel, ConfigDict, Field
from datetime import datetime, date
from typing import List, Optional
from decimal import Decimal

class TagBase(BaseModel):
    name: str
    color: Optional[str] = None

class TagCreate(TagBase):
    pass

class TagSchema(TagBase):
    id: int

    model_config = ConfigDict(from_attributes=True)

class ExecutionBase(BaseModel):
    timestamp: datetime
    side: str
    price: Decimal
    quantity: Decimal
    commission: Optional[Decimal] = Decimal("0.0")
    external_id: Optional[str] = None

class ExecutionCreate(ExecutionBase):
    pass

class ExecutionSchema(ExecutionBase):
    id: int
    trade_id: int

    model_config = ConfigDict(from_attributes=True)

class TradeBase(BaseModel):
    symbol: str
    status: str = "open"
    side: Optional[str] = None
    open_date: Optional[datetime] = None
    close_date: Optional[datetime] = None
    quantity: Optional[Decimal] = None
    avg_entry_price: Optional[Decimal] = None
    avg_exit_price: Optional[Decimal] = None
    gross_pnl: Optional[Decimal] = None
    net_pnl: Optional[Decimal] = None
    commissions: Optional[Decimal] = Decimal("0.0")
    return_pct: Optional[Decimal] = None
    notes: Optional[str] = None

class TradeCreate(TradeBase):
    pass

class TradeUpdate(BaseModel):
    status: Optional[str] = None
    notes: Optional[str] = None
    tag_ids: Optional[List[int]] = None

class TradeSchema(TradeBase):
    id: int
    executions: List[ExecutionSchema] = []
    tags: List[TagSchema] = []
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)

class JournalEntryBase(BaseModel):
    entry_date: date
    content: str
    sentiment: Optional[str] = None

class JournalEntryCreate(JournalEntryBase):
    pass

class JournalEntrySchema(JournalEntryBase):
    id: int
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)

class TradeStats(BaseModel):
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: float
    total_pnl: float
    avg_profit: float
    profit_factor: float
    max_drawdown: Optional[float] = None
