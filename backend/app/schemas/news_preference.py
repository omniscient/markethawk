"""
News Preference schemas for API requests and responses.
"""
from pydantic import BaseModel, ConfigDict
from typing import List, Optional
from datetime import datetime

class NewsPreferenceBase(BaseModel):
    tracked_tickers: List[str] = []
    tracked_universes: List[int] = []
    refresh_interval_minutes: Optional[int] = 5

class NewsPreferenceCreate(NewsPreferenceBase):
    pass

class NewsPreferenceUpdate(NewsPreferenceBase):
    pass

class NewsPreferenceResponse(NewsPreferenceBase):
    id: int
    created_at: datetime
    updated_at: datetime
    
    model_config = ConfigDict(from_attributes=True)

from typing import Optional

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
