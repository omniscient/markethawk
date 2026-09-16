"""
In-process WebSocket connection counters for per-user and global caps.

Single-process deployment only — counters are in-memory defaultdict(int).
For multi-replica deployments, replace with a Redis-backed counter.
"""

import logging
from collections import defaultdict
from contextlib import asynccontextmanager

from fastapi import WebSocketException

from app.core.config import settings

logger = logging.getLogger(__name__)

_per_user_counts: dict[str, int] = defaultdict(int)
_global_count: int = 0


@asynccontextmanager
async def ws_connection_slot(user_id: str):
    """Async context manager that reserves a WS connection slot for *user_id*.

    Raises WebSocketException(1008) before the slot is granted when either the
    per-user or global cap would be exceeded.  Releases the slot on exit.
    """
    global _global_count

    if _per_user_counts[user_id] >= settings.WS_MAX_CONNECTIONS_PER_USER:
        raise WebSocketException(
            code=1008,
            reason=f"per-user connection limit ({settings.WS_MAX_CONNECTIONS_PER_USER}) reached",
        )
    if _global_count >= settings.WS_MAX_CONNECTIONS_GLOBAL:
        raise WebSocketException(
            code=1008,
            reason=f"global connection limit ({settings.WS_MAX_CONNECTIONS_GLOBAL}) reached",
        )

    _per_user_counts[user_id] += 1
    _global_count += 1
    try:
        yield
    finally:
        _per_user_counts[user_id] -= 1
        if _per_user_counts[user_id] == 0:
            del _per_user_counts[user_id]
        _global_count -= 1


def get_per_user_count(user_id: str) -> int:
    return _per_user_counts.get(user_id, 0)


def get_global_count() -> int:
    return _global_count


def reset_counts() -> None:
    """Reset all counters — for use in tests only."""
    global _global_count
    _per_user_counts.clear()
    _global_count = 0
