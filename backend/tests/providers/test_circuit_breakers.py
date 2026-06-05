"""
Tests for circuit-breaker integration in MassiveDataProvider and IBKRDataProvider.
"""

import asyncio
from unittest.mock import MagicMock, patch

import pybreaker
import pytest

from app.exceptions import ProviderError

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_massive():
    from app.providers.massive import MassiveDataProvider

    p = MassiveDataProvider.__new__(MassiveDataProvider)
    p._client = MagicMock()
    return p


def _fresh_breaker(fail_max: int = 3) -> pybreaker.CircuitBreaker:
    return pybreaker.CircuitBreaker(fail_max=fail_max, reset_timeout=60)


# ---------------------------------------------------------------------------
# Settings: circuit-breaker parameters are tunable via env vars
# ---------------------------------------------------------------------------


class TestCircuitBreakerSettings:
    def test_polygon_cb_defaults(self):
        from app.core.config import Settings

        s = Settings(
            DATABASE_URL="postgresql://t:t@localhost/t",
            POLYGON_API_KEY="key",
        )
        assert s.POLYGON_CB_FAIL_MAX == 5
        assert s.POLYGON_CB_RESET_TIMEOUT == 60
        assert s.POLYGON_CONNECT_TIMEOUT == 10.0
        assert s.POLYGON_READ_TIMEOUT == 10.0

    def test_ibkr_cb_defaults(self):
        from app.core.config import Settings

        s = Settings(
            DATABASE_URL="postgresql://t:t@localhost/t",
            POLYGON_API_KEY="key",
        )
        assert s.IBKR_CB_FAIL_MAX == 3
        assert s.IBKR_CB_RESET_TIMEOUT == 120

    def test_polygon_cb_params_overrideable(self):
        from app.core.config import Settings

        s = Settings(
            DATABASE_URL="postgresql://t:t@localhost/t",
            POLYGON_API_KEY="key",
            POLYGON_CB_FAIL_MAX=10,
            POLYGON_CB_RESET_TIMEOUT=30,
        )
        assert s.POLYGON_CB_FAIL_MAX == 10
        assert s.POLYGON_CB_RESET_TIMEOUT == 30

    def test_ibkr_cb_params_overrideable(self):
        from app.core.config import Settings

        s = Settings(
            DATABASE_URL="postgresql://t:t@localhost/t",
            POLYGON_API_KEY="key",
            IBKR_CB_FAIL_MAX=7,
            IBKR_CB_RESET_TIMEOUT=90,
        )
        assert s.IBKR_CB_FAIL_MAX == 7
        assert s.IBKR_CB_RESET_TIMEOUT == 90


# ---------------------------------------------------------------------------
# MassiveDataProvider: CircuitBreakerError → ProviderError(is_retryable=False)
# ---------------------------------------------------------------------------


