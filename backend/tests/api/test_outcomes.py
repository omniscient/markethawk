"""
Integration tests for outcomes API endpoints.
Runs against a real Postgres DB (via testcontainers).
"""

from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.main import app
from app.models.scanner_event import ScannerEvent
from app.models.scanner_outcome_summary import ScannerOutcomeSummary
from app.models.signal_analysis_run import SignalAnalysisRun
from app.models.signal_cluster import SignalCluster
from app.utils.time import utc_now
from tests.fixtures.outcomes import (
    seed_outcomes,
    seed_outcomes_with_gate_tiers,
    seed_reviews,
)

client = TestClient(app)


def _trait_explanation(label: str = "Volume Spike") -> dict:
    return {
        "schema_version": "scanner_explanation.v1",
        "why": ["Synthetic API explanation."],
        "criteria_passed": {
            "premarket.volume_spike": {
                "label": label,
                "observed": True,
                "threshold": True,
                "operator": "==",
                "importance": 0.8,
            }
        },
        "criteria_failed": {},
        "confidence_inputs": {"signal_quality_score": 0.91},
        "data_quality_warnings": [],
        "evidence": {"reconstructed": False},
    }


def _seed_explained_outcome(
    db: Session,
    *,
    ticker: str,
    scanner_type: str = "pre_market_volume_spike",
    severity: str = "medium",
    eod_pct_change: str = "2.00",
) -> ScannerEvent:
    event = ScannerEvent(
        ticker=ticker,
        event_date=date(2026, 7, 3),
        scanner_type=scanner_type,
        summary=f"{ticker} signal",
        severity=severity,
        indicators={},
        criteria_met={},
        metadata_={},
        explanation=_trait_explanation(),
    )
    db.add(event)
    db.flush()
    db.add(
        ScannerOutcomeSummary(
            scanner_event_id=event.id,
            reference_price=Decimal("10.00"),
            mfe_pct=Decimal("4.00"),
            mae_pct=Decimal("1.00"),
            mfe_mae_ratio=Decimal("4.0000"),
            r_multiple=Decimal("2.0000"),
            eod_pct_change=Decimal(eod_pct_change),
            follow_through=True,
            gap_filled=False,
            is_complete=True,
        )
    )
    db.flush()
    return event


# ---------------------------------------------------------------------------
# GET /api/outcomes/scorecard/{scanner_type}
# ---------------------------------------------------------------------------


def test_scorecard_returns_correct_shape(db: Session):
    response = client.get("/api/v1/outcomes/scorecard/pre_market_volume_spike")

    assert response.status_code == 200
    data = response.json()
    for field in (
        "scanner_type",
        "period",
        "total_signals",
        "complete_signals",
        "win_rate_pct",
        "avg_mfe_pct",
        "avg_mae_pct",
        "mfe_mae_ratio",
        "avg_r_multiple",
        "expectancy",
        "profit_factor",
        "follow_through_rate_pct",
        "edge_decay",
        "interval_breakdown",
    ):
        assert field in data, f"Missing field: {field}"


def test_scorecard_empty_db_returns_zero_counts(db: Session):
    response = client.get("/api/v1/outcomes/scorecard/pre_market_volume_spike")

    assert response.status_code == 200
    data = response.json()
    assert data["total_signals"] == 0
    assert data["complete_signals"] == 0
    assert data["win_rate_pct"] is None


def test_scorecard_win_rate_reflects_complete_summaries(db: Session):
    seed_outcomes(db)  # 2 wins, 1 loss out of 3 complete signals

    response = client.get("/api/v1/outcomes/scorecard/pre_market_volume_spike")

    data = response.json()
    assert data["complete_signals"] == 3
    assert data["win_rate_pct"] == pytest.approx(66.67, abs=0.1)


def test_scorecard_filters_by_scanner_type(db: Session):
    seed_outcomes(db)  # includes 1 liquidity_hunt_pre event (no summary)

    response = client.get("/api/v1/outcomes/scorecard/liquidity_hunt_pre")

    data = response.json()
    assert data["total_signals"] == 0  # no summaries for liquidity_hunt_pre
    assert data["complete_signals"] == 0


def test_scorecard_query_param_missing_returns_400(db: Session):
    response = client.get("/api/v1/outcomes/scorecard")

    assert response.status_code == 400


