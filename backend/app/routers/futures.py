"""
Futures Router.

Provides REST API endpoints for accessing futures historical data,
rollover schedules, and contract catalogs.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session
from typing import Optional
import pandas as pd

from app.core.database import get_db
from app.models.futures_contract import FuturesContract
from app.models.futures_rollover import FuturesRollover
from app.services.futures_data import FuturesDataService
from app.providers import DataProviderFactory

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/futures", tags=["futures"])


@router.get("/history/{symbol}")
def get_futures_history(
    symbol: str,
    timespan: str = "day",
    multiplier: int = 1,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
):
    """
    Get stitched continuous historical bars for a futures symbol.
    Uses the volume-based rollover map stored in the database.
    """
    try:
        df = FuturesDataService.get_continuous_series(
            symbol=symbol.upper(),
            timespan=timespan,
            multiplier=multiplier,
            from_date=from_date,
            to_date=to_date,
        )

        if df.empty:
            return {
                "symbol": symbol.upper(),
                "timespan": timespan,
                "data_points": 0,
                "data": []
            }

        # Convert timestamp to ISO format for JSON response
        df['timestamp'] = df['timestamp'].dt.tz_localize('UTC').dt.strftime('%Y-%m-%dT%H:%M:%SZ')

        # Convert numeric types
        for col in ['open', 'high', 'low', 'close', 'vwap']:
            if col in df.columns:
                df[col] = df[col].astype(float)

        # Fill NaNs with None
        df = df.where(pd.notnull(df), None)

        data_dict = df.to_dict("records")

        return {
            "symbol": symbol.upper(),
            "timespan": timespan,
            "data_points": len(data_dict),
            "data": data_dict
        }

    except Exception as e:
        logger.error(f"Error serving futures history for {symbol}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/contracts/{symbol}")
def get_futures_contracts(
    symbol: str,
    db: Session = Depends(get_db),
):
    """List all known contract months for a symbol."""
    try:
        contracts = (
            db.query(FuturesContract)
            .filter(FuturesContract.symbol == symbol.upper())
            .order_by(FuturesContract.contract_month.asc())
            .all()
        )
        result = [
            {
                "symbol": c.symbol,
                "exchange": c.exchange,
                "contract_month": c.contract_month,
                "expiry_date": c.expiry_date.isoformat() if c.expiry_date else None,
                "con_id": c.con_id,
                "is_expired": c.is_expired,
                "data_downloaded": c.data_downloaded,
                "first_bar_date": c.first_bar_date.isoformat() if c.first_bar_date else None,
                "last_bar_date": c.last_bar_date.isoformat() if c.last_bar_date else None,
            }
            for c in contracts
        ]
        return {
            "symbol": symbol.upper(),
            "count": len(result),
            "contracts": result,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/rollovers/{symbol}")
def get_futures_rollovers(
    symbol: str,
    db: Session = Depends(get_db),
):
    """List the detected rollover dates used to stitch the continuous series."""
    try:
        rollovers = (
            db.query(FuturesRollover)
            .filter(FuturesRollover.symbol == symbol.upper())
            .order_by(FuturesRollover.roll_date.asc())
            .all()
        )
        result = [
            {
                "symbol": r.symbol,
                "from_contract": r.from_contract,
                "to_contract": r.to_contract,
                "roll_date": r.roll_date.isoformat() if r.roll_date else None,
                "detection_method": r.detection_method,
            }
            for r in rollovers
        ]
        return {
            "symbol": symbol.upper(),
            "count": len(result),
            "rollovers": result,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/download/{symbol}")
async def trigger_download(
    symbol: str,
    background_tasks: BackgroundTasks,
):
    """
    Trigger a background task to refresh the contract catalog from IBKR.
    """
    from app.services.futures_data import _resolve_exchange

    try:
        _resolve_exchange(symbol.upper())
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    ibkr = DataProviderFactory.get_or_none("ibkr")
    available = ibkr.is_available() if ibkr else (False, "IBKR provider not registered")
    if not ibkr or not available[0]:
        raise HTTPException(
            status_code=503,
            detail=f"IBKR provider is not available: {available[1]}",
        )

    background_tasks.add_task(FuturesDataService.sync_contracts, symbol.upper())

    return {
        "status": "started",
        "message": f"Contract catalog refresh for {symbol.upper()} started in background.",
    }


@router.get("/providers")
def list_providers():
    """List all known data providers and their supported asset classes."""
    return {"available": DataProviderFactory.get_all_with_classes()}
