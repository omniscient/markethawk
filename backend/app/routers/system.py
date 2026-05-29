"""
System-level information and status router.
"""

import asyncio
import logging
from datetime import timezone
from typing import Any, Dict, Optional

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session

from app.core.cache import get_cached
from app.core.database import SessionLocal, get_db
from app.core.rate_limits import limiter
from app.models.system_config import SystemConfig
from app.services.system_service import SystemService

router = APIRouter(prefix="/api/v1/system", tags=["system"])
logger = logging.getLogger(__name__)


@router.get("/storage")
def get_storage_stats(db: Session = Depends(get_db)):
    """Get storage usage statistics for major database tables."""
    return get_cached("mh:system:storage", 300, lambda: SystemService.get_storage_stats(db))


@router.get("/info", response_model=Dict[str, Any])
def get_app_info():
    """Get basic application information and configuration status."""
    from app.core.config import settings

    return {
        "name": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "data_mode": "delayed" if settings.POLYGON_DELAYED else "live",
        "log_level": settings.LOG_LEVEL,
    }


@router.get("/status")
def get_system_status(db: Session = Depends(get_db)):
    """Lightweight status snapshot: market session, last scan, IBKR reachability."""
    from app.core.config import settings
    from app.models.scanner_run import ScannerRun

    def _fetch():
        last_run = db.query(ScannerRun).order_by(ScannerRun.created_at.desc()).first()
        last_scan_at: Optional[str] = None
        if last_run and last_run.created_at:
            ts = last_run.created_at
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            last_scan_at = ts.isoformat()

        ibkr_host = getattr(settings, "IBKR_HOST", "127.0.0.1")
        ibkr_port = int(getattr(settings, "IBKR_PORT", 7497))

        return {
            "market_status": SystemService.get_market_status(),
            "last_scan_at": last_scan_at,
            "ibkr_reachable": SystemService.check_ibkr_reachable(ibkr_host, ibkr_port),
            "ibkr_host": ibkr_host,
            "ibkr_port": ibkr_port,
        }

    return get_cached("mh:system:status", 30, _fetch)


@router.get("/config")
def get_config(db: Session = Depends(get_db)):
    """Return all system config keys as a flat dict."""
    rows = db.query(SystemConfig).all()
    return {row.key: row.value for row in rows}


@router.patch("/config")
def update_config(payload: Dict[str, Any], db: Session = Depends(get_db)):
    """Upsert one or more system config keys."""
    for key, value in payload.items():
        row = db.query(SystemConfig).filter(SystemConfig.key == key).first()
        if row:
            row.value = str(value)
        else:
            db.add(SystemConfig(key=key, value=str(value)))
    db.commit()
    rows = db.query(SystemConfig).all()
    return {row.key: row.value for row in rows}


@router.post("/apply-split-adjustments")
def apply_split_adjustments(db: Session = Depends(get_db)):
    """Manually trigger split adjustments for all pending splits."""
    from app.services.split_adjustment import SplitAdjustmentService

    results = SplitAdjustmentService.apply_all_pending(db)
    applied = [r for r in results if not r.get("skipped")]
    return {
        "total_checked": len(results),
        "applied": len(applied),
        "details": applied,
    }


@router.websocket("/ws/tasks")
@limiter.exempt
async def system_tasks_websocket(websocket: WebSocket):
    """
    WebSocket endpoint that aggregates and pushes active system tasks to clients every 2.5 seconds.
    """
    from app.core.config import settings

    await websocket.accept()

    redis_client = aioredis.from_url(settings.REDIS_URL, decode_responses=True)

    try:
        while True:
            db = SessionLocal()
            try:
                tasks = await SystemService.get_active_tasks(redis_client, db)
            finally:
                db.close()
            await websocket.send_json({"tasks": tasks})
            await asyncio.sleep(2.5)
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.error(f"System tasks websocket error: {e}")
    finally:
        await redis_client.close()
