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
SUPPORTED_PROVENANCE_FIELDS = frozenset(
    {
        "facts.ticker",
        "facts.event_date",
        "facts.scanner_type",
        "facts.severity",
        "facts.summary",
        "facts.signal_quality_score",
        "facts.regime",
        "risks",
    }
)


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

        generated = _normalize_generated_narrative(
            self._generator.generate(brief, guardrails),
            input_payload,
        )
        rejection_reason = _rejection_reason(generated, brief, input_payload)
        if rejection_reason:
            return {
                "brief": brief,
                "narrative": None,
                "cache": {"status": "rejected"},
                "rejection": {"reason": rejection_reason},
                "guardrails": guardrails,
            }

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

        cache.narrative_text = generated["text"]
        cache.brief_schema_version = str(brief.get("schema_version") or "")
        cache.brief_fingerprint = fingerprint
        cache.input_payload = input_payload
        cache.provenance_payload = generated["provenance"]
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
            "provenance": list(cache.provenance_payload or []),
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


def _normalize_generated_narrative(
    generated: str | dict[str, Any],
    input_payload: dict[str, Any],
) -> dict[str, Any]:
    if isinstance(generated, str):
        return {
            "text": generated,
            "provenance": _default_provenance(input_payload),
        }
    if not isinstance(generated, dict):
        return {"text": "", "provenance": []}
    return {
        "text": generated.get("text") or "",
        "provenance": generated.get("provenance") or [],
    }


def _default_provenance(input_payload: dict[str, Any]) -> list[dict[str, Any]]:
    facts = input_payload.get("facts") or {}
    source_fields = [
        f"facts.{field}"
        for field in (
            "ticker",
            "event_date",
            "scanner_type",
            "severity",
            "summary",
            "signal_quality_score",
            "regime",
        )
        if facts.get(field) is not None
    ]
    provenance = []
    if source_fields:
        provenance.append(
            {
                "claim": "Scanner event facts",
                "source_fields": source_fields,
            }
        )
    if input_payload.get("risks"):
        provenance.append({"claim": "Risk summary", "source_fields": ["risks"]})
    return provenance


def _rejection_reason(
    generated: dict[str, Any],
    brief: dict[str, Any],
    input_payload: dict[str, Any],
) -> str | None:
    text = generated.get("text")
    if not isinstance(text, str) or not text.strip():
        return "Generated narrative is empty."

    forbidden = _forbidden_claim_match(text, brief.get("forbidden_claims") or [])
    if forbidden:
        return f"Generated narrative contains a forbidden claim: {forbidden}"

    provenance = generated.get("provenance")
    if not isinstance(provenance, list) or not provenance:
        return "Generated narrative is missing provenance."

    for entry in provenance:
        if not isinstance(entry, dict):
            return "Generated narrative provenance must be a list of objects."
        fields = entry.get("source_fields")
        if not isinstance(fields, list) or not fields:
            return "Generated narrative provenance is missing source fields."
        for field in fields:
            if field not in SUPPORTED_PROVENANCE_FIELDS:
                return f"Generated narrative uses unsupported provenance field: {field}"
            if field.startswith("facts."):
                fact_key = field.split(".", 1)[1]
                if fact_key not in (input_payload.get("facts") or {}):
                    return f"Generated narrative references absent provenance field: {field}"
    return None


def _forbidden_claim_match(text: str, forbidden_claims: list[str]) -> str | None:
    normalized_text = _normalize_claim_text(text)
    for claim in forbidden_claims:
        normalized_claim = _normalize_claim_text(claim)
        for prefix in ("do not ", "don't ", "never "):
            if normalized_claim.startswith(prefix):
                normalized_claim = normalized_claim[len(prefix) :]
                break
        if normalized_claim and normalized_claim in normalized_text:
            return claim
    return None


def _normalize_claim_text(value: str) -> str:
    return " ".join(
        "".join(char.lower() if char.isalnum() else " " for char in value).split()
    )
