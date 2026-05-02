"""
System-level information and status router.
"""

from typing import Dict, Any, Optional
from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session
from sqlalchemy import text
import logging
import asyncio
import json
import socket
import redis.asyncio as aioredis
from datetime import datetime, timezone
import zoneinfo

from app.core.database import get_db, SessionLocal
from app.models.universe_quality_report import UniverseQualityReport
from app.models.stock_universe import StockUniverse
from app.models.system_config import SystemConfig

router = APIRouter(prefix="/api/system", tags=["system"])
logger = logging.getLogger(__name__)

ET = zoneinfo.ZoneInfo("America/New_York")


def _market_status() -> str:
    """Return market session based on current ET time (weekday only)."""
    now_et = datetime.now(ET)
    if now_et.weekday() >= 5:
        return "closed"
    t = now_et.hour * 60 + now_et.minute
    if 240 <= t < 570:   # 04:00–09:30
        return "pre_market"
    if 570 <= t < 960:   # 09:30–16:00
        return "open"
    if 960 <= t < 1200:  # 16:00–20:00
        return "post_market"
    return "closed"


def _ibkr_reachable(host: str, port: int, timeout: float = 2.0) -> bool:
    try:
        sock = socket.create_connection((host, port), timeout=timeout)
        sock.close()
        return True
    except OSError:
        return False

def format_bytes(size: int) -> str:
    """Format bytes into a human-readable string."""
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} PB"

@router.get("/storage")
def get_storage_stats(db: Session = Depends(get_db)):
    """
    Get storage usage statistics for major database tables.
    Returns sizes in bytes and formatted strings.
    """
    try:
        # Define table groups as they appear in the UI
        table_groups = {
            "scanner": ["volume_events", "scanner_runs"],
            "historical": ["stock_aggregates", "stock_metrics", "ticker_references", "news_articles"],
            "settings": ["news_preferences", "scanner_configs"]
        }
        
        results = {
            "scanner": {"bytes": 0, "formatted": "0.0 B"},
            "historical": {"bytes": 0, "formatted": "0.0 B"},
            "settings": {"bytes": 0, "formatted": "0.0 B"},
            "total": {"bytes": 0, "formatted": "0.0 B"}
        }

        dialect = db.bind.dialect.name
        
        if dialect == "postgresql":
            # For PostgreSQL, we can get per-table sizes
            all_tables = []
            for group in table_groups.values():
                all_tables.extend(group)
            
            # Using a safer way to pass the list of tables for Postgres
            query = text("""
                SELECT 
                    relname as table_name,
                    pg_total_relation_size(relid) as total_size
                FROM pg_catalog.pg_statio_user_tables
                WHERE relname = ANY(:tables)
            """)
            
            db_results = db.execute(query, {"tables": all_tables}).fetchall()
            table_sizes = {row.table_name: row.total_size for row in db_results}
            
            for group_name, tables in table_groups.items():
                group_size = sum(table_sizes.get(t, 0) for t in tables)
                results[group_name]["bytes"] = group_size
                results[group_name]["formatted"] = format_bytes(group_size)
                results["total"]["bytes"] += group_size
        
        elif dialect == "sqlite":
            # For SQLite, the entire database is usually one file.
            # We'll get the total file size and label it as SQLITE
            import os
            db_url = str(db.bind.url)
            # Handle sqlite:///test.db or absolute paths
            db_path = db_url.replace("sqlite:///", "")
            
            total_size = 0
            if os.path.exists(db_path):
                total_size = os.path.getsize(db_path)
            
            # Since we can't easily break down SQLite by table group without 
            # complex queries, we'll assign the total to total and historical
            results["historical"]["bytes"] = total_size
            results["historical"]["formatted"] = f"{format_bytes(total_size)} (SQLite)"
            results["total"]["bytes"] = total_size
            results["total"]["formatted"] = f"{format_bytes(total_size)} (Full DB)"
        
        else:
            # Fallback for other dialects
            results["total"]["formatted"] = f"Unknown DB ({dialect})"

        results["total"]["formatted"] = format_bytes(results["total"]["bytes"])
        
        return results

    except Exception as e:
        logger.error(f"Error fetching storage stats: {e}", exc_info=True)
        # Final fallback to avoid 500ing the page
        return {
            "scanner": {"bytes": 0, "formatted": "N/A"},
            "historical": {"bytes": 0, "formatted": "N/A"},
            "settings": {"bytes": 0, "formatted": "N/A"},
            "total": {"bytes": 0, "formatted": "Service Error"}
        }

@router.get("/info", response_model=Dict[str, Any])
def get_app_info():
    """Get basic application information and configuration status."""
    from app.core.config import settings
    return {
        "name": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "data_mode": "delayed" if settings.POLYGON_DELAYED else "live",
        "log_level": settings.LOG_LEVEL
    }

