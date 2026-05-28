import inspect
import pytest
from pydantic import ValidationError


@pytest.fixture(autouse=True)
def clear_settings_cache():
    from app.core.config import get_settings
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


class TestSettingsRequiredFields:
    def test_missing_database_url_raises(self, monkeypatch):
        monkeypatch.delenv("DATABASE_URL", raising=False)
        from app.core.config import Settings
        with pytest.raises(ValidationError):
            Settings(POLYGON_API_KEY="test-key")

    def test_missing_polygon_api_key_raises(self, monkeypatch):
        monkeypatch.delenv("POLYGON_API_KEY", raising=False)
        from app.core.config import Settings
        with pytest.raises(ValidationError):
            Settings(DATABASE_URL="postgresql://test:test@localhost/test")

    def test_valid_required_fields_succeeds(self):
        from app.core.config import Settings
        s = Settings(
            DATABASE_URL="postgresql://test:test@localhost/test",
            POLYGON_API_KEY="test-key",
        )
        assert s.DATABASE_URL == "postgresql://test:test@localhost/test"
        assert s.POLYGON_API_KEY == "test-key"


class TestDatabaseUrlValidator:
    def test_non_postgresql_url_raises(self):
        from app.core.config import Settings
        with pytest.raises(ValidationError):
            Settings(
                DATABASE_URL="mysql://test:test@localhost/test",
                POLYGON_API_KEY="test-key",
            )

    def test_postgresql_asyncpg_scheme_accepted(self):
        from app.core.config import Settings
        s = Settings(
            DATABASE_URL="postgresql+asyncpg://test:test@localhost/test",
            POLYGON_API_KEY="test-key",
        )
        assert s.DATABASE_URL.startswith("postgresql+asyncpg")


class TestPortValidators:
    def test_ibkr_port_zero_raises(self):
        from app.core.config import Settings
        with pytest.raises(ValidationError):
            Settings(
                DATABASE_URL="postgresql://test:test@localhost/test",
                POLYGON_API_KEY="test-key",
                IBKR_PORT=0,
            )

    def test_ibkr_port_too_high_raises(self):
        from app.core.config import Settings
        with pytest.raises(ValidationError):
            Settings(
                DATABASE_URL="postgresql://test:test@localhost/test",
                POLYGON_API_KEY="test-key",
                IBKR_PORT=65536,
            )

    def test_smtp_port_out_of_range_raises(self):
        from app.core.config import Settings
        with pytest.raises(ValidationError):
            Settings(
                DATABASE_URL="postgresql://test:test@localhost/test",
                POLYGON_API_KEY="test-key",
                SMTP_PORT=99999,
            )

    def test_valid_ports_accepted(self):
        from app.core.config import Settings
        s = Settings(
            DATABASE_URL="postgresql://test:test@localhost/test",
            POLYGON_API_KEY="test-key",
            IBKR_PORT=7497,
            SMTP_PORT=465,
        )
        assert s.IBKR_PORT == 7497
        assert s.SMTP_PORT == 465


class TestCorsOrigins:
    def test_default_cors_origins(self, monkeypatch):
        monkeypatch.delenv("CORS_ORIGINS", raising=False)
        from app.core.config import Settings
        s = Settings(
            DATABASE_URL="postgresql://test:test@localhost/test",
            POLYGON_API_KEY="test-key",
        )
        assert s.CORS_ORIGINS == ["http://localhost:3333"]

    def test_cors_origins_from_env(self, monkeypatch):
        monkeypatch.setenv(
            "CORS_ORIGINS",
            '["http://localhost:3333","http://localhost:3000"]',
        )
        from app.core.config import Settings
        s = Settings(
            DATABASE_URL="postgresql://test:test@localhost/test",
            POLYGON_API_KEY="test-key",
        )
        assert "http://localhost:3000" in s.CORS_ORIGINS

    def test_no_load_dotenv_call(self):
        from app.core import config
        source = inspect.getsource(config)
        assert "load_dotenv" not in source
