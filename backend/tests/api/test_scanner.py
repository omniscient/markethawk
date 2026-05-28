"""
Integration tests for scanner API endpoints.
Runs against a real Postgres DB (via testcontainers).
"""

from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.main import app
from app.utils.session import get_market_today
from tests.fixtures.core import (
    seed_monitored_stocks,
    seed_scanner_configs,
    seed_universes,
)
from tests.fixtures.scanner import seed_scanner_events, seed_scanner_runs

client = TestClient(app)


# ---------------------------------------------------------------------------
# GET /api/scanner/results
# ---------------------------------------------------------------------------


def test_results_returns_all_events(db: Session):
    seed_scanner_events(db)

    response = client.get("/api/scanner/results")

    assert response.status_code == 200
    data = response.json()
    assert len(data) >= 10
    assert all("ticker" in e for e in data)
    assert all("scanner_type" in e for e in data)


def test_results_filter_by_ticker(db: Session):
    seed_scanner_events(db)

    response = client.get("/api/scanner/results?ticker=AAPL")

    assert response.status_code == 200
    data = response.json()
    assert len(data) > 0
    assert all(e["ticker"] == "AAPL" for e in data)


def test_results_filter_by_scanner_type(db: Session):
    seed_scanner_events(db)

    response = client.get("/api/scanner/results?scanner_type=pre_market_volume_spike")

    assert response.status_code == 200
    data = response.json()
    assert len(data) > 0
    assert all(e["scanner_type"] == "pre_market_volume_spike" for e in data)


def test_results_filter_by_universe_id(db: Session):
    universes = seed_universes(db)
    seed_monitored_stocks(db, universes)  # universe filter joins MonitoredStock
    seed_scanner_events(db)

    tech_universe_id = universes[0].id  # contains AAPL, MSFT, NVDA

    response = client.get(f"/api/scanner/results?universe_id={tech_universe_id}")

    assert response.status_code == 200
    data = response.json()
    assert len(data) > 0
    returned_tickers = {e["ticker"] for e in data}
    assert returned_tickers.issubset({"AAPL", "MSFT", "NVDA"})


def test_results_empty_when_no_events(db: Session):
    response = client.get("/api/scanner/results")

    assert response.status_code == 200
    assert response.json() == []


# ---------------------------------------------------------------------------
# GET /api/scanner/configs
# ---------------------------------------------------------------------------


def test_configs_returns_active_only(db: Session):
    seed_scanner_configs(db)

    response = client.get("/api/scanner/configs")

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2  # only the 2 active configs
    assert all(c["is_active"] for c in data)
    scanner_types = {c["scanner_type"] for c in data}
    assert scanner_types == {"pre_market_volume_spike", "liquidity_hunt"}


def test_configs_returns_empty_when_none(db: Session):
    response = client.get("/api/scanner/configs")

    assert response.status_code == 200
    assert response.json() == []


def test_configs_response_shape(db: Session):
    seed_scanner_configs(db)

    response = client.get("/api/scanner/configs")

    cfg = response.json()[0]
    for field in (
        "id",
        "uuid",
        "name",
        "scanner_type",
        "parameters",
        "criteria",
        "is_active",
    ):
        assert field in cfg, f"Missing field: {field}"


# ---------------------------------------------------------------------------
# GET /api/scanner/history
# ---------------------------------------------------------------------------


def test_history_returns_runs_desc(db: Session):
    seed_scanner_runs(db)

    response = client.get("/api/scanner/history")

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 5

    # Verify required fields present
    run = data[0]
    for field in (
        "scan_id",
        "status",
        "scanner_type",
        "stocks_scanned",
        "events_detected",
    ):
        assert field in run, f"Missing field: {field}"


def test_history_respects_limit(db: Session):
    seed_scanner_runs(db)

    response = client.get("/api/scanner/history?limit=2")

    assert response.status_code == 200
    assert len(response.json()) == 2


def test_history_empty_when_no_runs(db: Session):
    response = client.get("/api/scanner/history")

    assert response.status_code == 200
    assert response.json() == []


# ---------------------------------------------------------------------------
# GET /api/scanner/scan-status-block
# ---------------------------------------------------------------------------


def test_scan_status_block_without_universe(db: Session):
    seed_scanner_runs(db)

    response = client.get(
        "/api/scanner/scan-status-block?scanner_type=pre_market_volume_spike"
    )

    assert response.status_code == 200
    data = response.json()
    assert data["scanner_type"] == "pre_market_volume_spike"
    assert data["last_run"] is not None
    assert data["last_run"]["status"] in ("completed", "running", "failed")
    assert data["total_events"] >= 0
    assert data["success_rate"] is not None


