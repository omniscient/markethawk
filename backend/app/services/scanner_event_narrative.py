from __future__ import annotations

import hashlib
import json
from typing import Any, Protocol

from sqlalchemy.orm import Session

from app.core.config import Settings, settings
from app.core.llm_guardrails import LLMUsageGuardrails, build_llm_usage_guardrails
from app.models.scanner_event import ScannerEvent
from app.models.scanner_event_narrative import ScannerEventNarrative
from app.services.ai_signal_brief import AISignalBriefService

SCANNER_NARRATIVE_FEATURE = "scanner_narrative"
SCANNER_NARRATIVE_PROMPT_VERSION = "scanner_narrative.v1"


class ScannerNarrativeGenerator(Protocol):
    provider_name: str
    model_name: str

    def generate(
        self,
        brief: dict[str, Any],
        guardrails: LLMUsageGuardrails,
    ) -> str: ...


class LocalBriefNarrativeGenerator:
    """Grounded local renderer for scanner narratives.

    This intentionally reads only the deterministic brief facts and risks. External
    provider integration can replace this generator without changing cache policy.
    """

    provider_name = "local"
    model_name = "grounded-template-v1"

    def generate(
        self,
        brief: dict[str, Any],
        guardrails: LLMUsageGuardrails,
    ) -> str:
        facts = brief.get("facts") or {}
        risks = list(brief.get("risks") or [])
        ticker = facts.get("ticker") or "Unknown ticker"
        scanner_type = facts.get("scanner_type") or "unknown scanner"
        event_date = facts.get("event_date") or "unknown date"
        severity = facts.get("severity") or "unknown severity"
        summary = facts.get("summary") or "No summary provided."
        score = facts.get("signal_quality_score")

        score_text = f" Signal quality score: {score}." if score is not None else ""
        risk_text = " Key risks: " + "; ".join(risks) if risks else " Key risks: none listed."
        return (
            f"{ticker} produced a {severity} {scanner_type} signal on {event_date}. "
            f"{summary}.{score_text}{risk_text}"
        )


class ScannerEventNarrativeService:
    def __init__(
        self,
        *,
        brief_service: AISignalBriefService | None = None,
        generator: ScannerNarrativeGenerator | None = None,
        settings: Settings = settings,
    ) -> None:
        self._brief_service = brief_service or AISignalBriefService()
        self._settings = settings
        self._generator = generator or LocalBriefNarrativeGenerator()

    def build(self, db: Session, event: ScannerEvent) -> dict[str, Any]:
        brief = self._brief_service.build(db, event)
        guardrails = build_llm_usage_guardrails(self._settings)

        if not guardrails.allows(SCANNER_NARRATIVE_FEATURE):
            return {
                "brief": brief,
                "narrative": None,
                "cache": {"status": "disabled"},
                "guardrails": guardrails,
            }

        input_payload = _narrative_input_payload(brief)
        fingerprint = _brief_fingerprint(brief)
        cache = self._cache_query(db, event, guardrails).first()
        if cache and cache.brief_fingerprint == fingerprint:
            return {
                "brief": brief,
                "narrative": self._narrative_payload(cache),
                "cache": {"status": "hit"},
                "guardrails": guardrails,
            }

        narrative_text = self._generator.generate(brief, guardrails)
        status = "stale_regenerated" if cache else "miss"
        if cache is None:
            cache = ScannerEventNarrative(
                scanner_event_id=event.id,
                feature_area=SCANNER_NARRATIVE_FEATURE,
                provider=guardrails.provider,
                model=guardrails.model,
                prompt_version=SCANNER_NARRATIVE_PROMPT_VERSION,
            )
            db.add(cache)

        cache.narrative_text = narrative_text
        cache.brief_schema_version = str(brief.get("schema_version") or "")
        cache.brief_fingerprint = fingerprint
        cache.input_payload = input_payload
        db.flush()

        return {
            "brief": brief,
            "narrative": self._narrative_payload(cache),
            "cache": {"status": status},
            "guardrails": guardrails,
        }

    def _cache_query(
        self,
        db: Session,
        event: ScannerEvent,
        guardrails: LLMUsageGuardrails,
    ):
        return db.query(ScannerEventNarrative).filter(
            ScannerEventNarrative.scanner_event_id == event.id,
            ScannerEventNarrative.feature_area == SCANNER_NARRATIVE_FEATURE,
            ScannerEventNarrative.provider == guardrails.provider,
            ScannerEventNarrative.model == guardrails.model,
            ScannerEventNarrative.prompt_version == SCANNER_NARRATIVE_PROMPT_VERSION,
        )

    def _narrative_payload(self, cache: ScannerEventNarrative) -> dict[str, Any]:
        return {
            "text": cache.narrative_text,
            "provider": cache.provider,
            "model": cache.model,
            "prompt_version": cache.prompt_version,
            "brief_schema_version": cache.brief_schema_version,
            "brief_fingerprint": cache.brief_fingerprint,
            "created_at": cache.created_at.isoformat() if cache.created_at else None,
            "updated_at": cache.updated_at.isoformat() if cache.updated_at else None,
        }


def _narrative_input_payload(brief: dict[str, Any]) -> dict[str, Any]:
    return {
        "facts": brief.get("facts") or {},
        "risks": list(brief.get("risks") or []),
    }


def _brief_fingerprint(brief: dict[str, Any]) -> str:
    payload = {
        "schema_version": brief.get("schema_version"),
        **_narrative_input_payload(brief),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
