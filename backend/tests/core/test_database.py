"""Tests that create_engine() pool attributes match settings values."""

from app.core.database import engine
from app.core.config import settings


def test_engine_pool_size_matches_settings():
    assert engine.pool.size() == settings.DB_POOL_SIZE


def test_engine_pool_max_overflow_matches_settings():
    assert engine.pool._max_overflow == settings.DB_POOL_MAX_OVERFLOW


def test_engine_pre_ping_matches_settings():
    assert engine.pool._pre_ping == settings.DB_POOL_PRE_PING


def test_engine_pool_recycle_matches_settings():
    assert engine.pool._recycle == settings.DB_POOL_RECYCLE


def test_engine_pool_timeout_matches_settings():
    assert engine.pool._timeout == settings.DB_POOL_TIMEOUT
