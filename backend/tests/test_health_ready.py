"""
Tests for the /api/ready readiness probe endpoint.
"""

from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

_IBKR_OK = patch(
    "app.routers.health.SystemService.check_ibkr_reachable", return_value=True
)
_IBKR_FAIL = patch(
    "app.routers.health.SystemService.check_ibkr_reachable",
    side_effect=Exception("Connection refused"),
)


def test_ready_returns_200_when_all_probes_pass():
    mock_db = MagicMock()
    mock_redis = MagicMock()
    mock_redis.ping.return_value = True

    with patch("app.routers.health.SessionLocal", return_value=mock_db):
        with patch("app.routers.health.get_redis", return_value=mock_redis):
            with _IBKR_OK:
                response = client.get("/api/ready")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ready"
    assert data["db"]["ok"] is True
    assert data["redis"]["ok"] is True
    assert "latency_ms" in data["db"]
    assert "latency_ms" in data["redis"]


def test_ready_returns_503_when_db_fails():
    mock_db_class = MagicMock(side_effect=Exception("Connection refused"))
    mock_redis = MagicMock()
    mock_redis.ping.return_value = True

    with patch("app.routers.health.SessionLocal", mock_db_class):
        with patch("app.routers.health.get_redis", return_value=mock_redis):
            with _IBKR_OK:
                response = client.get("/api/ready")

    assert response.status_code == 503
    data = response.json()
    assert data["status"] == "not ready"
    assert data["db"]["ok"] is False
    assert "error" in data["db"]
    assert data["redis"]["ok"] is True


def test_ready_returns_503_when_redis_fails():
    mock_db = MagicMock()
    mock_redis = MagicMock()
    mock_redis.ping.side_effect = Exception("Redis connection error")

    with patch("app.routers.health.SessionLocal", return_value=mock_db):
        with patch("app.routers.health.get_redis", return_value=mock_redis):
            with _IBKR_OK:
                response = client.get("/api/ready")

    assert response.status_code == 503
    data = response.json()
    assert data["status"] == "not ready"
    assert data["db"]["ok"] is True
    assert data["redis"]["ok"] is False
    assert "error" in data["redis"]


def test_ready_returns_503_when_both_probes_fail():
    mock_db_class = MagicMock(side_effect=Exception("DB down"))
    mock_redis = MagicMock()
    mock_redis.ping.side_effect = Exception("Redis down")

    with patch("app.routers.health.SessionLocal", mock_db_class):
        with patch("app.routers.health.get_redis", return_value=mock_redis):
            with _IBKR_OK:
                response = client.get("/api/ready")

    assert response.status_code == 503
    data = response.json()
    assert data["db"]["ok"] is False
    assert data["redis"]["ok"] is False


def test_ready_both_probes_run_when_db_fails():
    """No short-circuit: Redis probe must be called even if DB probe fails."""
    mock_db_class = MagicMock(side_effect=Exception("DB down"))
    mock_redis = MagicMock()
    mock_redis.ping.return_value = True

    with patch("app.routers.health.SessionLocal", mock_db_class):
        with patch(
            "app.routers.health.get_redis", return_value=mock_redis
        ) as mock_get_redis:
            with _IBKR_OK:
                client.get("/api/ready")

    mock_get_redis.assert_called_once()
    mock_redis.ping.assert_called_once()


def test_ready_is_exempt_from_auth():
    """Endpoint returns non-401 without an auth cookie."""
    with patch("app.routers.health.SessionLocal", return_value=MagicMock()):
        with patch("app.routers.health.get_redis", return_value=MagicMock()):
            with _IBKR_OK:
                response = client.get("/api/ready")

    assert response.status_code != 401


def test_ready_probe_body_has_latency_ms():
    mock_db = MagicMock()
    mock_redis = MagicMock()
    mock_redis.ping.return_value = True

    with patch("app.routers.health.SessionLocal", return_value=mock_db):
        with patch("app.routers.health.get_redis", return_value=mock_redis):
            with _IBKR_OK:
                response = client.get("/api/ready")

    data = response.json()
    assert isinstance(data["db"]["latency_ms"], int)
    assert isinstance(data["redis"]["latency_ms"], int)


def test_ready_error_field_absent_on_success():
    mock_db = MagicMock()
    mock_redis = MagicMock()
    mock_redis.ping.return_value = True

    with patch("app.routers.health.SessionLocal", return_value=mock_db):
        with patch("app.routers.health.get_redis", return_value=mock_redis):
            with _IBKR_OK:
                response = client.get("/api/ready")

    data = response.json()
    assert "error" not in data["db"]
    assert "error" not in data["redis"]


def test_ready_handles_none_redis():
    """When get_redis() returns None (REDIS_URL unset), Redis probe reports failure."""
    mock_db = MagicMock()

    with patch("app.routers.health.SessionLocal", return_value=mock_db):
        with patch("app.routers.health.get_redis", return_value=None):
            with _IBKR_OK:
                response = client.get("/api/ready")

    assert response.status_code == 503
    data = response.json()
    assert data["redis"]["ok"] is False
    assert "error" in data["redis"]


# ── New tests for live_data IBKR probe ────────────────────────────────────


def test_ready_includes_live_data_probe():
    """live_data field present in response (informational)."""
    mock_db = MagicMock()
    mock_redis = MagicMock()
    mock_redis.ping.return_value = True

    with patch("app.routers.health.SessionLocal", return_value=mock_db):
        with patch("app.routers.health.get_redis", return_value=mock_redis):
            with _IBKR_OK:
                response = client.get("/api/ready")

    assert response.status_code == 200
    data = response.json()
    assert "live_data" in data
    assert data["live_data"]["ok"] is True
    assert "latency_ms" in data["live_data"]


def test_ready_returns_200_when_ibkr_unreachable_but_db_redis_ok():
    """live_data failure must NOT cause HTTP 503 — informational only."""
    mock_db = MagicMock()
    mock_redis = MagicMock()
    mock_redis.ping.return_value = True

    with patch("app.routers.health.SessionLocal", return_value=mock_db):
        with patch("app.routers.health.get_redis", return_value=mock_redis):
            with _IBKR_FAIL:
                response = client.get("/api/ready")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ready"
    assert data["live_data"]["ok"] is False
    assert "error" in data["live_data"]


def test_ready_503_when_db_fails_and_ibkr_ok():
    """DB failure still causes 503 regardless of live_data state."""
    mock_db_class = MagicMock(side_effect=Exception("DB down"))
    mock_redis = MagicMock()
    mock_redis.ping.return_value = True

    with patch("app.routers.health.SessionLocal", mock_db_class):
        with patch("app.routers.health.get_redis", return_value=mock_redis):
            with _IBKR_OK:
                response = client.get("/api/ready")

    assert response.status_code == 503
