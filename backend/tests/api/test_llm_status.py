from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_llm_status_endpoint_reports_disabled_provider_state(db):
    response = client.get("/api/v1/system/llm-status")

    assert response.status_code == 200
    data = response.json()
    assert data["enabled"] is False
    assert data["provider_state"] == "disabled"
    assert data["allowed_features"] == []
    assert "metrics" in data