def test_scorecard_follow_through_rate(db: Session):
    seed_outcomes(db)  # 2 of 3 summaries have follow_through=True

    response = client.get("/api/v1/outcomes/scorecard/pre_market_volume_spike")

    data = response.json()
    assert data["follow_through_rate_pct"] == pytest.approx(66.67, abs=0.1)


# ---------------------------------------------------------------------------
# GET /api/outcomes/traits/{scanner_type}
# ---------------------------------------------------------------------------


def test_explanation_traits_endpoint_filters_by_severity(db: Session):
    expected = _seed_explained_outcome(db, ticker="HIGH", severity="high")
    _seed_explained_outcome(db, ticker="MEDM", severity="medium")

    response = client.get(
        "/api/v1/outcomes/traits/pre_market_volume_spike"
        "?severity=high&min_sample_size=1"
    )

    assert response.status_code == 200
    data = response.json()
    assert data["event_count"] == 1
    assert data["filters"]["severity"] == "high"
    trait = next(
        item
        for item in data["traits"]
        if item["trait_key"] == "premarket.volume_spike"
    )
    assert trait["trait_key"] == "premarket.volume_spike"
    assert trait["trait_label"] == "Volume Spike"
    assert trait["event_ids"] == [expected.id]


# ---------------------------------------------------------------------------
# GET /api/outcomes/archetypes/{scanner_type}
# ---------------------------------------------------------------------------


def test_explanation_archetypes_endpoint_returns_latest_completed_run(db: Session):
    old_run = SignalAnalysisRun(
        scanner_type="pre_market_volume_spike",
        status="completed",
        event_count=1,
        completed_at=utc_now(),
    )
    db.add(old_run)
    db.flush()
    latest_run = SignalAnalysisRun(
        scanner_type="pre_market_volume_spike",
        status="completed",
        event_count=8,
        completed_at=utc_now(),
    )
    db.add(latest_run)
    db.flush()
    cluster = SignalCluster(
        analysis_run_id=latest_run.id,
        cluster_index=0,
        label="Volume Spike / Positive Outcomes",
        centroid={"premarket.volume_spike": 1.0},
        return_profile={"win_rate_pct": 75.0, "avg_mfe_pct": 5.5},
        event_count=8,
    )
    db.add(cluster)
    db.flush()
    matched = _seed_explained_outcome(db, ticker="ARCH", severity="high")
    filtered_out = _seed_explained_outcome(db, ticker="ARCM", severity="medium")
    matched.signal_cluster_id = cluster.id
    filtered_out.signal_cluster_id = cluster.id
    db.flush()

    response = client.get(
        "/api/v1/outcomes/archetypes/pre_market_volume_spike"
        "?severity=high&min_sample_size=1"
    )

    assert response.status_code == 200
    data = response.json()
    assert data["analysis_run_id"] == latest_run.id
    assert data["event_count"] == 1
    assert data["filters"]["severity"] == "high"
    assert data["warnings"] == []
    assert data["archetypes"][0]["label"] == "Volume Spike / Positive Outcomes"
    assert data["archetypes"][0]["sample_size"] == 1
    assert data["archetypes"][0]["event_ids"] == [matched.id]


# ---------------------------------------------------------------------------
# GET /api/outcomes/intervals/{scanner_type}
# ---------------------------------------------------------------------------


def test_intervals_returns_dict_keyed_by_interval(db: Session):
    seed_outcomes(db)  # snapshots for 5m, 15m, 30m

    response = client.get("/api/v1/outcomes/intervals/pre_market_volume_spike")

    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, dict)
    for key in ("5m", "15m", "30m"):
        assert key in data, f"Missing interval key: {key}"


def test_intervals_response_shape(db: Session):
    seed_outcomes(db)

    response = client.get("/api/v1/outcomes/intervals/pre_market_volume_spike")

    data = response.json()
    interval = data["5m"]
    for field in ("avg_pct", "median_pct", "stddev_pct", "win_rate", "sample_size"):
        assert field in interval, f"Missing field in interval: {field}"


def test_intervals_empty_db_returns_empty_dict(db: Session):
    response = client.get("/api/v1/outcomes/intervals/pre_market_volume_spike")

    assert response.status_code == 200
    assert response.json() == {}


def test_intervals_filter_by_interval_key(db: Session):
    seed_outcomes(db)

    response = client.get(
        "/api/v1/outcomes/intervals/pre_market_volume_spike?interval_key=5m"
    )

    assert response.status_code == 200
    data = response.json()
    assert "5m" in data
    assert "15m" not in data


