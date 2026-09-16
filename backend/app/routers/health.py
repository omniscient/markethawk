"""
Health check router.
"""

import time
from datetime import datetime, timezone

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.core.cache import get_redis
from app.core.config import settings
from app.core.database import SessionLocal
from app.core.rate_limits import limiter
from app.services.system_service import SystemService

router = APIRouter(prefix="/api", tags=["health"])


@router.get("/health")
@limiter.exempt
def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "version": settings.APP_VERSION,
    }


@router.get("/ready")
@limiter.exempt
def readiness_check():
    """Readiness probe — checks DB (SELECT 1) and Redis (PING).

    Returns HTTP 200 when all probes pass, HTTP 503 on any failure.
    Both probes always run (no short-circuit) with per-probe latency in ms.
    The live_data field is informational only and does not affect HTTP status.
    """
    probes = {}

    # DB probe — always runs first
    t0 = time.monotonic()
    try:
        db = SessionLocal()
        try:
            db.execute(text("SELECT 1"))
            probes["db"] = {
                "ok": True,
                "latency_ms": int((time.monotonic() - t0) * 1000),
            }
        finally:
            db.close()
    except Exception as exc:
        probes["db"] = {
            "ok": False,
            "latency_ms": int((time.monotonic() - t0) * 1000),
            "error": str(exc),
        }

    # Redis probe — always runs regardless of DB result
    t0 = time.monotonic()
    try:
        r = get_redis()
        if r is None:
            probes["redis"] = {
                "ok": False,
                "latency_ms": 0,
                "error": "Redis not configured",
            }
        else:
            r.ping()
            probes["redis"] = {
                "ok": True,
                "latency_ms": int((time.monotonic() - t0) * 1000),
            }
    except Exception as exc:
        probes["redis"] = {
            "ok": False,
            "latency_ms": int((time.monotonic() - t0) * 1000),
            "error": str(exc),
        }

    # IBKR probe — informational only, does not affect HTTP status
    t0 = time.monotonic()
    try:
        ok = SystemService.check_ibkr_reachable(settings.IBKR_HOST, settings.IBKR_PORT)
        probes["live_data"] = {
            "ok": ok,
            "latency_ms": int((time.monotonic() - t0) * 1000),
        }
    except Exception as exc:
        probes["live_data"] = {
            "ok": False,
            "latency_ms": int((time.monotonic() - t0) * 1000),
            "error": str(exc),
        }

    # Only DB and Redis gate the HTTP status — live_data is non-fatal
    all_ok = probes["db"]["ok"] and probes["redis"]["ok"]
    status_code = 200 if all_ok else 503
    return JSONResponse(
        status_code=status_code,
        content={
            "status": "ready" if all_ok else "not ready",
            "db": probes["db"],
            "redis": probes["redis"],
            "live_data": probes["live_data"],
        },
    )
