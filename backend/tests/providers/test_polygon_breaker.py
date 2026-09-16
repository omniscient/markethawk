"""
Circuit-breaker behaviour for provider errors.

Permanent, request-specific failures (e.g. Polygon NOT_AUTHORIZED plan-limit
responses) must not open the breaker: they say nothing about provider
availability, and one batch of unfetchable historical windows must not block
hundreds of subsequent legitimate calls.
"""

import pybreaker
import pytest

from app.core.circuit_breakers import _non_retryable_provider_error
from app.exceptions import ProviderError
from app.providers.massive import _is_plan_limit_error


def _make_breaker(fail_max=2):
    return pybreaker.CircuitBreaker(
        fail_max=fail_max,
        reset_timeout=60,
        exclude=[_non_retryable_provider_error],
    )


def test_non_retryable_provider_error_does_not_trip_breaker():
    breaker = _make_breaker(fail_max=2)

    def plan_limit():
        raise ProviderError("plan limit", is_retryable=False, provider="massive")

    for _ in range(5):
        with pytest.raises(ProviderError):
            breaker.call(plan_limit)

    assert breaker.current_state == "closed"


def test_retryable_provider_error_still_trips_breaker():
    breaker = _make_breaker(fail_max=2)

    def transient():
        raise ProviderError("timeout", is_retryable=True, provider="massive")

    for _ in range(2):
        with pytest.raises(Exception):
            breaker.call(transient)

    assert breaker.current_state == "open"


def test_exclude_predicate():
    assert _non_retryable_provider_error(ProviderError("x", is_retryable=False))
    assert not _non_retryable_provider_error(ProviderError("x", is_retryable=True))
    assert not _non_retryable_provider_error(ValueError("x"))


def test_is_plan_limit_error_matches_polygon_not_authorized():
    # Exact shape observed from the polygon client for out-of-plan windows
    exc = Exception(
        '{"status":"NOT_AUTHORIZED","request_id":"abc",'
        '"message":"Your plan doesn\'t include this data timeframe."}'
    )
    assert _is_plan_limit_error(exc)
    assert not _is_plan_limit_error(Exception("connection reset by peer"))
