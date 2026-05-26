"""
Universe router - CRUD operations for stock universes.
"""

from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.exceptions import UniverseNotFoundError, UniverseValidationError
from app.models import StockUniverse, MonitoredStock, StockUniverseTicker
from app.models.stock_aggregate import StockAggregate
from app.schemas import (
    StockUniverseCreate,
    StockUniverseUpdate,
    StockUniverseResponse,
    MonitoredStockResponse,
    UniverseSummary,
)
from app.services import universe_orchestrator, universe_export
from app.services.discovery_service import DiscoveryService
from app.services.universe_stats import UniverseStatsService

router = APIRouter(prefix="/api/universe", tags=["universe"])


class ExportAggregatesRequest(BaseModel):
    tickers: List[str]
    timespan: str = "day"
    multiplier: int = 1
    from_date: Optional[str] = None
    to_date: Optional[str] = None
    zip_format: str = "per_ticker"  # "per_ticker" | "single_csv"


class DeleteAggregatesRequest(BaseModel):
    ticker: str
    asset_class: str  # "stocks" | "futures"
    timespan: Optional[str] = None
    multiplier: Optional[int] = None


class NormalizeRequest(BaseModel):
    target_tickers: Optional[List[str]] = None


@router.post("/create", response_model=StockUniverseResponse)
def create_stock_universe(
    universe: StockUniverseCreate,
    db: Session = Depends(get_db),
):
    """Create a new stock universe."""
    db_universe = StockUniverse(**universe.dict())
    db.add(db_universe)
    db.commit()
    db.refresh(db_universe)
    return db_universe


@router.get("/by-ticker/{ticker}", response_model=List[UniverseSummary])
def get_universes_for_ticker(
    ticker: str,
    db: Session = Depends(get_db),
):
    """Return all active universes that contain the given ticker."""
    ticker_upper = ticker.upper()
    rows = (
        db.query(StockUniverse)
        .join(StockUniverseTicker, StockUniverseTicker.universe_id == StockUniverse.id)
        .filter(
            StockUniverseTicker.ticker == ticker_upper,
            StockUniverse.is_active == True,
        )
        .order_by(StockUniverse.name)
        .all()
    )
    return rows


@router.put("/{universe_id}", response_model=StockUniverseResponse)
def update_stock_universe(
    universe_id: int,
    universe_update: StockUniverseUpdate,
    db: Session = Depends(get_db),
):
    """Update a stock universe."""
    db_universe = (
        db.query(StockUniverse).filter(StockUniverse.id == universe_id).first()
    )
    if not db_universe:
        raise HTTPException(status_code=404, detail="Universe not found")

    update_data = universe_update.dict(exclude_unset=True)
    for key, value in update_data.items():
        setattr(db_universe, key, value)

    db.commit()
    db.refresh(db_universe)
    return db_universe


@router.delete("/{universe_id}")
def delete_stock_universe(
    universe_id: int,
    db: Session = Depends(get_db),
):
    """Delete (soft delete) a stock universe."""
    universe = db.query(StockUniverse).filter(StockUniverse.id == universe_id).first()
    if not universe:
        raise HTTPException(status_code=404, detail="Universe not found")

    universe.is_active = False
    db.commit()
    return {"message": "Universe deleted successfully"}


@router.get("/list", response_model=List[StockUniverseResponse])
def list_stock_universes(
    include_stats: bool = True,
    db: Session = Depends(get_db),
):
    """List all active stock universes. include_stats=false skips aggregate stats (for dropdowns)."""
    universes = db.query(StockUniverse).filter(StockUniverse.is_active == True).all()

    results = []
    for universe in universes:
        universe_data = StockUniverseResponse.from_orm(universe)

        if include_stats:
            universe_data.ticker_count = universe.cached_ticker_count or 0
            universe_data.aggregate_count = universe.cached_aggregate_count or 0
            universe_data.min_aggregate_date = universe.cached_min_date
            universe_data.max_aggregate_date = universe.cached_max_date
            universe_data.available_timespans = universe.cached_timespans or []
            universe_data.stats_refreshed_at = universe.stats_refreshed_at
        else:
            universe_data.ticker_count = 0
            universe_data.aggregate_count = 0
            universe_data.min_aggregate_date = None
            universe_data.max_aggregate_date = None
            universe_data.available_timespans = []

        results.append(universe_data)

    return results


