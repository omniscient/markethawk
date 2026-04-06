"""
Base Data Provider - Abstract interface all data providers must implement.
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional


class BaseDataProvider(ABC):
    """
    Abstract base class for all data providers.

    All providers expose a consistent async interface so the rest of the system
    is completely decoupled from any specific vendor.  Adding a 3rd provider
    only requires implementing this class and registering it with the factory.
    """

    # ------------------------------------------------------------------ #
    #  Identity                                                            #
    # ------------------------------------------------------------------ #

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable provider name (e.g. 'massive', 'ibkr')."""
        ...

    @abstractmethod
    def is_available(self) -> bool:
        """
        Return True if the provider is configured and can accept requests.
        Called by the factory before routing requests.
        """
        ...

    # ------------------------------------------------------------------ #
    #  Market Data                                                         #
    # ------------------------------------------------------------------ #

    @abstractmethod
    async def get_historical_bars(
        self,
        symbol: str,
        timespan: str,
        multiplier: int,
        from_date: str,
        to_date: str,
        **kwargs,
    ) -> List[Dict[str, Any]]:
        """
        Fetch OHLCV bars for a symbol.

        Returns a list of dicts with these keys (all providers must return this
        exact shape so callers never need to know which provider supplied data):

            {
                "timestamp": datetime (UTC-aware),
                "open":      float,
                "high":      float,
                "low":       float,
                "close":     float,
                "volume":    int,
                "vwap":      float | None,
                "transactions": int | None,
            }

        Args:
            symbol:     Ticker / symbol string (e.g. "AAPL", "ES").
            timespan:   Bar size: "minute", "hour", "day", "week", "month".
            multiplier: Bar multiplier (e.g. 5 for 5-minute bars).
            from_date:  Start date string "YYYY-MM-DD".
            to_date:    End date string "YYYY-MM-DD".
            **kwargs:   Provider-specific extras (e.g. adjusted=True).
        """
        ...

    @abstractmethod
    async def get_ticker_details(self, symbol: str) -> Dict[str, Any]:
        """
        Fetch reference/fundamental info for a symbol.

        Returns a dict with a best-effort subset of:
            { "name", "sector", "industry", "market_cap", "description" }

        Providers that don't support this (e.g. IBKR for futures) should
        return an empty dict rather than raising.
        """
        ...
