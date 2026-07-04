from datetime import date

from app.core.config import Settings
from app.models.scanner_event import ScannerEvent
from app.models.scanner_event_narrative import ScannerEventNarrative
from app.services.scanner_event_narrative import ScannerEventNarrativeService

BASE_SETTINGS = {
    "DATABASE_URL": "postgresql://test:test@localhost/test",
    "POLYGON_API_KEY": "test-key",
    "JWT_SECRET_KEY": "a" * 32,
    "REDIS_PASSWORD": "r" * 16,
}


class FakeBriefService:
    schema_version = "ai_signal_brief.v1"

    def __init__(self, brief: dict):
        self.brief = brief

    def build(self, db, event):
        return self.brief


class RecordingGenerator:
    provider_name = "local"
    model_name = "unit-narrator"

    def __init__(self):
        self.calls = []

    def generate(self, brief, guardrails):
        self.calls.append({"brief": brief, "guardrails": guardrails})
        facts = brief["facts"]
        risks = brief["risks"]
        return f"{facts['ticker']} narrative. Risks: {'; '.join(risks)}"


class StructuredGenerator:
    provider_name = "local"
    model_name = "unit-narrator"

    def __init__(self, payload):
        self.payload = payload

    def generate(self, brief, guardrails):
        return self.payload


def make_settings(**overrides) -> Settings:
    return Settings(_env_file=None, **{**BASE_SETTINGS, **overrides})


def make_brief(*, ticker: str = "TGT", risks: list[str] | None = None) -> dict:
    return {
        "schema_version": "ai_signal_brief.v1",
        "event_id": 1,
        "facts": {
            "ticker": ticker,
            "event_date": "2026-07-03",
            "scanner_type": "pre_market_volume_spike",
            "severity": "high",
            "summary": f"{ticker} signal",
            "signal_quality_score": 0.86,
            "regime": "risk_on",
        },
        "why": ["This must not be used by the narrative generator."],
        "risks": risks or ["Outcome summary is incomplete or unavailable."],
        "warnings": [],
        "analogs": [{"ticker": "OLD"}],
        "outcome_context": {"summary": None, "snapshots": []},
        "forbidden_claims": ["Do not recommend live trade execution."],
    }


def seed_event(db) -> ScannerEvent:
    event = ScannerEvent(
        ticker="TGT",
        event_date=date(2026, 7, 3),
        scanner_type="pre_market_volume_spike",
        summary="TGT signal",
        severity="high",
        indicators={},
        criteria_met={},
        metadata_={},
        explanation={},
    )
    db.add(event)
    db.flush()
    return event


def enabled_settings() -> Settings:
    return make_settings(
        LLM_FEATURES_ENABLED=True,
        LLM_PROVIDER="local",
        LLM_MODEL="unit-narrator",
        LLM_ALLOWED_FEATURES="scanner_narrative",
    )


def test_disabled_feature_returns_brief_without_generated_text(db):
    event = seed_event(db)
    generator = RecordingGenerator()
    service = ScannerEventNarrativeService(
        brief_service=FakeBriefService(make_brief()),
        generator=generator,
        settings=make_settings(),
    )

    result = service.build(db, event)

    assert result["brief"]["facts"]["ticker"] == "TGT"
    assert result["narrative"] is None
    assert result["cache"]["status"] == "disabled"
    assert generator.calls == []
    assert db.query(ScannerEventNarrative).count() == 0


def test_cache_miss_generates_narrative_from_facts_and_risks(db):
    event = seed_event(db)
    brief = make_brief()
    generator = RecordingGenerator()
    service = ScannerEventNarrativeService(
        brief_service=FakeBriefService(brief),
        generator=generator,
        settings=enabled_settings(),
    )

    result = service.build(db, event)

    assert result["cache"]["status"] == "miss"
    assert result["narrative"]["text"] == (
        "TGT narrative. Risks: Outcome summary is incomplete or unavailable."
    )
    assert result["narrative"]["provider"] == "local"
    assert result["narrative"]["model"] == "unit-narrator"
    assert result["narrative"]["prompt_version"] == "scanner_narrative.v1"
    assert result["narrative"]["brief_schema_version"] == "ai_signal_brief.v1"
    assert generator.calls == [{"brief": brief, "guardrails": result["guardrails"]}]

    cached = db.query(ScannerEventNarrative).one()
    assert cached.narrative_text == result["narrative"]["text"]
    assert cached.provider == "local"
    assert cached.model == "unit-narrator"
    assert cached.input_payload == {
        "facts": brief["facts"],
        "risks": brief["risks"],
    }


