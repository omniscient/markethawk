from __future__ import annotations

import json
from typing import Any

from sqlalchemy.orm import Session

from app.models.scanner_event import ScannerEvent
from app.services.ai_signal_brief import AISignalBriefService
from app.services.embedding_service import EmbeddingService
from app.services.historical_analog_service import HistoricalAnalogService

DOMAIN_SOURCE_TYPES = [
    "scanner_explanation",
    "generated_narrative",
    "news",
    "catalyst",
]


class SemanticSignalSearchService:
    """Find semantic matches while keeping deterministic analogs separate."""

    def __init__(
        self,
        *,
        embedding_service: EmbeddingService | None = None,
        brief_service: AISignalBriefService | None = None,
        analog_service: HistoricalAnalogService | None = None,
    ) -> None:
        self._embedding_service = embedding_service or EmbeddingService()
        self._brief_service = brief_service or AISignalBriefService()
        self._analog_service = analog_service or HistoricalAnalogService()

    def find_for_event(
        self,
        db: Session,
        event: ScannerEvent,
        *,
        top_k: int = 10,
        source_types: list[str] | None = None,
        analog_limit: int = 5,
    ) -> dict[str, Any]:
        brief = self._brief_service.build(db, event)
        search = self._embedding_service.search(
            db,
            query_text=_brief_query_text(brief),
            top_k=top_k + 5,
            source_types=source_types or DOMAIN_SOURCE_TYPES,
        )
        matches = [
            match
            for match in _semantic_matches(search.get("matches") or [])
            if not _same_event(match, event.id)
        ][:top_k]
        analogs = self._analog_service.find_similar_events(
            db,
            target_event_id=event.id,
            limit=analog_limit,
            min_sample_size=5,
        )
        return _result_payload(
            status="ok" if matches else "no_results",
            semantic_matches=matches,
            deterministic_analogs=analogs,
            search_status=search.get("status"),
        )

    def find_for_text(
        self,
        db: Session,
        *,
        query_text: str,
        top_k: int = 10,
        source_types: list[str] | None = None,
    ) -> dict[str, Any]:
        search = self._embedding_service.search(
            db,
            query_text=query_text,
            top_k=top_k,
            source_types=source_types or DOMAIN_SOURCE_TYPES,
        )
        matches = _semantic_matches(search.get("matches") or [])
        return _result_payload(
            status="ok" if matches else "no_results",
            semantic_matches=matches,
            deterministic_analogs=None,
            search_status=search.get("status"),
        )


def _result_payload(
    *,
    status: str,
    semantic_matches: list[dict[str, Any]],
    deterministic_analogs: dict[str, Any] | None,
    search_status: str | None,
) -> dict[str, Any]:
    warnings = []
    if not semantic_matches:
        warnings.append("No semantic matches were found.")
    return {
        "status": status,
        "label": "Semantic matches",
        "semantic_matches": semantic_matches,
        "deterministic_analogs": deterministic_analogs,
        "search_status": search_status,
        "warnings": warnings,
    }


def _semantic_matches(matches: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "match_type": "semantic",
            "source_type": match["source_type"],
            "source_id": match["source_id"],
            "score": match["score"],
            "metadata": match.get("metadata") or {},
            "why": _why(match),
        }
        for match in matches
    ]


def _why(match: dict[str, Any]) -> str:
    metadata = match.get("metadata") or {}
    ticker = metadata.get("ticker")
    suffix = f" for {ticker}" if ticker else ""
    return (
        f"Semantic similarity matched {match['source_type']} "
        f"{match['source_id']}{suffix}."
    )


def _same_event(match: dict[str, Any], event_id: int) -> bool:
    metadata = match.get("metadata") or {}
    if metadata.get("scanner_event_id") == event_id:
        return True
    return match.get("source_id") == f"scanner_event:{event_id}"


def _brief_query_text(brief: dict[str, Any]) -> str:
    facts = brief.get("facts") or {}
    return "\n".join(
        part
        for part in [
            json.dumps(facts, sort_keys=True, default=str),
            "Why: " + "; ".join(brief.get("why") or []),
            "Risks: " + "; ".join(brief.get("risks") or []),
        ]
        if part and not part.endswith(": ")
    )
