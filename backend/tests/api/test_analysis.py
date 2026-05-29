"""Integration tests for signal analysis endpoints."""

from app.main import app
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from tests.fixtures.analysis import seed_completed_analysis_run

client = TestClient(app)


# ---------------------------------------------------------------------------
# GET /api/outcomes/correlations
# ---------------------------------------------------------------------------


def test_correlations_returns_404_when_no_run(db: Session):
    response = client.get("/api/outcomes/correlations")
    assert response.status_code == 404


def test_correlations_returns_correct_shape(db: Session):
    seed_completed_analysis_run(db)
    response = client.get("/api/outcomes/correlations")

    assert response.status_code == 200
    data = response.json()
    assert "run_id" in data
    assert "features" in data
    assert "intervals" in data
    assert "pearson" in data
    assert "spearman" in data
    assert len(data["pearson"]) == len(data["features"])
    assert len(data["pearson"][0]) == len(data["intervals"])


def test_correlations_filters_by_scanner_type(db: Session):
    seed_completed_analysis_run(db)
    response = client.get("/api/outcomes/correlations?scanner_type=nonexistent_type")
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# GET /api/outcomes/analysis/latest
# ---------------------------------------------------------------------------


def test_latest_returns_404_when_no_run(db: Session):
    response = client.get("/api/outcomes/analysis/latest")
    assert response.status_code == 404


def test_latest_returns_feature_weights_and_clusters(db: Session):
    seed_completed_analysis_run(db)
    response = client.get("/api/outcomes/analysis/latest")

    assert response.status_code == 200
    data = response.json()
    assert "run_id" in data
    assert "feature_weights" in data
    assert "clusters" in data
    assert len(data["feature_weights"]) > 0
    assert len(data["clusters"]) > 0

    cluster = data["clusters"][0]
    assert "id" in cluster
    assert "label" in cluster
    assert "event_count" in cluster
    assert "centroid" in cluster
    assert "return_profile" in cluster


# ---------------------------------------------------------------------------
# POST /api/outcomes/analyze
# ---------------------------------------------------------------------------


def test_trigger_analysis_returns_202(db: Session):
    from unittest.mock import patch

    mock_result = type("R", (), {"id": "test-task-123"})()
    with patch("app.tasks.analyze_signal_features") as mock_task:
        mock_task.delay.return_value = mock_result
        response = client.post("/api/outcomes/analyze")
        assert response.status_code == 202
    data = response.json()
    assert "task_id" in data
