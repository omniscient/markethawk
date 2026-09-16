"""LiveDataProvider Protocol — the seam between main.py and any live data source."""

import asyncio
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

    def wire_disconnect_queue(
        self,
        queue: asyncio.Queue,
        disconnect_tag: str,
        loop: asyncio.AbstractEventLoop,
    ) -> None:
        """Register a handler that puts (disconnect_tag, None, None) on the queue when the
        underlying connection drops. Called once from run() after adapter and queue are created;
        re-called from _reconnect_coro after a successful reconnect."""
        ...

    async def reconnect(self) -> bool:
        """Re-establish the underlying connection with exponential-backoff retry.
        Returns True on success, False when all retries are exhausted."""
        ...

    def is_connected(self) -> bool:
        """Return True if the underlying connection is believed to be alive."""
        ...

    def force_disconnect(self) -> None:
        """Force-close the connection so disconnectedEvent fires (used by the liveness watchdog
        to recover from network-partition hangs where the process doesn't crash)."""
        ...
