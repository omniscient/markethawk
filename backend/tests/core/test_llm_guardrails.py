import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.core.llm_guardrails import build_llm_usage_guardrails

BASE_SETTINGS = {
    "DATABASE_URL": "postgresql://test:test@localhost/test",
    "POLYGON_API_KEY": "test-key",
    "JWT_SECRET_KEY": "a" * 32,
    "REDIS_PASSWORD": "r" * 16,
}


def make_settings(**overrides) -> Settings:
    return Settings(_env_file=None, **{**BASE_SETTINGS, **overrides})


def test_llm_features_are_disabled_by_default():
    settings = make_settings()

    guardrails = build_llm_usage_guardrails(settings)

    assert settings.LLM_FEATURES_ENABLED is False
    assert settings.llm_allowed_feature_set == frozenset()
    assert guardrails.enabled is False
    assert guardrails.allows("scanner_narrative") is False


def test_llm_config_parses_provider_model_and_guardrails():
    settings = make_settings(
        LLM_FEATURES_ENABLED=True,
        LLM_PROVIDER="OpenAI",
        LLM_MODEL="market-narrative-test",
        LLM_ALLOWED_FEATURES="scanner_narrative, semantic_search",
        LLM_MAX_TOKENS=1200,
        LLM_TIMEOUT_SECONDS=12.5,
        LLM_MAX_RETRIES=2,
        LLM_RETRY_BACKOFF_SECONDS=0.25,
    )

    guardrails = build_llm_usage_guardrails(settings)

    assert settings.LLM_PROVIDER == "openai"
    assert settings.llm_allowed_feature_set == frozenset(
        {"scanner_narrative", "semantic_search"}
    )
    assert guardrails.provider == "openai"
    assert guardrails.model == "market-narrative-test"
    assert guardrails.max_tokens == 1200
    assert guardrails.timeout_seconds == 12.5
    assert guardrails.max_retries == 2
    assert guardrails.retry_backoff_seconds == 0.25
    assert guardrails.allows("scanner_narrative") is True
    assert guardrails.allows("analyst_qa") is False


def test_llm_config_parses_from_environment(monkeypatch):
    for key, value in BASE_SETTINGS.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("LLM_FEATURES_ENABLED", "true")
    monkeypatch.setenv("LLM_PROVIDER", "local")
    monkeypatch.setenv("LLM_MODEL", "local-narrative")
    monkeypatch.setenv("LLM_ALLOWED_FEATURES", "post_mortem,analyst_qa")
    monkeypatch.setenv("LLM_MAX_TOKENS", "640")
    monkeypatch.setenv("LLM_TIMEOUT_SECONDS", "4.5")
    monkeypatch.setenv("LLM_MAX_RETRIES", "0")
    monkeypatch.setenv("LLM_RETRY_BACKOFF_SECONDS", "0.75")

    settings = Settings(_env_file=None)

    assert settings.LLM_FEATURES_ENABLED is True
    assert settings.LLM_PROVIDER == "local"
    assert settings.llm_allowed_feature_set == frozenset({"post_mortem", "analyst_qa"})
    assert settings.LLM_MAX_TOKENS == 640
    assert settings.LLM_TIMEOUT_SECONDS == 4.5
    assert settings.LLM_MAX_RETRIES == 0
    assert settings.LLM_RETRY_BACKOFF_SECONDS == 0.75


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("LLM_MAX_TOKENS", 0),
        ("LLM_TIMEOUT_SECONDS", 0),
        ("LLM_MAX_RETRIES", -1),
        ("LLM_RETRY_BACKOFF_SECONDS", 0),
    ],
)
def test_llm_numeric_guardrails_must_be_positive(field, value):
    with pytest.raises(ValidationError):
        make_settings(**{field: value})


def test_enabled_llm_requires_real_provider_and_model():
    with pytest.raises(ValidationError, match="LLM_PROVIDER"):
        make_settings(LLM_FEATURES_ENABLED=True)

    with pytest.raises(ValidationError, match="LLM_MODEL"):
        make_settings(
            LLM_FEATURES_ENABLED=True,
            LLM_PROVIDER="openai",
        )


def test_llm_allowed_features_reject_unknown_feature_area():
    with pytest.raises(ValidationError, match="unknown_llm_feature"):
        make_settings(
            LLM_FEATURES_ENABLED=True,
            LLM_PROVIDER="openai",
            LLM_MODEL="market-narrative-test",
            LLM_ALLOWED_FEATURES="scanner_narrative,unknown_llm_feature",
        )
