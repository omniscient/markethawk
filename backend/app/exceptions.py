"""
Domain exception hierarchy for MarketHawk.

All service and provider modules raise subclasses of MarketHawkError so
callers always know what to catch. The is_retryable flag drives Celery retry
logic: if exc.is_retryable: self.retry(exc=exc).

Structured context fields on each subclass make failures filterable in Seq.
"""

from typing import Any


class MarketHawkError(Exception):
    """Base exception for all MarketHawk domain errors."""

    def __init__(self, message: str, *, is_retryable: bool = False, **context: Any):
        super().__init__(message)
        self.is_retryable = is_retryable
        self.context = context

    def __str__(self) -> str:
        base = super().__str__()
        if self.context:
            ctx = ", ".join(f"{k}={v!r}" for k, v in self.context.items())
            return f"{base} [{ctx}]"
        return base


class ScanError(MarketHawkError):
    """
    Raised when a scanner fails — either at the run level or per-ticker.

    Structured context fields: scanner_type, universe_id, ticker, scan_id.
    """

    def __init__(
        self,
        message: str,
        *,
        is_retryable: bool = False,
        scanner_type: str | None = None,
        universe_id: int | None = None,
        ticker: str | None = None,
        scan_id: int | None = None,
        **context: Any,
    ):
        super().__init__(
            message,
            is_retryable=is_retryable,
            scanner_type=scanner_type,
            universe_id=universe_id,
            ticker=ticker,
            scan_id=scan_id,
            **context,
        )
        self.scanner_type = scanner_type
        self.universe_id = universe_id
        self.ticker = ticker
        self.scan_id = scan_id


class DataFetchError(MarketHawkError):
    """
    Raised when fetching market data fails in a service method.

    Structured context fields: provider, symbol, timespan, date_range.
    """

    def __init__(
        self,
        message: str,
        *,
        is_retryable: bool = False,
        provider: str | None = None,
        symbol: str | None = None,
        timespan: str | None = None,
        date_range: str | None = None,
        **context: Any,
    ):
        super().__init__(
            message,
            is_retryable=is_retryable,
            provider=provider,
            symbol=symbol,
            timespan=timespan,
            date_range=date_range,
            **context,
        )
        self.provider = provider
        self.symbol = symbol
        self.timespan = timespan
        self.date_range = date_range


class ProviderError(MarketHawkError):
    """
    Raised when an external data provider call fails.

    Structured context fields: provider, endpoint, status_code.
    """

    def __init__(
        self,
        message: str,
        *,
        is_retryable: bool = False,
        provider: str | None = None,
        endpoint: str | None = None,
        status_code: int | None = None,
        **context: Any,
    ):
        super().__init__(
            message,
            is_retryable=is_retryable,
            provider=provider,
            endpoint=endpoint,
            status_code=status_code,
            **context,
        )
        self.provider = provider
        self.endpoint = endpoint
        self.status_code = status_code
