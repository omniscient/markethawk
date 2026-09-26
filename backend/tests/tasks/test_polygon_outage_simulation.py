"""Acceptance (#388): a blocked-egress Polygon outage yields a degraded, never
empty-but-green, scan — and does not hang."""

import time
from datetime import date, datetime
from unittest.mock import MagicMock, patch

import fakeredis
import pytest

from app.core import provider_health as ph
from app.core.circuit_breakers import POLYGON_BREAKER
from app.exceptions import ProviderError
from app.providers.massive import MassiveDataProvider
from tests.tasks.test_scanning_tasks import (
    _make_assessment,
    _make_db,
    _make_run,
    _make_ticker,
)


@pytest.fixture
def outage(monkeypatch):
    server = fakeredis.FakeRedis(decode_responses=True)
    monkeypatch.setattr(ph, "get_redis", lambda: server)
    monkeypatch.setattr(ph, "_redis_backoff_until", 0.0)
    POLYGON_BREAKER.close()
    yield server
    POLYGON_BREAKER.close()


def _blocked_provider():
    p = MassiveDataProvider.__new__(MassiveDataProvider)
    p._client = MagicMock()
    p._client.get_aggs.side_effect = ConnectionError("egress to api.polygon.io blocked")
    return p


def test_blocked_egress_trips_health_and_stops_live_scan(outage):
    provider = _blocked_provider()
    # Ingestion pipeline hammering Polygon during the outage.
    for _ in range(25):
        with pytest.raises(ProviderError):
            provider.get_bars("AAPL", "minute", 1, "2026-06-02", "2026-06-02")

    snap = ph.get_provider_health("polygon")
    assert snap.breaker_state == "open"
    assert snap.errors_error_window >= 5
    assert ph.worker_id() in snap.breaker_open_workers

    from app.tasks.scanning import _run_universe_scan_logic

    run = _make_run("scan-outage")
    run.quality_gate = None
    published = []
    db = _make_db(run=run, tickers=[_make_ticker("AAPL")])
    started = time.monotonic()
    with (
        patch(
            "app.services.quality_gate.QualityGateService.assess",
            return_value=_make_assessment("trusted"),
        ),
        patch("app.tasks.scanning._compute_data_degraded", return_value=False),
        patch("app.tasks.scanning.utc_now", return_value=datetime(2026, 6, 2, 12, 0)),
    ):
        _run_universe_scan_logic(
            scan_id="scan-outage",
            scanner_type="pre_market_volume_spike",
            universe_id=1,
            start=date(2026, 6, 2),
            end=date(2026, 6, 2),
            db=db,
            publish=published.append,
            is_cancelled=lambda: False,
            task_id="task-outage",
        )
    assert time.monotonic() - started < 5  # no hang
    assert run.status == "failed"  # never "completed" on a dead feed
    assert run.data_degraded is True
    reasons = {
        i["detail"]["reason"]
        for i in run.quality_gate["issues"]
        if i["detail"].get("subtype") == "live_degradation"
    }
    assert "breaker_open" in reasons
    assert published[-1]["type"] == "failed"


def test_polygon_recovery_clears_signal(outage):
    ph.record_breaker_state("polygon", "open", now=time.time() - 400)  # long ago
    POLYGON_BREAKER.close()
    assert ph.get_provider_health("polygon").breaker_state == "closed"
