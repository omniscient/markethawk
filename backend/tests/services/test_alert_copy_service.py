from datetime import date

from app.core.config import Settings
from app.models.scanner_event import ScannerEvent
from app.services.alert_copy import AlertCopyService

BASE_SETTINGS = {
    "DATABASE_URL": "postgresql://test:test@localhost/test",
    "POLYGON_API_KEY": "test-key",
    "JWT_SECRET_KEY": "a" * 32,
    "REDIS_PASSWORD": "r" * 16,
}


class FakeNarrativeService:
    def __init__(self, result=None, exc: Exception | None = None):
        self.result = result
        self.exc = exc
        self.calls = []

    def build(self, db, event):
        self.calls.append(event.id)
        if self.exc:
            raise self.exc
        return self.result


def make_settings(**overrides) -> Settings:
    return Settings(_env_file=None, **{**BASE_SETTINGS, **overrides})


def enabled_settings() -> Settings:
    return make_settings(
        LLM_FEATURES_ENABLED=True,
        LLM_PROVIDER="local",
        LLM_MODEL="unit-copy",
        LLM_ALLOWED_FEATURES="alert_copy,scanner_narrative",
    )


def make_event(db) -> ScannerEvent:
    event = ScannerEvent(
        ticker="TGT",
        event_date=date(2026, 7, 3),
        scanner_type="pre_market_volume_spike",
        summary="TGT volume expanded before the open.",
        severity="high",
        indicators={"volume_spike_ratio": 6.0},
        criteria_met={},
        metadata_={},
        explanation={},
    )
    db.add(event)
    db.flush()
    return event


def narrative_result() -> dict:
    return {
        "brief": {
            "facts": {
                "ticker": "TGT",
                "scanner_type": "pre_market_volume_spike",
                "severity": "high",
                "summary": "TGT volume expanded before the open.",
            },
            "why": ["Volume and liquidity aligned with the scanner setup."],
            "risks": ["Outcome summary is incomplete or unavailable."],
            "warnings": [
                {
                    "code": "stale_quote",
                    "message": "Quote data is older than expected.",
                }
            ],
        },
        "narrative": {
            "text": "TGT produced a high pre-market volume signal.",
            "provenance": [{"claim": "summary", "source_fields": ["facts.summary"]}],
        },
        "cache": {"status": "hit"},
    }


def test_disabled_alert_copy_returns_deterministic_fallback_without_narrative_call(db):
    event = make_event(db)
    narrative_service = FakeNarrativeService(result=narrative_result())
    service = AlertCopyService(
        narrative_service=narrative_service,
        settings=make_settings(),
    )

    copy = service.build(db, event)

    assert copy["source"] == "deterministic"
    assert copy["title"] == "MarketHawk Alert: TGT - Pre Market Volume Spike"
    assert copy["summary"] == "TGT volume expanded before the open."
    assert copy["body"] == "TGT volume expanded before the open."
    assert narrative_service.calls == []


def test_enabled_alert_copy_uses_validated_narrative_brief_risks_and_warnings(db):
    event = make_event(db)
    service = AlertCopyService(
        narrative_service=FakeNarrativeService(result=narrative_result()),
        settings=enabled_settings(),
    )

    copy = service.build(db, event)

    assert copy["source"] == "generated"
    assert copy["title"] == "MarketHawk Alert: TGT - Pre Market Volume Spike"
    assert "TGT produced a high pre-market volume signal." in copy["body"]
    assert "Volume and liquidity aligned with the scanner setup." in copy["body"]
    assert "Outcome summary is incomplete or unavailable." in copy["body"]
    assert "Quote data is older than expected." in copy["body"]
    assert copy["risk_caveats"] == ["Outcome summary is incomplete or unavailable."]
    assert copy["data_quality_caveats"] == ["Quote data is older than expected."]


def test_alert_copy_generation_failure_returns_deterministic_fallback(db):
    event = make_event(db)
    service = AlertCopyService(
        narrative_service=FakeNarrativeService(exc=RuntimeError("provider timeout")),
        settings=enabled_settings(),
    )

    copy = service.build(db, event)

    assert copy["source"] == "fallback"
    assert copy["summary"] == "TGT volume expanded before the open."
    assert copy["body"] == "TGT volume expanded before the open."
    assert copy["generation_error"] == "provider timeout"


def test_enabled_alert_copy_falls_back_when_narrative_is_rejected(db):
    event = make_event(db)
    service = AlertCopyService(
        narrative_service=FakeNarrativeService(
            result={
                "brief": narrative_result()["brief"],
                "narrative": None,
                "cache": {"status": "rejected"},
                "rejection": {"reason": "Generated narrative is missing provenance."},
            }
        ),
        settings=enabled_settings(),
    )

    copy = service.build(db, event)

    assert copy["source"] == "fallback"
    assert copy["body"] == "TGT volume expanded before the open."
    assert copy["generation_error"] == "Generated narrative is missing provenance."
