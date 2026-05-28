"""
Scanner router - endpoints for running and viewing scanner results.
"""

import uuid
from datetime import date, datetime, timedelta, timezone
from typing import List, Optional

import sqlalchemy as sa
from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    Request,
    WebSocket,
    WebSocketDisconnect,
)
from sqlalchemy.orm import Session, joinedload

from app.core.database import get_db
from app.core.rate_limits import SCANNER_LIMIT, limiter
from app.models import MonitoredStock, ScannerConfig, ScannerEvent, ScannerRun
from app.models.signal_review import SignalReview
from app.schemas import (
    ClearEventsResponse,
    PreMarketMoversResponse,
    ScannerConfigResponse,
    ScannerEventResponse,
    ScannerRangeRequest,
    ScannerRunAsyncResponse,
    ScannerRunRequest,
    ScannerRunResponse,
    ScannerRunStatusResponse,
    ScannerStatsResponse,
    ScannerStatusBlockResponse,
)
from app.schemas.signal_review import (
    SignalReviewRequest,
    SignalReviewResponse,
    SignalReviewStatsResponse,
)
from app.services import StockDataService
from app.services.scan_orchestrator import get_scan_progress, request_scan_cancel
from app.services.scanner import ScannerService
from app.services.scanner_query_service import ScannerQueryService
from app.utils.session import get_market_today

router = APIRouter(prefix="/api/scanner", tags=["scanner"])


def _last_completed_weekday() -> "date":
    """Default scan date when none supplied — most recent completed weekday."""
    from datetime import timedelta as _td

    d = get_market_today() - _td(days=1)
    while d.weekday() >= 5:  # Saturday=5, Sunday=6
        d -= _td(days=1)
    return d


@router.get("/types")
def list_scanner_types():
    """Return all registered scanner types for frontend scanner pickers."""
    from app.services.scan_orchestrator import get_all

    return [
        {
            "key": d.key,
            "display_name": d.display_name,
            "description": d.description,
            "supports_date_range": d.supports_date_range,
        }
        for d in get_all()
    ]


@router.post("/run", response_model=ScannerRunAsyncResponse, status_code=202)
@limiter.limit(SCANNER_LIMIT)
def run_scanner(
    request: Request,
    body: ScannerRunRequest,
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
    from app.core.config import settings as _settings
    from app.tasks import run_universe_scan

    if not body.universe_id:
        raise HTTPException(
            status_code=400,
            detail="universe_id is required (per-ticker scans go through /run-range)",
        )

    in_flight = ScannerService.check_concurrency(
        _settings.REDIS_URL, body.universe_id, body.scanner_type
    )
    if in_flight:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "A scan is already running for this universe and scanner type",
                "scan_id": in_flight.get("scan_id"),
                "task_id": (in_flight.get("task_ids") or [None])[0],
                "started_at": in_flight.get("started_at"),
            },
        )

    try:
        start_date, end_date = ScannerService.resolve_date_range(
            body.start_date, body.end_date
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    ticker_count = ScannerService.count_active_tickers(db, body.universe_id)
    if ticker_count == 0:
        raise HTTPException(
            status_code=400, detail="No tickers found in the selected universe"
        )

    scan_id = str(uuid.uuid4())
    scanner_run = ScannerRun(
        uuid=uuid.UUID(scan_id),
        scanner_type=body.scanner_type,
        universe_id=body.universe_id,
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
        scanner_type=body.scanner_type,
        universe_id=body.universe_id,
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
        scanner_type=body.scanner_type,
        universe_id=body.universe_id,
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
        progress = get_scan_progress(
            _settings.REDIS_URL, run.universe_id, run.scanner_type
        )

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
    from app.core.config import settings as _settings

    try:
        scan_uuid = uuid.UUID(scan_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="invalid scan_id")

    run = db.query(ScannerRun).filter(ScannerRun.uuid == scan_uuid).first()
    if run is None:
        raise HTTPException(status_code=404, detail="scan not found")
    if run.status not in ("queued", "running"):
        raise HTTPException(
            status_code=409, detail=f"scan is {run.status}, not cancellable"
        )

    request_scan_cancel(_settings.REDIS_URL, scan_id)
    return {"status": "cancel_requested", "scan_id": scan_id}


@router.websocket("/ws/runs/{task_id}")
@limiter.exempt
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
            cursor, keys = await redis_client.scan(
                cursor=cursor, match="universe:*:scan:*", count=100
            )
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
        db.query(ScannerRun).order_by(ScannerRun.created_at.desc()).limit(limit).all()
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
            created_at=run.created_at,
        )
        for run in runs
    ]


