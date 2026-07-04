from datetime import date

from app.core.config import Settings
from app.models.scanner_event import ScannerEvent
from app.models.scanner_event_narrative import ScannerEventNarrative
from app.services.signal_post_mortem import SignalPostMortemService

BASE_SETTINGS = {
    "DATABASE_URL": "postgresql://test:test@localhost/test",
    "POLYGON_API_KEY": "test-key",
    "JWT_SECRET_KEY": "a" * 32,
    "REDIS_PASSWORD": "r" * 16,
}


class FakeBriefService:
    def __init__(self, brief: dict):
        self.brief = brief

    def build(self, db, event):
        return self.brief


class RecordingGenerator:
    provider_name = "local"
    model_name = "unit-post-mortem"

    def __init__(self, payload: dict | None = None):
        self.payload = payload
        self.calls = []

    def generate(self, post_mortem_input, guardrails):
        self.calls.append(
            {"post_mortem_input": post_mortem_input, "guardrails": guardrails}
        )
        if self.payload is not None:
            return self.payload
        facts = post_mortem_input["signal_time"]["facts"]
        outcome = post_mortem_input["realized_outcome"]["summary"]
        result = "won" if outcome["follow_through"] else "lost"
        return {
            "text": f"{facts['ticker']} post-mortem: signal {result}.",
            "provenance": [
                {"claim": "Signal context", "source_fields": ["signal_time.facts"]},
                {
                    "claim": "Realized outcome",
                    "source_fields": ["realized_outcome.summary"],
                },
            ],
        }


def make_settings(**overrides) -> Settings:
    return Settings(_env_file=None, **{**BASE_SETTINGS, **overrides})


def enabled_settings() -> Settings:
    return make_settings(
        LLM_FEATURES_ENABLED=True,
        LLM_PROVIDER="local",
        LLM_MODEL="unit-post-mortem",
        LLM_ALLOWED_FEATURES="post_mortem",
    )


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


def make_brief(
    *,
    follow_through: bool | None = True,
    eod_pct_change: float | None = 2.1,
    complete: bool = True,
) -> dict:
    summary = None
    if follow_through is not None:
        summary = {
            "scanner_event_id": 1,
            "reference_price": 10.0,
            "mfe_pct": 4.2,
            "mae_pct": 0.8,
            "mfe_mae_ratio": 5.25,
            "r_multiple": 2.0,
            "eod_pct_change": eod_pct_change,
            "follow_through": follow_through,
            "gap_filled": False,
            "is_complete": complete,
        }
    return {
        "schema_version": "ai_signal_brief.v1",
        "event_id": 1,
        "facts": {
            "ticker": "TGT",
            "event_date": "2026-07-03",
            "scanner_type": "pre_market_volume_spike",
            "severity": "high",
            "summary": "TGT pre-market volume expanded.",
            "signal_quality_score": 0.86,
            "regime": "risk_on",
        },
        "why": ["Volume and liquidity aligned with the scanner setup."],
        "risks": ["News catalyst did not pass."],
        "warnings": [{"code": "stale_quote", "message": "Quote was stale."}],
        "analogs": [
            {
                "ticker": "OLD",
                "similarity_score": 0.91,
                "outcome_summary": {"eod_pct_change": 1.8, "follow_through": True},
            }
        ],
        "outcome_context": {"summary": summary, "snapshots": []},
        "archetype": {
            "label": "Volume Spike / Positive Outcomes",
            "return_profile": {"win_rate_pct": 64.0, "sample_size": 25},
        },
        "forbidden_claims": ["Do not claim guaranteed future returns."],
    }


def test_disabled_post_mortem_returns_brief_without_generation(db):
    event = seed_event(db)
    generator = RecordingGenerator()
    service = SignalPostMortemService(
        brief_service=FakeBriefService(make_brief()),
        generator=generator,
        settings=make_settings(),
    )

    result = service.build(db, event)

    assert result["brief"]["facts"]["ticker"] == "TGT"
    assert result["post_mortem"] is None
    assert result["cache"]["status"] == "disabled"
    assert generator.calls == []
    assert db.query(ScannerEventNarrative).count() == 0


