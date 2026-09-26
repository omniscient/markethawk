"""Every Polygon REST call feeds the provider-health record (#388)."""

from unittest.mock import MagicMock

import pytest

from app.core.circuit_breakers import POLYGON_BREAKER
from app.exceptions import ProviderError
from app.providers.massive import MassiveDataProvider


@pytest.fixture(autouse=True)
def _reset_breaker():
    POLYGON_BREAKER.close()
    yield
    POLYGON_BREAKER.close()


@pytest.fixture
def recorded(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "app.core.provider_health.record_provider_call",
        lambda provider, endpoint, ok, latency_s, now=None: calls.append(
            (provider, endpoint, ok)
        ),
    )
    return calls


def _provider():
    p = MassiveDataProvider.__new__(MassiveDataProvider)
    p._client = MagicMock()
    return p


def _bars(p):
    return p.get_bars("AAPL", "minute", 1, "2026-06-01", "2026-06-02")


def test_get_bars_success_recorded(recorded):
    p = _provider()
    p._client.get_aggs.return_value = []
    assert _bars(p) == []
    assert recorded == [("polygon", "aggs", True)]


def test_get_bars_network_failure_recorded(recorded):
    p = _provider()
    p._client.get_aggs.side_effect = ConnectionError("egress blocked")
    with pytest.raises(ProviderError):
        _bars(p)
    assert recorded == [("polygon", "aggs", False)]


def test_plan_limit_error_is_not_a_health_failure(recorded):
    p = _provider()
    p._client.get_aggs.side_effect = Exception('{"status":"NOT_AUTHORIZED"}')
    with pytest.raises(ProviderError):
        _bars(p)
    assert recorded == [("polygon", "aggs", True)]


def test_ticker_details_recorded(recorded):
    p = _provider()
    p._client.get_ticker_details.side_effect = ConnectionError("egress blocked")
    assert p.get_ticker_details("AAPL") == {}
    assert recorded == [("polygon", "ticker_details", False)]


def test_snapshots_recorded(recorded):
    p = _provider()
    p._client.get_snapshot_all.return_value = []
    assert p.get_snapshots() == []
    assert recorded == [("polygon", "snapshot_all", True)]


def test_snapshot_extras_recorded(recorded):
    p = _provider()
    p._client.get_snapshot_all.side_effect = ConnectionError("egress blocked")
    p._client.get_snapshot_ticker.side_effect = ConnectionError("egress blocked")
    assert p.get_snapshot_all() == []
    assert p.get_snapshot_price("AAPL") is None
    assert recorded == [
        ("polygon", "snapshot_all", False),
        ("polygon", "snapshot_ticker", False),
    ]
