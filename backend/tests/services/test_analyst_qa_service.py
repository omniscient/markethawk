from datetime import date

from app.core.config import Settings
from app.models.scanner_event import ScannerEvent
from app.services.analyst_qa_service import AnalystQAService

BASE_SETTINGS = {
    "DATABASE_URL": "postgresql://test:test@localhost/test",
    "POLYGON_API_KEY": "test-key",
    "JWT_SECRET_KEY": "a" * 32,
    "REDIS_PASSWORD": "r" * 16,
}


class FakeBriefService:
    def __init__(self):
        self.calls = []

    def build(self, db, event):
        self.calls.append(event.id)
        return {
            "schema_version": "ai_signal_brief.v1",
            "event_id": event.id,
            "facts": {
                "ticker": event.ticker,
                "event_date": event.event_date.isoformat(),
                "scanner_type": event.scanner_type,
                "summary": event.summary,
                "severity": event.severity,
            },
            "why": ["Volume expanded before the open."],
            "risks": ["News catalyst did not pass."],
            "warnings": [{"code": "stale_quote", "message": "Quote was stale."}],
            "outcome_context": {
                "summary": {
                    "eod_pct_change": 2.4,
                    "follow_through": True,
                    "is_complete": True,
                },
                "snapshots": [],
            },
        }


class FakeSemanticSearch:
    def find_for_event(self, db, event, *, top_k=5, source_types=None):
        return {
            "semantic_matches": [
                {
                    "source_type": "generated_narrative",
                    "source_id": "scanner_event_narrative:1",
                    "score": 0.91,
                    "why": "Semantic similarity matched generated narrative.",
                }
            ]
        }


def make_settings(**overrides) -> Settings:
    return Settings(_env_file=None, **{**BASE_SETTINGS, **overrides})


def enabled_settings() -> Settings:
    return make_settings(
        LLM_FEATURES_ENABLED=True,
        LLM_PROVIDER="local",
        LLM_MODEL="unit-qa",
        LLM_ALLOWED_FEATURES="analyst_qa",
    )


def seed_event(db, *, ticker="TGT", scanner_type="pre_market_volume_spike"):
    event = ScannerEvent(
        ticker=ticker,
        event_date=date(2026, 7, 3),
        scanner_type=scanner_type,
        summary=f"{ticker} volume signal",
        severity="high",
        indicators={},
        criteria_met={},
        metadata_={},
        explanation={},
    )
    db.add(event)
    db.flush()
    return event


def test_disabled_qa_returns_no_answer_without_building_context(db):
    event = seed_event(db)
    brief_service = FakeBriefService()
    service = AnalystQAService(
        brief_service=brief_service,
        semantic_search_service=FakeSemanticSearch(),
        settings=make_settings(),
    )

    result = service.answer_for_event(db, event, question="What happened?")

    assert result["status"] == "disabled"
    assert result["answer"] is None
    assert brief_service.calls == []


def test_grounded_event_answer_includes_citations_and_semantic_context(db):
    event = seed_event(db)
    service = AnalystQAService(
        brief_service=FakeBriefService(),
        semantic_search_service=FakeSemanticSearch(),
        settings=enabled_settings(),
    )

    result = service.answer_for_event(db, event, question="Why did this signal work?")

    assert result["status"] == "answered"
    assert "TGT volume signal" in result["answer"]
    assert "Volume expanded before the open." in result["answer"]
    assert result["citations"] == [
        {"source": "brief.facts.summary", "value": "TGT volume signal"},
        {"source": "brief.why", "value": "Volume expanded before the open."},
        {"source": "outcome_context.summary", "value": "follow_through=True"},
        {
            "source": "semantic_matches[0]",
            "value": "generated_narrative scanner_event_narrative:1 score=0.91",
        },
    ]


def test_unsupported_question_is_rejected_before_context_generation(db):
    event = seed_event(db)
    brief_service = FakeBriefService()
    service = AnalystQAService(
        brief_service=brief_service,
        semantic_search_service=FakeSemanticSearch(),
        settings=enabled_settings(),
    )

    result = service.answer_for_event(db, event, question="Should I buy TGT now?")

    assert result["status"] == "unsupported"
    assert result["answer"] is None
    assert "trade recommendation" in result["reason"]
    assert brief_service.calls == []


def test_filtered_event_set_answer_uses_matching_events_only(db):
    target = seed_event(db, ticker="TGT", scanner_type="pre_market_volume_spike")
    seed_event(db, ticker="IGN", scanner_type="liquidity_hunt")
    brief_service = FakeBriefService()
    service = AnalystQAService(
        brief_service=brief_service,
        semantic_search_service=FakeSemanticSearch(),
        settings=enabled_settings(),
    )

    result = service.answer_for_events(
        db,
        question="Summarize pre-market volume signals.",
        scanner_type="pre_market_volume_spike",
    )

    assert result["status"] == "answered"
    assert result["event_count"] == 1
    assert "TGT volume signal" in result["answer"]
    assert brief_service.calls == [target.id]
