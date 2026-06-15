"""
Application configuration using pydantic-settings.
"""

from functools import lru_cache
from urllib.parse import quote

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(env_file=".env", case_sensitive=True)

    # Database - REQUIRED
    DATABASE_URL: str

    # Polygon.io API - REQUIRED
    POLYGON_API_KEY: str
    POLYGON_DELAYED: bool = True
    LIVE_WEBSOCKET_ENABLED: bool = True

    # Redis / Celery - REDIS_PASSWORD is REQUIRED (no default): an omitted value
    # must fail startup, not silently fall back to an unauthenticated URL (F-NET-01).
    REDIS_PASSWORD: str
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
    # API docs (Swagger/ReDoc/openapi.json) — default False (secure-by-default).
    # Set to true in docker-compose.override.yml for local dev. Never enable in production.
    DOCS_ENABLED: bool = False

    # Connection pool
    DB_POOL_SIZE: int = 20
    DB_POOL_MAX_OVERFLOW: int = 10
    DB_POOL_PRE_PING: bool = True
    DB_POOL_RECYCLE: int = 3600
    DB_POOL_TIMEOUT: int = 30

    # ── Outbound HTTP timeouts ─────────────────────────────────────────
    # Applied to the Polygon RESTClient (connect and read phases).
    POLYGON_CONNECT_TIMEOUT: float = 10.0
    POLYGON_READ_TIMEOUT: float = 10.0

    # ── Circuit-breaker parameters ─────────────────────────────────────
    # Polygon breaker: open after 5 consecutive failures; retry after 60 s.
    POLYGON_CB_FAIL_MAX: int = 5
    POLYGON_CB_RESET_TIMEOUT: int = 60
    # IBKR breaker: open after 3 consecutive failures; retry after 120 s.
    IBKR_CB_FAIL_MAX: int = 3
    IBKR_CB_RESET_TIMEOUT: int = 120

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

    # Scanner SLO thresholds — documented in ENV_VARIABLES.md
    SCAN_DURATION_SLO_SECONDS: int = 120
    SCAN_STALENESS_SLO_SECONDS: int = 900

    # ── WebSocket resource limits ──────────────────────────────────────────
    # Single-process in-memory counters (see app/core/ws_limits.py).
    # For multi-replica deployments, migrate counters to Redis.
    WS_MAX_CONNECTIONS_PER_USER: int = 10
    WS_MAX_CONNECTIONS_GLOBAL: int = 100
    # Idle timeout for all WS endpoints except scan-task (seconds).
    WS_IDLE_TIMEOUT_SECONDS: int = 300
    # Idle timeout for the scan-task WS (seconds); scan tasks produce no events for extended periods.
    WS_SCAN_TASK_IDLE_TIMEOUT_SECONDS: int = 1800
    # Absolute lifetime cap for all WS connections (seconds).
    WS_MAX_LIFETIME_SECONDS: int = 28800

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

    @field_validator("REDIS_PASSWORD")
    @classmethod
    def validate_redis_password(cls, v: str) -> str:
        if not v:
            raise ValueError(
                "REDIS_PASSWORD is required — Redis runs with requirepass and an "
                "unauthenticated connection is refused. "
                "Generate one with: python -c 'import secrets; print(secrets.token_urlsafe(24))'"
            )
        if len(v) < 16:
            raise ValueError(
                "REDIS_PASSWORD must be at least 16 characters. "
                "Generate one with: python -c 'import secrets; print(secrets.token_urlsafe(24))'"
            )
        return v

    @model_validator(mode="after")
    def _build_redis_url(self) -> "Settings":
        if self.REDIS_PASSWORD:
            if "://" not in self.REDIS_URL:
                raise ValueError("REDIS_URL must include a scheme (e.g. redis://...)")
            scheme, rest = self.REDIS_URL.split("://", 1)
            if "@" in rest:
                rest = rest.split("@", 1)[1]
            encoded = quote(self.REDIS_PASSWORD, safe="")
            self.REDIS_URL = f"{scheme}://:{encoded}@{rest}"
        return self

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
