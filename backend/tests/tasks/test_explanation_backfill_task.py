from datetime import date

from sqlalchemy.orm import Session

from app.models.scanner_event import ScannerEvent
from app.tasks.explanations import _backfill_scanner_explanations_logic


def _event(ticker: str, explanation=None):
    return ScannerEvent(
        ticker=ticker,
        event_date=date(2026, 6, 2),
        scanner_type="pre_market_volume_spike",
        indicators={"pre_market_volume": 650000, "avg_volume_20d": 125000},
        criteria_met={"volume_spike": True, "minimum_volume": True, "liquidity": True},
        metadata_={},
        explanation=explanation,
    )


def test_backfill_scanner_explanations_populates_missing_payloads(db: Session):
    missing = _event("AAPL")
    existing = _event(
        "MSFT",
        explanation={
            "schema_version": "scanner_explanation.v1",
            "why": ["Already present."],
            "criteria_passed": {},
            "criteria_failed": {},
            "confidence_inputs": {},
            "data_quality_warnings": [],
            "evidence": {"reconstructed": False},
        },
    )
    db.add_all([missing, existing])
    db.flush()

    result = _backfill_scanner_explanations_logic(
        db,
        scanner_type="pre_market_volume_spike",
        limit=100,
    )

    assert result == {"updated": 1, "skipped": 1}
    assert missing.explanation["evidence"]["reconstructed"] is True
    assert existing.explanation["why"] == ["Already present."]
