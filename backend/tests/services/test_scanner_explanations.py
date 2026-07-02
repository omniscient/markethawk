from datetime import date, datetime

from app.models.scanner_event import ScannerEvent
from app.services.pre_market_scan import EnrichedSignal, RawSignal
from app.services.scanner_explanations import (
    build_liquidity_hunt_explanation,
    build_pre_market_volume_explanation,
    reconstruct_explanation_for_event,
)


def _raw_signal(criteria_met=None):
    return RawSignal(
        ticker="AAPL",
        daily_bars=[],
        pre_market_volume=650000,
        volumes=[1000000] * 20,
        closes=[100.0] * 20,
        avg_volume_20d=125000,
        avg_volume_50d=None,
        previous_close=100.0,
        relative_volume=5.2,
        forecast={"p50": 100000, "p90": 350000},
        anomaly_score=2.4,
        threshold_method="timesfm",
        criteria_met=criteria_met
        or {"volume_spike": True, "minimum_volume": True, "liquidity": False},
    )


def _enriched_signal(criteria_met=None):
    return EnrichedSignal(
        raw=_raw_signal(criteria_met=criteria_met),
        day_metrics={"opening_price": 104.0, "closing_price": 106.0},
        indicators={
            "pre_market_volume": 650000,
            "avg_volume_20d": 125000,
            "relative_volume": 5.2,
            "volume_spike_ratio": 5.2,
            "volume_anomaly_score": 2.4,
            "volume_threshold_method": "timesfm",
            "gap_pct": 4.0,
            "has_news_catalyst": True,
        },
        enrichment={"quality_warnings": []},
    )


def test_build_pre_market_volume_explanation_splits_passed_and_failed_criteria():
    explanation = build_pre_market_volume_explanation(
        _enriched_signal(),
        signal_quality_score=88.0,
        gate_metadata={
            "tier": "warning",
            "warnings": [
                {
                    "code": "stale_bars",
                    "severity": "warning",
                    "message": "Some bars are stale.",
                }
            ],
        },
    )

    assert explanation["schema_version"] == "scanner_explanation.v1"
    assert "premarket.volume_spike" in explanation["criteria_passed"]
    assert "premarket.liquidity" in explanation["criteria_failed"]
    assert explanation["confidence_inputs"]["signal_quality_score"] == 88.0
    assert explanation["data_quality_warnings"][0]["severity"] == "medium"
    assert explanation["evidence"]["reconstructed"] is False


def test_build_liquidity_hunt_explanation_splits_variant_criteria():
    indicators = {
        "session": "pre",
        "session_volume": 350000,
        "avg_session_volume_20d": 35000,
        "session_volume_ratio": 10.0,
        "session_volume_pct_of_daily": 0.35,
        "session_high": 12.11,
        "reference_close": 11.0,
        "session_spike_pct": 0.1009,
        "regular_volume_ratio": 0.9474,
        "regular_range_ratio": 1.3575,
        "float_rotation_pct": 0.7,
    }
    criteria_met = {
        "volume_ratio": True,
        "volume_materiality": True,
        "session_spike": True,
        "quiet_regular_vol": True,
        "quiet_regular_range": False,
        "volume_floor": True,
    }

    explanation = build_liquidity_hunt_explanation(
        scanner_type="liquidity_hunt_pre",
        indicators=indicators,
        criteria_met=criteria_met,
        gate_metadata={
            "tier": "warning",
            "warnings": [
                {
                    "code": "provider_gaps",
                    "severity": "warning",
                    "message": "Provider gaps were detected.",
                }
            ],
        },
    )

    assert explanation["schema_version"] == "scanner_explanation.v1"
    assert "liquidity_hunt_pre.volume_ratio" in explanation["criteria_passed"]
    assert "liquidity_hunt_pre.quiet_regular_range" in explanation["criteria_failed"]
    assert explanation["confidence_inputs"]["session"] == "pre"
    assert explanation["data_quality_warnings"][0]["severity"] == "medium"
    assert explanation["evidence"]["reconstructed"] is False


def test_reconstruct_explanation_for_existing_event_marks_best_effort():
    event = ScannerEvent(
        ticker="AAPL",
        event_date=date(2026, 6, 2),
        scanner_type="pre_market_volume_spike",
        indicators={
            "pre_market_volume": 650000,
            "avg_volume_20d": 125000,
            "relative_volume": 5.2,
            "volume_spike_ratio": 5.2,
        },
        criteria_met={"volume_spike": True, "liquidity": True},
        metadata_={"quality_gate": {"tier": "trusted", "warnings": []}},
        signal_quality_score=81.0,
        created_at=datetime(2026, 6, 2),
        updated_at=datetime(2026, 6, 2),
    )

    explanation = reconstruct_explanation_for_event(event)

    assert explanation["schema_version"] == "scanner_explanation.v1"
    assert explanation["evidence"]["reconstructed"] is True
    assert explanation["evidence"]["reconstruction_quality"] == "best_effort"
    assert explanation["confidence_inputs"]["signal_quality_score"] == 81.0


def test_reconstruct_liquidity_hunt_event_uses_named_criteria():
    event = ScannerEvent(
        ticker="AAPL",
        event_date=date(2026, 6, 2),
        scanner_type="liquidity_hunt_pre",
        indicators={
            "session": "pre",
            "session_volume_ratio": 10.0,
            "session_spike_pct": 0.1009,
            "session_volume_pct_of_daily": 0.35,
        },
        criteria_met={"volume_ratio": True, "quiet_regular_range": False},
        metadata_={"quality_gate": {"tier": "trusted", "warnings": []}},
        created_at=datetime(2026, 6, 2),
        updated_at=datetime(2026, 6, 2),
    )

    explanation = reconstruct_explanation_for_event(event)

    assert "liquidity_hunt_pre.volume_ratio" in explanation["criteria_passed"]
    assert "liquidity_hunt_pre.quiet_regular_range" in explanation["criteria_failed"]
    assert (
        explanation["criteria_passed"]["liquidity_hunt_pre.volume_ratio"]["label"]
        == "Off-hours volume ratio"
    )
