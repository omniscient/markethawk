"""
Futures Router.

Provides REST API endpoints for accessing futures historical data,
rollover schedules, and contract catalogs.
"""

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session
from typing import Optional
from datetime import datetime, timezone
import json

from app.core.database import get_db
from app.services.futures_data import FuturesDataService
from app.providers import DataProviderFactory

router = APIRouter(prefix="/api/futures", tags=["futures"])


@router.get("/history/{symbol}")
async def get_futures_history(
    symbol: str,
    timespan: str = "day",
    multiplier: int = 1,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """
    Get stitched continuous historical bars for a futures symbol.
    Uses the volume-based rollover map stored in the database.
    """
    try:
        df = FuturesDataService.get_continuous_series(
            db=db,
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
        import logging
        logging.error(f"Error serving futures history for {symbol}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/contracts/{symbol}")
async def get_futures_contracts(
    symbol: str,
    db: Session = Depends(get_db),
):
    """List all known contract months for a symbol."""
    try:
        contracts = FuturesDataService.get_contracts(db, symbol.upper())
        return {
            "symbol": symbol.upper(),
            "count": len(contracts),
            "contracts": contracts
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/rollovers/{symbol}")
async def get_futures_rollovers(
    symbol: str,
    db: Session = Depends(get_db),
):
    """List the detected rollover dates used to stitch the continuous series."""
    try:
        rollovers = FuturesDataService.get_rollovers(db, symbol.upper())
        return {
            "symbol": symbol.upper(),
            "count": len(rollovers),
            "rollovers": rollovers
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/download/{symbol}")
async def trigger_download(
    symbol: str,
    exchange: str,
    background_tasks: BackgroundTasks,
    timespan: str = "day",
    multiplier: int = 1,
    force: bool = False,
    db: Session = Depends(get_db),
):
    """
    Trigger a background task to download full historical data from IBKR
    and detect rollovers.
    """
    ibkr = DataProviderFactory.get_or_none("ibkr")
    available = ibkr.is_available() if ibkr else (False, "IBKR provider not registered")
    if not ibkr or not available[0]:
        raise HTTPException(
            status_code=503,
            detail=f"IBKR provider is not available: {available[1]}",
        )

    # Note: Because the download can take a long time, we run it in the background
    background_tasks.add_task(
        FuturesDataService.download_full_history,
        db=db,
        symbol=symbol.upper(),
        exchange=exchange.upper(),
        timespan=timespan,
        multiplier=multiplier,
        force_refresh=force
    )

    return {
        "status": "started",
        "message": f"Historical download for {symbol.upper()} started in background.",
        "note": "Check server logs for progress. Large histories can take several minutes."
    }

@router.get("/providers")
async def list_providers():
    """List all known data providers and their supported asset classes."""
    return {"available": DataProviderFactory.get_all_with_classes()}
