"""
Scanner router - endpoints for running and viewing scanner results.
"""

from datetime import datetime, timedelta, timezone
from typing import List, Optional
import uuid

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session
from sqlalchemy import cast
from sqlalchemy.dialects.postgresql import JSONB
import sqlalchemy as sa

from app.utils.session import get_market_today
from app.core.database import get_db
from app.models import MonitoredStock, ScannerEvent, ScannerConfig, ScannerRun
from app.schemas import (
    ScannerRunRequest,
    ScannerRunResponse,
    ScannerRunAsyncResponse,
    ScannerRunStatusResponse,
    ScannerEventResponse,
    ScannerEventSummary,
    ScannerStatsResponse,
    ScannerConfigResponse,
    PreMarketMoversResponse,
    PreMarketMover,
    ScannerRangeRequest,
    ScannerStatusBlockResponse,
)
from app.services import StockDataService

router = APIRouter(prefix="/api/scanner", tags=["scanner"])


def _last_completed_weekday() -> "date":
    """Default scan date when none supplied — most recent completed weekday."""
    from datetime import timedelta as _td
    d = get_market_today() - _td(days=1)
    while d.weekday() >= 5:  # Saturday=5, Sunday=6
        d -= _td(days=1)
    return d


@router.post("/run", response_model=ScannerRunAsyncResponse, status_code=202)
def run_scanner(
    request: ScannerRunRequest,
    db: Session = Depends(get_db),
):
    """Enqueue a scan and return immediately.

    Progress is delivered via WS /api/scanner/ws/runs/{task_id} or polled at
    GET /api/scanner/runs/{scan_id}/status. Final events are persisted to the
    DB and queryable through /api/scanner/results once status='completed'.

    Returns 409 if a scan with the same (universe_id, scanner_type) is already
    in flight — the response includes the live task_id so the client can
    reattach instead of starting a duplicate.
    """
    import json
    import redis as _redis
    from app.core.config import settings as _settings
    from app.tasks import run_universe_scan

    if not request.universe_id:
        raise HTTPException(
            status_code=400,
            detail="universe_id is required (per-ticker scans go through /run-range)",
        )

    # Concurrency guard: one scan per (universe, scanner_type)
    r = _redis.Redis.from_url(_settings.REDIS_URL, decode_responses=True)
    state_key = f"universe:{request.universe_id}:scan:{request.scanner_type}"
    existing = r.get(state_key)
    if existing:
        try:
            data = json.loads(existing)
            raise HTTPException(
                status_code=409,
                detail={
                    "message": "A scan is already running for this universe and scanner type",
                    "scan_id": data.get("scan_id"),
                    "task_id": (data.get("task_ids") or [None])[0],
                    "started_at": data.get("started_at"),
                },
            )
        except json.JSONDecodeError:
            r.delete(state_key)  # corrupt key, clear and proceed

    # Resolve date range (default = last completed weekday for both bounds)
    start_date = request.start_date or _last_completed_weekday()
    end_date = request.end_date or start_date
    if end_date < start_date:
        raise HTTPException(status_code=400, detail="end_date must not be before start_date")

    # Verify universe has tickers before queueing — fail fast on misconfig.
    ticker_count = (
        db.query(MonitoredStock)
        .filter(
            MonitoredStock.universe_id == request.universe_id,
            MonitoredStock.is_active.is_(True),
        )
        .count()
    )
    if ticker_count == 0:
        raise HTTPException(
            status_code=400, detail="No tickers found in the selected universe"
        )

    scan_id = str(uuid.uuid4())
    scanner_run = ScannerRun(
        uuid=uuid.UUID(scan_id),
        scanner_type=request.scanner_type,
        universe_id=request.universe_id,
        status="queued",
        stocks_scanned=ticker_count,
        scan_start_date=start_date,
        scan_end_date=end_date,
    )
    db.add(scanner_run)
    db.commit()
    db.refresh(scanner_run)

    async_result = run_universe_scan.delay(
        scan_id=scan_id,
        scanner_type=request.scanner_type,
        universe_id=request.universe_id,
        start_date_iso=start_date.isoformat(),
        end_date_iso=end_date.isoformat(),
    )

    scanner_run.celery_task_id = async_result.id
    db.commit()

    started_at = scanner_run.created_at
    if started_at and started_at.tzinfo is None:
        started_at = started_at.replace(tzinfo=timezone.utc)

    return ScannerRunAsyncResponse(
        scan_id=scan_id,
        task_id=async_result.id,
        started_at=started_at,
        scanner_type=request.scanner_type,
        universe_id=request.universe_id,
        scan_start_date=start_date,
        scan_end_date=end_date,
        status="queued",
    )


