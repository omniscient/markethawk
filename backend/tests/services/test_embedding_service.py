from app.core.config import Settings
from app.models.semantic_embedding import SemanticEmbedding
from app.services.embedding_service import EmbeddingService

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

    def __init__(self):
        self.calls = []

    def embed(self, text: str) -> list[float]:
        self.calls.append(text)
        vectors = {
            "growth query": [1.0, 0.0, 0.0],
            "growth narrative": [0.9, 0.1, 0.0],
            "risk narrative": [0.0, 1.0, 0.0],
            "growth news": [0.8, 0.2, 0.0],
            "updated narrative": [0.0, 0.0, 1.0],
        }
        return vectors[text]


def make_settings(**overrides) -> Settings:
    return Settings(_env_file=None, **{**BASE_SETTINGS, **overrides})


def enabled_settings(**overrides) -> Settings:
    values = {
        "LLM_FEATURES_ENABLED": True,
        "LLM_PROVIDER": "local",
        "LLM_MODEL": "unit-embedder",
        "LLM_ALLOWED_FEATURES": "embeddings,semantic_search",
    }
    values.update(overrides)
    return make_settings(**values)


def test_disabled_embeddings_do_not_call_provider_or_persist(db):
    provider = FakeEmbeddingProvider()
    service = EmbeddingService(provider=provider, settings=make_settings())

    result = service.upsert_text(
        db,
        source_type="scanner_narrative",
        source_id="event:1",
        text="growth narrative",
        metadata={"ticker": "TGT"},
    )

    assert result["status"] == "disabled"
    assert result["record"] is None
    assert provider.calls == []
    assert db.query(SemanticEmbedding).count() == 0


def test_upsert_inserts_and_updates_embedding_record(db):
    provider = FakeEmbeddingProvider()
    service = EmbeddingService(provider=provider, settings=enabled_settings())

    first = service.upsert_text(
        db,
        source_type="scanner_narrative",
        source_id="event:1",
        text="growth narrative",
        metadata={"ticker": "TGT"},
    )
    second = service.upsert_text(
        db,
        source_type="scanner_narrative",
        source_id="event:1",
        text="updated narrative",
        metadata={"ticker": "TGT", "refreshed": True},
    )

    assert first["status"] == "inserted"
    assert second["status"] == "updated"
    assert db.query(SemanticEmbedding).count() == 1
    record = db.query(SemanticEmbedding).one()
    assert record.source_type == "scanner_narrative"
    assert record.source_id == "event:1"
    assert record.provider == "local"
    assert record.model == "unit-embedder"
    assert record.embedding_version == "unit.v1"
    assert record.vector == [0.0, 0.0, 1.0]
    assert record.metadata_ == {"ticker": "TGT", "refreshed": True}


def test_search_returns_top_k_matches_with_source_filtering(db):
    provider = FakeEmbeddingProvider()
    service = EmbeddingService(provider=provider, settings=enabled_settings())
    service.upsert_text(
        db,
        source_type="scanner_narrative",
        source_id="event:1",
        text="growth narrative",
        metadata={"ticker": "TGT"},
    )
    service.upsert_text(
        db,
        source_type="scanner_narrative",
        source_id="event:2",
        text="risk narrative",
        metadata={"ticker": "RISK"},
    )
    service.upsert_text(
        db,
        source_type="news",
        source_id="article:1",
        text="growth news",
        metadata={"ticker": "NEWS"},
    )

    result = service.search(
        db,
        query_text="growth query",
        top_k=2,
        source_types=["scanner_narrative"],
    )

    assert result["status"] == "ok"
    assert [match["source_id"] for match in result["matches"]] == ["event:1", "event:2"]
    assert result["matches"][0]["score"] > result["matches"][1]["score"]
    assert all(match["source_type"] == "scanner_narrative" for match in result["matches"])


def test_search_disabled_returns_no_matches_without_provider_call(db):
    provider = FakeEmbeddingProvider()
    service = EmbeddingService(provider=provider, settings=make_settings())

    result = service.search(db, query_text="growth query", top_k=5)

    assert result["status"] == "disabled"
    assert result["matches"] == []
    assert provider.calls == []


def test_enabled_embeddings_without_provider_report_provider_unavailable(db):
    service = EmbeddingService(provider=None, settings=enabled_settings(LLM_PROVIDER="openai"))

    result = service.upsert_text(
        db,
        source_type="scanner_narrative",
        source_id="event:1",
        text="growth narrative",
    )

    assert result["status"] == "provider_unavailable"
    assert result["record"] is None
    assert db.query(SemanticEmbedding).count() == 0