@router.get("/results", response_model=List[ScannerEventResponse])
def get_scanner_results(
    ticker: Optional[str] = None,
    scanner_type: Optional[str] = None,
    event_type: Optional[str] = None,  # Alias for backward compat
    universe_id: Optional[int] = None,
    sort_by: Optional[str] = "signal_quality_score",
    sort_order: Optional[str] = "desc",
    limit: int = 100,
    offset: int = 0,
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    db: Session = Depends(get_db),
):
    """Get scanner results with filtering."""
    query = db.query(ScannerEvent).options(joinedload(ScannerEvent.reviews))

    if ticker:
        query = query.filter(ScannerEvent.ticker == ticker.upper())

    # Support both scanner_type and the legacy event_type param
    stype = scanner_type or event_type
    if stype:
        # 'liquidity_hunt' is the umbrella type — include all three variants
        if stype == "liquidity_hunt":
            query = query.filter(
                ScannerEvent.scanner_type.in_(
                    ["liquidity_hunt", "liquidity_hunt_pre", "liquidity_hunt_post"]
                )
            )
        else:
            query = query.filter(ScannerEvent.scanner_type == stype)

    if universe_id:
        query = query.join(
            MonitoredStock,
            (ScannerEvent.ticker == MonitoredStock.ticker)
            & (MonitoredStock.universe_id == universe_id),
        )

    if start_date:
        query = query.filter(ScannerEvent.event_date >= start_date)
    if end_date:
        query = query.filter(ScannerEvent.event_date <= end_date)

    # Sorting logic
    try:
        if sort_by:
            sort_attr = getattr(ScannerEvent, sort_by, ScannerEvent.created_at)
            if sort_order.lower() == "desc":
                order_expr = sort_attr.desc().nulls_last()
            else:
                order_expr = sort_attr.asc().nulls_last()
            query = query.order_by(order_expr)
        else:
            query = query.order_by(
                ScannerEvent.signal_quality_score.desc().nulls_last()
            )
    except Exception:
        query = query.order_by(ScannerEvent.created_at.desc())

    results = query.limit(limit).offset(offset).all()

    return results


