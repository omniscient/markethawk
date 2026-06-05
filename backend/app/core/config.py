"""
Application configuration using pydantic-settings.
"""

from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(env_file=".env", case_sensitive=True)

    # Database - REQUIRED
    DATABASE_URL: str

    # Polygon.io API - REQUIRED
    POLYGON_API_KEY: str
    POLYGON_DELAYED: bool = True

    # Redis / Celery
    REDIS_URL: str = "redis://redis:6379/0"
    RATE_LIMITING_ENABLED: bool = True

    # Application
    APP_NAME: str = "Stock Scanner API"
    APP_VERSION: str = "1.0.0"
    LOG_LEVEL: str = "INFO"

    # Environment: "development" returns full stack traces to clients.
    # "production" hides internals and only returns error_id.
    # Default is "production" so that an unset env var NEVER leaks stack traces.
    ENVIRONMENT: str = "production"

    # Error Tracking
    # SEQ_URL: base URL for the Seq container (no trailing slash).
    # Set to an empty string or "disabled" to fall back to stdout-only logging.
    SEQ_URL: str = "http://seq:5341"

    # Distributed Tracing (OpenTelemetry)
    # OTEL_EXPORTER_OTLP_ENDPOINT: OTLP gRPC endpoint (e.g. http://jaeger:4317).
    # Leave empty to use the OTel no-op tracer (zero overhead, no Jaeger required).
    OTEL_EXPORTER_OTLP_ENDPOINT: str = ""
    # OTEL_SERVICE_NAME: identifies this process in Jaeger UI traces.
    OTEL_SERVICE_NAME: str = "markethawk"

    # CORS — JSON array format in .env: CORS_ORIGINS=["http://localhost:3333","https://example.com"]
    CORS_ORIGINS: list[str] = ["http://localhost:3333"]

    # Auth
    JWT_SECRET_KEY: str = ""
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    # Secure cookies — default True; set to false in docker-compose.override.yml for local HTTP dev
    COOKIE_SECURE: bool = True

    # Connection pool
    DB_POOL_SIZE: int = 20
    DB_POOL_MAX_OVERFLOW: int = 10
    DB_POOL_PRE_PING: bool = True
    DB_POOL_RECYCLE: int = 3600
    DB_POOL_TIMEOUT: int = 30

    # ── Interactive Brokers (IBKR) ─────────────────────────────────────
    # Host/port for TWS or IB Gateway:
    #   TWS live:    127.0.0.1:7496
    #   TWS paper:   127.0.0.1:7497
    #   Gateway live: 127.0.0.1:4001
    #   Gateway paper: 127.0.0.1:4002
    IBKR_HOST: str = "127.0.0.1"
    IBKR_PORT: int = 7496
    # Each API connection needs a unique clientId.
    # Keep this different from any other apps connecting to TWS simultaneously.
    IBKR_CLIENT_ID: int = 10

    # Dedicated clientId for the order manager (auto-trading).
    # Must differ from IBKR_CLIENT_ID and from the live scanner's clientId (5).
    IBKR_TRADING_CLIENT_ID: int = 11

    # ── Email / SMTP (Alert Notifications) ────────────────────────────────
    # Use Gmail + an App Password (not your real Gmail password).
    # Generate one at: https://myaccount.google.com/apppasswords
    SMTP_HOST: str = "smtp.gmail.com"
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM_EMAIL: str = "MarketHawk Alerts <noreply@example.com>"

    # ── Web Push / VAPID (Browser Push Notifications) ─────────────────────
    # Generate a key pair once with: python -c "from py_vapid import Vapid; v=Vapid(); v.generate_keys(); print('PRIV:', v.private_pem().decode()); print('PUB:', v.public_key)"
    # Or use the /api/alerts/push/generate-keys endpoint on first run.
    VAPID_PRIVATE_KEY: str = ""
    VAPID_PUBLIC_KEY: str = ""
    # Must be a mailto: or https: URL identifying the push sender
    VAPID_CLAIMS_EMAIL: str = "mailto:admin@example.com"

    @field_validator("DATABASE_URL")
    @classmethod
    def validate_database_url(cls, v: str) -> str:
        if not v.startswith("postgresql"):
            raise ValueError("DATABASE_URL must start with 'postgresql'")
        return v

    @field_validator("IBKR_PORT", "SMTP_PORT")
    @classmethod
    def validate_port_range(cls, v: int) -> int:
        if not 1 <= v <= 65535:
            raise ValueError("Port must be between 1 and 65535")
        return v

    @field_validator("LOG_LEVEL")
    @classmethod
    def normalize_log_level(cls, v: str) -> str:
        return v.upper()

    @field_validator("ENVIRONMENT")
    @classmethod
    def normalize_environment(cls, v: str) -> str:
        return v.lower()

    @field_validator("JWT_SECRET_KEY")
    @classmethod
    def validate_jwt_secret_key(cls, v: str) -> str:
        if len(v) < 32:
            raise ValueError(
                "JWT_SECRET_KEY must be at least 32 characters. "
                "Generate one with: python -c 'import secrets; print(secrets.token_urlsafe(48))'"
            )
        return v


@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()


settings = get_settings()
