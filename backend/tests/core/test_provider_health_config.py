"""Defaults for the #388 provider-health / degraded-feed settings (ADR-0013)."""

from app.core.config import settings


def test_provider_health_window_defaults():
    assert settings.PROVIDER_HEALTH_ERROR_WINDOW_SECONDS == 300
    assert settings.PROVIDER_HEALTH_LATENCY_WINDOW_SECONDS == 900
    assert settings.PROVIDER_HEALTH_MIN_CALLS == 20


def test_polygon_health_threshold_defaults():
    assert settings.POLYGON_HEALTH_ERROR_RATE_THRESHOLD == 0.25
    assert settings.POLYGON_HEALTH_LATENCY_P95_THRESHOLD_SECONDS == 5.0


def test_premarket_degradation_defaults():
    assert settings.PREMARKET_BAR_STALENESS_MINUTES == 10
    assert settings.PREMARKET_MIN_COVERAGE_RATIO == 0.5
