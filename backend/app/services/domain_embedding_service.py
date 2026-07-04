from __future__ import annotations

import hashlib
import json
from typing import Any

from sqlalchemy.orm import Session

from app.models.news_article import NewsArticle
from app.models.scanner_event import ScannerEvent
from app.models.scanner_event_narrative import ScannerEventNarrative
from app.models.semantic_embedding import SemanticEmbedding
from app.services.ai_signal_brief import AISignalBriefService
from app.services.embedding_service import EmbeddingService
from app.utils.time import utc_now


class DomainEmbeddingService:
    """Build embedding inputs for domain-specific MarketHawk sources."""

    def __init__(
        self,
        *,
        embedding_service: EmbeddingService | None = None,
        brief_service: AISignalBriefService | None = None,
    ) -> None:
        self._embedding_service = embedding_service or EmbeddingService()
        self._brief_service = brief_service or AISignalBriefService()

    def embed_news_article(self, db: Session, article: NewsArticle) -> dict[str, Any]:
        text = _news_text(article)
        metadata = {
            "source": "news_article",
            "news_article_id": article.id,
            "tickers": list(article.tickers or []),
            "provider": article.provider,
            "published_utc": article.published_utc.isoformat()
            if article.published_utc
            else None,
        }
        return self._embed_source(
            db,
            source_type="news",
            source_id=f"news:{article.id}",
            text=text,
            metadata=metadata,
        )

    def embed_scanner_catalyst(
        self,
        db: Session,
        event: ScannerEvent,
    ) -> dict[str, Any]:
        text = _catalyst_text(event)
        if not text:
            return {"status": "skipped", "reason": "No catalyst text available."}
        metadata = {
            "source": "scanner_catalyst",
            "scanner_event_id": event.id,
            "ticker": event.ticker,
            "scanner_type": event.scanner_type,
            "event_date": event.event_date.isoformat() if event.event_date else None,
        }
        return self._embed_source(
            db,
            source_type="catalyst",
            source_id=f"scanner_event:{event.id}",
            text=text,
            metadata=metadata,
        )

    def embed_signal_brief(self, db: Session, event: ScannerEvent) -> dict[str, Any]:
        brief = self._brief_service.build(db, event)
        text = _brief_text(brief)
        metadata = {
            "source": "ai_signal_brief",
            "schema_version": brief.get("schema_version"),
            "scanner_event_id": event.id,
            "ticker": event.ticker,
            "scanner_type": event.scanner_type,
        }
        return self._embed_source(
            db,
            source_type="scanner_explanation",
            source_id=f"scanner_event:{event.id}",
            text=text,
            metadata=metadata,
        )

    def embed_generated_narrative(
        self,
        db: Session,
        narrative: ScannerEventNarrative,
    ) -> dict[str, Any]:
        metadata = {
            "source": "scanner_event_narrative",
            "scanner_event_narrative_id": narrative.id,
            "scanner_event_id": narrative.scanner_event_id,
            "feature_area": narrative.feature_area,
            "provider": narrative.provider,
            "model": narrative.model,
            "prompt_version": narrative.prompt_version,
            "brief_fingerprint": narrative.brief_fingerprint,
        }
        return self._embed_source(
            db,
            source_type="generated_narrative",
            source_id=f"scanner_event_narrative:{narrative.id}",
            text=narrative.narrative_text,
            metadata=metadata,
        )

    def _embed_source(
        self,
        db: Session,
        *,
        source_type: str,
        source_id: str,
        text: str,
        metadata: dict[str, Any],
    ) -> dict[str, Any]:
        fingerprint = _fingerprint(text)
        existing = _existing_record(db, source_type, source_id)
        existing_fingerprint = (existing.metadata_ or {}).get("source_fingerprint") if existing else None
        freshness = (
            "new"
            if existing is None
            else "unchanged"
            if existing_fingerprint == fingerprint
            else "stale_recomputed"
        )
        if freshness == "unchanged":
            return {
                "status": "skipped",
                "freshness": freshness,
                "source_fingerprint": fingerprint,
                "record_id": existing.id,
            }

        embedding_metadata = {
            **metadata,
            "source_fingerprint": fingerprint,
            "embedded_at": utc_now().isoformat(),
        }
        try:
            result = self._embedding_service.upsert_text(
                db,
                source_type=source_type,
                source_id=source_id,
                text=text,
                metadata=embedding_metadata,
            )
        except Exception as exc:
            return {
                "status": "failed",
                "freshness": freshness,
                "source_fingerprint": fingerprint,
                "error": str(exc),
            }

        return {
            **result,
            "freshness": freshness,
            "source_fingerprint": fingerprint,
        }


def _existing_record(
    db: Session,
    source_type: str,
    source_id: str,
) -> SemanticEmbedding | None:
    return (
        db.query(SemanticEmbedding)
        .filter(
            SemanticEmbedding.source_type == source_type,
            SemanticEmbedding.source_id == source_id,
        )
        .order_by(SemanticEmbedding.updated_at.desc(), SemanticEmbedding.id.desc())
        .first()
    )


def _news_text(article: NewsArticle) -> str:
    return "\n".join(
        part
        for part in [
            article.title,
            article.description,
            "Tickers: " + ", ".join(article.tickers or []),
        ]
        if part
    )


def _catalyst_text(event: ScannerEvent) -> str:
    metadata = event.metadata_ or {}
    catalyst_payload = (
        metadata.get("catalyst")
        or metadata.get("catalysts")
        or metadata.get("news_catalyst")
        or metadata.get("news_catalysts")
    )
    if not catalyst_payload:
        return ""
    parts = [event.summary or ""]
    parts.extend(_flatten_text(catalyst_payload))
    return "\n".join(part for part in parts if part)


def _brief_text(brief: dict[str, Any]) -> str:
    facts = brief.get("facts") or {}
    warning_messages = [
        warning.get("message") or warning.get("code")
        for warning in brief.get("warnings") or []
        if warning.get("message") or warning.get("code")
    ]
    return "\n".join(
        part
        for part in [
            json.dumps(facts, sort_keys=True, default=str),
            "Why: " + "; ".join(brief.get("why") or []),
            "Risks: " + "; ".join(brief.get("risks") or []),
            "Warnings: " + "; ".join(warning_messages),
        ]
        if part and not part.endswith(": ")
    )


def _flatten_text(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [
            text
            for key in sorted(value)
            for text in _flatten_text(value[key])
            if text
        ]
    if isinstance(value, list):
        return [text for item in value for text in _flatten_text(item) if text]
    return [str(value)] if value is not None else []


def _fingerprint(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
