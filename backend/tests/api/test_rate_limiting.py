"""Tests for API rate limiting (SlowAPI, issue #87)."""

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIASGIMiddleware
from slowapi.util import get_remote_address

from app.core.rate_limits import GLOBAL_LIMIT, SCANNER_LIMIT, TRADING_LIMIT, limiter
from app.core.config import settings
from app.main import app as main_app


# ── Task 1: constants and limiter instance ────────────────────────────────────

def test_rate_limit_constants():
    assert GLOBAL_LIMIT == "100/minute"
    assert SCANNER_LIMIT == "5/minute"
    assert TRADING_LIMIT == "10/minute"


def test_limiter_is_limiter_instance():
    assert isinstance(limiter, Limiter)


def test_rate_limiting_enabled_setting_is_bool():
    assert isinstance(settings.RATE_LIMITING_ENABLED, bool)


# ── Task 2: middleware wiring ─────────────────────────────────────────────────

def _make_test_app() -> FastAPI:
    """Minimal FastAPI app with rate limiting wired identically to main.py."""
    test_limiter = Limiter(
        key_func=get_remote_address,
        default_limits=["100/minute"],
        storage_uri="memory://",
        headers_enabled=False,
    )
    test_app = FastAPI()
    test_app.state.limiter = test_limiter
    test_app.add_middleware(SlowAPIASGIMiddleware)

    @test_app.exception_handler(RateLimitExceeded)
    async def rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded):
        retry_after = exc.limit.limit.get_expiry() if exc.limit else 60
        return JSONResponse(
            status_code=429,
            headers={"Retry-After": str(retry_after)},
            content={"message": "Rate limit exceeded", "error_id": None, "retry_after": retry_after},
        )

    @test_app.get("/test-limited")
    @test_limiter.limit("1/minute")
    async def limited_route(request: Request):
        return {"ok": True}

    return test_app


def test_429_response_format():
    test_app = _make_test_app()
    client = TestClient(test_app, raise_server_exceptions=False)
    first = client.get("/test-limited")
    assert first.status_code == 200
    assert "X-RateLimit-Limit" not in first.headers
    second = client.get("/test-limited")
    assert second.status_code == 429
    body = second.json()
    assert body["message"] == "Rate limit exceeded"
    assert "error_id" in body
    assert body["error_id"] is None
    assert "retry_after" in body
    assert isinstance(body["retry_after"], int)
    assert "Retry-After" in second.headers
    assert "X-RateLimit-Limit" not in second.headers


def test_main_app_has_limiter_state():
    assert hasattr(main_app.state, "limiter")
    assert isinstance(main_app.state.limiter, Limiter)


def test_rate_limiting_disabled_is_noop():
    """When enabled=False, limiter is a true no-op."""
    disabled_limiter = Limiter(
        key_func=get_remote_address,
        headers_enabled=False,
        enabled=False,
    )
    test_app = FastAPI()
    test_app.state.limiter = disabled_limiter
    test_app.add_middleware(SlowAPIASGIMiddleware)

    @test_app.get("/test-disabled-limited")
    @disabled_limiter.limit("1/minute")
    async def limited_route(request: Request):
        return {"ok": True}

    client = TestClient(test_app, raise_server_exceptions=False)
    for _ in range(5):
        response = client.get("/test-disabled-limited")
        assert response.status_code == 200


# ── Task 6: exemption structural checks ──────────────────────────────────────

def test_health_check_is_exempt():
    from app.routers.health import health_check
    fn = health_check
    assert f"{fn.__module__}.{fn.__name__}" in limiter._exempt_routes


def test_scanner_websocket_is_exempt():
    from app.routers.scanner import scan_run_websocket
    fn = scan_run_websocket
    assert f"{fn.__module__}.{fn.__name__}" in limiter._exempt_routes


def test_live_data_websockets_are_exempt():
    from app.routers.live_data import (
        stock_live_websocket,
        watchlist_live_websocket,
        scan_task_websocket,
    )
    for fn in (stock_live_websocket, watchlist_live_websocket, scan_task_websocket):
        assert f"{fn.__module__}.{fn.__name__}" in limiter._exempt_routes


def test_system_websocket_is_exempt():
    from app.routers.system import system_tasks_websocket
    fn = system_tasks_websocket
    assert f"{fn.__module__}.{fn.__name__}" in limiter._exempt_routes


def test_tweets_websocket_is_exempt():
    from app.routers.tweets import tweet_feed_websocket
    fn = tweet_feed_websocket
    assert f"{fn.__module__}.{fn.__name__}" in limiter._exempt_routes


def test_news_websocket_is_exempt():
    from app.routers.news import news_websocket
    fn = news_websocket
    assert f"{fn.__module__}.{fn.__name__}" in limiter._exempt_routes
