"""
PushSubscription model — stores browser Web Push subscriptions.
One row per browser/device that has granted push permission.
"""

from sqlalchemy import Column, DateTime, Integer, String, Text

from app.core.database import Base
from app.utils.time import utc_now


class PushSubscription(Base):
    """A browser's Web Push subscription (endpoint + keys)."""

    __tablename__ = "push_subscriptions"

    id = Column(Integer, primary_key=True, index=True)

    # The unique push endpoint URL provided by the browser
    endpoint = Column(Text, nullable=False, unique=True, index=True)

    # ECDH public key (base64url) from the browser's PushSubscription.keys.p256dh
    p256dh = Column(Text, nullable=False)

    # Authentication secret (base64url) from the browser's PushSubscription.keys.auth
    auth = Column(Text, nullable=False)

    # Optional: browser user-agent for display
    user_agent = Column(String(500), nullable=True)

    created_at = Column(
        DateTime,
        default=utc_now,
    )
