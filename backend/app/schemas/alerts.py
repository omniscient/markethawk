"""
Pydantic schemas for alert-rule channel configuration validation.
"""

from typing import Optional

from pydantic import BaseModel, EmailStr, HttpUrl


class ChannelConfig(BaseModel):
    model_config = {"extra": "forbid"}

    email: Optional[EmailStr] = None
    google_chat_webhook: Optional[HttpUrl] = None
    webhook_url: Optional[HttpUrl] = None
