"""
Integration tests for outcomes API endpoints.
Runs against a real Postgres DB (via testcontainers).
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.main import app
from tests.fixtures.outcomes import seed_outcomes
from tests.fixtures.scanner import seed_scanner_events

client = TestClient(app)


# ---------------------------------------------------------------------------
# GET /api/outcomes/scorecard/{scanner_type}
# ---------------------------------------------------------------------------


def test_scorecard_returns_correct_shape(db: Session):
    response = client.get("/api/outcomes/scorecard/pre_market_volume_spike")

    assert response.status_code == 200
    data = response.json()
    for field in (
        "scanner_type", "period", "total_signals", "complete_signals",
        "win_rate_pct", "avg_mfe_pct", "avg_mae_pct", "mfe_mae_ratio",
        "avg_r_multiple", "expectancy", "profit_factor",
        "follow_through_rate_pct", "edge_decay", "interval_breakdown",
    ):
        assert field in data, f"Missing field: {field}"


def test_scorecard_empty_db_returns_zero_counts(db: Session):
    response = client.get("/api/outcomes/scorecard/pre_market_volume_spike")

    assert response.status_code == 200
    data = response.json()
    assert data["total_signals"] == 0
    assert data["complete_signals"] == 0
    assert data["win_rate_pct"] is None


def test_scorecard_win_rate_reflects_complete_summaries(db: Session):
    seed_outcomes(db)  # 2 wins, 1 loss out of 3 complete signals

    response = client.get("/api/outcomes/scorecard/pre_market_volume_spike")

    data = response.json()
    assert data["complete_signals"] == 3
    assert data["win_rate_pct"] == pytest.approx(66.67, abs=0.1)


def test_scorecard_filters_by_scanner_type(db: Session):
    seed_outcomes(db)  # includes 1 liquidity_hunt_pre event (no summary)

    response = client.get("/api/outcomes/scorecard/liquidity_hunt_pre")

    data = response.json()
    assert data["total_signals"] == 0  # no summaries for liquidity_hunt_pre
    assert data["complete_signals"] == 0


def test_scorecard_query_param_missing_returns_400(db: Session):
    response = client.get("/api/outcomes/scorecard")

    assert response.status_code == 400


def test_scorecard_follow_through_rate(db: Session):
    seed_outcomes(db)  # 2 of 3 summaries have follow_through=True

    response = client.get("/api/outcomes/scorecard/pre_market_volume_spike")

    data = response.json()
    assert data["follow_through_rate_pct"] == pytest.approx(66.67, abs=0.1)


# ---------------------------------------------------------------------------
# GET /api/outcomes/intervals/{scanner_type}
# ---------------------------------------------------------------------------


def test_intervals_returns_dict_keyed_by_interval(db: Session):
    seed_outcomes(db)  # snapshots for 5m, 15m, 30m

    response = client.get("/api/outcomes/intervals/pre_market_volume_spike")

    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, dict)
    for key in ("5m", "15m", "30m"):
        assert key in data, f"Missing interval key: {key}"


def test_intervals_response_shape(db: Session):
    seed_outcomes(db)

    response = client.get("/api/outcomes/intervals/pre_market_volume_spike")

    data = response.json()
    interval = data["5m"]
    for field in ("avg_pct", "median_pct", "stddev_pct", "win_rate", "sample_size"):
        assert field in interval, f"Missing field in interval: {field}"


def test_intervals_empty_db_returns_empty_dict(db: Session):
    response = client.get("/api/outcomes/intervals/pre_market_volume_spike")

    assert response.status_code == 200
    assert response.json() == {}


def test_intervals_filter_by_interval_key(db: Session):
    seed_outcomes(db)

    response = client.get("/api/outcomes/intervals/pre_market_volume_spike?interval_key=5m")

    assert response.status_code == 200
    data = response.json()
    assert "5m" in data
    assert "15m" not in data


# ---------------------------------------------------------------------------
# GET /api/outcomes/distribution/{scanner_type}
# ---------------------------------------------------------------------------


def test_distribution_returns_list(db: Session):
    seed_outcomes(db)  # 3 complete summaries with mfe_pct

    response = client.get("/api/outcomes/distribution/pre_market_volume_spike")

    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) == 3


def test_distribution_response_shape(db: Session):
    seed_outcomes(db)

    response = client.get("/api/outcomes/distribution/pre_market_volume_spike")

    item = response.json()[0]
    for field in ("ticker", "event_date", "value", "scanner_type", "severity"):
        assert field in item, f"Missing field: {field}"
    assert item["scanner_type"] == "pre_market_volume_spike"


def test_distribution_empty_db_returns_empty_list(db: Session):
    response = client.get("/api/outcomes/distribution/pre_market_volume_spike")

    assert response.status_code == 200
    assert response.json() == []


def test_distribution_metric_param(db: Session):
    seed_outcomes(db)

    response = client.get("/api/outcomes/distribution/pre_market_volume_spike?metric=mae_pct")

    assert response.status_code == 200
    assert len(response.json()) == 3


# ---------------------------------------------------------------------------
# GET /api/outcomes/edge-decay/{scanner_type}
# ---------------------------------------------------------------------------


def test_edge_decay_returns_list(db: Session):
    seed_outcomes(db)

    response = client.get("/api/outcomes/edge-decay/pre_market_volume_spike")

    assert response.status_code == 200
    assert isinstance(response.json(), list)


def test_edge_decay_empty_db_returns_empty_list(db: Session):
    response = client.get("/api/outcomes/edge-decay/pre_market_volume_spike")

    assert response.status_code == 200
    assert response.json() == []


def test_edge_decay_response_shape(db: Session):
    seed_outcomes(db)

    response = client.get("/api/outcomes/edge-decay/pre_market_volume_spike")

    data = response.json()
    if data:
        item = data[0]
        for field in ("period", "win_rate", "avg_mfe", "avg_mae", "sample_size"):
            assert field in item, f"Missing field: {field}"


# ---------------------------------------------------------------------------
# GET /api/outcomes/signals/{scanner_type}
# ---------------------------------------------------------------------------


def test_signals_returns_correct_shape(db: Session):
    response = client.get("/api/outcomes/signals/pre_market_volume_spike")

    assert response.status_code == 200
    data = response.json()
    for field in ("signals", "total", "limit", "offset"):
        assert field in data, f"Missing field: {field}"
    assert isinstance(data["signals"], list)


def test_signals_returns_seeded_events(db: Session):
    seed_outcomes(db)  # 3 pre_market_volume_spike events

    response = client.get("/api/outcomes/signals/pre_market_volume_spike")

    data = response.json()
    assert data["total"] == 3


def test_signals_item_shape(db: Session):
    seed_outcomes(db)

    response = client.get("/api/outcomes/signals/pre_market_volume_spike")

    signal = response.json()["signals"][0]
    for field in (
        "id", "ticker", "event_date", "severity", "summary",
        "mfe_pct", "mae_pct", "eod_pct_change", "follow_through", "is_complete",
    ):
        assert field in signal, f"Missing field: {field}"


def test_signals_limit_param(db: Session):
    seed_outcomes(db)

    response = client.get("/api/outcomes/signals/pre_market_volume_spike?limit=2")

    data = response.json()
    assert len(data["signals"]) == 2
    assert data["total"] == 3  # total unchanged


def test_signals_offset_param(db: Session):
    seed_outcomes(db)

    response = client.get("/api/outcomes/signals/pre_market_volume_spike?offset=2")

    data = response.json()
    assert len(data["signals"]) == 1


def test_signals_filters_by_scanner_type(db: Session):
    seed_outcomes(db)  # 1 liquidity_hunt_pre event, no summaries

    response = client.get("/api/outcomes/signals/liquidity_hunt_pre")

    data = response.json()
    assert data["total"] == 1
    assert data["signals"][0]["ticker"] == "MRNA"


# ---------------------------------------------------------------------------
# GET /api/outcomes/event/{event_id}
# ---------------------------------------------------------------------------


def test_event_outcome_returns_summary_and_snapshots(db: Session):
    seeded = seed_outcomes(db)
    event_id = seeded["events"][0].id

    response = client.get(f"/api/outcomes/event/{event_id}")

    assert response.status_code == 200
    data = response.json()
    assert "summary" in data
    assert "snapshots" in data
    assert data["summary"] is not None
    assert len(data["snapshots"]) == 3  # 5m, 15m, 30m


def test_event_outcome_no_summary_returns_null_summary(db: Session):
    seeded = seed_outcomes(db)
    event_id = seeded["events"][3].id  # MRNA — no summary or snapshots

    response = client.get(f"/api/outcomes/event/{event_id}")

    assert response.status_code == 200
    data = response.json()
    assert data["summary"] is None
    assert data["snapshots"] == []


def test_event_outcome_not_found_returns_404(db: Session):
    response = client.get("/api/outcomes/event/99999")

    assert response.status_code == 404


def test_event_outcome_summary_shape(db: Session):
    seeded = seed_outcomes(db)
    event_id = seeded["events"][0].id

    response = client.get(f"/api/outcomes/event/{event_id}")

    summary = response.json()["summary"]
    for field in (
        "id", "scanner_event_id", "reference_price",
        "mfe_pct", "mae_pct", "eod_pct_change", "follow_through", "is_complete",
    ):
        assert field in summary, f"Missing summary field: {field}"


def test_event_outcome_snapshot_shape(db: Session):
    seeded = seed_outcomes(db)
    event_id = seeded["events"][0].id

    response = client.get(f"/api/outcomes/event/{event_id}")

    snap = response.json()["snapshots"][0]
    for field in (
        "id", "scanner_event_id", "interval_key",
        "reference_price", "pct_change", "status",
    ):
        assert field in snap, f"Missing snapshot field: {field}"


def test_event_outcome_snapshots_ordered_by_interval_key(db: Session):
    seeded = seed_outcomes(db)
    event_id = seeded["events"][0].id

    response = client.get(f"/api/outcomes/event/{event_id}")

    keys = [s["interval_key"] for s in response.json()["snapshots"]]
    assert keys == sorted(keys)


# ---------------------------------------------------------------------------
# GET /api/outcomes/readiness/{ticker}
# ---------------------------------------------------------------------------


def test_readiness_missing_scanner_type_returns_400(db: Session):
    response = client.get("/api/outcomes/readiness/AAPL")

    assert response.status_code == 400


def test_readiness_returns_correct_shape(db: Session):
    response = client.get("/api/outcomes/readiness/AAPL?scanner_type=pre_market_volume_spike")

    assert response.status_code == 200
    data = response.json()
    for field in ("ticker", "scanner_type", "coverages", "is_ready", "missing_summary"):
        assert field in data, f"Missing field: {field}"
    assert data["ticker"] == "AAPL"
    assert data["scanner_type"] == "pre_market_volume_spike"
    assert isinstance(data["coverages"], list)
