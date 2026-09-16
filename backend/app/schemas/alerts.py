"""
Pydantic schemas for alert-rule channel configuration validation.
"""

from typing import Optional

from pydantic import BaseModel, ConfigDict, EmailStr

from app.schemas.common import HttpsUrl


class ChannelConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: Optional[EmailStr] = None
    google_chat_webhook: Optional[HttpsUrl] = None
    webhook_url: Optional[HttpsUrl] = None
