"""Tests for the MarketHawk exception hierarchy."""

import pytest
from app.exceptions import MarketHawkError, ScanError, DataFetchError, ProviderError


def test_markethawk_error_is_base():
    exc = MarketHawkError("base error")
    assert isinstance(exc, Exception)
    assert not exc.is_retryable
    assert str(exc) == "base error"


def test_markethawk_error_context_in_str():
    exc = MarketHawkError("base error", ticker="AAPL", provider="massive")
    assert "AAPL" in str(exc)
    assert "massive" in str(exc)


def test_markethawk_error_retryable():
    exc = MarketHawkError("transient", is_retryable=True)
    assert exc.is_retryable is True


def test_scan_error_is_markethawk_error():
    exc = ScanError("scan failed", scanner_type="pre_market_volume_spike", ticker="AAPL")
    assert isinstance(exc, MarketHawkError)
    assert exc.scanner_type == "pre_market_volume_spike"
    assert exc.ticker == "AAPL"
    assert not exc.is_retryable


def test_data_fetch_error_is_markethawk_error():
    exc = DataFetchError(
        "polygon unavailable",
        provider="massive",
        symbol="AAPL",
        is_retryable=True,
    )
    assert isinstance(exc, MarketHawkError)
    assert exc.provider == "massive"
    assert exc.symbol == "AAPL"
    assert exc.is_retryable is True


def test_provider_error_is_markethawk_error():
    exc = ProviderError(
        "IBKR connection refused",
        provider="ibkr",
        endpoint="connect",
        status_code=503,
        is_retryable=True,
    )
    assert isinstance(exc, MarketHawkError)
    assert exc.provider == "ibkr"
    assert exc.status_code == 503
    assert exc.is_retryable is True


def test_all_subtypes_catchable_as_base():
    for exc_cls, kwargs in [
        (ScanError, {"scanner_type": "test"}),
        (DataFetchError, {"provider": "massive"}),
        (ProviderError, {"provider": "ibkr"}),
    ]:
        exc = exc_cls("msg", **kwargs)
        assert isinstance(exc, MarketHawkError)
        caught = False
        try:
            raise exc
        except MarketHawkError:
            caught = True
        assert caught, f"{exc_cls.__name__} should be catchable as MarketHawkError"