# ---------------------------------------------------------------------------
# GET /api/outcomes/distribution/{scanner_type}
# ---------------------------------------------------------------------------


def test_distribution_returns_list(db: Session):
    seed_outcomes(db)  # 3 complete summaries with mfe_pct

    response = client.get("/api/v1/outcomes/distribution/pre_market_volume_spike")

    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) == 3


def test_distribution_response_shape(db: Session):
    seed_outcomes(db)

    response = client.get("/api/v1/outcomes/distribution/pre_market_volume_spike")

    item = response.json()[0]
    for field in ("ticker", "event_date", "value", "scanner_type", "severity"):
        assert field in item, f"Missing field: {field}"
    assert item["scanner_type"] == "pre_market_volume_spike"


def test_distribution_empty_db_returns_empty_list(db: Session):
    response = client.get("/api/v1/outcomes/distribution/pre_market_volume_spike")

    assert response.status_code == 200
    assert response.json() == []


def test_distribution_metric_param(db: Session):
    seed_outcomes(db)

    response = client.get(
        "/api/v1/outcomes/distribution/pre_market_volume_spike?metric=mae_pct"
    )

    assert response.status_code == 200
    assert len(response.json()) == 3


# ---------------------------------------------------------------------------
# GET /api/outcomes/edge-decay/{scanner_type}
# ---------------------------------------------------------------------------


def test_edge_decay_returns_list(db: Session):
    seed_outcomes(db)

    response = client.get("/api/v1/outcomes/edge-decay/pre_market_volume_spike")

    assert response.status_code == 200
    assert isinstance(response.json(), list)


def test_edge_decay_empty_db_returns_empty_list(db: Session):
    response = client.get("/api/v1/outcomes/edge-decay/pre_market_volume_spike")

    assert response.status_code == 200
    assert response.json() == []


def test_edge_decay_response_shape(db: Session):
    seed_outcomes(db)

    response = client.get("/api/v1/outcomes/edge-decay/pre_market_volume_spike")

    data = response.json()
    if data:
        item = data[0]
        for field in ("period", "win_rate", "avg_mfe", "avg_mae", "sample_size"):
            assert field in item, f"Missing field: {field}"


# ---------------------------------------------------------------------------
# GET /api/outcomes/signals/{scanner_type}
# ---------------------------------------------------------------------------


def test_signals_returns_correct_shape(db: Session):
    response = client.get("/api/v1/outcomes/signals/pre_market_volume_spike")

    assert response.status_code == 200
    data = response.json()
    for field in ("signals", "total", "limit", "offset"):
        assert field in data, f"Missing field: {field}"
    assert isinstance(data["signals"], list)


def test_signals_returns_seeded_events(db: Session):
    seed_outcomes(db)  # 3 pre_market_volume_spike events

    response = client.get("/api/v1/outcomes/signals/pre_market_volume_spike")

    data = response.json()
    assert data["total"] == 3


def test_signals_item_shape(db: Session):
    seed_outcomes(db)

    response = client.get("/api/v1/outcomes/signals/pre_market_volume_spike")

    signal = response.json()["signals"][0]
    for field in (
        "id",
        "ticker",
        "event_date",
        "severity",
        "summary",
        "mfe_pct",
        "mae_pct",
        "eod_pct_change",
        "follow_through",
        "is_complete",
    ):
        assert field in signal, f"Missing field: {field}"


def test_signals_limit_param(db: Session):
    seed_outcomes(db)

    response = client.get("/api/v1/outcomes/signals/pre_market_volume_spike?limit=2")

    data = response.json()
    assert len(data["signals"]) == 2
    assert data["total"] == 3  # total unchanged


def test_signals_offset_param(db: Session):
    seed_outcomes(db)

    response = client.get("/api/v1/outcomes/signals/pre_market_volume_spike?offset=2")

    data = response.json()
    assert len(data["signals"]) == 1


def test_signals_filters_by_scanner_type(db: Session):
    seed_outcomes(db)  # 1 liquidity_hunt_pre event, no summaries

    response = client.get("/api/v1/outcomes/signals/liquidity_hunt_pre")

    data = response.json()
    assert data["total"] == 1
    assert data["signals"][0]["ticker"] == "MRNA"


# ---------------------------------------------------------------------------
# GET /api/outcomes/event/{event_id}
# ---------------------------------------------------------------------------


