"""Unit tests for core/cache.py — all Redis calls are mocked."""
import json
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# get_redis
# ---------------------------------------------------------------------------

def test_get_redis_returns_none_when_no_url(monkeypatch):
    """If REDIS_URL is empty, get_redis() returns None."""
    import app.core.cache as cache_mod
    cache_mod.get_redis.cache_clear()
    monkeypatch.setattr("app.core.config.settings.REDIS_URL", "")
    result = cache_mod.get_redis()
    assert result is None
    cache_mod.get_redis.cache_clear()


def test_get_redis_returns_client_when_url_set(monkeypatch):
    """When REDIS_URL is set, get_redis() returns a redis.Redis instance."""
    import app.core.cache as cache_mod
    cache_mod.get_redis.cache_clear()
    monkeypatch.setattr("app.core.config.settings.REDIS_URL", "redis://localhost:6379/0")
    with patch("app.core.cache.redis.Redis") as mock_redis_cls:
        mock_redis_cls.from_url.return_value = MagicMock()
        result = cache_mod.get_redis()
        assert result is not None
        mock_redis_cls.from_url.assert_called_once()
    cache_mod.get_redis.cache_clear()


# ---------------------------------------------------------------------------
# get_cached — cache miss
# ---------------------------------------------------------------------------

def test_get_cached_calls_fn_on_cache_miss():
    """On a cache miss, get_cached calls fn() and returns its result."""
    from app.core.cache import get_cached
    mock_redis = MagicMock()
    mock_redis.get.return_value = None

    fn = MagicMock(return_value={"key": "value"})

    with patch("app.core.cache.get_redis", return_value=mock_redis):
        result = get_cached("test:key", 60, fn)

    assert result == {"key": "value"}
    fn.assert_called_once()


def test_get_cached_stores_json_on_cache_miss():
    """On cache miss, get_cached stores json.dumps(fn()) in Redis with the given TTL."""
    from app.core.cache import get_cached
    mock_redis = MagicMock()
    mock_redis.get.return_value = None

    fn = MagicMock(return_value={"key": "value"})

    with patch("app.core.cache.get_redis", return_value=mock_redis):
        get_cached("test:key", 60, fn)

    mock_redis.setex.assert_called_once_with("test:key", 60, json.dumps({"key": "value"}))


# ---------------------------------------------------------------------------
# get_cached — cache hit
# ---------------------------------------------------------------------------

def test_get_cached_returns_cached_value_on_hit():
    """On a cache hit, get_cached returns the deserialized value without calling fn."""
    from app.core.cache import get_cached
    mock_redis = MagicMock()
    mock_redis.get.return_value = json.dumps({"cached": True})

    fn = MagicMock()

    with patch("app.core.cache.get_redis", return_value=mock_redis):
        result = get_cached("test:key", 60, fn)

    assert result == {"cached": True}
    fn.assert_not_called()


# ---------------------------------------------------------------------------
# get_cached — Redis unavailable
# ---------------------------------------------------------------------------

def test_get_cached_falls_through_when_redis_none():
    """When get_redis() returns None, get_cached calls fn() without caching."""
    from app.core.cache import get_cached
    fn = MagicMock(return_value={"live": True})

    with patch("app.core.cache.get_redis", return_value=None):
        result = get_cached("test:key", 60, fn)

    assert result == {"live": True}
    fn.assert_called_once()


def test_get_cached_falls_through_on_redis_error():
    """When Redis.get() raises, get_cached calls fn() and returns without caching."""
    from app.core.cache import get_cached
    mock_redis = MagicMock()
    mock_redis.get.side_effect = Exception("connection refused")

    fn = MagicMock(return_value={"live": True})

    with patch("app.core.cache.get_redis", return_value=mock_redis):
        result = get_cached("test:key", 60, fn)

    assert result == {"live": True}
    fn.assert_called_once()


# ---------------------------------------------------------------------------
# invalidate
# ---------------------------------------------------------------------------

def test_invalidate_calls_delete():
    """invalidate() calls Redis.delete() with the given key."""
    from app.core.cache import invalidate
    mock_redis = MagicMock()

    with patch("app.core.cache.get_redis", return_value=mock_redis):
        invalidate("mh:universe:list")

    mock_redis.delete.assert_called_once_with("mh:universe:list")


def test_invalidate_is_noop_when_redis_none():
    """invalidate() does nothing when Redis is unavailable."""
    from app.core.cache import invalidate
    with patch("app.core.cache.get_redis", return_value=None):
        invalidate("mh:universe:list")  # must not raise


def test_invalidate_is_noop_on_redis_error():
    """invalidate() swallows Redis errors."""
    from app.core.cache import invalidate
    mock_redis = MagicMock()
    mock_redis.delete.side_effect = Exception("timeout")

    with patch("app.core.cache.get_redis", return_value=mock_redis):
        invalidate("mh:universe:list")  # must not raise


# ---------------------------------------------------------------------------
# invalidate_pattern
# ---------------------------------------------------------------------------

def test_invalidate_pattern_scans_and_deletes():
    """invalidate_pattern() scans for matching keys and deletes each one."""
    from app.core.cache import invalidate_pattern
    mock_redis = MagicMock()
    mock_redis.scan_iter.return_value = ["mh:stocks:details:AAPL", "mh:stocks:details:MSFT"]

    with patch("app.core.cache.get_redis", return_value=mock_redis):
        invalidate_pattern("mh:stocks:details:*")

    mock_redis.scan_iter.assert_called_once_with("mh:stocks:details:*")
    assert mock_redis.delete.call_count == 2


def test_invalidate_pattern_is_noop_when_redis_none():
    """invalidate_pattern() does nothing when Redis is unavailable."""
    from app.core.cache import invalidate_pattern
    with patch("app.core.cache.get_redis", return_value=None):
        invalidate_pattern("mh:*")  # must not raise


# ---------------------------------------------------------------------------
# cache_response decorator
# ---------------------------------------------------------------------------

def test_cache_response_wraps_handler():
    """@cache_response delegates to get_cached on invocation."""
    from app.core.cache import cache_response
    mock_redis = MagicMock()
    mock_redis.get.return_value = None

    @cache_response("mh:test:key", 300)
    def handler():
        return [{"item": 1}]

    with patch("app.core.cache.get_redis", return_value=mock_redis):
        result = handler()

    assert result == [{"item": 1}]


def test_cache_response_returns_cached_value():
    """@cache_response returns cached value without calling the handler body."""
    from app.core.cache import cache_response

    call_count = {"n": 0}

    @cache_response("mh:test:key", 300)
    def handler():
        call_count["n"] += 1
        return [{"item": 1}]

    mock_redis = MagicMock()
    mock_redis.get.return_value = json.dumps([{"item": 99}])

    with patch("app.core.cache.get_redis", return_value=mock_redis):
        result = handler()

    assert result == [{"item": 99}]
    assert call_count["n"] == 0
