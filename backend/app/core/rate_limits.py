"""Rate limiting constants and limiter instance (SlowAPI, issue #87).

The limiter lives here (not main.py) to avoid circular imports: main.py
imports all routers, and routers need to import limiter.
"""

from slowapi import Limiter
from slowapi.util import get_remote_address
from app.core.config import settings

GLOBAL_LIMIT = "100/minute"
SCANNER_LIMIT = "5/minute"
TRADING_LIMIT = "10/minute"


def _build_limiter() -> Limiter:
    # headers_enabled=False: suppresses X-RateLimit-* headers on every response.
    if not settings.RATE_LIMITING_ENABLED:
        # enabled=False is SlowAPI's purpose-built no-op — neither middleware nor
        # decorator auto_check will enforce limits.
        return Limiter(key_func=get_remote_address, headers_enabled=False, enabled=False)
    # rsplit('/', 1) safely strips the trailing /0 db segment.
    rate_redis_url = settings.REDIS_URL.rsplit("/", 1)[0] + "/1"
    return Limiter(
        key_func=get_remote_address,
        default_limits=[GLOBAL_LIMIT],
        storage_uri=rate_redis_url,
        headers_enabled=False,
    )


limiter = _build_limiter()
