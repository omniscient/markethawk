import asyncio
from datetime import date
from unittest.mock import AsyncMock

import pytest

import app.services.scan_orchestrator as orchestrator
from app.services.scan_orchestrator import ScannerDescriptor, get_all, register, run


@pytest.fixture(autouse=True)
def isolated_registry():
    original = dict(orchestrator._REGISTRY)
    yield
    orchestrator._REGISTRY.clear()
    orchestrator._REGISTRY.update(original)


def test_register_adds_descriptor():
    fn = AsyncMock(return_value=[])
    desc = ScannerDescriptor(key="test", display_name="Test", description="d", run=fn)
    register(desc)
    assert "test" in orchestrator._REGISTRY
    assert orchestrator._REGISTRY["test"] is desc


def test_get_all_includes_registered():
    fn = AsyncMock(return_value=[])
    register(ScannerDescriptor(key="s1", display_name="S1", description="d", run=fn))
    assert any(d.key == "s1" for d in get_all())


def test_run_dispatches_to_registered_fn():
    expected = [{"ticker": "AAPL", "score": 90}]
    fn = AsyncMock(return_value=expected)
    register(
        ScannerDescriptor(key="mock_scan", display_name="Mock", description="m", run=fn)
    )
    today = date(2026, 5, 23)
    result = asyncio.run(run("mock_scan", ["AAPL"], db=None, event_date=today))
    assert result == expected
    fn.assert_awaited_once_with(
        ["AAPL"], None, today, scanner_run=None, gate_metadata=None
    )


def test_run_raises_for_unknown_type():
    with pytest.raises(ValueError, match="Unknown scanner type: 'does_not_exist'"):
        asyncio.run(run("does_not_exist", [], db=None, event_date=date.today()))


def test_scanner_descriptor_is_frozen():
    fn = AsyncMock(return_value=[])
    desc = ScannerDescriptor(key="k", display_name="D", description="d", run=fn)
    with pytest.raises(Exception):
        desc.key = "changed"  # type: ignore[misc]


def test_register_returns_descriptor():
    fn = AsyncMock(return_value=[])
    desc = ScannerDescriptor(key="ret", display_name="R", description="d", run=fn)
    returned = register(desc)
    assert returned is desc


def test_pre_market_scanner_registered():
    import app.services.pre_market_scan  # noqa: F401

    assert "pre_market_volume_spike" in orchestrator._REGISTRY
    desc = orchestrator._REGISTRY["pre_market_volume_spike"]
    assert desc.display_name == "Pre-Market Volume Spike"
    assert desc.supports_date_range is True


def test_oversold_bounce_scanner_registered():
    import app.services.oversold_bounce_scan  # noqa: F401

    assert "oversold_bounce" in orchestrator._REGISTRY
    desc = orchestrator._REGISTRY["oversold_bounce"]
    assert desc.display_name == "Oversold Bounce"
    assert desc.supports_date_range is True


def test_liquidity_hunt_variants_registered():
    import app.services.liquidity_hunt  # noqa: F401

    for key in ("liquidity_hunt", "liquidity_hunt_pre", "liquidity_hunt_post"):
        assert key in orchestrator._REGISTRY, f"Expected {key!r} in registry"


# ── New orchestration functions ────────────────────────────────────────────

from unittest.mock import patch

import fakeredis

from app.services.scan_orchestrator import (
    compute_next_run,
    get_scan_progress,
    request_scan_cancel,
)


def test_compute_next_run_returns_none_for_non_scheduled():
    assert compute_next_run("pre_market_volume_spike") is None


def test_compute_next_run_returns_future_weekday_for_liquidity_hunt():
    from datetime import datetime, timezone

    result = compute_next_run("liquidity_hunt")
    assert result is not None
    assert result > datetime.now(timezone.utc)
    assert result.weekday() < 5  # not a weekend


def test_compute_next_run_returns_value_for_pre_variant():
    result = compute_next_run("liquidity_hunt_pre")
    assert result is not None


def test_compute_next_run_returns_value_for_post_variant():
    result = compute_next_run("liquidity_hunt_post")
    assert result is not None


def test_get_scan_progress_returns_none_when_no_key():
    server = fakeredis.FakeRedis(decode_responses=True)
    with patch(
        "app.services.scan_orchestrator._redis.Redis.from_url", return_value=server
    ):
        result = get_scan_progress(
            "redis://localhost", universe_id=1, scanner_type="liquidity_hunt"
        )
    assert result is None


def test_request_scan_cancel_sets_redis_key():
    server = fakeredis.FakeRedis(decode_responses=True)
    with patch(
        "app.services.scan_orchestrator._redis.Redis.from_url", return_value=server
    ):
        request_scan_cancel("redis://localhost", "test-scan-uuid")
        assert server.get("scan_cancel:test-scan-uuid") == "1"
