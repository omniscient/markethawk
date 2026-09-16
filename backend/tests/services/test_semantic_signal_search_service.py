from datetime import date

from app.core.config import Settings
from app.models.scanner_event import ScannerEvent
from app.services.embedding_service import EmbeddingService
from app.services.semantic_signal_search import SemanticSignalSearchService

BASE_SETTINGS = {
    "DATABASE_URL": "postgresql://test:test@localhost/test",
    "POLYGON_API_KEY": "test-key",
    "JWT_SECRET_KEY": "a" * 32,
    "REDIS_PASSWORD": "r" * 16,
}


class FakeEmbeddingProvider:
    provider_name = "local"
    model_name = "unit-embedder"
    embedding_version = "unit.v1"

    def embed(self, text: str) -> list[float]:
        if "target signal" in text or "growth query" in text:
            return [1.0, 0.0]
        if "similar signal" in text or "growth news" in text:
            return [0.9, 0.1]
        return [0.0, 1.0]


class FakeBriefService:
    def build(self, db, event):
        return {
            "schema_version": "ai_signal_brief.v1",
            "facts": {
                "ticker": event.ticker,
                "event_date": event.event_date.isoformat(),
                "scanner_type": event.scanner_type,
                "summary": event.summary,
            },
            "why": ["target signal setup had volume and liquidity support."],
            "risks": [],
            "warnings": [],
        }


class FakeAnalogService:
    def find_similar_events(self, db, *, target_event_id, limit, min_sample_size):
        return {
            "analogs": [
                {
                    "event_id": 99,
                    "ticker": "ANA",
                    "similarity_score": 0.72,
                    "outcome_summary": {"follow_through": True},
                }
            ],
            "warnings": [],
        }


def make_settings(**overrides) -> Settings:
    return Settings(_env_file=None, **{**BASE_SETTINGS, **overrides})


def enabled_settings() -> Settings:
    return make_settings(
        LLM_FEATURES_ENABLED=True,
        LLM_PROVIDER="local",
        LLM_MODEL="unit-embedder",
        LLM_ALLOWED_FEATURES="embeddings,semantic_search",
    )


def make_embedding_service() -> EmbeddingService:
    return EmbeddingService(provider=FakeEmbeddingProvider(), settings=enabled_settings())


def seed_event(db, *, ticker: str, summary: str) -> ScannerEvent:
    event = ScannerEvent(
        ticker=ticker,
        event_date=date(2026, 7, 3),
        scanner_type="pre_market_volume_spike",
        summary=summary,
        severity="high",
        indicators={},
        criteria_met={},
        metadata_={},
        explanation={},
    )
    db.add(event)
    db.flush()
    return event


def test_event_search_separates_semantic_matches_from_deterministic_analogs(db):
    target = seed_event(db, ticker="TGT", summary="target signal")
    other = seed_event(db, ticker="SIM", summary="similar signal")
    embedding_service = make_embedding_service()
    embedding_service.upsert_text(
        db,
        source_type="scanner_explanation",
        source_id=f"scanner_event:{other.id}",
        text="similar signal",
        metadata={"ticker": other.ticker, "scanner_event_id": other.id},
    )
    embedding_service.upsert_text(
        db,
        source_type="scanner_explanation",
        source_id=f"scanner_event:{target.id}",
        text="target signal",
        metadata={"ticker": target.ticker, "scanner_event_id": target.id},
    )
    service = SemanticSignalSearchService(
        embedding_service=embedding_service,
        brief_service=FakeBriefService(),
        analog_service=FakeAnalogService(),
    )

    result = service.find_for_event(db, target, top_k=5)

    assert result["label"] == "Semantic matches"
    assert result["deterministic_analogs"]["analogs"][0]["event_id"] == 99
    assert [match["source_id"] for match in result["semantic_matches"]] == [
        f"scanner_event:{other.id}"
    ]
    match = result["semantic_matches"][0]
    assert match["match_type"] == "semantic"
    assert match["source_type"] == "scanner_explanation"
    assert match["score"] > 0.8
    assert "SIM" in match["why"]


def test_text_query_search_returns_labeled_semantic_matches(db):
    embedding_service = make_embedding_service()
    embedding_service.upsert_text(
        db,
        source_type="news",
        source_id="news:1",
        text="growth news",
        metadata={"ticker": "TGT", "title": "TGT growth news"},
    )
    service = SemanticSignalSearchService(embedding_service=embedding_service)

    result = service.find_for_text(db, query_text="growth query", top_k=3)

    assert result["label"] == "Semantic matches"
    assert result["deterministic_analogs"] is None
    assert result["semantic_matches"][0]["source_type"] == "news"
    assert result["semantic_matches"][0]["why"] == (
        "Semantic similarity matched news news:1 for TGT."
    )


def test_text_query_search_no_results_state(db):
    service = SemanticSignalSearchService(embedding_service=make_embedding_service())

    result = service.find_for_text(db, query_text="growth query", top_k=3)

    assert result["status"] == "no_results"
    assert result["semantic_matches"] == []
    assert result["warnings"] == ["No semantic matches were found."]
