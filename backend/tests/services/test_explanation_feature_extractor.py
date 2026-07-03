from datetime import date
from decimal import Decimal

from app.models.scanner_event import ScannerEvent
from app.models.scanner_outcome_snapshot import ScannerOutcomeSnapshot
from app.models.scanner_outcome_summary import ScannerOutcomeSummary
from app.services.explanation_feature_extractor import ExplanationFeatureExtractor


def _explanation(
    prefix: str,
    *,
    reconstructed: bool = False,
    warnings: list[dict] | None = None,
) -> dict:
    return {
        "schema_version": "scanner_explanation.v1",
        "why": ["Deterministic explanation for feature tests."],
        "criteria_passed": {
            f"{prefix}.volume_spike": {
                "label": "Volume spike",
                "observed": 6.2,
                "threshold": 4.0,
                "operator": ">=",
                "unit": "x",
                "source": "minute_aggregates",
                "importance": 1.0,
            }
        },
        "criteria_failed": {
            f"{prefix}.news_catalyst": {
                "label": "News catalyst",
                "observed": False,
                "threshold": True,
                "operator": "==",
                "importance": 0.4,
            }
        },
        "confidence_inputs": {
            "signal_quality_score": 0.83,
            "threshold_method": "static",
            "has_news_catalyst": False,
        },
        "data_quality_warnings": warnings or [],
        "evidence": {
            "reconstructed": reconstructed,
            "reconstruction_quality": "partial" if reconstructed else None,
            "generator_version": "explanation_builder.v1",
            "provider": "polygon",
        },
    }


def _event(
    *,
    event_id: int,
    scanner_type: str,
    explanation: dict | None,
) -> ScannerEvent:
    return ScannerEvent(
        id=event_id,
        ticker=f"T{event_id}",
        event_date=date(2026, 7, 3),
        scanner_type=scanner_type,
        summary="feature test signal",
        severity="medium",
        indicators={"legacy_indicator": 9.5},
        criteria_met={},
        metadata_={},
        explanation=explanation,
    )


def _summary(event_id: int) -> ScannerOutcomeSummary:
    return ScannerOutcomeSummary(
        scanner_event_id=event_id,
        reference_price=Decimal("10.00"),
        mfe_pct=Decimal("4.25"),
        mae_pct=Decimal("1.25"),
        mfe_mae_ratio=Decimal("3.4000"),
        r_multiple=Decimal("2.1000"),
        eod_pct_change=Decimal("2.50"),
        follow_through=True,
        gap_filled=False,
        is_complete=True,
    )


def _snapshot(event_id: int, interval_key: str = "15m") -> ScannerOutcomeSnapshot:
    return ScannerOutcomeSnapshot(
        scanner_event_id=event_id,
        interval_key=interval_key,
        reference_price=Decimal("10.00"),
        snapshot_price=Decimal("10.25"),
        pct_change=Decimal("2.50"),
        high_since_signal=Decimal("10.50"),
        low_since_signal=Decimal("9.90"),
        volume_since_signal=120000,
        status="captured",
    )


def test_extract_event_flattens_two_scanner_types_and_warnings():
    extractor = ExplanationFeatureExtractor()
    warning = {
        "code": "missing_float",
        "severity": "medium",
        "message": "Float data was missing.",
        "affected_inputs": ["float_shares"],
    }
    events = [
        _event(
            event_id=101,
            scanner_type="pre_market_volume_spike",
            explanation=_explanation("premarket", warnings=[warning]),
        ),
        _event(
            event_id=102,
            scanner_type="liquidity_hunt_pre",
            explanation=_explanation("liquidity_hunt_pre"),
        ),
    ]

    rows = [
        extractor.extract_event(event, _summary(event.id), [_snapshot(event.id)])[0]
        for event in events
    ]

    assert rows[0]["event_id"] == 101
    assert rows[0]["scanner_event_id"] == 101
    assert rows[0]["scanner_type"] == "pre_market_volume_spike"
    assert rows[0]["criterion_premarket_volume_spike_passed"] == 1.0
    assert rows[0]["criterion_premarket_volume_spike_observed"] == 6.2
    assert rows[0]["criterion_premarket_news_catalyst_passed"] == 0.0
    assert rows[0]["confidence_signal_quality_score"] == 0.83
    assert rows[0]["confidence_threshold_method_category"] == "static"
    assert rows[0]["data_quality_warning_count"] == 1
    assert rows[0]["warning_missing_float"] == 1.0
    assert rows[0]["warning_severity_medium_count"] == 1
    assert rows[0]["criteria_passed_ids"] == ["premarket.volume_spike"]
    assert rows[0]["criteria_failed_ids"] == ["premarket.news_catalyst"]

    assert rows[1]["criterion_liquidity_hunt_pre_volume_spike_passed"] == 1.0
    assert rows[1]["scanner_type"] == "liquidity_hunt_pre"


def test_extract_event_handles_missing_and_reconstructed_explanations():
    extractor = ExplanationFeatureExtractor()
    missing = _event(event_id=201, scanner_type="pre_market_volume_spike", explanation=None)
    reconstructed = _event(
        event_id=202,
        scanner_type="liquidity_hunt_post",
        explanation=_explanation("liquidity_hunt_post", reconstructed=True),
    )

    missing_row = extractor.extract_event(missing, _summary(201), [_snapshot(201)])[0]
    reconstructed_row = extractor.extract_event(
        reconstructed, _summary(202), [_snapshot(202)]
    )[0]

    assert missing_row["has_explanation"] == 0.0
    assert missing_row["criteria_passed_count"] == 0
    assert missing_row["data_quality_warning_count"] == 0
    assert missing_row["outcome_is_complete"] == 1.0

    assert reconstructed_row["has_explanation"] == 1.0
    assert reconstructed_row["explanation_reconstructed"] == 1.0
    assert reconstructed_row["reconstruction_quality_category"] == "partial"
    assert reconstructed_row["reconstruction_quality_partial"] == 1.0


def test_extract_rows_for_analysis_joins_summary_and_captured_snapshots(db):
    extractor = ExplanationFeatureExtractor()
    event = _event(
        event_id=301,
        scanner_type="pre_market_volume_spike",
        explanation=_explanation("premarket"),
    )
    db.add(event)
    db.flush()
    summary = _summary(event.id)
    captured = _snapshot(event.id, "5m")
    pending = _snapshot(event.id, "30m")
    pending.status = "pending"
    db.add(summary)
    db.add(captured)
    db.add(pending)
    db.flush()

    rows = extractor.extract_rows_for_analysis(db, scanner_type="pre_market_volume_spike")

    assert len(rows) == 1
    row = rows[0]
    assert row["event_id"] == event.id
    assert row["interval_key"] == "5m"
    assert row["pct_change"] == 2.5
    assert row["outcome_mfe_pct"] == 4.25
    assert row["outcome_mae_pct"] == 1.25
    assert row["outcome_follow_through"] == 1.0
    assert row["snapshot_volume_since_signal"] == 120000
