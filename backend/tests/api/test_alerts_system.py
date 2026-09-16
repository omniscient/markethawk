from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import create_app


def _client():
    return TestClient(create_app())


def test_503_when_token_unset():
    with patch("app.routers.alerts.settings") as s:
        s.INTERNAL_API_TOKEN = ""
        r = _client().post("/api/v1/alerts/system", json={"title": "t", "body": "b"})
    assert r.status_code == 503


def test_401_on_bad_token():
    with patch("app.routers.alerts.settings") as s:
        s.INTERNAL_API_TOKEN = "secret"
        r = _client().post(
            "/api/v1/alerts/system",
            json={"title": "t", "body": "b"},
            headers={"X-Internal-Token": "wrong"},
        )
    assert r.status_code == 401


def test_200_dispatches():
    with patch("app.routers.alerts.settings") as s, patch(
        "app.routers.alerts.notify_system"
    ) as ns:
        s.INTERNAL_API_TOKEN = "secret"
        ns.return_value = {"email": "sent", "browser_push": "sent:0"}
        r = _client().post(
            "/api/v1/alerts/system",
            json={"title": "t", "body": "b", "severity": "warning"},
            headers={"X-Internal-Token": "secret"},
        )
    assert r.status_code == 200
    assert r.json()["channels"]["email"] == "sent"


def test_422_missing_fields():
    with patch("app.routers.alerts.settings") as s:
        s.INTERNAL_API_TOKEN = "secret"
        r = _client().post(
            "/api/v1/alerts/system",
            json={"title": "t"},
            headers={"X-Internal-Token": "secret"},
        )
    assert r.status_code == 422