class TestMassiveProviderCircuitBreaker:
    def test_get_bars_open_circuit_raises_non_retryable_provider_error(self):
        p = _make_massive()
        open_breaker = _fresh_breaker(fail_max=2)

        # Exhaust fail_max to open the circuit
        def always_fail(*_a, **_kw):
            raise RuntimeError("polygon down")

        for _ in range(open_breaker.fail_max):
            try:
                open_breaker.call(always_fail)
            except Exception:
                pass
        assert open_breaker.current_state == "open"

        with patch("app.providers.massive.POLYGON_BREAKER", open_breaker):
            with pytest.raises(ProviderError) as exc_info:
                p.get_bars("AAPL", "minute", 1, "2026-01-01", "2026-01-31")
        err = exc_info.value
        assert err.is_retryable is False
        assert err.provider == "massive"

    def test_get_bars_success_path_uses_impl(self):
        p = _make_massive()
        mock_agg = MagicMock()
        mock_agg.timestamp = 1_700_000_000_000
        mock_agg.open = mock_agg.high = mock_agg.low = mock_agg.close = 100.0
        mock_agg.volume = 1000
        mock_agg.vwap = 100.0
        mock_agg.transactions = 10
        p._client.get_aggs.return_value = [mock_agg]

        result = p.get_bars("AAPL", "minute", 1, "2026-01-01", "2026-01-31")
        assert len(result) == 1
        assert result[0]["close"] == 100.0

    def test_get_snapshots_open_circuit_returns_empty_list(self):
        p = _make_massive()
        open_breaker = _fresh_breaker(fail_max=2)
        for _ in range(open_breaker.fail_max):
            try:
                open_breaker.call(lambda: (_ for _ in ()).throw(RuntimeError()))
            except Exception:
                pass

        with patch("app.providers.massive.POLYGON_BREAKER", open_breaker):
            result = p.get_snapshots()
        assert result == []

    def test_get_ticker_details_open_circuit_returns_empty_dict(self):
        p = _make_massive()
        open_breaker = _fresh_breaker(fail_max=2)
        for _ in range(open_breaker.fail_max):
            try:
                open_breaker.call(lambda: (_ for _ in ()).throw(RuntimeError()))
            except Exception:
                pass

        with patch("app.providers.massive.POLYGON_BREAKER", open_breaker):
            result = p.get_ticker_details("AAPL")
        assert result == {}

    def test_restclient_receives_timeout_settings(self):
        from app.core.config import Settings

        s = Settings(
            DATABASE_URL="postgresql://t:t@localhost/t",
            POLYGON_API_KEY="test-key",
            POLYGON_CONNECT_TIMEOUT=5.0,
            POLYGON_READ_TIMEOUT=15.0,
        )
        with patch("app.providers.massive.settings", s):
            with patch("app.providers.massive.RESTClient") as mock_cls:
                from app.providers.massive import MassiveDataProvider

                p = MassiveDataProvider.__new__(MassiveDataProvider)
                p._init_client()
        mock_cls.assert_called_once_with(
            "test-key",
            connect_timeout=5.0,
            read_timeout=15.0,
        )


# ---------------------------------------------------------------------------
# IBKRDataProvider: CircuitBreakerError → ProviderError(is_retryable=False)
# ---------------------------------------------------------------------------


class TestIBKRProviderCircuitBreaker:
    def _open_breaker(self, fail_max: int = 2) -> pybreaker.CircuitBreaker:
        breaker = _fresh_breaker(fail_max=fail_max)
        for _ in range(breaker.fail_max):
            try:
                breaker.call(lambda: (_ for _ in ()).throw(RuntimeError()))
            except Exception:
                pass
        return breaker

    def test_get_futures_contracts_open_circuit_raises_non_retryable(self):
        try:
            from ib_insync import IB  # noqa: F401

            ib_available = True
        except ImportError:
            ib_available = False

        if not ib_available:
            pytest.skip("ib_insync not installed")

        from app.providers.ibkr import IBKRDataProvider

        p = IBKRDataProvider.__new__(IBKRDataProvider)
        p._ib = None
        p._connected = False

        open_breaker = self._open_breaker()
        assert open_breaker.current_state == "open"

        with patch("app.providers.ibkr.IBKR_BREAKER", open_breaker):
            with pytest.raises(ProviderError) as exc_info:
                asyncio.get_event_loop().run_until_complete(
                    p.get_futures_contracts("ES", "CME")
                )
        err = exc_info.value
        assert err.is_retryable is False
        assert err.provider == "ibkr"

    def test_get_futures_bars_open_circuit_raises_non_retryable(self):
        try:
            from ib_insync import IB  # noqa: F401

            ib_available = True
        except ImportError:
            ib_available = False

        if not ib_available:
            pytest.skip("ib_insync not installed")

        from app.providers.ibkr import IBKRDataProvider

        p = IBKRDataProvider.__new__(IBKRDataProvider)
        p._ib = None
        p._connected = False

        open_breaker = self._open_breaker()

        with patch("app.providers.ibkr.IBKR_BREAKER", open_breaker):
            with pytest.raises(ProviderError) as exc_info:
                asyncio.get_event_loop().run_until_complete(
                    p.get_futures_bars("ES", "CME", "20260321")
                )
        err = exc_info.value
        assert err.is_retryable is False
        assert err.provider == "ibkr"

    @pytest.mark.asyncio
    async def test_ibkr_call_async_happy_path(self):
        """Verifies pybreaker.call_async correctly awaits a coroutine."""
        breaker = _fresh_breaker(fail_max=5)

        async def async_fn(x: int) -> int:
            return x * 2

        result = await breaker.call_async(async_fn, 21)
        assert result == 42
        assert breaker.fail_counter == 0
        assert breaker.current_state == "closed"
