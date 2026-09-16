from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_semantic_search_endpoint_returns_disabled_without_feature_flag(db):
    response = client.get(
        "/api/v1/outcomes/semantic-search",
        params={"query": "growth signal", "top_k": 3, "source_type": "scanner_narrative"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "disabled"
    assert data["matches"] == []
