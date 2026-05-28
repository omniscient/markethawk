import csv
import io
from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy.orm import Session

from app.models.trade import JournalEntry, Tag, Trade, TradeExecution
from app.schemas.journal import (
    JournalEntryCreate,
    TagCreate,
    TradeCreate,
    TradeStats,
    TradeUpdate,
)


def get_trades(db: Session, symbol: Optional[str] = None, status: Optional[str] = None):
    query = db.query(Trade)
    if symbol:
        query = query.filter(Trade.symbol == symbol.upper())
    if status:
        query = query.filter(Trade.status == status)
    return query.order_by(Trade.open_date.desc()).all()


def get_trade(db: Session, trade_id: int):
    return db.query(Trade).filter(Trade.id == trade_id).first()


def create_trade(db: Session, trade: TradeCreate):
    db_trade = Trade(**trade.model_dump())
    db.add(db_trade)
    db.commit()
    db.refresh(db_trade)
    return db_trade


def update_trade(db: Session, trade_id: int, trade_update: TradeUpdate):
    db_trade = db.query(Trade).filter(Trade.id == trade_id).first()
    if not db_trade:
        return None

    if trade_update.status:
        db_trade.status = trade_update.status
    if trade_update.notes is not None:
        db_trade.notes = trade_update.notes

    if trade_update.tag_ids is not None:
        db_trade.tags = []
        tags = db.query(Tag).filter(Tag.id.in_(trade_update.tag_ids)).all()
        db_trade.tags = tags

    db.commit()
    db.refresh(db_trade)
    return db_trade


def get_trade_stats(db: Session) -> TradeStats:
    trades = db.query(Trade).all()

    total_trades = len(trades)
    winning_trades = len([t for t in trades if t.net_pnl and t.net_pnl > 0])
    losing_trades = len([t for t in trades if t.net_pnl and t.net_pnl < 0])

    win_rate = (winning_trades / total_trades) if total_trades > 0 else 0
    total_pnl = sum([t.net_pnl for t in trades if t.net_pnl]) or Decimal("0")
    avg_profit = (total_pnl / total_trades) if total_trades > 0 else Decimal("0")

    gross_profit = sum(
        [t.net_pnl for t in trades if t.net_pnl and t.net_pnl > 0]
    ) or Decimal("1")
    gross_loss = abs(
        sum([t.net_pnl for t in trades if t.net_pnl and t.net_pnl < 0])
    ) or Decimal("1")
    profit_factor = (
        float(gross_profit / gross_loss) if gross_loss != 0 else float(gross_profit)
    )

    return TradeStats(
        total_trades=total_trades,
        winning_trades=winning_trades,
        losing_trades=losing_trades,
        win_rate=win_rate,
        total_pnl=total_pnl,
        avg_profit=avg_profit,
        profit_factor=profit_factor,
    )


def get_journal_entries(db: Session):
    return db.query(JournalEntry).order_by(JournalEntry.entry_date.desc()).all()


def create_journal_entry(db: Session, entry: JournalEntryCreate):
    db_entry = JournalEntry(**entry.model_dump())
    db.add(db_entry)
    db.commit()
    db.refresh(db_entry)
    return db_entry


def get_tags(db: Session):
    return db.query(Tag).all()


def create_tag(db: Session, tag: TagCreate):
    db_tag = Tag(**tag.model_dump())
    db.add(db_tag)
    db.commit()
    db.refresh(db_tag)
    return db_tag


def import_trades_from_csv(db: Session, content: str, broker: str):
    f = io.StringIO(content)
    reader = csv.DictReader(f)

    imported_count = 0
    for row in reader:
        symbol = row.get("Symbol")
        if not symbol:
            continue

        try:
            timestamp = datetime.strptime(row.get("Time", ""), "%Y-%m-%d %H:%M:%S")
            side = row.get("Type", "").lower()
            price = Decimal(row.get("Price", "0"))
            qty = Decimal(row.get("Qty", "0"))

            trade = (
                db.query(Trade)
                .filter(Trade.symbol == symbol, Trade.status == "open")
                .first()
            )
            if not trade:
                trade = Trade(symbol=symbol, status="open", open_date=timestamp)
                db.add(trade)
                db.flush()

            execution = TradeExecution(
                trade_id=trade.id,
                timestamp=timestamp,
                side=side,
                price=price,
                quantity=qty,
            )
            db.add(execution)
            imported_count += 1

        except Exception as e:
            print(f"Error importing row: {e}")
            continue

    db.commit()
    return {"status": "success", "imported": imported_count}