@router.get("/runs/{scan_id}/status", response_model=ScannerRunStatusResponse)
def get_scan_status(scan_id: str, db: Session = Depends(get_db)):
    """Snapshot of an in-flight or finished scan.

    Live scans: progress payload comes from the Redis state key written by the
    Celery worker after each day. Finished scans: progress is None and the row
    fields (status, events_detected, execution_time_ms) are authoritative.
    """
    import json
    import redis as _redis
    from app.core.config import settings as _settings

    try:
        scan_uuid = uuid.UUID(scan_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="invalid scan_id")

    run = db.query(ScannerRun).filter(ScannerRun.uuid == scan_uuid).first()
    if run is None:
        raise HTTPException(status_code=404, detail="scan not found")

    progress = None
    if run.status in ("queued", "running"):
        try:
            r = _redis.Redis.from_url(_settings.REDIS_URL, decode_responses=True)
            state = r.get(f"universe:{run.universe_id}:scan:{run.scanner_type}")
            if state:
                progress = json.loads(state)
        except Exception:
            progress = None

    started_at = run.created_at
    if started_at and started_at.tzinfo is None:
        started_at = started_at.replace(tzinfo=timezone.utc)

    return ScannerRunStatusResponse(
        scan_id=str(run.uuid),
        task_id=run.celery_task_id,
        status=run.status,
        scanner_type=run.scanner_type,
        universe_id=run.universe_id,
        scan_start_date=run.scan_start_date,
        scan_end_date=run.scan_end_date,
        stocks_scanned=run.stocks_scanned or 0,
        events_detected=run.events_detected or 0,
        execution_time_ms=run.execution_time_ms or 0,
        error_message=run.error_message,
        started_at=started_at,
        progress=progress,
    )


@router.post("/runs/{scan_id}/cancel")
def cancel_scan(scan_id: str, db: Session = Depends(get_db)):
    """Request cancellation of an in-flight scan.

    Sets a Redis flag the worker checks at each day boundary. Mid-day work
    completes; the worker then writes status='cancelled' and emits a
    'cancelled' message on its progress channel.
    """
    import redis as _redis
    from app.core.config import settings as _settings

    try:
        scan_uuid = uuid.UUID(scan_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="invalid scan_id")

    run = db.query(ScannerRun).filter(ScannerRun.uuid == scan_uuid).first()
    if run is None:
        raise HTTPException(status_code=404, detail="scan not found")
    if run.status not in ("queued", "running"):
        raise HTTPException(status_code=409, detail=f"scan is {run.status}, not cancellable")

    r = _redis.Redis.from_url(_settings.REDIS_URL, decode_responses=True)
    r.set(f"scan_cancel:{scan_id}", "1", ex=3600)
    return {"status": "cancel_requested", "scan_id": scan_id}


@router.websocket("/ws/runs/{task_id}")
async def scan_run_websocket(websocket: WebSocket, task_id: str):
    """Stream progress messages for one running scan.

    On connect the most recent state is replayed once (so a page reload doesn't
    miss already-published progress), then the client subscribes to live
    pub/sub messages for the same channel until the task completes/fails.
    """
    import json
    from redis import asyncio as aioredis
    from app.core.config import settings as _settings

    await websocket.accept()
    redis_client = aioredis.from_url(_settings.REDIS_URL, decode_responses=True)

    try:
        # 1. Replay last known state (Redis state key is universe-scoped, so we
        #    locate it by scanning for any key whose stored task_id matches).
        cursor = 0
        while True:
            cursor, keys = await redis_client.scan(cursor=cursor, match="universe:*:scan:*", count=100)
            for key in keys:
                raw = await redis_client.get(key)
                if not raw:
                    continue
                try:
                    data = json.loads(raw)
                    if task_id in (data.get("task_ids") or []):
                        await websocket.send_json({"type": "snapshot", **data})
                        raise StopIteration
                except StopIteration:
                    raise
                except Exception:
                    pass
            if str(cursor) == "0":
                break

    except StopIteration:
        pass
    except WebSocketDisconnect:
        await redis_client.close()
        return
    except Exception:
        pass

    # 2. Subscribe to live messages.
    pubsub = redis_client.pubsub()
    channel = f"scan_task:{task_id}"
    await pubsub.subscribe(channel)
    try:
        async for message in pubsub.listen():
            if message.get("type") != "message":
                continue
            try:
                payload = json.loads(message["data"])
            except Exception:
                continue
            await websocket.send_json(payload)
            if payload.get("type") in ("completed", "failed", "cancelled"):
                break
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        try:
            await pubsub.unsubscribe(channel)
            await pubsub.close()
        except Exception:
            pass
        await redis_client.close()
        try:
            await websocket.close()
        except Exception:
            pass


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
        # 'liquidity_hunt' is the umbrella type — include all three variants
        if stype == "liquidity_hunt":
            query = query.filter(ScannerEvent.scanner_type.in_([
                "liquidity_hunt", "liquidity_hunt_pre", "liquidity_hunt_post"
            ]))
        else:
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
    today = get_market_today()
    today_events = (
        db.query(func.count(ScannerEvent.id))
        .filter(ScannerEvent.event_date == today)
        .scalar()
        or 0
    )

    # Active alerts (last 24 hours)
    last_24h = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=24)
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
        .filter(ScannerEvent.scanner_type.in_([
            'pre_market_volume_spike', 'liquidity_hunt',
            'liquidity_hunt_pre', 'liquidity_hunt_post',
        ]))
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