@router.post("/{universe_id}/refresh-stats", response_model=StockUniverseResponse)
def refresh_universe_stats(
    universe_id: int,
    db: Session = Depends(get_db),
):
    """Recompute and persist aggregate stats. Call after sync or refresh to update the cache."""
    universe = db.query(StockUniverse).filter(StockUniverse.id == universe_id).first()
    if not universe:
        raise HTTPException(status_code=404, detail="Universe not found")

    stats = UniverseStatsService.compute(universe_id, db)

    universe.cached_ticker_count = stats["ticker_count"]
    universe.cached_aggregate_count = stats["aggregate_count"]
    universe.cached_min_date = stats["min_date"]
    universe.cached_max_date = stats["max_date"]
    universe.cached_timespans = stats["timespans"]
    universe.stats_refreshed_at = datetime.now(timezone.utc).replace(tzinfo=None)
    db.commit()
    db.refresh(universe)

    universe_data = StockUniverseResponse.from_orm(universe)
    universe_data.ticker_count = universe.cached_ticker_count or 0
    universe_data.aggregate_count = universe.cached_aggregate_count or 0
    universe_data.min_aggregate_date = universe.cached_min_date
    universe_data.max_aggregate_date = universe.cached_max_date
    universe_data.available_timespans = universe.cached_timespans or []
    universe_data.stats_refreshed_at = universe.stats_refreshed_at
    return universe_data


@router.post("/sync/fundamentals")
def sync_fundamental_data(
    background_tasks: BackgroundTasks,
    delay: float = 15.0,
    db: Session = Depends(get_db),
):
    """Trigger background sync of fundamental data from Polygon."""
    service = DiscoveryService(db)
    background_tasks.add_task(service.sync_fundamental_data, delay_seconds=delay)
    return {"status": "accepted", "message": f"Fundamental sync started in background (delay={delay}s)"}


@router.post("/sync/details")
def sync_ticker_details(
    background_tasks: BackgroundTasks,
    delay: float = 15.0,
    resync: bool = False,
    db: Session = Depends(get_db),
):
    """Trigger background sync of ticker details. delay: 15.0=Free, 0.2=Paid. resync: force re-crawl."""
    service = DiscoveryService(db)
    background_tasks.add_task(service.sync_ticker_details_crawler, delay, resync)
    return {"status": "accepted", "message": f"Ticker details sync started in background (delay={delay}s, resync={resync})"}


@router.post("/sync/stop")
def stop_sync(
    db: Session = Depends(get_db),
):
    """Stops any running sync process by setting a Stop Flag in Redis and purging the queue."""
    from app.core.celery_app import celery_app
    from app.core.config import settings
    import redis

    try:
        r = redis.from_url(settings.REDIS_URL)
        r.setex("CRAWLER_STOP_FLAG", 60, "1")
        redis_status = "Flag set."
    except Exception as e:
        redis_status = f"Redis error: {e}"
    purged_count = celery_app.control.purge()
    return {"status": "stopped", "message": f"Stop signal sent ({redis_status}). {purged_count} pending tasks removed."}


