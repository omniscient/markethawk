"""
Active Watchlist router — CRUD for the manually curated live-observation list.
"""

import asyncio
import logging
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.active_watchlist import WATCHLIST_SOFT_LIMIT, ActiveWatchlist
from app.schemas.active_watchlist import (
    ActiveWatchlistAdd,
    ActiveWatchlistItem,
    ActiveWatchlistUpdate,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/watchlist", tags=["watchlist"])


@router.get("/", response_model=List[ActiveWatchlistItem])
async def list_watchlist(db: Session = Depends(get_db)):
    """Return all symbols currently in the active watchlist, oldest first."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        None,
        lambda: db.query(ActiveWatchlist).order_by(ActiveWatchlist.added_at.asc()).all(),
    )


@router.post("/", response_model=ActiveWatchlistItem, status_code=201)
async def add_to_watchlist(payload: ActiveWatchlistAdd, db: Session = Depends(get_db)):
    """
    Add a symbol to the active watchlist.

    Returns 409 if the symbol is already present.
    Returns 422 if the soft limit of 50 symbols would be exceeded.
    """
    loop = asyncio.get_running_loop()

    existing = await loop.run_in_executor(
        None,
        lambda: db.query(ActiveWatchlist)
        .filter(ActiveWatchlist.symbol == payload.symbol)
        .first(),
    )
    if existing:
        raise HTTPException(
            status_code=409,
            detail=f"{payload.symbol} is already in the active watchlist.",
        )

    count = await loop.run_in_executor(
        None, lambda: db.query(ActiveWatchlist).count()
    )
    if count >= WATCHLIST_SOFT_LIMIT:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Active watchlist is at the {WATCHLIST_SOFT_LIMIT}-symbol limit. "
                "Remove a symbol before adding a new one."
            ),
        )

    def _add():
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

    return await loop.run_in_executor(None, _add)


@router.patch("/{symbol}", response_model=ActiveWatchlistItem)
async def update_watchlist_entry(
    symbol: str,
    payload: ActiveWatchlistUpdate,
    db: Session = Depends(get_db),
):
    """Update the notes for a watchlist entry."""
    symbol = symbol.strip().upper()
    loop = asyncio.get_running_loop()

    entry = await loop.run_in_executor(
        None,
        lambda: db.query(ActiveWatchlist)
        .filter(ActiveWatchlist.symbol == symbol)
        .first(),
    )
    if not entry:
        raise HTTPException(status_code=404, detail=f"{symbol} not found in watchlist.")

    def _update():
        entry.notes = payload.notes
        db.commit()
        db.refresh(entry)
        return entry

    return await loop.run_in_executor(None, _update)


@router.delete("/{symbol}", status_code=204)
async def remove_from_watchlist(symbol: str, db: Session = Depends(get_db)):
    """Remove a symbol from the active watchlist."""
    symbol = symbol.strip().upper()
    loop = asyncio.get_running_loop()

    entry = await loop.run_in_executor(
        None,
        lambda: db.query(ActiveWatchlist)
        .filter(ActiveWatchlist.symbol == symbol)
        .first(),
    )
    if not entry:
        raise HTTPException(status_code=404, detail=f"{symbol} not found in watchlist.")

    def _delete():
        db.delete(entry)
        db.commit()
        logger.info(f"ActiveWatchlist: removed {symbol}")

    await loop.run_in_executor(None, _delete)
