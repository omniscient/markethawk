"""LiveDataProvider Protocol — the seam between main.py and any live data source."""

from typing import Awaitable, Callable, Protocol, runtime_checkable


BarCallback = Callable[[str, object], Awaitable[None]]
QuoteCallback = Callable[[str, dict], Awaitable[None]]


@runtime_checkable
class LiveDataProvider(Protocol):
    async def fetch_seed_data(
        self,
        symbol: str,
        security_type: str,
        exchange: str,
    ) -> tuple[float, float]:
        """Return (prior_close, avg_daily_volume). Both 0.0 on failure."""
        ...

    async def subscribe(
        self,
        symbol: str,
        security_type: str,
        exchange: str,
        *,
        on_bar: BarCallback,
        on_quote: QuoteCallback,
    ) -> None:
        """Begin streaming bars and quotes for symbol."""
        ...

    async def unsubscribe(self, symbol: str) -> None:
        """Stop streaming for symbol."""
        ...

    async def disconnect(self) -> None:
        """Tear down the underlying connection."""
        ...
