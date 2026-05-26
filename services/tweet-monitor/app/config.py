from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql://postgres:postgres@postgres:5432/stockscanner"
    redis_url: str = "redis://redis:6379/0"
    seq_url: str = "http://seq:5341"
    log_level: str = "INFO"

    # X authentication (cookie-based, rotate ~every 30 days)
    x_auth_token: str = ""
    x_csrf_token: str = ""

    # Classification thresholds
    promotion_threshold: float = 0.7

    # Browser lifecycle
    browser_max_age_minutes: int = 30
    browser_max_memory_mb: int = 512
    poll_timeout_seconds: int = 25

    # Exponential backoff
    backoff_initial_seconds: int = 90
    backoff_max_seconds: int = 600

    # Fallback internal scheduler (disabled by default — Celery beat is primary)
    fallback_timer_enabled: bool = False
    fallback_timer_seconds: int = 60

    class Config:
        env_file = ".env"
        case_sensitive = False


settings = Settings()
