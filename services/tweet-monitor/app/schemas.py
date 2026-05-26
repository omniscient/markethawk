from datetime import datetime
from typing import Any, Optional
from pydantic import BaseModel


class PollSummary(BaseModel):
    accounts_polled: int
    tweets_found: int
    tweets_new: int
    tweets_promoted: int
    duration_ms: float
    errors: list[str] = []


class AccountStatus(BaseModel):
    id: int
    handle: str
    display_name: str
    platform: str
    enabled: bool
    last_poll_at: Optional[datetime]
    last_tweet_id: Optional[str]
    poll_interval_seconds: int


class AccountCreate(BaseModel):
    handle: str
    display_name: str
    platform: str = "x"
    poll_interval_seconds: int = 45
    enabled: bool = True
    classification_config: dict[str, Any] = {}


class HealthResponse(BaseModel):
    healthy: bool
    browser: bool
    browser_age_seconds: int
    db: bool
    redis: bool
    auth_expired: bool


class StatusResponse(BaseModel):
    accounts: list[AccountStatus]
    health: HealthResponse
