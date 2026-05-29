from typing import List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas.journal import (
    JournalEntryCreate,
    JournalEntrySchema,
    TagCreate,
    TagSchema,
    TradeCreate,
    TradeSchema,
    TradeStats,
    TradeUpdate,
)
from app.services import journal_service

router = APIRouter(prefix="/api/journal", tags=["Journal"])


@router.get("/trades", response_model=List[TradeSchema])
def get_trades(
    symbol: Optional[str] = None,
    status: Optional[str] = None,
    db: Session = Depends(get_db),
):
    return journal_service.get_trades(db, symbol=symbol, status=status)


@router.post("/trades", response_model=TradeSchema)
def create_trade(trade: TradeCreate, db: Session = Depends(get_db)):
    return journal_service.create_trade(db, trade)


@router.get("/trades/{trade_id}", response_model=TradeSchema)
def get_trade(trade_id: int, db: Session = Depends(get_db)):
    trade = journal_service.get_trade(db, trade_id)
    if not trade:
        raise HTTPException(status_code=404, detail="Trade not found")
    return trade


@router.patch("/trades/{trade_id}", response_model=TradeSchema)
def update_trade(
    trade_id: int, trade_update: TradeUpdate, db: Session = Depends(get_db)
):
    trade = journal_service.update_trade(db, trade_id, trade_update)
    if not trade:
        raise HTTPException(status_code=404, detail="Trade not found")
    return trade


@router.post("/import", response_model=dict)
async def import_trades(
    file: UploadFile = File(...),
    broker: str = Query(..., description="Broker name (e.g., TOS, ETrade)"),
    db: Session = Depends(get_db),
):
    content = await file.read()
    results = journal_service.import_trades_from_csv(
        db, content.decode("utf-8"), broker
    )
    return results


@router.get("/stats", response_model=TradeStats)
def get_journal_stats(db: Session = Depends(get_db)):
    return journal_service.get_trade_stats(db)


@router.get("/entries", response_model=List[JournalEntrySchema])
def get_journal_entries(db: Session = Depends(get_db)):
    return journal_service.get_journal_entries(db)


@router.post("/entries", response_model=JournalEntrySchema)
def create_journal_entry(entry: JournalEntryCreate, db: Session = Depends(get_db)):
    return journal_service.create_journal_entry(db, entry)


@router.get("/tags", response_model=List[TagSchema])
def get_tags(db: Session = Depends(get_db)):
    return journal_service.get_tags(db)


@router.post("/tags", response_model=TagSchema)
def create_tag(tag: TagCreate, db: Session = Depends(get_db)):
    return journal_service.create_tag(db, tag)
