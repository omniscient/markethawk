import os

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-unit-tests-only-32chars!")

# Clear cached settings so the env var above is picked up
from app.core.config import get_settings

get_settings.cache_clear()

from app.core.auth import (
    create_access_token,
    create_refresh_token,
    hash_password,
    verify_password,
)
from jose import jwt


def test_hash_and_verify():
    hashed = hash_password("mysecret")
    assert hashed != "mysecret"
    assert verify_password("mysecret", hashed)
    assert not verify_password("wrong", hashed)


def test_create_access_token_is_valid_jwt():
    settings = get_settings()
    token = create_access_token("user-123")
    payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=["HS256"])
    assert payload["sub"] == "user-123"
    assert "exp" in payload


def test_create_refresh_token_is_hex():
    token = create_refresh_token()
    assert len(token) == 64
    int(token, 16)  # raises ValueError if not hex