def test_scan_status_block_with_universe(db: Session):
    universes = seed_universes(db)
    universe_id = universes[0].id
    seed_scanner_runs(db, universe_id=universe_id)

    response = client.get(
        f"/api/scanner/scan-status-block?scanner_type=pre_market_volume_spike&universe_id={universe_id}"
    )

    assert response.status_code == 200
    data = response.json()
    assert data["universe_id"] == universe_id
    assert data["last_run"] is not None


def test_scan_status_block_no_runs(db: Session):
    response = client.get(
        "/api/scanner/scan-status-block?scanner_type=pre_market_volume_spike"
    )

    assert response.status_code == 200
    data = response.json()
    assert data["last_run"] is None
    assert data["success_rate"] is None
    assert data["total_events"] == 0


def test_scan_status_block_sparkline(db: Session):
    seed_scanner_runs(db)

    response = client.get(
        "/api/scanner/scan-status-block?scanner_type=pre_market_volume_spike"
    )

    data = response.json()
    assert "sparkline" in data
    assert isinstance(data["sparkline"], list)
    assert len(data["sparkline"]) >= 1
    assert "events_detected" in data["sparkline"][0]


# ---------------------------------------------------------------------------
# GET /api/scanner/stats
# ---------------------------------------------------------------------------


def test_stats_returns_counts(db: Session):
    seed_scanner_events(db)

    response = client.get("/api/scanner/stats")

    assert response.status_code == 200
    data = response.json()
    assert data["totalEvents"] >= 10
    for field in ("activeAlerts", "avgVolumeSpike", "totalEvents", "todayEvents"):
        assert field in data


def test_stats_empty_db(db: Session):
    response = client.get("/api/scanner/stats")

    assert response.status_code == 200
    data = response.json()
    assert data["totalEvents"] == 0
    assert data["todayEvents"] == 0
    assert data["activeAlerts"] == 0
    assert data["avgVolumeSpike"] == 0.0


def test_stats_today_events(db: Session):
    seed_scanner_events(db)

    response = client.get("/api/scanner/stats")

    data = response.json()
    # seed_scanner_events seeds events on today's date — at least 5 of them
    assert data["todayEvents"] >= 5


# ---------------------------------------------------------------------------
# GET /api/scanner/results — date range filters
# ---------------------------------------------------------------------------


def test_results_filter_by_start_date(db: Session):
    seed_scanner_events(db)
    today = get_market_today()
    today_str = str(today)

    response = client.get(f"/api/scanner/results?start_date={today_str}")

    assert response.status_code == 200
    data = response.json()
    assert len(data) > 0
    assert all(e["event_date"] >= today_str for e in data)


def test_results_filter_by_end_date(db: Session):
    seed_scanner_events(db)
    today = get_market_today()
    two_days_ago = str(today - timedelta(days=2))

    response = client.get(f"/api/scanner/results?end_date={two_days_ago}")

    assert response.status_code == 200
    data = response.json()
    assert len(data) > 0
    assert all(e["event_date"] <= two_days_ago for e in data)


def test_results_filter_by_date_range(db: Session):
    seed_scanner_events(db)
    today = get_market_today()
    yesterday = str(today - timedelta(days=1))

    response = client.get(
        f"/api/scanner/results?start_date={yesterday}&end_date={yesterday}"
    )

    assert response.status_code == 200
    data = response.json()
    assert len(data) > 0
    assert all(e["event_date"] == yesterday for e in data)


# ---------------------------------------------------------------------------
# GET /api/scanner/types
# ---------------------------------------------------------------------------


def test_list_scanner_types():
    import app.services.liquidity_hunt  # noqa: F401
    import app.services.oversold_bounce_scan  # noqa: F401
    import app.services.pre_market_scan  # noqa: F401

    response = client.get("/api/scanner/types")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    keys = [item["key"] for item in data]
    assert "pre_market_volume_spike" in keys
    assert "oversold_bounce" in keys
    assert "liquidity_hunt" in keys
    assert "liquidity_hunt_pre" in keys
    assert "liquidity_hunt_post" in keys
    for item in data:
        assert {"key", "display_name", "description", "supports_date_range"} == set(
            item
        )
        assert isinstance(item["supports_date_range"], bool)
