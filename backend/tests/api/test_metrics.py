"""Integration tests for the /metrics endpoint."""

import os

import pytest
import yaml
from fastapi.testclient import TestClient

from app.main import app

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
_COMPOSE_FILE = os.path.join(_REPO_ROOT, "docker-compose.yml")
_OVERRIDE_FILE = os.path.join(_REPO_ROOT, "docker-compose.override.yml")

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


@pytest.mark.skipif(
    not os.path.exists(_COMPOSE_FILE), reason="docker-compose.yml not accessible"
)
def test_docker_compose_backend_command_wipes_prometheus_dir():
    """docker-compose.yml backend command must wipe stale .db files on cold start."""
    with open(_COMPOSE_FILE) as f:
        compose = yaml.safe_load(f)
    cmd = compose["services"]["backend"]["command"]
    assert "rm -rf /tmp/prometheus_multiproc/*" in cmd


@pytest.mark.skipif(
    not os.path.exists(_COMPOSE_FILE), reason="docker-compose.yml not accessible"
)
def test_docker_compose_celery_worker_command_wipes_prometheus_dir():
    """docker-compose.yml celery-worker command must wipe stale .db files on cold start."""
    with open(_COMPOSE_FILE) as f:
        compose = yaml.safe_load(f)
    cmd = compose["services"]["celery-worker"]["command"]
    assert "rm -rf /tmp/prometheus_multiproc/*" in cmd


@pytest.mark.skipif(
    not os.path.exists(_OVERRIDE_FILE),
    reason="docker-compose.override.yml not accessible",
)
def test_docker_compose_override_backend_command_wipes_prometheus_dir():
    """docker-compose.override.yml backend command must also wipe stale .db files."""
    with open(_OVERRIDE_FILE) as f:
        override = yaml.safe_load(f)
    cmd = override["services"]["backend"]["command"]
    assert "rm -rf /tmp/prometheus_multiproc/*" in cmd


@pytest.mark.skipif(
    not os.path.exists(_OVERRIDE_FILE),
    reason="docker-compose.override.yml not accessible",
)
def test_docker_compose_override_celery_worker_command_wipes_prometheus_dir():
    """docker-compose.override.yml celery-worker command must also wipe stale .db files."""
    with open(_OVERRIDE_FILE) as f:
        override = yaml.safe_load(f)
    cmd = override["services"]["celery-worker"]["command"]
    assert "rm -rf /tmp/prometheus_multiproc/*" in cmd
