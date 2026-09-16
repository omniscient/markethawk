from datetime import date
from decimal import Decimal

from app.models.scanner_event import ScannerEvent
from app.models.scanner_outcome_summary import ScannerOutcomeSummary
from app.services.explanation_archetype_service import ExplanationArchetypeService


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
        "why": ["Synthetic archetype explanation."],
        "criteria_passed": {
            f"premarket.{name}": criterion(name) for name in passed or []
        },
        "criteria_failed": {
            f"premarket.{name}": criterion(name, observed=False)
            for name in failed or []
        },
        "confidence_inputs": {"signal_quality_score": confidence},
        "data_quality_warnings": [
            {
                "code": code,
                "severity": "medium",
                "message": f"{code.replace('_', ' ').title()} warning.",
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
    scanner_type: str = "pre_market_volume_spike",
    explanation: dict,
    eod_pct_change: str,
    follow_through: bool,
    mfe_pct: str = "4.00",
    mae_pct: str = "1.00",
) -> ScannerEvent:
    event = ScannerEvent(
        ticker=ticker,
        event_date=date(2026, 7, 3),
        scanner_type=scanner_type,
        summary=f"{ticker} signal",
        severity="medium",
        indicators={},
        criteria_met={},
        metadata_={},
        explanation=explanation,
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


def test_generate_archetypes_persists_labels_profiles_and_assignments(db):
    winners = [
        _seed_event(
            db,
            ticker=f"WIN{i}",
            explanation=_explanation(
                passed=["volume_spike", "liquidity"],
                confidence=0.92,
            ),
            eod_pct_change="3.00",
            follow_through=True,
            mfe_pct="5.00",
            mae_pct="1.00",
        )
        for i in range(2)
    ]
    laggards = [
        _seed_event(
            db,
            ticker=f"LAG{i}",
            explanation=_explanation(
                failed=["news_catalyst"],
                warnings=["missing_float"],
                confidence=0.2,
            ),
            eod_pct_change="-2.00",
            follow_through=False,
            mfe_pct="1.00",
            mae_pct="3.00",
        )
        for i in range(2)
    ]

    result = ExplanationArchetypeService().generate(
        db,
        scanner_type="pre_market_volume_spike",
        min_sample_size=2,
    )

    assert result["status"] == "completed"
    assert result["event_count"] == 4
    assert len(result["archetypes"]) == 2

    winner = result["archetypes"][0]
    assert winner["label"] == "Liquidity + Volume Spike / Positive Outcomes"
    assert winner["sample_size"] == 2
    assert winner["return_profile"]["win_rate_pct"] == 100.0
    assert winner["trait_drivers"][:2] == ["premarket.liquidity", "premarket.volume_spike"]

    laggard = result["archetypes"][1]
    assert laggard["label"] == "Missing Float + News Catalyst / Weak Outcomes"
    assert laggard["return_profile"]["avg_mae_pct"] == 3.0

    db.expire_all()
    for event in winners:
        refreshed = db.get(ScannerEvent, event.id)
        assert refreshed.signal_cluster_id == winner["cluster_id"]
    for event in laggards:
        refreshed = db.get(ScannerEvent, event.id)
        assert refreshed.signal_cluster_id == laggard["cluster_id"]


def test_generate_archetypes_reports_low_sample_without_assigning(db):
    event = _seed_event(
        db,
        ticker="ONE",
        explanation=_explanation(passed=["volume_spike"]),
        eod_pct_change="1.00",
        follow_through=True,
    )

    result = ExplanationArchetypeService().generate(
        db,
        scanner_type="pre_market_volume_spike",
        min_sample_size=2,
    )

    assert result["status"] == "insufficient_data"
    assert result["archetypes"] == []
    assert result["warnings"][0]["code"] == "insufficient_archetype_sample"
    db.expire_all()
    assert db.get(ScannerEvent, event.id).signal_cluster_id is None


def test_generate_archetypes_filters_by_scanner_type(db):
    expected = _seed_event(
        db,
        ticker="PRE",
        explanation=_explanation(passed=["volume_spike"]),
        eod_pct_change="2.00",
        follow_through=True,
    )
    other = _seed_event(
        db,
        ticker="LIQ",
        scanner_type="liquidity_hunt_pre",
        explanation=_explanation(passed=["volume_spike"]),
        eod_pct_change="-2.00",
        follow_through=False,
    )

    result = ExplanationArchetypeService().generate(
        db,
        scanner_type="pre_market_volume_spike",
        min_sample_size=1,
    )

    assert result["event_count"] == 1
    assert result["archetypes"][0]["event_ids"] == [expected.id]
    db.expire_all()
    assert db.get(ScannerEvent, expected.id).signal_cluster_id is not None
    assert db.get(ScannerEvent, other.id).signal_cluster_id is None
