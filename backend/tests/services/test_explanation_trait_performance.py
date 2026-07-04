from datetime import date
from decimal import Decimal

import pytest

from app.models.scanner_event import ScannerEvent
from app.models.scanner_outcome_summary import ScannerOutcomeSummary
from app.services.explanation_trait_performance import (
    ExplanationTraitPerformanceService,
)


def _explanation(
    *,
    passed: list[str] | None = None,
    failed: list[str] | None = None,
    warnings: list[str] | None = None,
    confidence: float = 0.9,
) -> dict:
    def criterion(name: str, observed=True) -> dict:
        return {
            "label": name.replace("_", " ").title(),
            "observed": observed,
            "threshold": True,
            "operator": "==",
            "importance": 0.8,
        }

    return {
        "schema_version": "scanner_explanation.v1",
        "why": ["Synthetic trait aggregation explanation."],
        "criteria_passed": {
            f"premarket.{name}": criterion(name) for name in passed or []
        },
        "criteria_failed": {
            f"premarket.{name}": criterion(name, observed=False)
            for name in failed or []
        },
        "confidence_inputs": {
            "signal_quality_score": confidence,
            "threshold_method": "static",
        },
        "data_quality_warnings": [
            {
                "code": code,
                "severity": "medium",
                "message": f"{code} warning.",
                "affected_inputs": ["input"],
            }
            for code in warnings or []
        ],
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
    eod_pct_change: str = "2.00",
    follow_through: bool = True,
    mfe_pct: str = "4.00",
    mae_pct: str = "1.00",
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
        explanation=explanation
        if explanation is not None
        else _explanation(passed=["volume_spike"]),
    )
    db.add(event)
    db.flush()
    db.add(
        ScannerOutcomeSummary(
            scanner_event_id=event.id,
            reference_price=Decimal("10.00"),
            mfe_pct=Decimal(mfe_pct),
            mae_pct=Decimal(mae_pct),
            mfe_mae_ratio=Decimal("4.0000"),
            r_multiple=Decimal("2.0000"),
            eod_pct_change=Decimal(eod_pct_change),
            follow_through=follow_through,
            gap_filled=False,
            is_complete=True,
        )
    )
    db.flush()
    return event


def _find_trait(result: dict, trait_type: str, trait_key: str) -> dict:
    for trait in result["traits"]:
        if trait["trait_type"] == trait_type and trait["trait_key"] == trait_key:
            return trait
    raise AssertionError(f"Trait not found: {trait_type}:{trait_key}")


def test_aggregate_trait_performance_covers_criteria_warnings_and_confidence(db):
    _seed_event(
        db,
        ticker="AAA",
        event_date=date(2026, 7, 1),
        explanation=_explanation(
            passed=["volume_spike"],
            failed=["news_catalyst"],
            confidence=0.92,
        ),
        eod_pct_change="2.00",
        follow_through=True,
        mfe_pct="4.00",
        mae_pct="1.00",
    )
    _seed_event(
        db,
        ticker="BBB",
        event_date=date(2026, 7, 2),
        explanation=_explanation(
            passed=["volume_spike"],
            failed=["news_catalyst"],
            warnings=["missing_float"],
            confidence=0.88,
        ),
        eod_pct_change="-1.00",
        follow_through=False,
        mfe_pct="1.00",
        mae_pct="2.00",
    )
    _seed_event(
        db,
        ticker="CCC",
        event_date=date(2026, 7, 3),
        explanation=_explanation(
            passed=["volume_spike", "liquidity"],
            confidence=0.25,
        ),
        eod_pct_change="3.00",
        follow_through=True,
        mfe_pct="5.00",
        mae_pct="1.50",
    )

    result = ExplanationTraitPerformanceService().aggregate(
        db,
        scanner_type="pre_market_volume_spike",
        min_sample_size=3,
    )

    passed = _find_trait(result, "criterion_passed", "premarket.volume_spike")
    assert passed["sample_size"] == 3
    assert passed["win_rate_pct"] == pytest.approx(66.67, abs=0.01)
    assert passed["follow_through_rate_pct"] == pytest.approx(66.67, abs=0.01)
    assert passed["avg_mfe_pct"] == pytest.approx(3.3333, abs=0.0001)
    assert passed["avg_mae_pct"] == pytest.approx(1.5, abs=0.0001)
    assert set(passed["win_rate_ci_95_pct"]) == {"lower", "upper"}
    assert passed["warnings"] == []

    failed = _find_trait(result, "criterion_failed", "premarket.news_catalyst")
    assert failed["sample_size"] == 2
    assert failed["warnings"][0]["code"] == "weak_sample_size"

    warning = _find_trait(result, "warning", "missing_float")
    assert warning["sample_size"] == 1
    assert warning["win_rate_pct"] == 0.0

    high_confidence = _find_trait(
        result,
        "confidence_input",
        "signal_quality_score:high",
    )
    assert high_confidence["sample_size"] == 2

    low_confidence = _find_trait(
        result,
        "confidence_input",
        "signal_quality_score:low",
    )
    assert low_confidence["sample_size"] == 1


def test_aggregate_trait_performance_filters_by_scanner_type_and_date_range(db):
    _seed_event(
        db,
        ticker="OLD",
        event_date=date(2026, 6, 30),
        explanation=_explanation(passed=["volume_spike"]),
    )
    expected = _seed_event(
        db,
        ticker="INR",
        event_date=date(2026, 7, 2),
        explanation=_explanation(passed=["volume_spike"]),
    )
    _seed_event(
        db,
        ticker="ALT",
        event_date=date(2026, 7, 2),
        scanner_type="liquidity_hunt_pre",
        explanation=_explanation(passed=["volume_spike"]),
    )

    result = ExplanationTraitPerformanceService().aggregate(
        db,
        scanner_type="pre_market_volume_spike",
        start_date=date(2026, 7, 1),
        end_date=date(2026, 7, 3),
    )

    passed = _find_trait(result, "criterion_passed", "premarket.volume_spike")
    assert result["event_count"] == 1
    assert result["filters"] == {
        "scanner_type": "pre_market_volume_spike",
        "start_date": "2026-07-01",
        "end_date": "2026-07-03",
        "severity": None,
        "min_sample_size": 5,
    }
    assert passed["sample_size"] == 1
    assert passed["event_ids"] == [expected.id]
