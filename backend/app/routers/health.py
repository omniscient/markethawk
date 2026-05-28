"""
Health check router.
"""

from datetime import datetime, timezone
from fastapi import APIRouter

from app.core.config import settings
from app.core.rate_limits import limiter

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
