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

POST_MORTEM_FEATURE = "post_mortem"
POST_MORTEM_PROMPT_VERSION = "signal_post_mortem.v1"
SUPPORTED_PROVENANCE_FIELDS = frozenset(
    {
        "signal_time.facts",
        "signal_time.why",
        "signal_time.risks",
        "signal_time.warnings",
        "expected_behavior.analogs",
        "expected_behavior.archetype",
        "realized_outcome.summary",
        "realized_outcome.snapshots",
    }
)


class SignalPostMortemGenerator(Protocol):
    provider_name: str
    model_name: str

    def generate(
        self,
        post_mortem_input: dict[str, Any],
        guardrails: LLMUsageGuardrails,
    ) -> str | dict[str, Any]: ...


class LocalSignalPostMortemGenerator:
    """Grounded local renderer for post-mortems.

    The renderer only uses the deterministic post-mortem input payload. External
    providers can replace it without changing cache or provenance policy.
    """

    provider_name = "local"
    model_name = "grounded-post-mortem-v1"

    def generate(
        self,
        post_mortem_input: dict[str, Any],
        guardrails: LLMUsageGuardrails,
    ) -> dict[str, Any]:
        signal_time = post_mortem_input["signal_time"]
        expected = post_mortem_input["expected_behavior"]
        outcome = post_mortem_input["realized_outcome"]
        facts = signal_time.get("facts") or {}
        summary = outcome.get("summary") or {}
        ticker = facts.get("ticker") or "Unknown ticker"
        scanner_type = facts.get("scanner_type") or "unknown scanner"
        status = _outcome_status(summary)
        why = "; ".join(signal_time.get("why") or ["No signal-time rationale listed."])
        analog_count = len(expected.get("analogs") or [])
        eod_change = summary.get("eod_pct_change")
        outcome_text = (
            f"follow-through={summary.get('follow_through')}, "
            f"eod_pct_change={eod_change}"
        )
        return {
            "text": (
                f"{ticker} {scanner_type} post-mortem: the signal finished as "
                f"{status}. Known at signal time: {why}. Expected behavior used "
                f"{analog_count} analogs. Realized outcome: {outcome_text}."
            ),
            "provenance": [
                {"claim": "Signal-time context", "source_fields": ["signal_time.why"]},
                {
                    "claim": "Expected behavior",
                    "source_fields": ["expected_behavior.analogs"],
                },
                {
                    "claim": "Realized outcome",
                    "source_fields": ["realized_outcome.summary"],
                },
            ],
        }


class SignalPostMortemService:
    def __init__(
        self,
        *,
        brief_service: AISignalBriefService | None = None,
        generator: SignalPostMortemGenerator | None = None,
        settings: Settings = settings,
    ) -> None:
        self._brief_service = brief_service or AISignalBriefService()
        self._generator = generator or LocalSignalPostMortemGenerator()
        self._settings = settings

    def build(self, db: Session, event: ScannerEvent) -> dict[str, Any]:
        brief = self._brief_service.build(db, event)
        guardrails = build_llm_usage_guardrails(self._settings)
        if not guardrails.allows(POST_MORTEM_FEATURE):
            return {
                "brief": brief,
                "post_mortem": None,
                "cache": {"status": "disabled"},
                "guardrails": guardrails,
            }

        outcome_summary = (brief.get("outcome_context") or {}).get("summary")
        if not outcome_summary or not outcome_summary.get("is_complete"):
            return {
                "brief": brief,
                "post_mortem": None,
                "cache": {"status": "incomplete_outcome"},
                "rejection": {
                    "reason": "Outcome summary is incomplete or unavailable."
                },
                "guardrails": guardrails,
            }

        input_payload = _post_mortem_input_payload(brief)
        fingerprint = _input_fingerprint(brief, input_payload)
        cache = self._cache_query(db, event, guardrails).first()
        if cache and cache.brief_fingerprint == fingerprint:
            return {
                "brief": brief,
                "post_mortem": self._post_mortem_payload(cache),
                "cache": {"status": "hit"},
                "guardrails": guardrails,
            }

        generated = _normalize_generated_post_mortem(
            self._generator.generate(input_payload, guardrails),
            input_payload,
        )
        rejection_reason = _rejection_reason(generated, brief, input_payload)
        if rejection_reason:
            return {
                "brief": brief,
                "post_mortem": None,
                "cache": {"status": "rejected"},
                "rejection": {"reason": rejection_reason},
                "guardrails": guardrails,
            }

        status = "stale_regenerated" if cache else "miss"
        if cache is None:
            cache = ScannerEventNarrative(
                scanner_event_id=event.id,
                feature_area=POST_MORTEM_FEATURE,
                provider=guardrails.provider,
                model=guardrails.model,
                prompt_version=POST_MORTEM_PROMPT_VERSION,
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
            "post_mortem": self._post_mortem_payload(cache),
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
            ScannerEventNarrative.feature_area == POST_MORTEM_FEATURE,
            ScannerEventNarrative.provider == guardrails.provider,
            ScannerEventNarrative.model == guardrails.model,
            ScannerEventNarrative.prompt_version == POST_MORTEM_PROMPT_VERSION,
        )

    def _post_mortem_payload(self, cache: ScannerEventNarrative) -> dict[str, Any]:
        input_payload = cache.input_payload or {}
        realized_outcome = input_payload.get("realized_outcome") or {}
        summary = realized_outcome.get("summary") or {}
        return {
            "text": cache.narrative_text,
            "provider": cache.provider,
            "model": cache.model,
            "prompt_version": cache.prompt_version,
            "brief_schema_version": cache.brief_schema_version,
            "brief_fingerprint": cache.brief_fingerprint,
            "outcome_status": _outcome_status(summary),
            "known_at_signal_time": input_payload.get("signal_time") or {},
            "expected_behavior": input_payload.get("expected_behavior") or {},
            "realized_outcome": realized_outcome,
            "provenance": list(cache.provenance_payload or []),
            "created_at": cache.created_at.isoformat() if cache.created_at else None,
            "updated_at": cache.updated_at.isoformat() if cache.updated_at else None,
        }


