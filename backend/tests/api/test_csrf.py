"""Tests CSRF enforcement via CSRFMiddleware (issue #192)."""

import os

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-unit-tests-only-32chars!")
os.environ.setdefault("RATE_LIMITING_ENABLED", "false")

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from jose import jwt
from starlette.requests import Request

from app.core.auth import create_access_token
from app.core.config import get_settings
from app.main import CSRFMiddleware  # fails until CSRFMiddleware is added to main.py


def _make_app() -> FastAPI:
    """Minimal test app: auth + CSRF middleware, no DB dependency."""
    _app = FastAPI()
    _settings = get_settings()

    class _AuthMiddleware:
        def __init__(self, app):
            self.app = app

        async def __call__(self, scope, receive, send):
            if scope["type"] != "http":
                await self.app(scope, receive, send)
                return
            request = Request(scope)
            if request.url.path.startswith("/api/auth/"):
                await self.app(scope, receive, send)
                return
            token = request.cookies.get("access_token")
            if not token:
                await JSONResponse(
                    status_code=401, content={"detail": "Not authenticated"}
                )(scope, receive, send)
                return
            try:
                jwt.decode(
                    token,
                    _settings.JWT_SECRET_KEY,
                    algorithms=[_settings.JWT_ALGORITHM],
                )
            except Exception:
                await JSONResponse(
                    status_code=401, content={"detail": "Invalid token"}
                )(scope, receive, send)
                return
            await self.app(scope, receive, send)

    # CSRF innermost (added first), auth outer (added second)
    _app.add_middleware(CSRFMiddleware)
    _app.add_middleware(_AuthMiddleware)

    @_app.post("/api/v1/resource")
    async def post_resource():
        return {"ok": True}

    @_app.get("/api/v1/resource")
    async def get_resource():
        return {"ok": True}

    @_app.post("/api/auth/login")
    async def auth_login():
        return {"ok": True}

    return _app


_test_app = _make_app()


def _authed_client() -> TestClient:
    token = create_access_token("test-user-id")
    c = TestClient(_test_app)
    c.cookies.set("access_token", token)
    return c


def test_post_without_csrf_header_returns_403():
    response = _authed_client().post("/api/v1/resource", json={})
    assert response.status_code == 403
    assert "X-Requested-With" in response.json()["detail"]


def test_post_with_csrf_header_passes_csrf():
    response = _authed_client().post(
        "/api/v1/resource",
        json={},
        headers={"X-Requested-With": "XMLHttpRequest"},
    )
    assert response.status_code == 200


def test_get_without_csrf_header_passes():
    response = _authed_client().get("/api/v1/resource")
    assert response.status_code == 200


def test_auth_endpoint_exempt_from_csrf():
    # no auth cookie — path is CSRF-exempt and auth-exempt
    c = TestClient(_test_app)
    response = c.post("/api/auth/login", json={})
    assert response.status_code != 403
