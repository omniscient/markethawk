from app.core.config import Settings
from app.services.llm_observability import LLMObservabilityService

BASE_SETTINGS = {
    "DATABASE_URL": "postgresql://test:test@localhost/test",
    "POLYGON_API_KEY": "test-key",
    "JWT_SECRET_KEY": "a" * 32,
    "REDIS_PASSWORD": "r" * 16,
}


def make_settings(**overrides) -> Settings:
    return Settings(_env_file=None, **{**BASE_SETTINGS, **overrides})


def enabled_settings(**overrides) -> Settings:
    values = {
        "LLM_FEATURES_ENABLED": True,
        "LLM_PROVIDER": "local",
        "LLM_MODEL": "unit-model",
        "LLM_ALLOWED_FEATURES": "scanner_narrative",
        "LLM_TIMEOUT_SECONDS": 2.0,
        "LLM_MAX_COST_USD_PER_CALL": 0.01,
    }
    values.update(overrides)
    return make_settings(**values)


def test_metrics_snapshot_tracks_counts_cache_tokens_cost_latency_and_errors():
    service = LLMObservabilityService(settings=enabled_settings())
    service.reset()

    service.record_request(
        feature_area="scanner_narrative",
        status="success",
        latency_seconds=0.25,
        cache_status="hit",
        input_tokens=100,
        output_tokens=50,
        cost_usd=0.002,
    )
    service.record_request(
        feature_area="scanner_narrative",
        status="error",
        latency_seconds=0.75,
        cache_status="miss",
        input_tokens=20,
        output_tokens=0,
        cost_usd=0.0,
        error="provider timeout",
    )

    snapshot = service.snapshot()["features"]["scanner_narrative"]

    assert snapshot["request_count"] == 2
    assert snapshot["cache_hit_rate"] == 0.5
    assert snapshot["input_tokens"] == 120
    assert snapshot["output_tokens"] == 50
    assert snapshot["cost_usd"] == 0.002
    assert snapshot["error_rate"] == 0.5
    assert snapshot["avg_latency_seconds"] == 0.5
    assert snapshot["last_error"] == "provider timeout"


def test_limit_check_fails_closed_for_cost_or_latency_without_throwing():
    service = LLMObservabilityService(settings=enabled_settings())

    cost = service.check_limits(
        feature_area="scanner_narrative",
        estimated_cost_usd=0.02,
        estimated_latency_seconds=0.5,
    )
    latency = service.check_limits(
        feature_area="scanner_narrative",
        estimated_cost_usd=0.001,
        estimated_latency_seconds=3.0,
    )

    assert cost == {
        "allowed": False,
        "status": "limit_exceeded",
        "reason": "Estimated cost exceeds per-call limit.",
        "deterministic_workflows_safe": True,
    }
    assert latency["allowed"] is False
    assert latency["reason"] == "Estimated latency exceeds configured timeout."


def test_disabled_status_exposes_provider_state():
    service = LLMObservabilityService(settings=make_settings())

    status = service.status()

    assert status["enabled"] is False
    assert status["provider_state"] == "disabled"
    assert status["allowed_features"] == []
