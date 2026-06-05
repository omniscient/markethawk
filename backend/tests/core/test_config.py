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
