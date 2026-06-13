"""
Pydantic schemas for alert-rule channel configuration validation.
"""

from typing import Optional

from pydantic import BaseModel


class ChannelConfig(BaseModel):
    model_config = {"extra": "forbid"}

    email: Optional[str] = None
    google_chat_webhook: Optional[str] = None
    webhook_url: Optional[str] = None
