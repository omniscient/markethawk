"""
Active Watchlist router — CRUD for the manually curated live-observation list.
"""

import logging
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.active_watchlist import ActiveWatchlist, WATCHLIST_SOFT_LIMIT
from app.schemas.active_watchlist import (
    ActiveWatchlistAdd,
    ActiveWatchlistUpdate,
    ActiveWatchlistItem,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/watchlist", tags=["watchlist"])


@router.get("/", response_model=List[ActiveWatchlistItem])
def list_watchlist(db: Session = Depends(get_db)):
    """Return all symbols currently in the active watchlist, oldest first."""
    return db.query(ActiveWatchlist).order_by(ActiveWatchlist.added_at.asc()).all()


@router.post("/", response_model=ActiveWatchlistItem, status_code=201)
def add_to_watchlist(payload: ActiveWatchlistAdd, db: Session = Depends(get_db)):
    """
    Add a symbol to the active watchlist.

    Returns 409 if the symbol is already present.
    Returns 422 if the soft limit of 50 symbols would be exceeded.
    """
    existing = (
        db.query(ActiveWatchlist)
        .filter(ActiveWatchlist.symbol == payload.symbol)
        .first()
    )
    if existing:
        raise HTTPException(
            status_code=409,
            detail=f"{payload.symbol} is already in the active watchlist.",
        )

    count = db.query(ActiveWatchlist).count()
    if count >= WATCHLIST_SOFT_LIMIT:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Active watchlist is at the {WATCHLIST_SOFT_LIMIT}-symbol limit. "
                "Remove a symbol before adding a new one."
            ),
        )

    entry = ActiveWatchlist(
        symbol=payload.symbol,
        security_type=payload.security_type,
        exchange=payload.exchange,
        notes=payload.notes,
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    logger.info(f"ActiveWatchlist: added {payload.symbol}")
    return entry


@router.patch("/{symbol}", response_model=ActiveWatchlistItem)
def update_watchlist_entry(
    symbol: str,
    payload: ActiveWatchlistUpdate,
    db: Session = Depends(get_db),
):
    """Update the notes for a watchlist entry."""
    symbol = symbol.strip().upper()
    entry = (
        db.query(ActiveWatchlist).filter(ActiveWatchlist.symbol == symbol).first()
    )
    if not entry:
        raise HTTPException(status_code=404, detail=f"{symbol} not found in watchlist.")

    entry.notes = payload.notes
    db.commit()
    db.refresh(entry)
    return entry


@router.delete("/{symbol}", status_code=204)
def remove_from_watchlist(symbol: str, db: Session = Depends(get_db)):
    """Remove a symbol from the active watchlist."""
    symbol = symbol.strip().upper()
    entry = (
        db.query(ActiveWatchlist).filter(ActiveWatchlist.symbol == symbol).first()
    )
    if not entry:
        raise HTTPException(status_code=404, detail=f"{symbol} not found in watchlist.")

    db.delete(entry)
    db.commit()
    logger.info(f"ActiveWatchlist: removed {symbol}")
