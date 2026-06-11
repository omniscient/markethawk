"""
Tests for journal_service CRUD functions against the testcontainers DB.
"""

from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from app.schemas.journal import JournalEntryCreate, TagCreate, TradeCreate, TradeUpdate
from app.services.journal_service import (
    create_journal_entry,
    create_tag,
    create_trade,
    get_journal_entries,
    get_tags,
    get_trade,
    get_trade_stats,
    get_trades,
    update_trade,
)

# ── helpers ──────────────────────────────────────────────────────────────


def _trade(symbol="AAPL", status="open"):
    return TradeCreate(symbol=symbol, status=status)


# ── create_trade / get_trade ─────────────────────────────────────────────


def test_create_trade_returns_persisted_object(db: Session):
    trade = create_trade(db, _trade())
    assert trade.id is not None
    assert trade.symbol == "AAPL"
    assert trade.status == "open"


def test_get_trade_returns_correct_record(db: Session):
    created = create_trade(db, _trade("TSLA"))
    fetched = get_trade(db, created.id)
    assert fetched is not None
    assert fetched.symbol == "TSLA"


def test_get_trade_returns_none_for_missing_id(db: Session):
    assert get_trade(db, 999999) is None


# ── get_trades ───────────────────────────────────────────────────────────


def test_get_trades_returns_all(db: Session):
    create_trade(db, _trade("AAPL"))
    create_trade(db, _trade("MSFT"))
    trades = get_trades(db)
    symbols = [t.symbol for t in trades]
    assert "AAPL" in symbols
    assert "MSFT" in symbols


def test_get_trades_filters_by_symbol(db: Session):
    create_trade(db, _trade("AAPL"))
    create_trade(db, _trade("MSFT"))
    trades = get_trades(db, symbol="AAPL")
    assert all(t.symbol == "AAPL" for t in trades)


def test_get_trades_filters_by_status(db: Session):
    create_trade(db, TradeCreate(symbol="AAPL", status="open"))
    create_trade(db, TradeCreate(symbol="MSFT", status="closed"))
    open_trades = get_trades(db, status="open")
    assert all(t.status == "open" for t in open_trades)


# ── update_trade ─────────────────────────────────────────────────────────


def test_update_trade_status(db: Session):
    trade = create_trade(db, _trade())
    updated = update_trade(db, trade.id, TradeUpdate(status="closed"))
    assert updated.status == "closed"


def test_update_trade_notes(db: Session):
    trade = create_trade(db, _trade())
    updated = update_trade(db, trade.id, TradeUpdate(notes="Good entry"))
    assert updated.notes == "Good entry"


def test_update_trade_returns_none_for_missing(db: Session):
    result = update_trade(db, 999999, TradeUpdate(status="closed"))
    assert result is None


# ── trade stats ───────────────────────────────────────────────────────────


def test_trade_stats_empty_db(db: Session):
    stats = get_trade_stats(db)
    assert stats.total_trades == 0
    assert stats.win_rate == 0


def test_trade_stats_win_rate(db: Session):
    from app.models.trade import Trade

    winner = Trade(symbol="AAPL", status="closed", net_pnl=Decimal("100"))
    loser = Trade(symbol="MSFT", status="closed", net_pnl=Decimal("-50"))
    db.add_all([winner, loser])
    db.flush()
    stats = get_trade_stats(db)
    assert stats.total_trades == 2
    assert stats.winning_trades == 1
    assert stats.losing_trades == 1
    assert pytest.approx(stats.win_rate, rel=1e-3) == 0.5


# ── journal entries ────────────────────────────────────────────────────────


def test_create_and_get_journal_entry(db: Session):
    from datetime import date

    entry = create_journal_entry(
        db,
        JournalEntryCreate(
            entry_date=date.today(), title="Test Entry", content="Notes here"
        ),
    )
    entries = get_journal_entries(db)
    ids = [e.id for e in entries]
    assert entry.id in ids


# ── tags ──────────────────────────────────────────────────────────────────


def test_create_and_get_tag(db: Session):
    tag = create_tag(db, TagCreate(name="momentum"))
    tags = get_tags(db)
    names = [t.name for t in tags]
    assert "momentum" in names


# ── eager loading ─────────────────────────────────────────────────────────


def test_get_trades_preloads_executions_and_tags(db: Session):
    """get_trades() must selectinload executions and tags so they survive session expunge."""
    from datetime import datetime

    from app.models.trade import Tag, Trade, TradeExecution

    tag = Tag(name="eager-load-test")
    db.add(tag)
    db.flush()

    trade = Trade(symbol="EAGER", status="open")
    db.add(trade)
    db.flush()

    execution = TradeExecution(
        trade_id=trade.id,
        timestamp=datetime(2026, 5, 1, 9, 30),
        side="buy",
        price=Decimal("100.00"),
        quantity=Decimal("10"),
    )
    db.add(execution)
    trade.tags = [tag]
    db.flush()

    trades = get_trades(db)
    db.expunge_all()

    eager_trade = next(t for t in trades if t.symbol == "EAGER")
    # Accessing these after expunge raises DetachedInstanceError if not eagerly loaded
    assert len(eager_trade.executions) == 1
    assert len(eager_trade.tags) == 1
