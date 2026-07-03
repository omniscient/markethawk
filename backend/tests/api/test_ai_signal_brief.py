from datetime import date
from decimal import Decimal

from fastapi.testclient import TestClient

from app.main import app
from app.models.scanner_event import ScannerEvent
from app.models.scanner_outcome_summary import ScannerOutcomeSummary
from app.models.signal_analysis_run import SignalAnalysisRun
from app.models.signal_cluster import SignalCluster

client = TestClient(app)


def _explanation(*, warnings: list[str] | None = None) -> dict:
    return {
        "schema_version": "scanner_explanation.v1",
        "why": ["Volume and liquidity aligned with the scanner setup."],
        "criteria_passed": {
            "premarket.volume_spike": {
                "label": "Volume Spike",
                "observed": 6.0,
                "threshold": 4.0,
                "operator": ">=",
                "importance": 1.0,
            }
        },
        "criteria_failed": {
            "premarket.news_catalyst": {
                "label": "News Catalyst",
                "observed": False,
                "threshold": True,
                "operator": "==",
                "importance": 0.5,
            }
        },
        "confidence_inputs": {"signal_quality_score": 0.86},
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
    explanation: dict | None,
    complete: bool = True,
) -> ScannerEvent:
    event = ScannerEvent(
        ticker=ticker,
        event_date=event_date,
        scanner_type="pre_market_volume_spike",
        summary=f"{ticker} signal",
        severity="high",
        indicators={"volume_spike_ratio": 6.0},
        criteria_met={},
        metadata_={},
        explanation=explanation,
    )
    db.add(event)
    db.flush()
    if complete:
        db.add(
            ScannerOutcomeSummary(
                scanner_event_id=event.id,
                reference_price=Decimal("10.00"),
                mfe_pct=Decimal("4.00"),
                mae_pct=Decimal("1.00"),
                mfe_mae_ratio=Decimal("4.0000"),
                r_multiple=Decimal("2.0000"),
                eod_pct_change=Decimal("2.00"),
                follow_through=True,
                gap_filled=False,
                is_complete=True,
            )
        )
    db.flush()
    return event


def _assign_archetype(db, event: ScannerEvent) -> SignalCluster:
    run = SignalAnalysisRun(status="completed", scanner_type=event.scanner_type, event_count=1)
    db.add(run)
    db.flush()
    cluster = SignalCluster(
        analysis_run_id=run.id,
        cluster_index=0,
        label="Volume Spike / Positive Outcomes",
        centroid={"traits": {"premarket.volume_spike": 1.0}},
        return_profile={"win_rate_pct": 100.0, "sample_size": 1},
        event_count=1,
    )
    db.add(cluster)
    db.flush()
    event.signal_cluster_id = cluster.id
    db.flush()
    return cluster


def test_ai_signal_brief_complete_event_includes_contexts(db):
    _seed_event(
        db,
        ticker="OLD",
        event_date=date(2026, 7, 1),
        explanation=_explanation(),
    )
    target = _seed_event(
        db,
        ticker="TGT",
        event_date=date(2026, 7, 3),
        explanation=_explanation(),
    )
    cluster = _assign_archetype(db, target)

    response = client.get(f"/api/v1/outcomes/event/{target.id}/ai-signal-brief")

    assert response.status_code == 200
    data = response.json()
    assert data["schema_version"] == "ai_signal_brief.v1"
    assert data["facts"]["ticker"] == "TGT"
    assert data["why"] == ["Volume and liquidity aligned with the scanner setup."]
    assert data["outcome_context"]["summary"]["eod_pct_change"] == 2.0
    assert data["archetype"]["label"] == cluster.label
    assert len(data["analogs"]) == 1
    assert data["forbidden_claims"]


def test_ai_signal_brief_partial_event_without_explanation_or_outcome(db):
    target = _seed_event(
        db,
        ticker="NEW",
        event_date=date(2026, 7, 3),
        explanation=None,
        complete=False,
    )

    response = client.get(f"/api/v1/outcomes/event/{target.id}/ai-signal-brief")

    assert response.status_code == 200
    data = response.json()
    assert data["why"] == []
    assert data["outcome_context"]["summary"] is None
    assert "Scanner explanation is missing." in data["risks"]


def test_ai_signal_brief_warning_heavy_event_surfaces_warnings_and_risks(db):
    target = _seed_event(
        db,
        ticker="WRN",
        event_date=date(2026, 7, 3),
        explanation=_explanation(warnings=["missing_float", "stale_quote"]),
    )

    response = client.get(f"/api/v1/outcomes/event/{target.id}/ai-signal-brief")

    assert response.status_code == 200
    data = response.json()
    assert [warning["code"] for warning in data["warnings"][:2]] == [
        "missing_float",
        "stale_quote",
    ]
    assert "Data quality warnings are present." in data["risks"]


def test_ai_signal_brief_no_analog_event_reports_warning(db):
    target = _seed_event(
        db,
        ticker="SOLO",
        event_date=date(2026, 7, 3),
        explanation=_explanation(),
    )

    response = client.get(f"/api/v1/outcomes/event/{target.id}/ai-signal-brief")

    assert response.status_code == 200
    data = response.json()
    assert data["analogs"] == []
    assert any(
        warning["code"] == "no_historical_analogs" for warning in data["warnings"]
    )
