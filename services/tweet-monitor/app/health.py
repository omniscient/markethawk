"""
HealthChecker: aggregates browser, DB, and Redis liveness into a single status dict.
Reports auth_expired as a distinct failure mode.
"""
from __future__ import annotations

import logging

import redis
from sqlalchemy import create_engine, text

import app.state as state
from app.browser import browser_manager
from app.config import settings

logger = logging.getLogger(__name__)

_engine = create_engine(settings.database_url, pool_pre_ping=True)


async def check_health() -> dict:
    browser_ok = browser_manager.is_running
    auth_expired = not state.auth_ok

    db_ok = _check_db()
    redis_ok = _check_redis()

    healthy = browser_ok and db_ok and redis_ok and not auth_expired

    return {
        "healthy": healthy,
        "browser": browser_ok,
        "browser_age_seconds": round(browser_manager.age_seconds),
        "db": db_ok,
        "redis": redis_ok,
        "auth_expired": auth_expired,
    }


def _check_db() -> bool:
    try:
        with _engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception as exc:
        logger.warning(f"DB health check failed: {exc}")
        return False


def _check_redis() -> bool:
    try:
        r = redis.from_url(settings.redis_url)
        r.ping()
        return True
    except Exception as exc:
        logger.warning(f"Redis health check failed: {exc}")
        return False
