from datetime import date, datetime

from app.core.config import Settings
from app.models.news_article import NewsArticle
from app.models.scanner_event import ScannerEvent
from app.models.scanner_event_narrative import ScannerEventNarrative
from app.models.semantic_embedding import SemanticEmbedding
from app.services.domain_embedding_service import DomainEmbeddingService
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

    def __init__(self, exc: Exception | None = None):
        self.calls = []
        self.exc = exc

    def embed(self, text: str) -> list[float]:
        self.calls.append(text)
        if self.exc:
            raise self.exc
        return [float(len(text)), 1.0]


class FakeBriefService:
    def build(self, db, event):
        return {
            "schema_version": "ai_signal_brief.v1",
            "event_id": event.id,
            "facts": {
                "ticker": event.ticker,
                "event_date": event.event_date.isoformat(),
                "scanner_type": event.scanner_type,
                "summary": event.summary,
            },
            "why": ["Volume expanded before the open."],
            "risks": ["News catalyst did not pass."],
            "warnings": [{"code": "stale_quote", "message": "Quote was stale."}],
            "analogs": [],
            "outcome_context": {"summary": None, "snapshots": []},
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


def embedding_service(provider: FakeEmbeddingProvider) -> EmbeddingService:
    return EmbeddingService(provider=provider, settings=enabled_settings())


def seed_event(db, *, metadata=None) -> ScannerEvent:
    event = ScannerEvent(
        ticker="TGT",
        event_date=date(2026, 7, 3),
        scanner_type="pre_market_volume_spike",
        summary="TGT pre-market volume expanded.",
        severity="high",
        indicators={},
        criteria_met={},
        metadata_=metadata or {},
        explanation={},
    )
    db.add(event)
    db.flush()
    return event


def seed_news(db) -> NewsArticle:
    article = NewsArticle(
        title="TGT announces growth plan",
        description="Management raised revenue guidance.",
        published_utc=datetime(2026, 7, 3, 12, 0, 0),
        article_url="https://example.com/tgt-growth",
        provider="unit",
        tickers=["TGT"],
    )
    db.add(article)
    db.flush()
    return article


def seed_narrative(db, event: ScannerEvent) -> ScannerEventNarrative:
    narrative = ScannerEventNarrative(
        scanner_event_id=event.id,
        feature_area="scanner_narrative",
        narrative_text="TGT generated narrative with risks and provenance.",
        provider="local",
        model="unit-narrator",
        prompt_version="scanner_narrative.v1",
        brief_schema_version="ai_signal_brief.v1",
        brief_fingerprint="abc123",
        input_payload={},
        provenance_payload=[],
    )
    db.add(narrative)
    db.flush()
    return narrative


def test_embeds_news_catalyst_signal_brief_and_generated_narrative(db):
    provider = FakeEmbeddingProvider()
    service = DomainEmbeddingService(
        embedding_service=embedding_service(provider),
        brief_service=FakeBriefService(),
    )
    event = seed_event(
        db,
        metadata={
            "catalyst": {
                "headline": "FDA clearance",
                "summary": "Device clearance expanded the addressable market.",
            }
        },
    )
    article = seed_news(db)
    narrative = seed_narrative(db, event)

    news = service.embed_news_article(db, article)
    catalyst = service.embed_scanner_catalyst(db, event)
    brief = service.embed_signal_brief(db, event)
    generated = service.embed_generated_narrative(db, narrative)

    assert news["status"] == "inserted"
    assert catalyst["status"] == "inserted"
    assert brief["status"] == "inserted"
    assert generated["status"] == "inserted"
    rows = {
        (row.source_type, row.source_id): row
        for row in db.query(SemanticEmbedding).order_by(SemanticEmbedding.source_type)
    }
    assert ("news", f"news:{article.id}") in rows
    assert ("catalyst", f"scanner_event:{event.id}") in rows
    assert ("scanner_explanation", f"scanner_event:{event.id}") in rows
    assert ("generated_narrative", f"scanner_event_narrative:{narrative.id}") in rows
    assert rows[("news", f"news:{article.id}")].metadata_["tickers"] == ["TGT"]
    assert rows[
        ("generated_narrative", f"scanner_event_narrative:{narrative.id}")
    ].metadata_["feature_area"] == "scanner_narrative"
    assert any("FDA clearance" in text for text in provider.calls)
    assert any("Volume expanded before the open." in text for text in provider.calls)


def test_repeated_news_embedding_tracks_unchanged_and_stale_recomputed(db):
    provider = FakeEmbeddingProvider()
    service = DomainEmbeddingService(embedding_service=embedding_service(provider))
    article = seed_news(db)

    first = service.embed_news_article(db, article)
    second = service.embed_news_article(db, article)
    article.description = "Management cut guidance after the first report."
    third = service.embed_news_article(db, article)

    assert first["freshness"] == "new"
    assert second["freshness"] == "unchanged"
    assert third["freshness"] == "stale_recomputed"
    assert db.query(SemanticEmbedding).count() == 1
    assert db.query(SemanticEmbedding).one().metadata_["source_fingerprint"] == third[
        "source_fingerprint"
    ]


def test_missing_catalyst_is_skipped_without_embedding_call(db):
    provider = FakeEmbeddingProvider()
    service = DomainEmbeddingService(embedding_service=embedding_service(provider))
    event = seed_event(db)

    result = service.embed_scanner_catalyst(db, event)

    assert result["status"] == "skipped"
    assert result["reason"] == "No catalyst text available."
    assert provider.calls == []
    assert db.query(SemanticEmbedding).count() == 0


def test_embedding_failure_is_reported_without_raising(db):
    provider = FakeEmbeddingProvider(exc=RuntimeError("provider timeout"))
    service = DomainEmbeddingService(embedding_service=embedding_service(provider))
    article = seed_news(db)

    result = service.embed_news_article(db, article)

    assert result["status"] == "failed"
    assert result["error"] == "provider timeout"
    assert db.query(SemanticEmbedding).count() == 0
