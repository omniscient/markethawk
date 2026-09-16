"""
News Preference schemas for API requests and responses.
"""

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict

from app.schemas.common import Ticker


class NewsPreferenceBase(BaseModel):
    tracked_tickers: List[Ticker] = []
    tracked_universes: List[int] = []
    refresh_interval_minutes: Optional[int] = 5


class NewsPreferenceCreate(NewsPreferenceBase):
    model_config = ConfigDict(extra="forbid")


class NewsPreferenceUpdate(NewsPreferenceBase):
    model_config = ConfigDict(extra="forbid")


class NewsPreferenceResponse(NewsPreferenceBase):
    id: int
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


from typing import Optional  # noqa: E402


class NewsArticleResponse(BaseModel):
    id: int
    title: str
    author: Optional[str] = None
    published_utc: datetime
    article_url: str
    image_url: Optional[str] = None
    description: Optional[str] = None
    provider: Optional[str] = None
    tickers: Optional[List[str]] = []

    model_config = ConfigDict(from_attributes=True)
