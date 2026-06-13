"""Tests for Settings pool configuration defaults."""

import pytest
from pydantic import ValidationError

from app.core.config import Settings


def test_pool_size_default():
    s = Settings()
    assert s.DB_POOL_SIZE == 20


def test_pool_max_overflow_default():
    s = Settings()
    assert s.DB_POOL_MAX_OVERFLOW == 10


def test_pool_pre_ping_default():
    s = Settings()
    assert s.DB_POOL_PRE_PING is True


def test_pool_recycle_default():
    s = Settings()
    assert s.DB_POOL_RECYCLE == 3600


def test_pool_timeout_default():
    s = Settings()
    assert s.DB_POOL_TIMEOUT == 30


def test_pool_settings_are_correct_types():
    s = Settings()
    assert isinstance(s.DB_POOL_SIZE, int)
    assert isinstance(s.DB_POOL_MAX_OVERFLOW, int)
    assert isinstance(s.DB_POOL_PRE_PING, bool)
    assert isinstance(s.DB_POOL_RECYCLE, int)
    assert isinstance(s.DB_POOL_TIMEOUT, int)


def test_jwt_secret_key_empty_raises_validation_error():
    with pytest.raises(ValidationError):
        Settings(JWT_SECRET_KEY="")


def test_jwt_secret_key_short_raises_validation_error():
    with pytest.raises(ValidationError):
        Settings(JWT_SECRET_KEY="tooshort")


def test_jwt_secret_key_32_chars_accepted():
    s = Settings(JWT_SECRET_KEY="a" * 32)
    assert s.JWT_SECRET_KEY == "a" * 32


def test_redis_password_short_raises_validation_error():
    with pytest.raises(ValidationError):
        Settings(REDIS_PASSWORD="tooshort")


def test_redis_password_empty_raises_validation_error():
    with pytest.raises(ValidationError):
        Settings(REDIS_PASSWORD="")


def test_redis_url_built_with_authenticated_form():
    s = Settings(REDIS_PASSWORD="a" * 16)
    assert f":{'a' * 16}@" in s.REDIS_URL


def test_redis_url_not_double_injected():
    """model_validator must not inject the password a second time if REDIS_URL already has auth."""
    s1 = Settings(REDIS_PASSWORD="a" * 16)
    s2 = Settings(REDIS_PASSWORD="a" * 16, REDIS_URL=s1.REDIS_URL)
    assert s2.REDIS_URL == s1.REDIS_URL


def test_redis_url_password_special_chars_are_encoded():
    """Passwords with URL-special characters must be percent-encoded in REDIS_URL."""
    # '@' in password would break URL parsing if not encoded
    password = "a" * 14 + "@:"
    s = Settings(REDIS_PASSWORD=password)
    assert "%40%3A" in s.REDIS_URL
    assert f":{password}@" not in s.REDIS_URL
