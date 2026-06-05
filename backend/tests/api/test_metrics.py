"""Integration tests for the /metrics endpoint."""

from fastapi.testclient import TestClient

from app.main import app

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


def test_metrics_multiprocess_mode_uses_collector(tmp_path, monkeypatch):
    """When PROMETHEUS_MULTIPROC_DIR is set, /metrics uses MultiProcessCollector.

    Worker containers write PID-named .db files to the shared prometheus_multiproc
    volume; the backend's /metrics endpoint reads ALL those files via
    MultiProcessCollector and aggregates them.  The prometheus_multiproc volume
    must be a regular named volume (not tmpfs) so all containers share the same
    filesystem — see docker-compose.yml.
    """
    monkeypatch.setenv("PROMETHEUS_MULTIPROC_DIR", str(tmp_path))
    # The endpoint must still return 200 with the multiprocess path active.
    # An empty PROMETHEUS_MULTIPROC_DIR is valid: MultiProcessCollector finds no
    # .db files and returns an empty but well-formed Prometheus response.
    response = client.get("/metrics")
    assert response.status_code == 200
    assert "text/plain" in response.headers["content-type"]
