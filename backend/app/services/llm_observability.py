from __future__ import annotations

from copy import deepcopy
from typing import Any

from app.core.config import Settings, settings
from app.core.llm_guardrails import build_llm_usage_guardrails


class LLMObservabilityService:
    """In-process LLM/embedding control and metrics snapshot service."""

    _metrics: dict[str, dict[str, Any]] = {}

    def __init__(self, *, settings: Settings = settings) -> None:
        self._settings = settings

    def reset(self) -> None:
        self._metrics.clear()

    def record_request(
        self,
        *,
        feature_area: str,
        status: str,
        latency_seconds: float,
        cache_status: str | None = None,
        input_tokens: int = 0,
        output_tokens: int = 0,
        cost_usd: float = 0.0,
        error: str | None = None,
    ) -> None:
        metric = self._metrics.setdefault(
            feature_area,
            {
                "request_count": 0,
                "latency_seconds_total": 0.0,
                "cache_hits": 0,
                "cache_observations": 0,
                "input_tokens": 0,
                "output_tokens": 0,
                "cost_usd": 0.0,
                "error_count": 0,
                "last_error": None,
            },
        )
        metric["request_count"] += 1
        metric["latency_seconds_total"] += latency_seconds
        if cache_status is not None:
            metric["cache_observations"] += 1
            if cache_status == "hit":
                metric["cache_hits"] += 1
        metric["input_tokens"] += input_tokens
        metric["output_tokens"] += output_tokens
        metric["cost_usd"] += cost_usd
        if status == "error":
            metric["error_count"] += 1
            metric["last_error"] = error

    def check_limits(
        self,
        *,
        feature_area: str,
        estimated_cost_usd: float,
        estimated_latency_seconds: float,
    ) -> dict[str, Any]:
        if (
            self._settings.LLM_MAX_COST_USD_PER_CALL > 0
            and estimated_cost_usd > self._settings.LLM_MAX_COST_USD_PER_CALL
        ):
            return _blocked("Estimated cost exceeds per-call limit.")
        if estimated_latency_seconds > self._settings.LLM_TIMEOUT_SECONDS:
            return _blocked("Estimated latency exceeds configured timeout.")
        guardrails = build_llm_usage_guardrails(self._settings)
        return {
            "allowed": guardrails.allows(feature_area),
            "status": "allowed" if guardrails.allows(feature_area) else "disabled",
            "reason": None if guardrails.allows(feature_area) else "Feature is disabled.",
            "deterministic_workflows_safe": True,
        }

    def status(self) -> dict[str, Any]:
        guardrails = build_llm_usage_guardrails(self._settings)
        provider_state = "disabled"
        if guardrails.enabled:
            provider_state = "available" if guardrails.provider == "local" else "degraded"
        return {
            "enabled": guardrails.enabled,
            "provider": guardrails.provider,
            "model": guardrails.model,
            "provider_state": provider_state,
            "allowed_features": sorted(guardrails.allowed_features),
            "limits": {
                "timeout_seconds": guardrails.timeout_seconds,
                "max_tokens": guardrails.max_tokens,
                "max_cost_usd_per_call": self._settings.LLM_MAX_COST_USD_PER_CALL,
            },
            "metrics": self.snapshot()["features"],
        }

    def snapshot(self) -> dict[str, Any]:
        features = {}
        for feature_area, metric in deepcopy(self._metrics).items():
            request_count = metric["request_count"]
            cache_observations = metric["cache_observations"]
            features[feature_area] = {
                "request_count": request_count,
                "cache_hit_rate": _rate(metric["cache_hits"], cache_observations),
                "input_tokens": metric["input_tokens"],
                "output_tokens": metric["output_tokens"],
                "cost_usd": metric["cost_usd"],
                "error_rate": _rate(metric["error_count"], request_count),
                "avg_latency_seconds": _rate(
                    metric["latency_seconds_total"],
                    request_count,
                ),
                "last_error": metric["last_error"],
            }
        return {"features": features}


def _blocked(reason: str) -> dict[str, Any]:
    return {
        "allowed": False,
        "status": "limit_exceeded",
        "reason": reason,
        "deterministic_workflows_safe": True,
    }


def _rate(numerator: float, denominator: float) -> float:
    if denominator == 0:
        return 0.0
    return numerator / denominator
