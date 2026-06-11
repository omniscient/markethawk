"""
Journal seed helpers — trades, tags, journal entries.
Each function inserts rows and flushes; the caller's transaction provides rollback.
"""

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy.orm import Session

from app.models.trade import JournalEntry, Tag, Trade


def seed_trades(db: Session) -> list[Trade]:
    specs = [
        # (symbol, side, status, qty, avg_entry, avg_exit, gross_pnl, net_pnl, open_offset_days, close_offset_days)
        (
            "AAPL",
            "long",
            "closed",
            Decimal("100"),
            Decimal("175.00"),
            Decimal("182.50"),
            Decimal("750.00"),
            Decimal("742.50"),
            10,
            5,
        ),
        (
            "MSFT",
            "long",
            "closed",
            Decimal("50"),
            Decimal("410.00"),
            Decimal("395.00"),
            Decimal("-750.00"),
            Decimal("-757.50"),
            8,
            3,
        ),
        (
            "NVDA",
            "long",
            "open",
            Decimal("30"),
            Decimal("870.00"),
            None,
            None,
            None,
            2,
            None,
        ),
        (
            "MRNA",
            "short",
            "closed",
            Decimal("40"),
            Decimal("95.00"),
            Decimal("88.00"),
            Decimal("280.00"),
            Decimal("274.00"),
            15,
            10,
        ),
        (
            "TSLA",
            "short",
            "open",
            Decimal("20"),
            Decimal("175.00"),
            None,
            None,
            None,
            1,
            None,
        ),
        (
            "AAPL",
            "long",
            "closed",
            Decimal("60"),
            Decimal("168.00"),
            Decimal("174.00"),
            Decimal("360.00"),
            Decimal("354.00"),
            20,
            14,
        ),
    ]

    today = datetime.now(timezone.utc).replace(tzinfo=None)
    trades = []
    for (
        symbol,
        side,
        status,
        qty,
        avg_entry,
        avg_exit,
        gross_pnl,
        net_pnl,
        open_offset,
        close_offset,
    ) in specs:
        open_dt = today - timedelta(days=open_offset)
        close_dt = (
            (today - timedelta(days=close_offset)) if close_offset is not None else None
        )
        commissions = Decimal("7.50") if status == "closed" else Decimal("3.75")
        return_pct = (
            float(
                (avg_exit - avg_entry) / avg_entry * 100 * (1 if side == "long" else -1)
            )
            if avg_exit is not None
            else None
        )
        trade = Trade(
            symbol=symbol,
            side=side,
            status=status,
            quantity=qty,
            avg_entry_price=avg_entry,
            avg_exit_price=avg_exit,
            gross_pnl=gross_pnl,
            net_pnl=net_pnl,
            commissions=commissions,
            return_pct=Decimal(str(round(return_pct, 4)))
            if return_pct is not None
            else None,
            open_date=open_dt,
            close_date=close_dt,
        )
        db.add(trade)
        trades.append(trade)
    db.flush()
    return trades


def seed_tags(db: Session) -> list[Tag]:
    tags = [
        Tag(name="momentum", color="#FF6B6B"),
        Tag(name="breakout", color="#4ECDC4"),
        Tag(name="reversal", color="#45B7D1"),
    ]
    for t in tags:
        db.add(t)
    db.flush()
    return tags


def seed_journal_entries(db: Session) -> list[JournalEntry]:
    today = date.today()
    entries = [
        JournalEntry(
            entry_date=today,
            content="Strong market open, watching NVDA for breakout.",
            sentiment="bullish",
        ),
        JournalEntry(
            entry_date=today - timedelta(days=1),
            content="Choppy session, stayed mostly flat.",
            sentiment="neutral",
        ),
        JournalEntry(
            entry_date=today - timedelta(days=2),
            content="Fed news caused selloff. Avoided losses by staying in cash.",
            sentiment="bearish",
        ),
    ]
    for e in entries:
        db.add(e)
    db.flush()
    return entries
