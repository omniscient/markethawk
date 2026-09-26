"""
Circuit-breaker singletons for external provider calls.

Two module-level breakers are provided:
  POLYGON_BREAKER — wraps synchronous Polygon API calls in MassiveDataProvider.
  IBKR_BREAKER    — wraps async IBKR calls in IBKRDataProvider.

Both are built from Settings at import time so parameters are tunable via env vars
(POLYGON_CB_FAIL_MAX, POLYGON_CB_RESET_TIMEOUT, IBKR_CB_FAIL_MAX, IBKR_CB_RESET_TIMEOUT).

State is in-process per worker — no distributed coordination is needed or desired.

POLYGON_BREAKER carries a HealthRecordingListener that mirrors each state change
into the cross-process provider-health record (app/core/provider_health.py, #388)
so a scan running in a different process can see a breaker tripped here.
"""

import pybreaker

from app.core.config import settings
from app.exceptions import ProviderError


def _non_retryable_provider_error(exc: BaseException) -> bool:
    """
    Breaker exclusion predicate: permanent, request-specific failures (e.g.
    Polygon NOT_AUTHORIZED plan-limit responses) must not count toward opening
    the breaker — they say nothing about provider availability, and a batch of
    unfetchable historical windows must not block subsequent legitimate calls.
    """
    return isinstance(exc, ProviderError) and not exc.is_retryable


class HealthRecordingListener(pybreaker.CircuitBreakerListener):
    """Mirror breaker state changes into the Redis provider-health record.

    The import is lazy because provider_health imports this module (for the
    local POLYGON_BREAKER fast path). Errors are swallowed: a Redis problem
    must never change breaker behaviour.
    """

    def __init__(self, provider: str):
        self.provider = provider

    def state_change(self, cb, old_state, new_state) -> None:
        try:
            from app.core.provider_health import record_breaker_state

            record_breaker_state(self.provider, new_state.name)
        except Exception:
            pass


POLYGON_BREAKER: pybreaker.CircuitBreaker = pybreaker.CircuitBreaker(
    fail_max=settings.POLYGON_CB_FAIL_MAX,
    reset_timeout=settings.POLYGON_CB_RESET_TIMEOUT,
    exclude=[_non_retryable_provider_error],
    listeners=[HealthRecordingListener("polygon")],
)

IBKR_BREAKER: pybreaker.CircuitBreaker = pybreaker.CircuitBreaker(
    fail_max=settings.IBKR_CB_FAIL_MAX,
    reset_timeout=settings.IBKR_CB_RESET_TIMEOUT,
    exclude=[_non_retryable_provider_error],
)
