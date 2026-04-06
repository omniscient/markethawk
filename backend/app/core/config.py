"""
Application configuration using pydantic-settings.
"""

from functools import lru_cache
from typing import Optional
import os
from dotenv import load_dotenv
from pathlib import Path

# Load .env from root directory
root_dir = Path(__file__).resolve().parent.parent.parent.parent
env_path = root_dir / ".env"
load_dotenv(dotenv_path=env_path)


class Settings:
    """Application settings loaded from environment variables."""
    
    # Database
    DATABASE_URL: str = os.getenv(
        "DATABASE_URL", 
        "postgresql://username:password@localhost/stockscanner"
    )
    
    # Polygon.io API
    POLYGON_API_KEY: str = os.getenv("POLYGON_API_KEY", "")
    POLYGON_DELAYED: bool = os.getenv("POLYGON_DELAYED", "true").lower() == "true"
    
    # Redis / Celery
    REDIS_URL: str = os.getenv("REDIS_URL", "redis://redis:6379/0")
    
    # Application
    APP_NAME: str = "Stock Scanner API"
    APP_VERSION: str = "1.0.0"
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO").upper()

    # Environment: "development" returns full stack traces to clients.
    # "production" hides internals and only returns error_id.
    ENVIRONMENT: str = os.getenv("ENVIRONMENT", "development").lower()

    # Error Tracking
    # SEQ_URL: base URL for the Seq container (no trailing slash).
    # Set to an empty string or "disabled" to fall back to stdout-only logging.
    SEQ_URL: str = os.getenv("SEQ_URL", "http://seq:5341")

    # CORS
    CORS_ORIGINS: list = ["*"]

    # ── Interactive Brokers (IBKR) ─────────────────────────────────────
    # Host/port for TWS or IB Gateway:
    #   TWS live:    127.0.0.1:7496
    #   TWS paper:   127.0.0.1:7497
    #   Gateway live: 127.0.0.1:4001
    #   Gateway paper: 127.0.0.1:4002
    IBKR_HOST: str = os.getenv("IBKR_HOST", "127.0.0.1")
    IBKR_PORT: int = int(os.getenv("IBKR_PORT", "7496"))
    # Each API connection needs a unique clientId.
    # Keep this different from any other apps connecting to TWS simultaneously.
    IBKR_CLIENT_ID: int = int(os.getenv("IBKR_CLIENT_ID", "10"))


@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()


settings = get_settings()