@router.get("/signal-quality-distribution")
def get_signal_quality_distribution(
    scanner_type: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """Returns avg eod_pct_change and follow_through rate per score decile for EdgeExplorer."""
    return ScannerQueryService.get_signal_quality_distribution(
        db, scanner_type=scanner_type, start_date=start_date, end_date=end_date
    )


@router.get("/stats", response_model=ScannerStatsResponse)
def get_scanner_stats(
    db: Session = Depends(get_db),
):
    """Get scanner statistics for the dashboard."""
    from datetime import datetime

    from sqlalchemy import func

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
        db.query(
            func.avg(
                sa.cast(
                    ScannerEvent.indicators["volume_spike_ratio"].astext, sa.Numeric
                )
            )
        )
        .filter(
            ScannerEvent.scanner_type.in_(
                [
                    "pre_market_volume_spike",
                    "liquidity_hunt",
                    "liquidity_hunt_pre",
                    "liquidity_hunt_post",
                ]
            )
        )
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

    return StatsService.get_edge_stats(
        db, ticker=ticker, period=period, scanner_type=scanner_type
    )


@router.get("/edge-distribution")
def get_edge_distribution(
    ticker: Optional[str] = None,
    scanner_type: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """Get distribution data for scatter plots."""
    from app.services.stats import StatsService

    return StatsService.get_distribution_data(
        db, ticker=ticker, scanner_type=scanner_type
    )


@router.get("/scan-status-block", response_model=ScannerStatusBlockResponse)
def get_scan_status_block(
    scanner_type: str,
    universe_id: Optional[int] = None,
    db: Session = Depends(get_db),
):
    """Rich status data for the Scan Status card."""
    data = ScannerQueryService.get_scan_status_block(
        db, scanner_type, universe_id=universe_id
    )
    return ScannerStatusBlockResponse(**data)


@router.get("/configs", response_model=List[ScannerConfigResponse])
def get_scanner_configs(
    db: Session = Depends(get_db),
):
    """Get all available scanner configurations."""
    return db.query(ScannerConfig).filter(ScannerConfig.is_active == True).all()


@router.get("/movers/pre-market", response_model=PreMarketMoversResponse)
def get_pre_market_movers(
    min_volume: int = 10000, limit: int = 100, db: Session = Depends(get_db)
):
    """Get top pre-market movers."""
    movers = StockDataService.get_pre_market_movers(
        db=db, min_volume=min_volume, limit=limit
    )

    # Map to schema if necessary, but the dicts should match
    return {
        "status": "success",
        "movers": movers,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@router.post("/run-range")
@limiter.limit(SCANNER_LIMIT)
def run_scanner_range(
    request: Request,
    body: ScannerRangeRequest,
    db: Session = Depends(get_db),
):
    """Enqueue a date-range scan for a single ticker as a background Celery task."""
    from app.tasks import run_range_scan

    task = run_range_scan.delay(
        ticker=body.ticker.upper(),
        scanner_types=body.scanner_types,
        start_date_str=body.start_date.isoformat(),
        end_date_str=body.end_date.isoformat(),
        fetch_missing_data=body.fetch_missing_data,
    )
    return {"task_id": task.id, "status": "queued"}


@router.delete("/events/{ticker}", response_model=ClearEventsResponse)
def clear_scanner_events(
    ticker: str,
    db: Session = Depends(get_db),
):
    """Delete all scanner events for the given ticker and return the count removed."""
    ticker = ticker.strip().upper()
    deleted = (
        db.query(ScannerEvent)
        .filter(ScannerEvent.ticker == ticker)
        .delete(synchronize_session=False)
    )
    db.commit()
    return ClearEventsResponse(ticker=ticker, deleted_count=deleted)


@router.post(
    "/events/{event_uuid}/review", response_model=SignalReviewResponse, status_code=201
)
def create_event_review(
    event_uuid: str,
    payload: SignalReviewRequest,
    db: Session = Depends(get_db),
):
    """Submit a verdict for a scanner event."""
    try:
        parsed_uuid = uuid.UUID(event_uuid)
    except ValueError:
        raise HTTPException(status_code=400, detail="invalid event UUID")

    event = db.query(ScannerEvent).filter(ScannerEvent.uuid == parsed_uuid).first()
    if not event:
        raise HTTPException(status_code=404, detail="ScannerEvent not found")

    review = SignalReview(
        scanner_event_id=event.id,
        verdict=payload.verdict,
        reject_reason=payload.reject_reason,
        notes=payload.notes,
        enhance_suggestion=payload.enhance_suggestion,
    )
    db.add(review)
    db.commit()
    db.refresh(review)
    return review


@router.get("/events/reviews", response_model=List[SignalReviewResponse])
def list_event_reviews(
    scanner_type: str = Query(...),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    verdict: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    """List reviews with optional filters."""
    query = db.query(
        SignalReview,
        ScannerEvent.ticker,
        ScannerEvent.event_date,
        ScannerEvent.scanner_type,
    ).join(ScannerEvent, SignalReview.scanner_event_id == ScannerEvent.id)
    if scanner_type == "liquidity_hunt":
        query = query.filter(
            ScannerEvent.scanner_type.in_(
                ["liquidity_hunt", "liquidity_hunt_pre", "liquidity_hunt_post"]
            )
        )
    else:
        query = query.filter(ScannerEvent.scanner_type == scanner_type)
    if start_date:
        query = query.filter(ScannerEvent.event_date >= start_date)
    if end_date:
        query = query.filter(ScannerEvent.event_date <= end_date)
    if verdict:
        query = query.filter(SignalReview.verdict == verdict)

    rows = query.order_by(ScannerEvent.event_date, ScannerEvent.ticker).all()

    return [
        SignalReviewResponse(
            id=review.id,
            scanner_event_id=review.scanner_event_id,
            verdict=review.verdict,
            reject_reason=review.reject_reason,
            notes=review.notes,
            enhance_suggestion=review.enhance_suggestion,
            reviewed_at=review.reviewed_at,
            reviewed_by=review.reviewed_by,
            ticker=ticker,
            event_date=str(event_date),
            scanner_type=stype,
        )
        for review, ticker, event_date, stype in rows
    ]


@router.get("/reviews/stats", response_model=SignalReviewStatsResponse)
def get_review_stats(
    scanner_type: Optional[str] = Query(None),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    db: Session = Depends(get_db),
):
    """Aggregate review stats: coverage, acceptance rate, by-type breakdown, top rejection reasons."""
    data = ScannerQueryService.get_review_stats(
        db, scanner_type=scanner_type, start_date=start_date, end_date=end_date
    )
    return SignalReviewStatsResponse(**data)
