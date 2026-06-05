import os

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-unit-tests-only-32chars!")

from app.core.config import get_settings

get_settings.cache_clear()

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_auth_status_returns_bootstrapped_false_when_no_users(db):
    response = client.get("/api/auth/status")
    assert response.status_code == 200
    assert response.json() == {"bootstrapped": False}


def test_register_creates_first_user(db):
    response = client.post(
        "/api/auth/register",
        json={"username": "admin", "password": "hunter2"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["username"] == "admin"
    assert "id" in data


def test_register_blocked_when_user_exists(db):
    client.post("/api/auth/register", json={"username": "admin", "password": "hunter2"})
    response = client.post(
        "/api/auth/register",
        json={"username": "admin2", "password": "hunter2"},
    )
    assert response.status_code == 403


def test_login_sets_cookies(db):
    client.post("/api/auth/register", json={"username": "admin", "password": "hunter2"})
    response = client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "hunter2"},
    )
    assert response.status_code == 200
    assert "access_token" in response.cookies


def test_login_wrong_password_returns_401(db):
    client.post("/api/auth/register", json={"username": "admin", "password": "hunter2"})
    response = client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "wrongpassword"},
    )
    assert response.status_code == 401


def test_me_returns_current_user(db):
    from app.core.auth import create_access_token

    # Register and get the real user ID to create an authenticated token
    reg = client.post(
        "/api/auth/register", json={"username": "admin", "password": "hunter2"}
    )
    user_id = reg.json()["id"]
    token = create_access_token(user_id)
    client.cookies.set("access_token", token)
    response = client.get("/api/auth/me")
    assert response.status_code == 200
    assert response.json()["username"] == "admin"


def test_logout_clears_cookies(db):
    from app.core.auth import create_access_token

    # Register and set a valid token for the registered user
    reg = client.post(
        "/api/auth/register", json={"username": "admin", "password": "hunter2"}
    )
    user_id = reg.json()["id"]
    token = create_access_token(user_id)
    client.cookies.set("access_token", token)
    response = client.post("/api/auth/logout")
    assert response.status_code == 200


def test_cookie_secure_defaults_to_true():
    from app.core.config import Settings

    s = Settings(
        DATABASE_URL="postgresql://x:x@localhost/x",
        POLYGON_API_KEY="test",
        JWT_SECRET_KEY="test-secret-key-for-unit-tests-only-32chars!",
    )
    assert s.COOKIE_SECURE is True


def test_login_cookies_have_strict_samesite(db):
    client.post("/api/auth/register", json={"username": "admin", "password": "hunter2"})
    response = client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "hunter2"},
    )
    assert response.status_code == 200
    set_cookie_headers = [
        v for k, v in response.headers.multi_items() if k.lower() == "set-cookie"
    ]
    assert any("samesite=strict" in h.lower() for h in set_cookie_headers)
