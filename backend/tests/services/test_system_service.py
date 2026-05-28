"""Tests for SystemService."""
import socket
from datetime import datetime
from unittest.mock import MagicMock, patch

import fakeredis.aioredis
import pytest

from app.services.system_service import SystemService


# ── get_market_status ──────────────────────────────────────────────────────

@pytest.mark.parametrize("hour,minute,weekday,expected", [
    (3, 59, 0, "closed"),       # before pre-market on Monday
    (4, 0, 0, "pre_market"),    # 04:00 ET Monday
    (9, 29, 1, "pre_market"),   # 09:29 ET Tuesday
    (9, 30, 2, "open"),         # 09:30 ET Wednesday
    (15, 59, 3, "open"),        # 15:59 ET Thursday
    (16, 0, 4, "post_market"),  # 16:00 ET Friday
    (19, 59, 4, "post_market"), # 19:59 ET Friday
    (20, 0, 4, "closed"),       # 20:00 ET Friday
    (12, 0, 5, "closed"),       # Saturday
    (12, 0, 6, "closed"),       # Sunday
])
def test_get_market_status(hour, minute, weekday, expected):
    fake_now = MagicMock()
    fake_now.weekday.return_value = weekday
    fake_now.hour = hour
    fake_now.minute = minute
    with patch("app.services.system_service._now_et", return_value=fake_now):
        result = SystemService.get_market_status()
    assert result == expected


# ── check_ibkr_reachable ──────────────────────────────────────────────────

def test_check_ibkr_reachable_returns_true_on_success():
    mock_sock = MagicMock()
    mock_sock.__enter__ = MagicMock(return_value=mock_sock)
    mock_sock.__exit__ = MagicMock(return_value=False)
    with patch("socket.create_connection", return_value=mock_sock):
        assert SystemService.check_ibkr_reachable("127.0.0.1", 7497) is True


def test_check_ibkr_reachable_returns_false_on_oserror():
    with patch("socket.create_connection", side_effect=OSError("refused")):
        assert SystemService.check_ibkr_reachable("127.0.0.1", 7497) is False


# ── format_bytes ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("size,expected", [
    (0, "0.0 B"),
    (512, "512.0 B"),
    (1024, "1.0 KB"),
    (1024 * 1024, "1.0 MB"),
    (1024 ** 3, "1.0 GB"),
])
def test_format_bytes(size, expected):
    assert SystemService.format_bytes(size) == expected


# ── get_storage_stats ─────────────────────────────────────────────────────

def test_get_storage_stats_returns_dict(db):
    result = SystemService.get_storage_stats(db)
    assert "scanner" in result
    assert "historical" in result
    assert "settings" in result
    assert "total" in result
    assert "bytes" in result["total"]
    assert "formatted" in result["total"]


# ── get_active_tasks ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_active_tasks_empty_on_no_keys(db):
    redis_client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    tasks = await SystemService.get_active_tasks(redis_client, db)
    assert tasks == []


@pytest.mark.asyncio
async def test_get_active_tasks_skips_stale_sync_key(db):
    import json
    from datetime import timezone, timedelta

    redis_client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    old_ts = (datetime.now(timezone.utc) - timedelta(hours=5)).isoformat()
    await redis_client.set("universe:1:sync", json.dumps({
        "started_at": old_ts,
        "task_ids": ["abc"],
    }))
    tasks = await SystemService.get_active_tasks(redis_client, db)
    assert tasks == []
    # Key must be deleted after stale detection
    assert await redis_client.get("universe:1:sync") is None
