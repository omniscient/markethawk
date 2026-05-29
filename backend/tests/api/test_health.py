from app.main import app
from fastapi.testclient import TestClient

client = TestClient(app)


def test_health_check():
    response = client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert "timestamp" in data
    assert "version" in data


def test_health_is_exempt_from_auth():
    c = TestClient(app)
    response = c.get("/api/health")
    assert response.status_code == 200


def test_protected_endpoint_returns_401_without_cookie():
    c = TestClient(app, raise_server_exceptions=False)
    response = c.get("/api/scanner/runs")
    assert response.status_code == 401
