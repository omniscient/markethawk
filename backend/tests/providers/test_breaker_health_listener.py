"""POLYGON_BREAKER state changes are recorded to the provider-health store (#388)."""

import pybreaker
import pytest

from app.core.circuit_breakers import POLYGON_BREAKER, HealthRecordingListener


def _boom():
    raise RuntimeError("egress blocked")


def test_listener_records_open_state(monkeypatch):
    seen = []
    monkeypatch.setattr(
        "app.core.provider_health.record_breaker_state",
        lambda provider, state, now=None: seen.append((provider, state)),
    )
    breaker = pybreaker.CircuitBreaker(
        fail_max=1, reset_timeout=60, listeners=[HealthRecordingListener("polygon")]
    )
    with pytest.raises(Exception):
        breaker.call(_boom)
    assert ("polygon", "open") in seen


def test_listener_never_raises(monkeypatch):
    def _explode(provider, state, now=None):
        raise ConnectionError("redis down")

    monkeypatch.setattr("app.core.provider_health.record_breaker_state", _explode)
    breaker = pybreaker.CircuitBreaker(
        fail_max=1, reset_timeout=60, listeners=[HealthRecordingListener("polygon")]
    )
    with pytest.raises(pybreaker.CircuitBreakerError):
        breaker.call(_boom)  # listener error must not replace the breaker error
    assert breaker.current_state == "open"


def test_polygon_breaker_has_health_listener():
    assert any(
        isinstance(listener, HealthRecordingListener) and listener.provider == "polygon"
        for listener in POLYGON_BREAKER.listeners
    )