def test_cache_hit_returns_cached_narrative_without_generation(db):
    event = seed_event(db)
    brief = make_brief()
    generator = RecordingGenerator()
    service = ScannerEventNarrativeService(
        brief_service=FakeBriefService(brief),
        generator=generator,
        settings=enabled_settings(),
    )
    first = service.build(db, event)
    generator.calls.clear()

    second = service.build(db, event)

    assert second["cache"]["status"] == "hit"
    assert second["narrative"]["text"] == first["narrative"]["text"]
    assert generator.calls == []
    assert db.query(ScannerEventNarrative).count() == 1


def test_stale_brief_regenerates_and_updates_existing_cache_row(db):
    event = seed_event(db)
    generator = RecordingGenerator()
    service = ScannerEventNarrativeService(
        brief_service=FakeBriefService(make_brief(risks=["Initial risk."])),
        generator=generator,
        settings=enabled_settings(),
    )
    first = service.build(db, event)
    cache_id = db.query(ScannerEventNarrative).one().id

    service = ScannerEventNarrativeService(
        brief_service=FakeBriefService(make_brief(risks=["Updated risk."])),
        generator=generator,
        settings=enabled_settings(),
    )
    second = service.build(db, event)

    assert second["cache"]["status"] == "stale_regenerated"
    assert second["narrative"]["text"] == "TGT narrative. Risks: Updated risk."
    assert second["narrative"]["brief_fingerprint"] != first["narrative"][
        "brief_fingerprint"
    ]
    cached = db.query(ScannerEventNarrative).one()
    assert cached.id == cache_id
    assert cached.input_payload["risks"] == ["Updated risk."]


def test_supported_provenance_is_returned_and_cached(db):
    event = seed_event(db)
    provenance = [
        {
            "claim": "Ticker and setup summary",
            "source_fields": ["facts.ticker", "facts.summary"],
        },
        {"claim": "Risk summary", "source_fields": ["risks"]},
    ]
    service = ScannerEventNarrativeService(
        brief_service=FakeBriefService(make_brief()),
        generator=StructuredGenerator(
            {
                "text": "TGT signal narrative. Key risks: incomplete outcome.",
                "provenance": provenance,
            }
        ),
        settings=enabled_settings(),
    )

    result = service.build(db, event)

    assert result["cache"]["status"] == "miss"
    assert result["narrative"]["provenance"] == provenance
    cached = db.query(ScannerEventNarrative).one()
    assert cached.provenance_payload == provenance


def test_forbidden_claim_is_rejected_before_persistence(db):
    event = seed_event(db)
    service = ScannerEventNarrativeService(
        brief_service=FakeBriefService(make_brief()),
        generator=StructuredGenerator(
            {
                "text": "TGT is strong, so recommend live trade execution now.",
                "provenance": [
                    {"claim": "Ticker summary", "source_fields": ["facts.ticker"]}
                ],
            }
        ),
        settings=enabled_settings(),
    )

    result = service.build(db, event)

    assert result["narrative"] is None
    assert result["cache"]["status"] == "rejected"
    assert "forbidden claim" in result["rejection"]["reason"]
    assert db.query(ScannerEventNarrative).count() == 0


def test_missing_provenance_is_rejected_before_persistence(db):
    event = seed_event(db)
    service = ScannerEventNarrativeService(
        brief_service=FakeBriefService(make_brief()),
        generator=StructuredGenerator({"text": "TGT narrative without provenance."}),
        settings=enabled_settings(),
    )

    result = service.build(db, event)

    assert result["narrative"] is None
    assert result["cache"]["status"] == "rejected"
    assert "provenance" in result["rejection"]["reason"]
    assert db.query(ScannerEventNarrative).count() == 0


def test_unsupported_provenance_field_is_rejected_before_persistence(db):
    event = seed_event(db)
    service = ScannerEventNarrativeService(
        brief_service=FakeBriefService(make_brief()),
        generator=StructuredGenerator(
            {
                "text": "TGT narrative with unsupported provenance.",
                "provenance": [
                    {"claim": "Analog claim", "source_fields": ["analogs"]}
                ],
            }
        ),
        settings=enabled_settings(),
    )

    result = service.build(db, event)

    assert result["narrative"] is None
    assert result["cache"]["status"] == "rejected"
    assert "unsupported provenance field" in result["rejection"]["reason"]
    assert db.query(ScannerEventNarrative).count() == 0
