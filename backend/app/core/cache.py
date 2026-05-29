"""
Application-level Redis caching utilities.

Provides a shared Redis client factory and read-through cache helpers used by
route handlers to reduce repeated DB/provider calls for slowly-changing data.

All cache keys use the `mh:` prefix to avoid collisions with Celery and
live-scanner keys (which use `universe:*:scan:*` and `universe:*:sync` patterns).
"""

import json
from functools import lru_cache, wraps
from typing import Callable, Optional, TypeVar

import redis

from app.core.config import settings

T = TypeVar("T")


@lru_cache(maxsize=1)
def get_redis() -> Optional[redis.Redis]:
    """Return a process-scoped sync Redis client, or None if REDIS_URL is unset.

    The redis.Redis constructor does not connect eagerly; connection errors
    surface at command time and are caught inside get_cached/invalidate.
    """
    if not settings.REDIS_URL:
        return None
    return redis.Redis.from_url(
        settings.REDIS_URL,
        decode_responses=True,
        socket_connect_timeout=1,
        socket_timeout=0.5,
    )


def get_cached(key: str, ttl: int, fn: Callable[[], T]) -> T:
    """Return cached value if present; otherwise call fn(), cache, and return it.

    If Redis is unavailable or raises, calls fn() and returns without caching.
    fn() must return a JSON-serializable value.
    """
    r = get_redis()
    if r is not None:
        try:
            cached = r.get(key)
            if cached is not None:
                return json.loads(cached)
        except Exception:
            return fn()

        result = fn()
        try:
            r.setex(key, ttl, json.dumps(result))
        except Exception:
            pass
        return result

    return fn()


def invalidate(key: str) -> None:
    """Delete a single cache key. No-op if Redis is unavailable."""
    r = get_redis()
    if r is None:
        return
    try:
        r.delete(key)
    except Exception:
        pass


def invalidate_pattern(pattern: str) -> None:
    """Delete all keys matching a glob pattern (SCAN + DEL). No-op if Redis unavailable."""
    r = get_redis()
    if r is None:
        return
    try:
        for key in r.scan_iter(pattern):
            r.delete(key)
    except Exception:
        pass


def cache_response(key: str, ttl: int):
    """Decorator for parameter-less GET handlers. Wraps the handler body in get_cached()."""
    def decorator(fn: Callable) -> Callable:
        @wraps(fn)
        def wrapper(*args, **kwargs):
            return get_cached(key, ttl, lambda: fn(*args, **kwargs))
        return wrapper
    return decorator
