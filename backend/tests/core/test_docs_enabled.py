"""Tests for DOCS_ENABLED: Settings field, route registration, and auth gating."""

import os

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost/test")
os.environ.setdefault("POLYGON_API_KEY", "test-key-for-unit-tests-only")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret-key-for-unit-tests-only-aaa")
os.environ.setdefault("RATE_LIMITING_ENABLED", "false")


@pytest.fixture(autouse=True)
def clear_settings_cache(monkeypatch):
    from app.core.config import get_settings

    # Strip the local-dev container overrides (docker-compose.override.yml sets
    # DOCS_ENABLED=true / COOKIE_SECURE=false for http dev) so the default-asserting
    # test sees the secure code default regardless of ambient env. Tests that need a
    # specific value set it explicitly (monkeypatch.setenv / Settings kwarg) afterwards.
    monkeypatch.delenv("DOCS_ENABLED", raising=False)
    monkeypatch.delenv("COOKIE_SECURE", raising=False)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


# ── Settings: DOCS_ENABLED field ──────────────────────────────────────────────


class TestDocsEnabledSetting:
    def test_default_is_false(self):
        from app.core.config import Settings

        s = Settings(
            DATABASE_URL="postgresql://test:test@localhost/test",
            POLYGON_API_KEY="test-key",
        )
        assert s.DOCS_ENABLED is False

    def test_init_kwarg_true(self):
        from app.core.config import Settings

        s = Settings(
            DATABASE_URL="postgresql://test:test@localhost/test",
            POLYGON_API_KEY="test-key",
            DOCS_ENABLED=True,
        )
        assert s.DOCS_ENABLED is True

    def test_env_var_coercion(self, monkeypatch):
        monkeypatch.setenv("DOCS_ENABLED", "true")
        from app.core.config import Settings

        s = Settings(
            DATABASE_URL="postgresql://test:test@localhost/test",
            POLYGON_API_KEY="test-key",
        )
        assert s.DOCS_ENABLED is True


# ── App factory: route registration ───────────────────────────────────────────


def _make_test_app(docs_enabled: bool):
    """Create a fresh app instance with the given DOCS_ENABLED value."""
    import app.main as main_mod
    from app.core.config import Settings
    from app.main import create_app

    fake_settings = Settings(
        DATABASE_URL="postgresql://test:test@localhost/test",
        POLYGON_API_KEY="test-key",
        DOCS_ENABLED=docs_enabled,
    )
    original = main_mod.settings
    main_mod.settings = fake_settings
    try:
        test_app = create_app()
    finally:
        main_mod.settings = original
    return test_app


class TestDocsUrlsWhenDisabled:
    def test_docs_url_is_none(self):
        test_app = _make_test_app(docs_enabled=False)
        assert test_app.docs_url is None

    def test_redoc_url_is_none(self):
        test_app = _make_test_app(docs_enabled=False)
        assert test_app.redoc_url is None

    def test_openapi_url_is_none(self):
        test_app = _make_test_app(docs_enabled=False)
        assert test_app.openapi_url is None


class TestDocsUrlsWhenEnabled:
    def test_docs_url_set(self):
        test_app = _make_test_app(docs_enabled=True)
        assert test_app.docs_url == "/docs"

    def test_redoc_url_set(self):
        test_app = _make_test_app(docs_enabled=True)
        assert test_app.redoc_url == "/redoc"

    def test_openapi_url_set(self):
        test_app = _make_test_app(docs_enabled=True)
        assert test_app.openapi_url == "/openapi.json"


# ── Auth gating via EXEMPT_PREFIXES ───────────────────────────────────────────


class TestAuthGating:
    def test_docs_unauthenticated_401_when_disabled(self):
        """When disabled, /docs is not exempt — AuthMiddleware returns 401."""
        test_app = _make_test_app(docs_enabled=False)
        client = TestClient(test_app, raise_server_exceptions=False)
        response = client.get("/docs", follow_redirects=False)
        assert response.status_code == 401

    def test_openapi_json_unauthenticated_401_when_disabled(self):
        """/openapi.json without auth returns 401 (not exempt, not registered)."""
        test_app = _make_test_app(docs_enabled=False)
        client = TestClient(test_app, raise_server_exceptions=False)
        response = client.get("/openapi.json")
        assert response.status_code == 401

    def test_docs_unauthenticated_200_when_enabled(self):
        """When enabled, /docs is exempt from auth — accessible without a cookie."""
        test_app = _make_test_app(docs_enabled=True)
        client = TestClient(test_app, raise_server_exceptions=False)
        response = client.get("/docs")
        assert response.status_code == 200

    def test_metrics_always_exempt_when_disabled(self):
        """/metrics is always accessible — DOCS_ENABLED does not affect it."""
        test_app = _make_test_app(docs_enabled=False)
        client = TestClient(test_app, raise_server_exceptions=False)
        response = client.get("/metrics")
        assert response.status_code == 200

    def test_metrics_always_exempt_when_enabled(self):
        """/metrics remains accessible when DOCS_ENABLED=True."""
        test_app = _make_test_app(docs_enabled=True)
        client = TestClient(test_app, raise_server_exceptions=False)
        response = client.get("/metrics")
        assert response.status_code == 200
