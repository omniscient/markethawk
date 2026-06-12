"""Unit tests for check_health() — runtime auth state."""
import asyncio
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from unittest.mock import patch

import app.state as state
from app.health import check_health


def _run(coro):
    return asyncio.run(coro)


def _mock_externals():
    return [
        patch("app.health._check_db", return_value=True),
        patch("app.health._check_redis", return_value=True),
        patch("app.health.browser_manager"),
    ]


def test_auth_expired_false_when_state_auth_ok_true():
    state.auth_ok = True
    patches = _mock_externals()
    with patches[0], patches[1], patches[2] as mock_bm:
        mock_bm.is_running = True
        mock_bm.age_seconds = 10.0
        result = _run(check_health())
    assert result["auth_expired"] is False


def test_auth_expired_true_when_state_auth_ok_false():
    state.auth_ok = False
    patches = _mock_externals()
    with patches[0], patches[1], patches[2] as mock_bm:
        mock_bm.is_running = True
        mock_bm.age_seconds = 10.0
        result = _run(check_health())
    assert result["auth_expired"] is True
    assert result["healthy"] is False


def test_healthy_is_false_when_auth_expired():
    state.auth_ok = False
    patches = _mock_externals()
    with patches[0], patches[1], patches[2] as mock_bm:
        mock_bm.is_running = True
        mock_bm.age_seconds = 10.0
        result = _run(check_health())
    assert result["healthy"] is False


def test_healthy_is_true_when_all_ok():
    state.auth_ok = True
    patches = _mock_externals()
    with patches[0], patches[1], patches[2] as mock_bm:
        mock_bm.is_running = True
        mock_bm.age_seconds = 10.0
        result = _run(check_health())
    assert result["healthy"] is True
