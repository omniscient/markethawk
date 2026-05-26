"""MockLiveAdapter — a no-op LiveDataProvider for testing without an IBKR connection."""

from live_scanner.provider import BarCallback, QuoteCallback


class MockLiveAdapter:
    """Satisfies LiveDataProvider. Accepts subscriptions silently, never emits bars."""

    def __init__(self) -> None:
        self.subscribed: set[str] = set()

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
        self.subscribed.add(symbol)

    async def unsubscribe(self, symbol: str) -> None:
        self.subscribed.discard(symbol)

    async def disconnect(self) -> None:
        self.subscribed.clear()
