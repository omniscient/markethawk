"""
Circuit-breaker singletons for external provider calls.

Two module-level breakers are provided:
  POLYGON_BREAKER — wraps synchronous Polygon API calls in MassiveDataProvider.
  IBKR_BREAKER    — wraps async IBKR calls in IBKRDataProvider.

Both are built from Settings at import time so parameters are tunable via env vars
(POLYGON_CB_FAIL_MAX, POLYGON_CB_RESET_TIMEOUT, IBKR_CB_FAIL_MAX, IBKR_CB_RESET_TIMEOUT).

State is in-process per worker — no distributed coordination is needed or desired.
"""

import pybreaker

from app.core.config import settings

POLYGON_BREAKER: pybreaker.CircuitBreaker = pybreaker.CircuitBreaker(
    fail_max=settings.POLYGON_CB_FAIL_MAX,
    reset_timeout=settings.POLYGON_CB_RESET_TIMEOUT,
)

IBKR_BREAKER: pybreaker.CircuitBreaker = pybreaker.CircuitBreaker(
    fail_max=settings.IBKR_CB_FAIL_MAX,
    reset_timeout=settings.IBKR_CB_RESET_TIMEOUT,
)
