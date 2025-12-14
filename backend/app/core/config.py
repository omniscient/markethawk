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
    
    # Redis / Celery
    REDIS_URL: str = os.getenv("REDIS_URL", "redis://redis:6379/0")
    
    # Application
    APP_NAME: str = "Stock Scanner API"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = os.getenv("DEBUG", "false").lower() == "true"
    
    # CORS
    CORS_ORIGINS: list = ["*"]


@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()


settings = get_settings()
