from __future__ import annotations

from typing import Any, Protocol

from sqlalchemy.orm import Session

from app.core.config import Settings, settings
from app.core.llm_guardrails import build_llm_usage_guardrails
from app.models.scanner_event import ScannerEvent
from app.services.scanner_event_narrative import ScannerEventNarrativeService

ALERT_COPY_FEATURE = "alert_copy"


class NarrativeBundleService(Protocol):
    def build(self, db: Session, event: ScannerEvent) -> dict[str, Any]: ...


class AlertCopyService:
    def __init__(
        self,
        *,
        narrative_service: NarrativeBundleService | None = None,
        settings: Settings = settings,
    ) -> None:
        self._narrative_service = narrative_service or ScannerEventNarrativeService()
        self._settings = settings

    def build(self, db: Session, event: ScannerEvent) -> dict[str, Any]:
        fallback = _deterministic_copy(event)
        guardrails = build_llm_usage_guardrails(self._settings)
        if not guardrails.allows(ALERT_COPY_FEATURE):
            return fallback

        try:
            bundle = self._narrative_service.build(db, event)
        except Exception as exc:
            return {**fallback, "source": "fallback", "generation_error": str(exc)}

        narrative = bundle.get("narrative")
        if not narrative:
            reason = (bundle.get("rejection") or {}).get("reason")
            return {
                **fallback,
                "source": "fallback",
                "generation_error": reason or "Narrative unavailable.",
            }

        brief = bundle.get("brief") or {}
        facts = brief.get("facts") or {}
        why = list(brief.get("why") or [])
        risks = list(brief.get("risks") or [])
        warnings = [
            warning.get("message") or warning.get("code")
            for warning in brief.get("warnings") or []
            if warning.get("message") or warning.get("code")
        ]
        body_parts = [
            narrative.get("text") or fallback["body"],
            *_section_lines("Why", why),
            *_section_lines("Risks", risks),
            *_section_lines("Data quality", warnings),
        ]
        return {
            "source": "generated",
            "title": _title(event, facts=facts),
            "summary": facts.get("summary") or fallback["summary"],
            "body": "\n".join(part for part in body_parts if part),
            "risk_caveats": risks,
            "data_quality_caveats": warnings,
            "narrative": narrative,
        }


def _deterministic_copy(event: ScannerEvent) -> dict[str, Any]:
    summary = event.summary or f"{_scanner_type_display(event)} detected on {event.ticker}"
    return {
        "source": "deterministic",
        "title": _title(event),
        "summary": summary,
        "body": summary,
        "risk_caveats": [],
        "data_quality_caveats": [],
    }


def _title(event: ScannerEvent, *, facts: dict[str, Any] | None = None) -> str:
    facts = facts or {}
    ticker = facts.get("ticker") or event.ticker
    scanner_type = facts.get("scanner_type") or event.scanner_type
    scanner_type_display = scanner_type.replace("_", " ").title()
    return f"MarketHawk Alert: {ticker} - {scanner_type_display}"


def _scanner_type_display(event: ScannerEvent) -> str:
    return event.scanner_type.replace("_", " ").title()


def _section_lines(label: str, values: list[str]) -> list[str]:
    if not values:
        return []
    return [f"{label}:", *[f"- {value}" for value in values]]