def test_winning_outcome_generates_grounded_post_mortem_and_cache(db):
    event = seed_event(db)
    brief = make_brief(follow_through=True, eod_pct_change=2.1)
    generator = RecordingGenerator()
    service = SignalPostMortemService(
        brief_service=FakeBriefService(brief),
        generator=generator,
        settings=enabled_settings(),
    )

    result = service.build(db, event)

    assert result["cache"]["status"] == "miss"
    assert result["post_mortem"]["text"] == "TGT post-mortem: signal won."
    assert result["post_mortem"]["outcome_status"] == "winning"
    assert result["post_mortem"]["prompt_version"] == "signal_post_mortem.v1"
    assert result["post_mortem"]["provenance"] == [
        {"claim": "Signal context", "source_fields": ["signal_time.facts"]},
        {"claim": "Realized outcome", "source_fields": ["realized_outcome.summary"]},
    ]
    post_mortem_input = generator.calls[0]["post_mortem_input"]
    assert post_mortem_input["signal_time"]["why"] == brief["why"]
    assert post_mortem_input["expected_behavior"]["analogs"] == brief["analogs"]
    assert post_mortem_input["realized_outcome"]["summary"]["follow_through"] is True

    cached = db.query(ScannerEventNarrative).one()
    assert cached.feature_area == "post_mortem"
    assert cached.narrative_text == result["post_mortem"]["text"]
    assert cached.input_payload == post_mortem_input


def test_losing_outcome_is_labeled_without_changing_signal_time_context(db):
    event = seed_event(db)
    service = SignalPostMortemService(
        brief_service=FakeBriefService(
            make_brief(follow_through=False, eod_pct_change=-1.4)
        ),
        generator=RecordingGenerator(),
        settings=enabled_settings(),
    )

    result = service.build(db, event)

    assert result["post_mortem"]["outcome_status"] == "losing"
    assert "News catalyst did not pass." in result["post_mortem"]["known_at_signal_time"][
        "risks"
    ]
    assert result["post_mortem"]["realized_outcome"]["summary"]["eod_pct_change"] == -1.4


def test_incomplete_outcome_does_not_generate_post_mortem(db):
    event = seed_event(db)
    generator = RecordingGenerator()
    service = SignalPostMortemService(
        brief_service=FakeBriefService(make_brief(follow_through=True, complete=False)),
        generator=generator,
        settings=enabled_settings(),
    )

    result = service.build(db, event)

    assert result["post_mortem"] is None
    assert result["cache"]["status"] == "incomplete_outcome"
    assert result["rejection"]["reason"] == "Outcome summary is incomplete or unavailable."
    assert generator.calls == []
    assert db.query(ScannerEventNarrative).count() == 0


def test_cache_hit_reuses_post_mortem_without_generation(db):
    event = seed_event(db)
    brief = make_brief()
    generator = RecordingGenerator()
    service = SignalPostMortemService(
        brief_service=FakeBriefService(brief),
        generator=generator,
        settings=enabled_settings(),
    )
    first = service.build(db, event)
    generator.calls.clear()

    second = service.build(db, event)

    assert second["cache"]["status"] == "hit"
    assert second["post_mortem"]["text"] == first["post_mortem"]["text"]
    assert generator.calls == []
    assert db.query(ScannerEventNarrative).count() == 1


def test_unsupported_provenance_field_is_rejected_before_persistence(db):
    event = seed_event(db)
    service = SignalPostMortemService(
        brief_service=FakeBriefService(make_brief()),
        generator=RecordingGenerator(
            {
                "text": "TGT post-mortem with unsupported provenance.",
                "provenance": [
                    {"claim": "Unsupported", "source_fields": ["future_prediction"]}
                ],
            }
        ),
        settings=enabled_settings(),
    )

    result = service.build(db, event)

    assert result["post_mortem"] is None
    assert result["cache"]["status"] == "rejected"
    assert "unsupported provenance field" in result["rejection"]["reason"]
    assert db.query(ScannerEventNarrative).count() == 0
