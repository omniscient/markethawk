from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.core.config import Settings, settings
from app.core.llm_guardrails import build_llm_usage_guardrails
from app.models.scanner_event import ScannerEvent
from app.services.ai_signal_brief import AISignalBriefService
from app.services.semantic_signal_search import SemanticSignalSearchService

ANALYST_QA_FEATURE = "analyst_qa"


class AnalystQAService:
    """Grounded analyst Q&A over deterministic signal context."""

    def __init__(
        self,
        *,
        brief_service: AISignalBriefService | None = None,
        semantic_search_service: SemanticSignalSearchService | None = None,
        settings: Settings = settings,
    ) -> None:
        self._brief_service = brief_service or AISignalBriefService()
        self._semantic_search_service = (
            semantic_search_service or SemanticSignalSearchService()
        )
        self._settings = settings

    def answer_for_event(
        self,
        db: Session,
        event: ScannerEvent,
        *,
        question: str,
    ) -> dict[str, Any]:
        unavailable = self._unavailable(question)
        if unavailable:
            return unavailable

        brief = self._brief_service.build(db, event)
        semantic = self._semantic_search_service.find_for_event(db, event, top_k=5)
        return _answer_payload(question=question, briefs=[brief], semantic=semantic)

    def answer_for_events(
        self,
        db: Session,
        *,
        question: str,
        scanner_type: str | None = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        unavailable = self._unavailable(question)
        if unavailable:
            return unavailable

        query = db.query(ScannerEvent)
        if scanner_type:
            query = query.filter(ScannerEvent.scanner_type == scanner_type)
        events = query.order_by(ScannerEvent.event_date.desc(), ScannerEvent.id.desc()).limit(limit).all()
        briefs = [self._brief_service.build(db, event) for event in events]
        return {
            **_answer_payload(question=question, briefs=briefs, semantic=None),
            "event_count": len(events),
        }

    def _unavailable(self, question: str) -> dict[str, Any] | None:
        guardrails = build_llm_usage_guardrails(self._settings)
        if not guardrails.allows(ANALYST_QA_FEATURE):
            return {"status": "disabled", "answer": None, "guardrails": guardrails}
        unsupported = _unsupported_reason(question)
        if unsupported:
            return {"status": "unsupported", "answer": None, "reason": unsupported}
        return None


def _answer_payload(
    *,
    question: str,
    briefs: list[dict[str, Any]],
    semantic: dict[str, Any] | None,
) -> dict[str, Any]:
    if not briefs:
        return {
            "status": "no_context",
            "question": question,
            "answer": None,
            "citations": [],
        }

    answer_parts = []
    citations = []
    for brief in briefs:
        facts = brief.get("facts") or {}
        summary = facts.get("summary")
        why = list(brief.get("why") or [])
        outcome_summary = (brief.get("outcome_context") or {}).get("summary") or {}
        if summary:
            answer_parts.append(summary)
            citations.append({"source": "brief.facts.summary", "value": summary})
        if why:
            answer_parts.append(why[0])
            citations.append({"source": "brief.why", "value": why[0]})
        if "follow_through" in outcome_summary:
            value = f"follow_through={outcome_summary['follow_through']}"
            answer_parts.append(value)
            citations.append({"source": "outcome_context.summary", "value": value})

    semantic_matches = (semantic or {}).get("semantic_matches") or []
    if semantic_matches:
        match = semantic_matches[0]
        value = (
            f"{match['source_type']} {match['source_id']} "
            f"score={match['score']:.2f}"
        )
        answer_parts.append(match.get("why") or value)
        citations.append({"source": "semantic_matches[0]", "value": value})

    return {
        "status": "answered",
        "question": question,
        "answer": " ".join(answer_parts),
        "citations": citations,
    }


def _unsupported_reason(question: str) -> str | None:
    normalized = question.lower()
    if any(phrase in normalized for phrase in ("should i buy", "should i sell")):
        return "Analyst Q&A cannot provide a trade recommendation."
    if "guarantee" in normalized or "guaranteed" in normalized:
        return "Analyst Q&A cannot claim guaranteed outcomes."
    return None
