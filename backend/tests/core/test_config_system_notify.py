from app.core.config import Settings


def test_system_notify_fields_default_empty(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://smoke:smoke@localhost:5432/smoke")
    monkeypatch.setenv("POLYGON_API_KEY", "x")
    monkeypatch.setenv("JWT_SECRET_KEY", "smoke-gate-only-not-secret-0123456789abcdef")
    monkeypatch.setenv("REDIS_PASSWORD", "smoke-gate-only-not-a-real-redis-password")
    s = Settings()
    assert s.OPS_ALERT_EMAIL == ""
    assert s.INTERNAL_API_TOKEN == ""
