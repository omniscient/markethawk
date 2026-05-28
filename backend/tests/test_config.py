import importlib
import os


def test_cors_origins_default():
    os.environ.pop("CORS_ORIGINS", None)
    import app.core.config as cfg

    importlib.reload(cfg)
    settings = cfg.Settings()
    assert settings.CORS_ORIGINS == ["http://localhost:3333"]


def test_cors_origins_from_env():
    os.environ["CORS_ORIGINS"] = '["http://localhost:3333","https://myapp.example.com"]'
    try:
        import app.core.config as cfg

        importlib.reload(cfg)
        settings = cfg.Settings()
        assert "https://myapp.example.com" in settings.CORS_ORIGINS
    finally:
        os.environ.pop("CORS_ORIGINS", None)


def test_jwt_secret_key_field_exists():
    import app.core.config as cfg

    importlib.reload(cfg)
    settings = cfg.Settings()
    assert hasattr(settings, "JWT_SECRET_KEY")
    assert hasattr(settings, "JWT_ALGORITHM")
    assert hasattr(settings, "ACCESS_TOKEN_EXPIRE_MINUTES")
    assert hasattr(settings, "REFRESH_TOKEN_EXPIRE_DAYS")
