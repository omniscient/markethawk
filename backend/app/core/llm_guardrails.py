from __future__ import annotations

from dataclasses import dataclass

from app.core.config import Settings


@dataclass(frozen=True)
class LLMUsageGuardrails:
    enabled: bool
    provider: str
    model: str
    max_tokens: int
    timeout_seconds: float
    max_retries: int
    retry_backoff_seconds: float
    allowed_features: frozenset[str]

    def allows(self, feature_area: str) -> bool:
        return self.enabled and feature_area in self.allowed_features


def build_llm_usage_guardrails(settings: Settings) -> LLMUsageGuardrails:
    return LLMUsageGuardrails(
        enabled=settings.LLM_FEATURES_ENABLED,
        provider=settings.LLM_PROVIDER,
        model=settings.LLM_MODEL,
        max_tokens=settings.LLM_MAX_TOKENS,
        timeout_seconds=settings.LLM_TIMEOUT_SECONDS,
        max_retries=settings.LLM_MAX_RETRIES,
        retry_backoff_seconds=settings.LLM_RETRY_BACKOFF_SECONDS,
        allowed_features=settings.llm_allowed_feature_set,
    )
