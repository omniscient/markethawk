"""
Scanner router - endpoints for running and viewing scanner results.
"""

from datetime import datetime
from typing import List, Optional
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import cast
from sqlalchemy.dialects.postgresql import JSONB
import sqlalchemy as sa

from app.core.database import get_db
from app.models import MonitoredStock, ScannerEvent, ScannerConfig, ScannerRun
from app.schemas import (
    ScannerRunRequest, 
    ScannerRunResponse, 
    ScannerEventResponse,
    ScannerEventSummary, 
    ScannerStatsResponse,
    ScannerConfigResponse,
    PreMarketMoversResponse,
    PreMarketMover
)
from app.services import ScannerService, StockDataService

router = APIRouter(prefix="/api/scanner", tags=["scanner"])


@router.post("/run", response_model=ScannerRunResponse)
def run_scanner(
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
            results = ScannerService.run_liquidity_hunt_scan(tickers, db)
        elif request.scanner_type == "oversold_bounce":
            results = ScannerService.run_oversold_bounce_scan(tickers, db)
        else:
            results = ScannerService.run_pre_market_scan(tickers, db)
        
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
def get_scanner_history(
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


@router.get("/results", response_model=List[ScannerEventResponse])
def get_scanner_results(
    ticker: Optional[str] = None,
    scanner_type: Optional[str] = None,
    event_type: Optional[str] = None, # Alias for backward compat
    universe_id: Optional[int] = None,
    sort_by: Optional[str] = "created_at",
    sort_order: Optional[str] = "desc",
    limit: int = 100,
    offset: int = 0,
    db: Session = Depends(get_db),
):
    """Get scanner results with filtering."""
    query = db.query(ScannerEvent)

    if ticker:
        query = query.filter(ScannerEvent.ticker == ticker.upper())

    # Support both scanner_type and the legacy event_type param
    stype = scanner_type or event_type
    if stype:
        query = query.filter(ScannerEvent.scanner_type == stype)

    if universe_id:
        query = query.join(
            MonitoredStock, 
            (ScannerEvent.ticker == MonitoredStock.ticker) & 
            (MonitoredStock.universe_id == universe_id)
        )

    # Sorting logic
    try:
        if sort_by:
            # Handle metadata mapping if needed (e.g., frontend sends a legacy col name)
            # For now, we prefer sorting by fixed columns. 
            # If they want to sort by indicators, we'd need -> JSON logic.
            sort_attr = getattr(ScannerEvent, sort_by, ScannerEvent.created_at)
            
            if sort_order.lower() == "desc":
                query = query.order_by(sort_attr.desc())
            else:
                query = query.order_by(sort_attr.asc())
        else:
            query = query.order_by(ScannerEvent.created_at.desc())
    except Exception:
        query = query.order_by(ScannerEvent.created_at.desc())

    results = (
        query.limit(limit).offset(offset).all()
    )

    return results


@router.get("/stats", response_model=ScannerStatsResponse)
def get_scanner_stats(
    db: Session = Depends(get_db),
):
    """Get scanner statistics for the dashboard."""
    from sqlalchemy import func
    from datetime import datetime, timedelta

    # Total events
    total_events = db.query(func.count(ScannerEvent.id)).scalar() or 0

    # Today's events
    today = datetime.now().date()
    today_events = (
        db.query(func.count(ScannerEvent.id))
        .filter(ScannerEvent.event_date == today)
        .scalar()
        or 0
    )

    # Active alerts (last 24 hours)
    last_24h = datetime.utcnow() - timedelta(hours=24)
    active_alerts = (
        db.query(func.count(ScannerEvent.id))
        .filter(ScannerEvent.created_at >= last_24h)
        .scalar()
        or 0
    )

    # Average volume spike ratio (specifically for volume scanners)
    # We use cast for JSON access in Postgres
    avg_spike = (
        db.query(func.avg(sa.cast(ScannerEvent.indicators['volume_spike_ratio'].astext, sa.Numeric)))
        .filter(ScannerEvent.scanner_type.in_(['pre_market_volume_spike', 'liquidity_hunt']))
        .scalar()
    )
    if avg_spike is None:
        avg_spike = 0.0

    return ScannerStatsResponse(
        activeAlerts=active_alerts,
        avgVolumeSpike=round(float(avg_spike), 2),
        totalEvents=total_events,
        todayEvents=today_events,
    )


@router.get("/edge-stats")
def get_edge_stats(
    period: str = "monthly",
    ticker: Optional[str] = None,
    scanner_type: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """Get aggregated statistical edge data."""
    from app.services.stats import StatsService
    return StatsService.get_edge_stats(db, ticker=ticker, period=period, scanner_type=scanner_type)


@router.get("/edge-distribution")
def get_edge_distribution(
    ticker: Optional[str] = None,
    scanner_type: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """Get distribution data for scatter plots."""
    from app.services.stats import StatsService
    return StatsService.get_distribution_data(db, ticker=ticker, scanner_type=scanner_type)


@router.get("/configs", response_model=List[ScannerConfigResponse])
def get_scanner_configs(
    db: Session = Depends(get_db),
):
    """Get all available scanner configurations."""
    return db.query(ScannerConfig).filter(ScannerConfig.is_active == True).all()


@router.get("/movers/pre-market", response_model=PreMarketMoversResponse)
def get_pre_market_movers(
    min_volume: int = 10000,
    limit: int = 100,
    db: Session = Depends(get_db)
):
    """Get top pre-market movers."""
    movers = StockDataService.get_pre_market_movers(
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
