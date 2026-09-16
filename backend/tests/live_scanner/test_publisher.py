import inspect
import json
from datetime import datetime, timezone
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


def test_write_scanner_event_persists_explanation(monkeypatch):
    from live_scanner.bar_aggregator import MinuteBar
    from live_scanner.conditions import ConditionResult
    from live_scanner.publisher import LivePublisher

    captured = {}

    class FakeSession:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def add(self, event):
            captured["event"] = event

        def commit(self):
            captured["event"].id = 42

        def refresh(self, event):
            event.id = 42

    monkeypatch.setattr(pub_mod, "SessionLocal", lambda: FakeSession())
    monkeypatch.setattr(
        pub_mod, "load_ranker_config", lambda session: {"enabled": False}
    )

    bar = MinuteBar(
        minute_ts=datetime(2026, 6, 2, 14, 31, tzinfo=timezone.utc),
        symbol="AAPL",
        open=100.0,
        high=103.0,
        low=99.5,
        close=102.5,
        volume=25000,
        vwap=101.8,
        bar_count=12,
        session="regular",
        session_volume=250000,
        minutes_elapsed=30.0,
        prior_close=100.0,
        avg_daily_volume=500000,
    )
    condition = ConditionResult(
        scanner_type="live_price_move",
        indicators={
            "price_move_pct": 2.5,
            "current_price": 102.5,
            "prior_close": 100.0,
            "session": "regular",
        },
        criteria_met={"price_move_1pct": True},
    )

    event_id = LivePublisher("redis://localhost:6379")._write_scanner_event(
        bar=bar,
        condition=condition,
        summary="AAPL live price move",
        severity="medium",
    )

    assert event_id == 42
    explanation = captured["event"].explanation
    assert explanation["schema_version"] == "scanner_explanation.v1"
    assert "live_price_move.price_move_1pct" in explanation["criteria_passed"]
    assert explanation["confidence_inputs"]["scanner_type"] == "live_price_move"