def _compute_next_run(scanner_type: str) -> Optional[datetime]:
    """Return next scheduled fire time for scanner_type, or None if not scheduled."""
    from datetime import timedelta as _td

    if scanner_type not in {"liquidity_hunt", "liquidity_hunt_pre", "liquidity_hunt_post"}:
        return None

    now = datetime.now(timezone.utc)
    candidate = now.replace(minute=0, second=0, microsecond=0, hour=2)
    if candidate <= now:
        candidate += _td(days=1)
    while candidate.weekday() >= 5:
        candidate += _td(days=1)
    return candidate


@router.get("/scan-status-block", response_model=ScannerStatusBlockResponse)
def get_scan_status_block(
    scanner_type: str,
    universe_id: Optional[int] = None,
    db: Session = Depends(get_db),
):
    """Rich status data for the Scan Status card."""
    from sqlalchemy import func

    base_q = db.query(ScannerRun).filter(ScannerRun.scanner_type == scanner_type)
    if universe_id is not None:
        base_q = base_q.filter(ScannerRun.universe_id == universe_id)

    last_run_record: Optional[ScannerRun] = (
        base_q.order_by(ScannerRun.created_at.desc()).first()
    )

    last_run_info = None
    if last_run_record is not None:
        ts = last_run_record.created_at
        if ts is not None and ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        last_run_info = {
            "timestamp": ts,
            "status": last_run_record.status,
            "events_detected": last_run_record.events_detected or 0,
            "duration_ms": last_run_record.execution_time_ms or 0,
        }

    recent_20 = (
        base_q.order_by(ScannerRun.created_at.desc()).limit(20).all()
    )
    success_rate: Optional[float] = None
    avg_events: Optional[float] = None
    if recent_20:
        completed = [r for r in recent_20 if r.status == "completed"]
        success_rate = round(len(completed) / len(recent_20) * 100, 1)
        if completed:
            avg_events = round(
                sum(r.events_detected or 0 for r in completed) / len(completed), 1
            )

    sparkline_rows = (
        base_q.order_by(ScannerRun.created_at.desc()).limit(10).all()
    )
    sparkline = [
        {
            "created_at": (
                r.created_at.replace(tzinfo=timezone.utc).isoformat()
                if r.created_at and r.created_at.tzinfo is None
                else r.created_at.isoformat() if r.created_at else None
            ),
            "events_detected": r.events_detected or 0,
            "status": r.status,
        }
        for r in reversed(sparkline_rows)
    ]

    type_variants = [scanner_type]
    if scanner_type == "liquidity_hunt":
        type_variants = ["liquidity_hunt", "liquidity_hunt_pre", "liquidity_hunt_post"]

    event_q = db.query(func.count(ScannerEvent.id)).filter(
        ScannerEvent.scanner_type.in_(type_variants)
    )
    if universe_id is not None:
        event_q = event_q.join(
            MonitoredStock,
            sa.and_(
                ScannerEvent.ticker == MonitoredStock.ticker,
                MonitoredStock.universe_id == universe_id,
                MonitoredStock.is_active.is_(True),
            ),
        )
    total_events: int = event_q.scalar() or 0

    return ScannerStatusBlockResponse(
        scanner_type=scanner_type,
        universe_id=universe_id,
        last_run=last_run_info,
        next_run=_compute_next_run(scanner_type),
        total_events=total_events,
        success_rate=success_rate,
        avg_events_per_scan=avg_events,
        sparkline=sparkline,
    )


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
        "timestamp": datetime.now(timezone.utc).isoformat()
    }


@router.post("/run-range")
def run_scanner_range(
    request: ScannerRangeRequest,
    db: Session = Depends(get_db),
):
    """Enqueue a date-range scan for a single ticker as a background Celery task."""
    from app.tasks import run_range_scan
    task = run_range_scan.delay(
        ticker=request.ticker.upper(),
        scanner_types=request.scanner_types,
        start_date_str=request.start_date.isoformat(),
        end_date_str=request.end_date.isoformat(),
        fetch_missing_data=request.fetch_missing_data,
    )
    return {"task_id": task.id, "status": "queued"}
