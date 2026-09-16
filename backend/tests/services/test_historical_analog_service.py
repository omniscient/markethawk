from datetime import date
from decimal import Decimal

from app.models.scanner_event import ScannerEvent
from app.models.scanner_outcome_snapshot import ScannerOutcomeSnapshot
from app.models.scanner_outcome_summary import ScannerOutcomeSummary
from app.services.historical_analog_service import HistoricalAnalogService

TARGET_DATE = date(2026, 7, 3)


def _explanation(
    prefix: str = "premarket",
    *,
    volume: float = 6.0,
    confidence: float = 0.8,
    warning_count: int = 0,
    extra_passed: list[str] | None = None,
) -> dict:
    passed = {
        f"{prefix}.volume_spike": {
            "label": "Volume spike",
            "observed": volume,
            "threshold": 4.0,
            "operator": ">=",
            "unit": "x",
            "source": "minute_aggregates",
            "importance": 1.0,
        }
    }
    for name in extra_passed or []:
        passed[f"{prefix}.{name}"] = {
            "label": name.replace("_", " ").title(),
            "observed": True,
            "threshold": True,
            "operator": "==",
            "importance": 0.7,
        }

    warnings = [
        {
            "code": f"warning_{idx}",
            "severity": "medium",
            "message": "Synthetic warning.",
            "affected_inputs": ["input"],
        }
        for idx in range(warning_count)
    ]
    return {
        "schema_version": "scanner_explanation.v1",
        "why": ["Synthetic explanation."],
        "criteria_passed": passed,
        "criteria_failed": {},
        "confidence_inputs": {
            "signal_quality_score": confidence,
            "threshold_method": "static",
        },
        "data_quality_warnings": warnings,
        "evidence": {
            "reconstructed": False,
            "generator_version": "explanation_builder.v1",
            "provider": "polygon",
        },
    }


def _seed_event(
    db,
    *,
    ticker: str,
    event_date: date,
    scanner_type: str = "pre_market_volume_spike",
    explanation: dict | None = None,
    complete: bool = True,
    captured_snapshots: int = 1,
    eod_pct_change: str = "2.50",
) -> ScannerEvent:
    event = ScannerEvent(
        ticker=ticker,
        event_date=event_date,
        scanner_type=scanner_type,
        summary=f"{ticker} signal",
        severity="medium",
        indicators={},
        criteria_met={},
        metadata_={},
        explanation=explanation if explanation is not None else _explanation(),
    )
    db.add(event)
    db.flush()

    summary = ScannerOutcomeSummary(
        scanner_event_id=event.id,
        reference_price=Decimal("10.00"),
        mfe_pct=Decimal("4.00"),
        mae_pct=Decimal("1.00"),
        mfe_mae_ratio=Decimal("4.0000"),
        r_multiple=Decimal("2.0000"),
        eod_pct_change=Decimal(eod_pct_change),
        follow_through=Decimal(eod_pct_change) > 0,
        gap_filled=False,
        is_complete=complete,
    )
    db.add(summary)
    for idx in range(captured_snapshots):
        db.add(
            ScannerOutcomeSnapshot(
                scanner_event_id=event.id,
                interval_key=f"{idx + 1}h",
                reference_price=Decimal("10.00"),
                snapshot_price=Decimal("10.25"),
                pct_change=Decimal("2.50"),
                status="captured",
            )
        )
    db.flush()
    return event


def test_find_similar_events_ranks_by_explanation_similarity(db):
    target = _seed_event(
        db,
        ticker="TGT",
        event_date=TARGET_DATE,
        explanation=_explanation(volume=6.0, confidence=0.85, extra_passed=["liquidity"]),
        complete=False,
        captured_snapshots=0,
    )
    close = _seed_event(
        db,
        ticker="NEAR",
        event_date=date(2026, 7, 1),
        explanation=_explanation(volume=6.1, confidence=0.82, extra_passed=["liquidity"]),
        eod_pct_change="3.25",
    )
    far = _seed_event(
        db,
        ticker="FAR",
        event_date=date(2026, 7, 2),
        explanation=_explanation(volume=2.0, confidence=0.25, warning_count=2),
        eod_pct_change="-1.50",
    )

    result = HistoricalAnalogService().find_similar_events(
        db,
        target_event_id=target.id,
        limit=2,
        min_sample_size=2,
    )

    assert result["target_event_id"] == target.id
    assert result["sample_size"] == 2
    assert [analog["event_id"] for analog in result["analogs"]] == [close.id, far.id]
    assert result["analogs"][0]["similarity_score"] > result["analogs"][1][
        "similarity_score"
    ]
    assert result["analogs"][0]["matched_criteria"] == [
        "premarket.liquidity",
        "premarket.volume_spike",
    ]
    assert result["analogs"][0]["score_components"]["criterion_overlap"] == 1.0
    assert result["analogs"][0]["outcome_summary"]["eod_pct_change"] == 3.25
    assert result["analogs"][0]["captured_snapshot_count"] == 1


def test_find_similar_events_filters_future_incomplete_and_scanner_type(db):
    target = _seed_event(
        db,
        ticker="TGT",
        event_date=TARGET_DATE,
        complete=False,
        captured_snapshots=0,
    )
    valid = _seed_event(db, ticker="OLD", event_date=date(2026, 7, 1))
    _seed_event(db, ticker="FUT", event_date=date(2026, 7, 4))
    _seed_event(db, ticker="INC", event_date=date(2026, 7, 2), complete=False)
    alternate_scanner = _seed_event(
        db,
        ticker="ALT",
        event_date=date(2026, 7, 1),
        scanner_type="liquidity_hunt_pre",
        explanation=_explanation("liquidity_hunt_pre"),
    )

    result = HistoricalAnalogService().find_similar_events(db, target_event_id=target.id)

    assert [analog["event_id"] for analog in result["analogs"]] == [valid.id]
    assert result["sample_size"] == 1
    assert result["filters"] == {
        "scanner_type": "pre_market_volume_spike",
        "same_scanner_only": True,
        "prior_only": True,
        "complete_only": True,
    }

    broadened = HistoricalAnalogService().find_similar_events(
        db,
        target_event_id=target.id,
        same_scanner_only=False,
    )

    assert {analog["event_id"] for analog in broadened["analogs"]} == {
        valid.id,
        alternate_scanner.id,
    }
    assert broadened["sample_size"] == 2
    assert broadened["filters"]["scanner_type"] is None


def test_find_similar_events_returns_no_analog_state(db):
    target = _seed_event(
        db,
        ticker="TGT",
        event_date=TARGET_DATE,
        complete=False,
        captured_snapshots=0,
    )

    result = HistoricalAnalogService().find_similar_events(db, target_event_id=target.id)

    assert result["analogs"] == []
    assert result["sample_size"] == 0
    assert result["warnings"] == [
        {
            "code": "no_historical_analogs",
            "message": "No complete prior analogs were available for this target event.",
        },
        {
            "code": "weak_sample_size",
            "message": "Only 0 analog candidates were available; minimum recommended sample is 5.",
        },
    ]
