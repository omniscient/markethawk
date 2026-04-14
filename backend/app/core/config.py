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
    # Default is "production" so that an unset env var NEVER leaks stack traces.
    ENVIRONMENT: str = os.getenv("ENVIRONMENT", "production").lower()

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

    # Dedicated clientId for the order manager (auto-trading).
    # Must differ from IBKR_CLIENT_ID and from the live scanner's clientId (5).
    IBKR_TRADING_CLIENT_ID: int = int(os.getenv("IBKR_TRADING_CLIENT_ID", "11"))

    # ── Email / SMTP (Alert Notifications) ────────────────────────────────
    # Use Gmail + an App Password (not your real Gmail password).
    # Generate one at: https://myaccount.google.com/apppasswords
    SMTP_HOST: str = os.getenv("SMTP_HOST", "smtp.gmail.com")
    SMTP_PORT: int = int(os.getenv("SMTP_PORT", "587"))
    SMTP_USER: str = os.getenv("SMTP_USER", "")
    SMTP_PASSWORD: str = os.getenv("SMTP_PASSWORD", "")
    SMTP_FROM_EMAIL: str = os.getenv("SMTP_FROM_EMAIL", "MarketHawk Alerts <noreply@example.com>")

    # ── Web Push / VAPID (Browser Push Notifications) ─────────────────────
    # Generate a key pair once with: python -c "from py_vapid import Vapid; v=Vapid(); v.generate_keys(); print('PRIV:', v.private_pem().decode()); print('PUB:', v.public_key)"
    # Or use the /api/alerts/push/generate-keys endpoint on first run.
    VAPID_PRIVATE_KEY: str = os.getenv("VAPID_PRIVATE_KEY", "")
    VAPID_PUBLIC_KEY: str = os.getenv("VAPID_PUBLIC_KEY", "")
    # Must be a mailto: or https: URL identifying the push sender
    VAPID_CLAIMS_EMAIL: str = os.getenv("VAPID_CLAIMS_EMAIL", "mailto:admin@example.com")


@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()


settings = get_settings()
