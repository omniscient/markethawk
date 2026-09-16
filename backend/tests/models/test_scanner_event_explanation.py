from datetime import date

from sqlalchemy.orm import Session

from app.models.scanner_event import ScannerEvent


def test_scanner_event_persists_explanation_payload(db: Session):
    event = ScannerEvent(
        ticker="AAPL",
        event_date=date(2026, 6, 2),
        scanner_type="pre_market_volume_spike",
        indicators={},
        criteria_met={},
        metadata_={},
        explanation={
            "schema_version": "scanner_explanation.v1",
            "why": ["Volume was elevated."],
            "criteria_passed": {},
            "criteria_failed": {},
            "confidence_inputs": {},
            "data_quality_warnings": [],
            "evidence": {"reconstructed": False},
        },
    )
    db.add(event)
    db.flush()
    db.expire(event)

    loaded = db.query(ScannerEvent).filter_by(id=event.id).one()

    assert loaded.explanation["schema_version"] == "scanner_explanation.v1"
