"""
Scanner router - endpoints for running and viewing scanner results.
"""

from datetime import datetime
from typing import List, Optional
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models import MonitoredStock, VolumeEvent, ScannerConfig, ScannerRun
from app.schemas import (
    ScannerRunRequest, 
    ScannerRunResponse, 
    VolumeEventResponse, 
    ScannerStatsResponse,
    ScannerConfigResponse,
    PreMarketMoversResponse,
    PreMarketMover
)
from app.services import ScannerService, StockDataService

router = APIRouter(prefix="/api/scanner", tags=["scanner"])


@router.post("/run", response_model=ScannerRunResponse)
async def run_scanner(
    request: ScannerRunRequest,
    db: Session = Depends(get_db),
):
    """Run scanner on demand."""
    start_time = datetime.now()
    scan_id = str(uuid.uuid4())
    
    # Create initial run record
    scanner_run = ScannerRun(
        uuid=uuid.UUID(scan_id),
        scanner_type=request.scanner_type,
        universe_id=request.universe_id,
        status="running",
    )
    db.add(scanner_run)
    db.commit()

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
        scanner_run.status = "failed"
        scanner_run.error_message = "No tickers provided or found in universe"
        db.commit()
        raise HTTPException(
            status_code=400, detail="No tickers provided or found in universe"
        )

    # Run scanner
    try:
        if request.scanner_type == "liquidity_hunt":
            results = await ScannerService.run_liquidity_hunt_scan(tickers, db)
        elif request.scanner_type == "oversold_bounce":
            results = await ScannerService.run_oversold_bounce_scan(tickers, db)
        else:
            results = await ScannerService.run_pre_market_scan(tickers, db)
        
        status = "completed"
        error_msg = None
    except Exception as e:
        results = []
        status = "failed"
        error_msg = str(e)

    execution_time = int((datetime.now() - start_time).total_seconds() * 1000)

    # Update run record
    scanner_run.status = status
    scanner_run.stocks_scanned = len(tickers)
    scanner_run.events_detected = len(results)
    scanner_run.execution_time_ms = execution_time
    scanner_run.error_message = error_msg
    db.commit()

    return ScannerRunResponse(
        scan_id=scan_id,
        status=status,
        stocks_scanned=len(tickers),
        events_detected=len(results),
        execution_time_ms=execution_time,
        events=results,
        scanner_type=request.scanner_type,
        error_message=error_msg,
        created_at=scanner_run.created_at
    )


@router.get("/history", response_model=List[ScannerRunResponse])
async def get_scanner_history(
    limit: int = 20,
    db: Session = Depends(get_db),
):
    """Get recent scanner runs."""
    runs = (
        db.query(ScannerRun)
        .order_by(ScannerRun.created_at.desc())
        .limit(limit)
        .all()
    )
    
    # Map to schema
    return [
        ScannerRunResponse(
            scan_id=str(run.uuid),
            status=run.status,
            scanner_type=run.scanner_type,
            stocks_scanned=run.stocks_scanned,
            events_detected=run.events_detected,
            execution_time_ms=run.execution_time_ms,
            error_message=run.error_message,
            created_at=run.created_at
        )
        for run in runs
    ]


@router.get("/results", response_model=List[VolumeEventResponse])
async def get_scanner_results(
    ticker: Optional[str] = None,
    event_type: Optional[str] = None,
    universe_id: Optional[int] = None,
    sort_by: Optional[str] = "created_at",
    sort_order: Optional[str] = "desc",
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

    if universe_id:
        query = query.join(
            MonitoredStock, 
            (VolumeEvent.ticker == MonitoredStock.ticker) & 
            (MonitoredStock.universe_id == universe_id)
        )

    # Sorting logic
    try:
        if sort_by:
            # Map frontend names to model fields if necessary
            # For now, assume they match or handle specifically
            sort_attr = getattr(VolumeEvent, sort_by, VolumeEvent.created_at)
            
            if sort_order.lower() == "desc":
                query = query.order_by(sort_attr.desc())
            else:
                query = query.order_by(sort_attr.asc())
        else:
            query = query.order_by(VolumeEvent.created_at.desc())
    except Exception:
        # Fallback to default sorting if attribute is invalid
        query = query.order_by(VolumeEvent.created_at.desc())

    results = (
        query.limit(limit).offset(offset).all()
    )

    return results


@router.get("/stats", response_model=ScannerStatsResponse)
async def get_scanner_stats(
    db: Session = Depends(get_db),
):
    """Get scanner statistics for the dashboard."""
    from sqlalchemy import func
    from datetime import datetime, timedelta

    # Total events
    total_events = db.query(func.count(VolumeEvent.id)).scalar() or 0

    # Today's events
    today = datetime.now().date()
    today_events = (
        db.query(func.count(VolumeEvent.id))
        .filter(VolumeEvent.event_date == today)
        .scalar()
        or 0
    )

    # Active alerts (last 24 hours)
    last_24h = datetime.utcnow() - timedelta(hours=24)
    active_alerts = (
        db.query(func.count(VolumeEvent.id))
        .filter(VolumeEvent.created_at >= last_24h)
        .scalar()
        or 0
    )

    # Average volume spike ratio (of all events or recent ones)
    avg_spike = (
        db.query(func.avg(VolumeEvent.volume_spike_ratio)).scalar() or 0.0
    )

    return ScannerStatsResponse(
        activeAlerts=active_alerts,
        avgVolumeSpike=round(float(avg_spike), 2),
        totalEvents=total_events,
        todayEvents=today_events,
    )


@router.get("/edge-stats")
async def get_edge_stats(
    period: str = "monthly",
    ticker: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """Get aggregated statistical edge data."""
    from app.services.stats import StatsService
    return StatsService.get_edge_stats(db, ticker=ticker, period=period)


@router.get("/edge-distribution")
async def get_edge_distribution(
    ticker: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """Get distribution data for scatter plots."""
    from app.services.stats import StatsService
    return StatsService.get_distribution_data(db, ticker=ticker)


@router.get("/configs", response_model=List[ScannerConfigResponse])
async def get_scanner_configs(
    db: Session = Depends(get_db),
):
    """Get all available scanner configurations."""
    return db.query(ScannerConfig).filter(ScannerConfig.is_active == True).all()


@router.get("/movers/pre-market", response_model=PreMarketMoversResponse)
async def get_pre_market_movers(
    min_volume: int = 10000,
    limit: int = 100,
    db: Session = Depends(get_db)
):
    """Get top pre-market movers."""
    movers = await StockDataService.get_pre_market_movers(
        db=db,
        min_volume=min_volume,
        limit=limit
    )
    
    # Map to schema if necessary, but the dicts should match
    return {
        "status": "success",
        "movers": movers,
        "timestamp": datetime.now()
    }
