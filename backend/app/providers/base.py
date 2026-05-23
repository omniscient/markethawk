"""
Base Data Provider - Abstract interface all data providers must implement.
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional


class BaseDataProvider(ABC):
    """
    Abstract base class for all data providers.

    All providers expose a consistent sync interface so the rest of the system
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

    @property
    @abstractmethod
    def supported_asset_classes(self) -> List[str]:
        """List of asset classes supported (e.g. ['stocks'], ['futures'])."""
        ...

    @abstractmethod
    def is_available(self) -> tuple[bool, str]:
        """
        Return (available_bool, status_message).
        Called by the factory before routing requests.
        """
        return True, "Ready"

    # ------------------------------------------------------------------ #
    #  Market Data                                                         #
    # ------------------------------------------------------------------ #

    @abstractmethod
    def get_bars(
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
    def get_snapshots(self, symbols: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        """
        Fetch market snapshots, optionally filtered to a list of symbols.

        Returns a list of dicts:
            {
                "ticker":       str,
                "price":        float,
                "change_pct":   float,   # % change from previous close
                "change_value": float,   # absolute $ change from previous close
                "volume":       int,
                "prev_close":   float,
            }

        Providers that don't support snapshots (e.g. IBKR for futures) should
        return an empty list rather than raising.
        """
        ...

    @abstractmethod
    def get_ticker_details(self, symbol: str) -> Dict[str, Any]:
        """
        Fetch reference/fundamental info for a symbol.

        Returns a dict with a best-effort subset of:
            { "name", "sector", "industry", "market_cap", "description" }

        Providers that don't support this (e.g. IBKR for futures) should
        return an empty dict rather than raising.
        """
        ...
