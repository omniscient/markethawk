import secrets
import uuid
from datetime import datetime, timedelta, timezone

import bcrypt
from fastapi import (
    Cookie,
    Depends,
    HTTPException,
    WebSocket,
    WebSocketException,
    status,
)
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_db
from app.models.user import User


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode(), hashed.encode())


def create_access_token(user_id: str) -> str:
    settings = get_settings()
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES
    )
    return jwt.encode(
        {"sub": user_id, "exp": expire},
        settings.JWT_SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM,
    )


def create_refresh_token() -> str:
    return secrets.token_hex(32)


def _resolve_user_from_token(token: str, db: Session) -> User | None:
    """Decode JWT and fetch the active user. Returns None on any auth failure.

    JWT errors and malformed sub/UUID return None. DB errors propagate so real
    outages are not silently converted into auth rejections.
    """
    settings = get_settings()
    try:
        payload = jwt.decode(
            token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM]
        )
    except JWTError:
        return None
    user_id: str | None = payload.get("sub")
    if not user_id:
        return None
    try:
        uid = uuid.UUID(user_id)
    except (ValueError, AttributeError):
        return None
    return db.execute(
        select(User).where(User.id == uid, User.is_active == True)
    ).scalar_one_or_none()


def get_current_user(
    access_token: str | None = Cookie(default=None),
    db: Session = Depends(get_db),
) -> User:
    if not access_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    user = _resolve_user_from_token(access_token, db)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    return user


def ws_get_current_user(
    websocket: WebSocket,
    db: Session = Depends(get_db),
) -> User:
    """WebSocket counterpart to get_current_user.

    Reads access_token from the handshake cookies. Raises WebSocketException(1008)
    on any auth failure so the connection is rejected before accept() is called.
    """
    token = websocket.cookies.get("access_token")
    if not token:
        raise WebSocketException(code=1008, reason="Not authenticated")
    user = _resolve_user_from_token(token, db)
    if not user:
        raise WebSocketException(code=1008, reason="Not authenticated")
    return user