def test_event_outcome_returns_summary_and_snapshots(db: Session):
    seeded = seed_outcomes(db)
    event_id = seeded["events"][0].id

    response = client.get(f"/api/v1/outcomes/event/{event_id}")

    assert response.status_code == 200
    data = response.json()
    assert "summary" in data
    assert "snapshots" in data
    assert data["summary"] is not None
    assert len(data["snapshots"]) == 3  # 5m, 15m, 30m


def test_event_outcome_no_summary_returns_null_summary(db: Session):
    seeded = seed_outcomes(db)
    event_id = seeded["events"][3].id  # MRNA — no summary or snapshots

    response = client.get(f"/api/v1/outcomes/event/{event_id}")

    assert response.status_code == 200
    data = response.json()
    assert data["summary"] is None
    assert data["snapshots"] == []


def test_event_outcome_not_found_returns_404(db: Session):
    response = client.get("/api/v1/outcomes/event/99999")

    assert response.status_code == 404


def test_event_outcome_summary_shape(db: Session):
    seeded = seed_outcomes(db)
    event_id = seeded["events"][0].id

    response = client.get(f"/api/v1/outcomes/event/{event_id}")

    summary = response.json()["summary"]
    for field in (
        "id",
        "scanner_event_id",
        "reference_price",
        "mfe_pct",
        "mae_pct",
        "eod_pct_change",
        "follow_through",
        "is_complete",
    ):
        assert field in summary, f"Missing summary field: {field}"


def test_event_outcome_snapshot_shape(db: Session):
    seeded = seed_outcomes(db)
    event_id = seeded["events"][0].id

    response = client.get(f"/api/v1/outcomes/event/{event_id}")

    snap = response.json()["snapshots"][0]
    for field in (
        "id",
        "scanner_event_id",
        "interval_key",
        "reference_price",
        "pct_change",
        "status",
    ):
        assert field in snap, f"Missing snapshot field: {field}"


def test_event_outcome_snapshots_ordered_by_interval_key(db: Session):
    seeded = seed_outcomes(db)
    event_id = seeded["events"][0].id

    response = client.get(f"/api/v1/outcomes/event/{event_id}")

    keys = [s["interval_key"] for s in response.json()["snapshots"]]
    assert keys == sorted(keys)


# ---------------------------------------------------------------------------
# GET /api/outcomes/readiness/{ticker}
# ---------------------------------------------------------------------------


def test_readiness_missing_scanner_type_returns_400(db: Session):
    response = client.get("/api/v1/outcomes/readiness/AAPL")

    assert response.status_code == 400


def test_readiness_returns_correct_shape(db: Session):
    response = client.get(
        "/api/v1/outcomes/readiness/AAPL?scanner_type=pre_market_volume_spike"
    )

    assert response.status_code == 200
    data = response.json()
    for field in ("ticker", "scanner_type", "coverages", "is_ready", "missing_summary"):
        assert field in data, f"Missing field: {field}"
    assert data["ticker"] == "AAPL"
    assert data["scanner_type"] == "pre_market_volume_spike"
    assert isinstance(data["coverages"], list)


# ---------------------------------------------------------------------------
# Trust filter — quality gate tier exclusion from Scorecard
# ---------------------------------------------------------------------------


def test_scorecard_default_excludes_blocked_and_skipped(db: Session):
    seed_outcomes_with_gate_tiers(db)  # 1 trusted, 1 warning, 1 blocked, 1 skipped

    response = client.get("/api/v1/outcomes/scorecard/pre_market_volume_spike")

    assert response.status_code == 200
    data = response.json()
    # Default: only the trusted event is counted
    assert data["complete_signals"] == 1
    assert data["gate_filter"] == "trusted"


def test_scorecard_include_warnings_adds_warning_tier(db: Session):
    seed_outcomes_with_gate_tiers(db)

    response = client.get(
        "/api/v1/outcomes/scorecard/pre_market_volume_spike?include_warnings=true"
    )

    data = response.json()
    # trusted + warning = 2 events
    assert data["complete_signals"] == 2
    assert data["gate_filter"] == "trusted+warning"


def test_scorecard_include_all_returns_all_events(db: Session):
    seed_outcomes_with_gate_tiers(db)

    response = client.get(
        "/api/v1/outcomes/scorecard/pre_market_volume_spike?include_all=true"
    )

    data = response.json()
    # All 4 events (trusted, warning, blocked, skipped)
    assert data["complete_signals"] == 4
    assert data["gate_filter"] == "all"


