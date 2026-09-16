"""MockLiveAdapter — a no-op LiveDataProvider for testing without an IBKR connection.

Extends the basic mock with queue-wiring and simulate_disconnect() for chaos-test
scenarios where the caller needs to inject disconnect events programmatically.
"""

import asyncio
from typing import Optional

from live_scanner.provider import BarCallback, QuoteCallback


class MockLiveAdapter:
    """Satisfies LiveDataProvider. Accepts subscriptions silently, never emits real bars.

    Call wire_disconnect_queue() then simulate_disconnect() to inject TAG_DISCONNECT
    events into the main-loop queue for chaos-test flows.
    """

    def __init__(self) -> None:
        self.subscribed: set[str] = set()
        self._connected: bool = True
        self._queue: Optional[asyncio.Queue] = None
        self._disconnect_tag: Optional[str] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    # ── Protocol: queue wiring ────────────────────────────────────────────

    def wire_disconnect_queue(
        self,
        queue: asyncio.Queue,
        disconnect_tag: str,
        loop: asyncio.AbstractEventLoop,
    ) -> None:
        self._queue = queue
        self._disconnect_tag = disconnect_tag
        self._loop = loop

    # ── Chaos-test hook ───────────────────────────────────────────────────

    def simulate_disconnect(self) -> None:
        """Put TAG_DISCONNECT on the queue (mirrors what disconnectedEvent does in
        IBKRLiveAdapter). Marks the adapter as not-connected."""
        self._connected = False
        if (
            self._queue is not None
            and self._disconnect_tag is not None
            and self._loop is not None
        ):
            self._loop.call_soon_threadsafe(
                self._queue.put_nowait, (self._disconnect_tag, None, None)
            )

    # ── Protocol: connection state ────────────────────────────────────────

    def is_connected(self) -> bool:
        return self._connected

    def force_disconnect(self) -> None:
        self.simulate_disconnect()

    async def reconnect(self) -> bool:
        self._connected = True
        return True

    # ── Protocol: data streaming ──────────────────────────────────────────

    async def fetch_seed_data(
        self,
        symbol: str,
        security_type: str,
        exchange: str,
    ) -> tuple[float, float]:
        return 100.0, 500_000.0

    async def subscribe(
        self,
        symbol: str,
        security_type: str,
        exchange: str,
        *,
        on_bar: BarCallback,
        on_quote: QuoteCallback,
    ) -> None:
        self._connected = True
        self.subscribed.add(symbol)

    async def unsubscribe(self, symbol: str) -> None:
        self.subscribed.discard(symbol)

    async def disconnect(self) -> None:
        self.subscribed.clear()
        self._connected = False