def _post_mortem_input_payload(brief: dict[str, Any]) -> dict[str, Any]:
    outcome_context = brief.get("outcome_context") or {}
    return {
        "signal_time": {
            "facts": brief.get("facts") or {},
            "why": list(brief.get("why") or []),
            "risks": list(brief.get("risks") or []),
            "warnings": list(brief.get("warnings") or []),
        },
        "expected_behavior": {
            "analogs": list(brief.get("analogs") or []),
            "archetype": brief.get("archetype"),
        },
        "realized_outcome": {
            "summary": outcome_context.get("summary"),
            "snapshots": list(outcome_context.get("snapshots") or []),
        },
    }


def _input_fingerprint(
    brief: dict[str, Any],
    input_payload: dict[str, Any],
) -> str:
    payload = {
        "schema_version": brief.get("schema_version"),
        **input_payload,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _normalize_generated_post_mortem(
    generated: str | dict[str, Any],
    input_payload: dict[str, Any],
) -> dict[str, Any]:
    if isinstance(generated, str):
        return {"text": generated, "provenance": _default_provenance(input_payload)}
    if not isinstance(generated, dict):
        return {"text": "", "provenance": []}
    return {
        "text": generated.get("text") or "",
        "provenance": generated.get("provenance") or [],
    }


def _default_provenance(input_payload: dict[str, Any]) -> list[dict[str, Any]]:
    provenance = [
        {"claim": "Signal context", "source_fields": ["signal_time.facts"]},
        {"claim": "Realized outcome", "source_fields": ["realized_outcome.summary"]},
    ]
    if (input_payload.get("expected_behavior") or {}).get("analogs"):
        provenance.insert(
            1,
            {
                "claim": "Expected behavior",
                "source_fields": ["expected_behavior.analogs"],
            },
        )
    return provenance


def _rejection_reason(
    generated: dict[str, Any],
    brief: dict[str, Any],
    input_payload: dict[str, Any],
) -> str | None:
    text = generated.get("text")
    if not isinstance(text, str) or not text.strip():
        return "Generated post-mortem is empty."

    forbidden = _forbidden_claim_match(text, brief.get("forbidden_claims") or [])
    if forbidden:
        return f"Generated post-mortem contains a forbidden claim: {forbidden}"

    provenance = generated.get("provenance")
    if not isinstance(provenance, list) or not provenance:
        return "Generated post-mortem is missing provenance."

    for entry in provenance:
        if not isinstance(entry, dict):
            return "Generated post-mortem provenance must be a list of objects."
        fields = entry.get("source_fields")
        if not isinstance(fields, list) or not fields:
            return "Generated post-mortem provenance is missing source fields."
        for field in fields:
            if field not in SUPPORTED_PROVENANCE_FIELDS:
                return f"Generated post-mortem uses unsupported provenance field: {field}"
            if _field_value(input_payload, field) is None:
                return f"Generated post-mortem references absent provenance field: {field}"
    return None


def _field_value(input_payload: dict[str, Any], field: str) -> Any:
    current: Any = input_payload
    for part in field.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def _outcome_status(summary: dict[str, Any]) -> str:
    if summary.get("follow_through") is True:
        return "winning"
    if summary.get("follow_through") is False:
        return "losing"
    eod_change = summary.get("eod_pct_change")
    if isinstance(eod_change, (int, float)):
        return "winning" if eod_change > 0 else "losing"
    return "unknown"


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