def test_scorecard_gate_status_counts_all_tiers(db: Session):
    seed_outcomes_with_gate_tiers(db)

    response = client.get("/api/v1/outcomes/scorecard/pre_market_volume_spike")

    data = response.json()
    gs = data["gate_status"]
    assert gs["trusted"] == 1
    assert gs["warning"] == 1
    assert gs["blocked"] == 1
    assert gs["skipped"] == 1


def test_scorecard_legacy_events_treated_as_trusted(db: Session):
    seed_outcomes(db)  # legacy events: metadata_={}, no quality_gate key

    response = client.get("/api/v1/outcomes/scorecard/pre_market_volume_spike")

    data = response.json()
    # 3 legacy trusted events should all be included in default trusted filter
    assert data["complete_signals"] == 3
    assert data["gate_status"]["trusted"] == 3


def test_signals_response_includes_gate_tier_field(db: Session):
    seed_outcomes_with_gate_tiers(db)

    response = client.get("/api/v1/outcomes/signals/pre_market_volume_spike")

    assert response.status_code == 200
    for signal in response.json()["signals"]:
        assert "gate_tier" in signal, "gate_tier missing from signal item"


def test_signals_rejects_oversized_limit(db: Session):
    # CWE-770: signals limit must be capped before any DB query runs
    response = client.get(
        "/api/v1/outcomes/signals/pre_market_volume_spike?limit=10000000"
    )

    assert response.status_code == 422


# ---------------------------------------------------------------------------
# Scorecard review-side fields (issue #303)
# ---------------------------------------------------------------------------


def test_scorecard_review_fields_absent_when_no_reviews(db: Session):
    seed_outcomes(db)

    response = client.get("/api/v1/outcomes/scorecard/pre_market_volume_spike")

    data = response.json()
    assert response.status_code == 200
    assert "precision_pct" in data
    assert "review_coverage_pct" in data
    assert "verdict_counts" in data
    assert "top_reject_reasons" in data
    assert "review_sample_n" in data
    # No reviews seeded — all nullable fields should be None / zero
    assert data["precision_pct"] is None
    assert data["review_sample_n"] == 0
    assert data["top_reject_reasons"] == []


def test_scorecard_precision_pct_correct(db: Session):
    seeded = seed_outcomes(db)
    # seed_reviews: 2 confirmed, 1 rejected → precision = 66.67
    seed_reviews(db, seeded["events"])

    response = client.get("/api/v1/outcomes/scorecard/pre_market_volume_spike")

    data = response.json()
    assert data["precision_pct"] == pytest.approx(66.67, abs=0.1)
    assert data["review_sample_n"] == 3


def test_scorecard_review_coverage_pct_correct(db: Session):
    seeded = seed_outcomes(db)
    seed_reviews(db, seeded["events"])

    response = client.get("/api/v1/outcomes/scorecard/pre_market_volume_spike")

    data = response.json()
    # total_signals = 3 (trust-filtered summaries for pre_market_volume_spike)
    # review_sample_n = 3 (2 confirmed + 1 rejected)
    # review_coverage_pct = 3 / 3 * 100 = 100.0
    assert data["review_coverage_pct"] == pytest.approx(100.0, abs=0.1)


def test_scorecard_verdict_counts_correct(db: Session):
    seeded = seed_outcomes(db)
    seed_reviews(db, seeded["events"])

    response = client.get("/api/v1/outcomes/scorecard/pre_market_volume_spike")

    data = response.json()
    vc = data["verdict_counts"]
    assert vc["confirmed"] == 2
    assert vc["rejected"] == 1
    assert vc["enhanced"] == 0


def test_scorecard_top_reject_reasons_correct(db: Session):
    seeded = seed_outcomes(db)
    seed_reviews(db, seeded["events"])

    response = client.get("/api/v1/outcomes/scorecard/pre_market_volume_spike")

    data = response.json()
    reasons = data["top_reject_reasons"]
    assert len(reasons) == 1
    assert reasons[0]["reason"] == "noise"
    assert reasons[0]["count"] == 1


def test_scorecard_review_fields_null_when_no_complete_signals(db: Session):
    # Early-return path: no complete signals but reviews may exist
    response = client.get("/api/v1/outcomes/scorecard/pre_market_volume_spike")

    data = response.json()
    assert response.status_code == 200
    # Empty DB — all review fields still present and null/empty
    assert data["precision_pct"] is None
    assert data["review_sample_n"] == 0
    assert data["top_reject_reasons"] == []