@router.post("/sync/metrics")
def sync_daily_metrics(
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """Trigger background update of daily technical metrics."""
    service = DiscoveryService(db)
    background_tasks.add_task(service.update_daily_metrics_snapshot)
    return {"status": "accepted", "message": "Daily metrics update started in background"}


@router.post("/{universe_id}/refresh")
def refresh_universe(
    universe_id: int,
    db: Session = Depends(get_db),
):
    """Refresh stocks in a universe using the Universe Discovery Engine."""
    try:
        return universe_orchestrator.discover_and_refresh(universe_id, db)
    except UniverseNotFoundError:
        raise HTTPException(status_code=404, detail="Universe not found")


@router.post("/{universe_id}/sync-missing")
def sync_missing_aggregates(
    universe_id: int,
    db: Session = Depends(get_db),
):
    """For every recorded (timespan, multiplier), queue a sync from last bar to today."""
    return universe_orchestrator.sync_missing_aggregates(universe_id, db)


@router.get("/{universe_id}/sync-status")
def get_universe_sync_status(universe_id: int):
    """Return the current sync progress for a universe."""
    return universe_orchestrator.get_sync_status(universe_id)


@router.post("/{universe_id}/export-aggregates")
def export_universe_aggregates(
    universe_id: int,
    request: ExportAggregatesRequest,
    db: Session = Depends(get_db),
):
    """Stream a ZIP file containing aggregate (OHLCV) data for the requested tickers."""
    try:
        return universe_export.export_aggregates(universe_id, request, db)
    except UniverseNotFoundError:
        raise HTTPException(status_code=404, detail="Universe not found")


@router.get("/{universe_id}/stocks", response_model=List[MonitoredStockResponse])
def get_universe_stocks(
    universe_id: int,
    db: Session = Depends(get_db),
):
    """List all stocks in a universe."""
    stocks = (
        db.query(MonitoredStock)
        .filter(
            MonitoredStock.universe_id == universe_id,
            MonitoredStock.is_active == True,
        )
        .all()
    )
    return stocks


@router.post("/{universe_id}/sync-aggregates")
def sync_universe_aggregates(
    universe_id: int,
    from_date: str,
    to_date: str,
    multiplier: int = 1,
    timespan: str = "minute",
    adjusted: bool = True,
    sort: str = "asc",
    limit: int = 50000,
    db: Session = Depends(get_db),
):
    """Trigger backfill of aggregates for all stocks in the universe."""
    return universe_orchestrator.sync_aggregates(
        universe_id, from_date, to_date, multiplier, timespan, adjusted, sort, limit, db
    )


@router.post("/{universe_id}/analyze-quality")
def trigger_quality_analysis(
    universe_id: int,
    db: Session = Depends(get_db),
):
    """Queue a background data-quality analysis. Poll GET .../quality-report for results."""
    try:
        return universe_orchestrator.queue_quality_analysis(universe_id, db)
    except UniverseNotFoundError:
        raise HTTPException(status_code=404, detail="Universe not found")


@router.delete("/{universe_id}/aggregates")
def delete_ticker_aggregates(
    universe_id: int,
    request: DeleteAggregatesRequest,
    db: Session = Depends(get_db),
):
    """Delete aggregate bars for a ticker (optionally scoped to timespan/multiplier) and remove from universe."""
    from app.models.futures_aggregate import FuturesAggregate

    if request.asset_class == "futures":
        q = db.query(FuturesAggregate).filter(FuturesAggregate.symbol == request.ticker)
        if request.timespan is not None:
            q = q.filter(
                FuturesAggregate.timespan == request.timespan,
                FuturesAggregate.multiplier == request.multiplier,
            )
        deleted = q.delete(synchronize_session=False)
    else:
        q = db.query(StockAggregate).filter(StockAggregate.ticker == request.ticker)
        if request.timespan is not None:
            q = q.filter(
                StockAggregate.timespan == request.timespan,
                StockAggregate.multiplier == request.multiplier,
            )
        deleted = q.delete(synchronize_session=False)

    db.query(StockUniverseTicker).filter(
        StockUniverseTicker.universe_id == universe_id,
        StockUniverseTicker.ticker == request.ticker,
    ).delete(synchronize_session=False)

    db.commit()
    return {"deleted_bars": deleted, "ticker": request.ticker, "removed_from_universe": True}


@router.get("/{universe_id}/quality-report")
def get_quality_report(
    universe_id: int,
    db: Session = Depends(get_db),
):
    """Return the latest quality report for a universe (or null if none exists)."""
    from app.models.universe_quality_report import UniverseQualityReport

    report = db.query(UniverseQualityReport).filter(UniverseQualityReport.universe_id == universe_id).first()
    if not report:
        return None
    return {
        "universe_id": universe_id,
        "status": report.status,
        "overall_grade": report.overall_grade,
        "overall_score": float(report.overall_score) if report.overall_score is not None else None,
        "ticker_count": report.ticker_count,
        "started_at": report.started_at.isoformat() if report.started_at else None,
        "generated_at": report.generated_at.isoformat() if report.generated_at else None,
        "report_data": report.report_data,
        "error_message": report.error_message,
        "normalization_status": report.normalization_status,
        "normalization_data": report.normalization_data,
    }


@router.post("/{universe_id}/normalize")
def trigger_normalization(
    universe_id: int,
    request: Optional[NormalizeRequest] = None,
    db: Session = Depends(get_db),
):
    """Start (or resume) a normalization run. Poll GET .../quality-report for status."""
    target_tickers = request.target_tickers if request else None
    try:
        return universe_orchestrator.queue_normalization(universe_id, target_tickers, db)
    except UniverseNotFoundError:
        raise HTTPException(status_code=404, detail="Universe not found")
    except UniverseValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))
