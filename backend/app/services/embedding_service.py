from __future__ import annotations

import hashlib
import math
from typing import Any, Protocol

from sqlalchemy.orm import Session

from app.core.config import Settings, settings
from app.core.llm_guardrails import build_llm_usage_guardrails
from app.models.semantic_embedding import SemanticEmbedding

EMBEDDINGS_FEATURE = "embeddings"
SEMANTIC_SEARCH_FEATURE = "semantic_search"


class EmbeddingProvider(Protocol):
    provider_name: str
    model_name: str
    embedding_version: str

    def embed(self, text: str) -> list[float]: ...


class LocalHashEmbeddingProvider:
    """Deterministic local embedding provider for development and tests.

    This is a non-semantic fallback. External embedding providers can replace it
    without changing storage or retrieval behavior.
    """

    provider_name = "local"
    model_name = "hash-embedding"
    embedding_version = "hash.v1"

    def embed(self, text: str) -> list[float]:
        tokens = [token for token in _tokenize(text) if token]
        vector = [0.0] * 32
        for token in tokens:
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            index = digest[0] % len(vector)
            sign = 1.0 if digest[1] % 2 == 0 else -1.0
            vector[index] += sign
        return _normalize(vector)


class EmbeddingService:
    def __init__(
        self,
        *,
        provider: EmbeddingProvider | None = None,
        settings: Settings = settings,
    ) -> None:
        self._settings = settings
        self._provider = provider if provider is not None else _default_provider(settings)

    def upsert_text(
        self,
        db: Session,
        *,
        source_type: str,
        source_id: str,
        text: str,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        guardrails = build_llm_usage_guardrails(self._settings)
        if not guardrails.allows(EMBEDDINGS_FEATURE):
            return {"status": "disabled", "record": None, "guardrails": guardrails}
        if self._provider is None:
            return {
                "status": "provider_unavailable",
                "record": None,
                "guardrails": guardrails,
            }

        vector = _coerce_vector(self._provider.embed(text))
        record = self._query_record(db, source_type=source_type, source_id=source_id).first()
        status = "updated" if record else "inserted"
        if record is None:
            record = SemanticEmbedding(
                source_type=source_type,
                source_id=source_id,
                provider=self._provider.provider_name,
                model=self._provider.model_name,
                embedding_version=self._provider.embedding_version,
            )
            db.add(record)

        record.vector = vector
        record.metadata_ = metadata or {}
        db.flush()
        return {"status": status, "record": _record_payload(record), "guardrails": guardrails}

    def search(
        self,
        db: Session,
        *,
        query_text: str,
        top_k: int = 10,
        source_types: list[str] | None = None,
    ) -> dict[str, Any]:
        guardrails = build_llm_usage_guardrails(self._settings)
        if not guardrails.allows(SEMANTIC_SEARCH_FEATURE):
            return {"status": "disabled", "matches": [], "guardrails": guardrails}
        if self._provider is None:
            return {
                "status": "provider_unavailable",
                "matches": [],
                "guardrails": guardrails,
            }

        query_vector = _coerce_vector(self._provider.embed(query_text))
        query = db.query(SemanticEmbedding).filter(
            SemanticEmbedding.provider == self._provider.provider_name,
            SemanticEmbedding.model == self._provider.model_name,
            SemanticEmbedding.embedding_version == self._provider.embedding_version,
        )
        if source_types:
            query = query.filter(SemanticEmbedding.source_type.in_(source_types))

        matches = []
        for record in query.all():
            score = _cosine_similarity(query_vector, _coerce_vector(record.vector))
            matches.append({**_record_payload(record), "score": score})
        matches.sort(key=lambda match: (-match["score"], match["source_type"], match["source_id"]))
        return {
            "status": "ok",
            "matches": matches[: max(0, top_k)],
            "guardrails": guardrails,
        }

    def _query_record(
        self,
        db: Session,
        *,
        source_type: str,
        source_id: str,
    ):
        if self._provider is None:
            raise RuntimeError("Embedding provider is unavailable.")
        return db.query(SemanticEmbedding).filter(
            SemanticEmbedding.source_type == source_type,
            SemanticEmbedding.source_id == source_id,
            SemanticEmbedding.provider == self._provider.provider_name,
            SemanticEmbedding.model == self._provider.model_name,
            SemanticEmbedding.embedding_version == self._provider.embedding_version,
        )


def _default_provider(settings: Settings) -> EmbeddingProvider | None:
    if settings.LLM_PROVIDER == "local":
        return LocalHashEmbeddingProvider()
    return None


def _record_payload(record: SemanticEmbedding) -> dict[str, Any]:
    return {
        "id": record.id,
        "source_type": record.source_type,
        "source_id": record.source_id,
        "provider": record.provider,
        "model": record.model,
        "embedding_version": record.embedding_version,
        "metadata": record.metadata_ or {},
        "created_at": record.created_at.isoformat() if record.created_at else None,
        "updated_at": record.updated_at.isoformat() if record.updated_at else None,
    }


def _coerce_vector(vector: list[float]) -> list[float]:
    if not isinstance(vector, list) or not vector:
        raise ValueError("Embedding vector must be a non-empty list.")
    coerced = [float(value) for value in vector]
    if not all(math.isfinite(value) for value in coerced):
        raise ValueError("Embedding vector contains non-finite values.")
    return coerced


def _cosine_similarity(left: list[float], right: list[float]) -> float:
    if len(left) != len(right):
        return 0.0
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return sum(a * b for a, b in zip(left, right)) / (left_norm * right_norm)


def _normalize(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(value * value for value in vector))
    if norm == 0:
        return vector
    return [value / norm for value in vector]


def _tokenize(text: str) -> list[str]:
    return ["".join(char.lower() if char.isalnum() else " " for char in text).strip()]
