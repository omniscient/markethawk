import uuid
from datetime import datetime

import redis
from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.auth import (
    create_access_token,
    create_refresh_token,
    get_current_user,
    hash_password,
    verify_password,
)
from app.core.config import get_settings
from app.core.database import get_db
from app.core.rate_limits import AUTH_LIMIT, limiter
from app.models.user import User

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _get_redis():
    settings = get_settings()
    return redis.from_url(settings.REDIS_URL, decode_responses=True)


def _set_auth_cookies(
    response: Response, access_token: str, refresh_token: str
) -> None:
    settings = get_settings()
    response.set_cookie(
        key="access_token",
        value=access_token,
        httponly=True,
        samesite="strict",
        secure=settings.COOKIE_SECURE,
        max_age=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        path="/",
    )
    response.set_cookie(
        key="refresh_token",
        value=refresh_token,
        httponly=True,
        samesite="strict",
        secure=settings.COOKIE_SECURE,
        max_age=settings.REFRESH_TOKEN_EXPIRE_DAYS * 86400,
        path="/api/auth/refresh",
    )


class RegisterRequest(BaseModel):
    username: str
    password: str


class LoginRequest(BaseModel):
    username: str
    password: str


class UserResponse(BaseModel):
    id: uuid.UUID
    username: str
    created_at: datetime


@router.get("/status")
def auth_status(db: Session = Depends(get_db)):
    count = db.execute(select(func.count()).select_from(User)).scalar_one()
    return {"bootstrapped": count > 0}


@router.post("/register", response_model=UserResponse)
@limiter.limit(AUTH_LIMIT)
def register(request: Request, body: RegisterRequest, db: Session = Depends(get_db)):
    count = db.execute(select(func.count()).select_from(User)).scalar_one()
    if count > 0:
        raise HTTPException(
            status_code=403, detail="Registration is closed — a user already exists"
        )
    user = User(username=body.username, password_hash=hash_password(body.password))
    db.add(user)
    db.commit()
    db.refresh(user)
    return UserResponse(id=user.id, username=user.username, created_at=user.created_at)


@router.post("/login")
@limiter.limit(AUTH_LIMIT)
def login(request: Request, body: LoginRequest, db: Session = Depends(get_db)):
    user = db.execute(
        select(User).where(User.username == body.username, User.is_active == True)
    ).scalar_one_or_none()
    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials"
        )

    access_token = create_access_token(str(user.id))
    refresh_token = create_refresh_token()

    settings = get_settings()
    r = _get_redis()
    r.setex(
        f"auth:refresh:{refresh_token}",
        settings.REFRESH_TOKEN_EXPIRE_DAYS * 86400,
        str(user.id),
    )

    response = JSONResponse(content={"message": "Logged in"})
    _set_auth_cookies(response, access_token, refresh_token)
    return response


@router.post("/logout")
def logout(
    refresh_token: str | None = Cookie(default=None),
    _current_user: User = Depends(get_current_user),
):
    if refresh_token:
        r = _get_redis()
        r.delete(f"auth:refresh:{refresh_token}")

    response = JSONResponse(content={"message": "Logged out"})
    response.delete_cookie("access_token", path="/")
    response.delete_cookie("refresh_token", path="/api/auth/refresh")
    return response


@router.post("/refresh")
@limiter.limit(AUTH_LIMIT)
def refresh(request: Request, refresh_token: str | None = Cookie(default=None)):
    if not refresh_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)

    r = _get_redis()
    user_id = r.get(f"auth:refresh:{refresh_token}")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
        )

    settings = get_settings()
    new_access_token = create_access_token(user_id)
    new_refresh_token = create_refresh_token()

    r.delete(f"auth:refresh:{refresh_token}")
    r.setex(
        f"auth:refresh:{new_refresh_token}",
        settings.REFRESH_TOKEN_EXPIRE_DAYS * 86400,
        user_id,
    )

    response = JSONResponse(content={"message": "Token refreshed"})
    _set_auth_cookies(response, new_access_token, new_refresh_token)
    return response


@router.get("/me", response_model=UserResponse)
def me(current_user: User = Depends(get_current_user)):
    return UserResponse(
        id=current_user.id,
        username=current_user.username,
        created_at=current_user.created_at,
    )
