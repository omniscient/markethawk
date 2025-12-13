"""
Scanner router - endpoints for running and viewing scanner results.
"""

from datetime import datetime
from typing import List, Optional
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models import MonitoredStock, VolumeEvent
from app.schemas import ScannerRunRequest, ScannerRunResponse, VolumeEventResponse
from app.services import ScannerService

router = APIRouter(prefix="/api/scanner", tags=["scanner"])


@router.post("/run", response_model=ScannerRunResponse)
async def run_scanner(
    request: ScannerRunRequest,
    db: Session = Depends(get_db),
):
    """Run scanner on demand."""
    start_time = datetime.now()

    # Get tickers to scan
    tickers = request.tickers
    if not tickers and request.universe_id:
        # Get tickers from universe
        stocks = (
            db.query(MonitoredStock)
            .filter(
                MonitoredStock.universe_id == request.universe_id,
                MonitoredStock.is_active == True,
            )
            .all()
        )
        tickers = [stock.ticker for stock in stocks]

    if not tickers:
        raise HTTPException(
            status_code=400, detail="No tickers provided or found in universe"
        )

    # Run scanner
    scan_id = str(uuid.uuid4())
    results = await ScannerService.run_pre_market_scan(tickers, db)

    execution_time = int((datetime.now() - start_time).total_seconds() * 1000)

    return ScannerRunResponse(
        scan_id=scan_id,
        status="completed",
        stocks_scanned=len(tickers),
        events_detected=len(results),
        execution_time_ms=execution_time,
    )


@router.get("/results", response_model=List[VolumeEventResponse])
async def get_scanner_results(
    ticker: Optional[str] = None,
    event_type: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
    db: Session = Depends(get_db),
):
    """Get scanner results with filtering."""
    query = db.query(VolumeEvent)

    if ticker:
        query = query.filter(VolumeEvent.ticker == ticker.upper())

    if event_type:
        query = query.filter(VolumeEvent.event_type == event_type)

    results = (
        query.order_by(VolumeEvent.created_at.desc()).limit(limit).offset(offset).all()
    )

    return results
