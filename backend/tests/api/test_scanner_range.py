from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_run_range_returns_task_id(db):

    with patch("app.tasks.run_range_scan") as mock_task:
        mock_task.delay.return_value = type("R", (), {"id": "test-task-123"})()

        response = client.post(
            "/api/scanner/run-range",
            json={
                "ticker": "AAPL",
                "scanner_types": ["pre_market_volume_spike"],
                "start_date": "2025-01-01",
                "end_date": "2025-01-31",
                "fetch_missing_data": False,
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "queued"
    assert "task_id" in body


def test_run_range_rejects_empty_scanner_types(db):

    response = client.post(
        "/api/scanner/run-range",
        json={
            "ticker": "AAPL",
            "scanner_types": [],
            "start_date": "2025-01-01",
            "end_date": "2025-01-31",
            "fetch_missing_data": False,
        },
    )

    assert response.status_code == 422
