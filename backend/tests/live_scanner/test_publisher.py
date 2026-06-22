import inspect
import json
from unittest.mock import AsyncMock

import pytest

import live_scanner.publisher as pub_mod


def test_live_publisher_init_does_not_accept_db_url():
    """LivePublisher.__init__ must no longer have a db_url parameter."""
    sig = inspect.signature(pub_mod.LivePublisher.__init__)
    params = list(sig.parameters.keys())
    assert "db_url" not in params, (
        "db_url parameter must be removed from LivePublisher.__init__"
    )


def test_publisher_does_not_import_create_engine():
    """publisher.py must not import create_engine (uses SessionLocal instead)."""
    import ast
    import pathlib

    src = pathlib.Path(pub_mod.__file__).read_text()
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = [alias.name for alias in node.names]
            assert "create_engine" not in names, (
                "publisher.py must not import create_engine — use SessionLocal from app.core.database"
            )
    # Also assert Session import from sqlalchemy.orm is removed
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.module == "sqlalchemy.orm":
                names = [alias.name for alias in node.names]
                assert "Session" not in names, (
                    "publisher.py must not import Session from sqlalchemy.orm (dead import)"
                )


@pytest.mark.asyncio
async def test_publish_feed_loss_sends_to_watchlist_alerts():
    from live_scanner.publisher import LivePublisher

    publisher = LivePublisher("redis://localhost:6379")
    publisher._redis = AsyncMock()

    await publisher.publish_feed_loss()

    publisher._redis.publish.assert_awaited_once()
    channel, raw = publisher._redis.publish.call_args[0]
    assert channel == "watchlist:alerts"
    msg = json.loads(raw)
    assert msg["type"] == "feed_loss"
    assert "timestamp" in msg


@pytest.mark.asyncio
async def test_publish_feed_recovered_sends_to_watchlist_alerts():
    from live_scanner.publisher import LivePublisher

    publisher = LivePublisher("redis://localhost:6379")
    publisher._redis = AsyncMock()

    await publisher.publish_feed_recovered()

    publisher._redis.publish.assert_awaited_once()
    channel, raw = publisher._redis.publish.call_args[0]
    assert channel == "watchlist:alerts"
    msg = json.loads(raw)
    assert msg["type"] == "feed_recovered"
    assert "timestamp" in msg
