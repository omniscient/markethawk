"""Integration tests for the /metrics endpoint."""

from app.main import app
from fastapi.testclient import TestClient

client = TestClient(app)


def test_metrics_endpoint_returns_200():
    response = client.get("/metrics")
    assert response.status_code == 200


def test_metrics_endpoint_returns_prometheus_format():
    response = client.get("/metrics")
    assert "text/plain" in response.headers["content-type"]
    assert b"# TYPE" in response.content


def test_metrics_endpoint_not_in_openapi_schema():
    response = client.get("/openapi.json")
    assert "/metrics" not in response.json().get("paths", {})