@router.get("/status")
def get_system_status(db: Session = Depends(get_db)):
    """Lightweight status snapshot: market session, last scan, IBKR reachability."""
    from app.core.config import settings
    from app.models.scanner_run import ScannerRun

    # Last scan
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
        "market_status": _market_status(),
        "last_scan_at": last_scan_at,
        "ibkr_reachable": _ibkr_reachable(ibkr_host, ibkr_port),
        "ibkr_host": ibkr_host,
        "ibkr_port": ibkr_port,
    }


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
async def system_tasks_websocket(websocket: WebSocket):
    """
    WebSocket endpoint that aggregates and pushes active system tasks 
    (data syncing, analysis, normalization) to clients every 2 seconds.
    """
    from app.core.config import settings
    await websocket.accept()
    
    redis_client = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
    
    try:
        while True:
            active_tasks = []
            
            # 1. Check Redis for active syncs
            sync_keys = []
            cursor = '0'
            while True:
                cursor, keys = await redis_client.scan(cursor=cursor, match="universe:*:sync", count=100)
                sync_keys.extend(keys)
                if cursor == 0 or cursor == '0' or str(cursor) == '0':
                    break
                    
            from datetime import datetime, timezone
            from celery.result import AsyncResult
            from app.core.celery_app import celery_app

            db = SessionLocal()
            try:
                for key in sync_keys:
                    parts = key.split(":")
                    if len(parts) >= 2 and parts[1].isdigit():
                        uid = int(parts[1])

                        raw = await redis_client.get(key)
                        if not raw:
                            continue
                        data = json.loads(raw)

                        # Stale check: if started >4h ago, the key is a leftover — clean it up.
                        # AsyncResult returns "PENDING" for expired results, making done tasks
                        # look like they're still running. The 4h window covers all realistic syncs.
                        started_at_str = data.get("started_at")
                        if started_at_str:
                            try:
                                started_at = datetime.fromisoformat(started_at_str).replace(tzinfo=timezone.utc)
                                age_hours = (datetime.now(timezone.utc) - started_at).total_seconds() / 3600
                                if age_hours > 4:
                                    await redis_client.delete(key)
                                    continue
                            except (ValueError, TypeError):
                                pass

                        # Check actual Celery task states.
                        task_ids = data.get("task_ids", [])
                        pending = sum(
                            1 for tid in task_ids
                            if AsyncResult(tid, app=celery_app).state in ("PENDING", "STARTED", "RETRY")
                        )
                        if pending == 0:
                            # All tasks done — delete the key so it stops showing up.
                            await redis_client.delete(key)
                            continue

                        universe = db.query(StockUniverse).filter(StockUniverse.id == uid).first()
                        name = universe.name if universe else f"Universe {uid}"
                        active_tasks.append({
                            "id": f"sync_{uid}",
                            "type": "sync",
                            "title": f"Syncing Data: {name}",
                            "status": "running"
                        })
                
                # 1.5. Check Redis for active ticker syncs
                ticker_sync_keys = []
                cursor = '0'
                while True:
                    cursor, keys = await redis_client.scan(cursor=cursor, match="ticker:*:sync", count=100)
                    ticker_sync_keys.extend(keys)
                    if cursor == 0 or cursor == '0' or str(cursor) == '0':
                        break
                
                for key in ticker_sync_keys:
                    parts = key.split(":")
                    if len(parts) >= 2:
                        ticker = parts[1]
                        raw = await redis_client.get(key)
                        if not raw:
                            continue
                        try:
                            tdata = json.loads(raw)
                            ts_str = tdata.get("started_at")
                            if ts_str:
                                ts = datetime.fromisoformat(ts_str).replace(tzinfo=timezone.utc)
                                if (datetime.now(timezone.utc) - ts).total_seconds() / 3600 > 4:
                                    await redis_client.delete(key)
                                    continue
                            tids = tdata.get("task_ids", [])
                            if tids:
                                tpending = sum(
                                    1 for tid in tids
                                    if AsyncResult(tid, app=celery_app).state in ("PENDING", "STARTED", "RETRY")
                                )
                                if tpending == 0:
                                    await redis_client.delete(key)
                                    continue
                        except (ValueError, TypeError, AttributeError):
                            pass
                        active_tasks.append({
                            "id": f"sync_ticker_{ticker}",
                            "type": "sync",
                            "title": f"Syncing Data: {ticker}",
                            "status": "running"
                        })
                
                # 1.6. Check Redis for active range scans
                scan_keys = []
                cursor = '0'
                while True:
                    cursor, keys = await redis_client.scan(cursor=cursor, match="scan:*:range", count=100)
                    scan_keys.extend(keys)
                    if cursor == 0 or cursor == '0' or str(cursor) == '0':
                        break

                for key in scan_keys:
                    parts = key.split(":")
                    ticker_name = parts[1] if len(parts) >= 2 else "?"
                    raw = await redis_client.get(key)
                    if not raw:
                        continue
                    try:
                        sdata = json.loads(raw)
                        ts_str = sdata.get("started_at")
                        if ts_str:
                            ts = datetime.fromisoformat(ts_str).replace(tzinfo=timezone.utc)
                            if (datetime.now(timezone.utc) - ts).total_seconds() / 3600 > 4:
                                await redis_client.delete(key)
                                continue
                        tids = sdata.get("task_ids", [])
                        if tids:
                            tpending = sum(
                                1 for tid in tids
                                if AsyncResult(tid, app=celery_app).state in ("PENDING", "STARTED", "RETRY")
                            )
                            if tpending == 0:
                                await redis_client.delete(key)
                                continue
                    except (ValueError, TypeError, AttributeError):
                        pass
                    active_tasks.append({
                        "id": f"scan_{ticker_name}",
                        "type": "scan",
                        "title": f"Range Scan: {ticker_name}",
                        "status": "running",
                    })

                # 1.7. Check Redis for active universe scans
                #     Key shape: universe:{universe_id}:scan:{scanner_type}
                uscan_keys = []
                cursor = '0'
                while True:
                    cursor, keys = await redis_client.scan(cursor=cursor, match="universe:*:scan:*", count=100)
                    uscan_keys.extend(keys)
                    if cursor == 0 or cursor == '0' or str(cursor) == '0':
                        break

                for key in uscan_keys:
                    parts = key.split(":")
                    if len(parts) < 4 or not parts[1].isdigit():
                        continue
                    uid = int(parts[1])
                    scanner_type = parts[3]
                    raw = await redis_client.get(key)
                    if not raw:
                        continue
                    try:
                        udata = json.loads(raw)
                        ts_str = udata.get("started_at")
                        if ts_str:
                            ts = datetime.fromisoformat(ts_str).replace(tzinfo=timezone.utc)
                            if (datetime.now(timezone.utc) - ts).total_seconds() / 3600 > 4:
                                await redis_client.delete(key)
                                continue
                        tids = udata.get("task_ids", [])
                        if tids:
                            tpending = sum(
                                1 for tid in tids
                                if AsyncResult(tid, app=celery_app).state in ("PENDING", "STARTED", "RETRY")
                            )
                            if tpending == 0:
                                await redis_client.delete(key)
                                continue
                    except (ValueError, TypeError, AttributeError):
                        pass
                    universe = db.query(StockUniverse).filter(StockUniverse.id == uid).first()
                    universe_name = universe.name if universe else f"Universe {uid}"
                    day_idx = udata.get("day_index", 0) if isinstance(udata, dict) else 0
                    total_days = udata.get("total_days", 0) if isinstance(udata, dict) else 0
                    active_tasks.append({
                        "id": f"scan_{uid}_{scanner_type}",
                        "type": "scan",
                        "title": (
                            f"Scanning {universe_name}: {scanner_type.replace('_', ' ')}"
                            + (f" — day {day_idx}/{total_days}" if total_days else "")
                        ),
                        "status": "running",
                    })

                # 2. Check DB for quality and normalization tasks.
                # Auto-reset rows that have been stuck in pending/running for >4 hours
                # (worker crash without updating status).
                stale_cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - __import__('datetime').timedelta(hours=4)
                quality_reports = db.query(UniverseQualityReport).filter(
                    (UniverseQualityReport.status.in_(["pending", "running"])) |
                    (UniverseQualityReport.normalization_status.in_(["pending", "running"]))
                ).all()

                for report in quality_reports:
                    is_stale = report.started_at and report.started_at < stale_cutoff

                    if is_stale:
                        # Reset stuck rows so they don't show up forever
                        if report.status in ("pending", "running"):
                            report.status = "failed"
                        if report.normalization_status in ("pending", "running"):
                            report.normalization_status = "failed"
                        db.add(report)
                        db.commit()
                        continue

                    universe = db.query(StockUniverse).filter(StockUniverse.id == report.universe_id).first()
                    name = universe.name if universe else f"Universe {report.universe_id}"

                    if report.status in ["pending", "running"]:
                        active_tasks.append({
                            "id": f"qa_{report.universe_id}",
                            "type": "analysis",
                            "title": f"Quality Analysis: {name}",
                            "status": report.status
                        })

                    if report.normalization_status in ["pending", "running"]:
                        active_tasks.append({
                            "id": f"norm_{report.universe_id}",
                            "type": "normalization",
                            "title": f"Normalizing Data: {name}",
                            "status": report.normalization_status
                        })
                        
            except Exception as e:
                logger.error(f"Error querying active tasks for WS: {e}")
            finally:
                db.close()
                
            await websocket.send_json({"tasks": active_tasks})
            
            # Re-poll every 2.5 seconds
            await asyncio.sleep(2.5)
            
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.error(f"System tasks websocket error: {e}")
    finally:
        await redis_client.close()
