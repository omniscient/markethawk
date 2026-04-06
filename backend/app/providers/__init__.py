"""
Data Providers Package.

Implements a provider registry / factory pattern so the rest of the application
is decoupled from any specific data vendor.

Usage
-----
    from app.providers import DataProviderFactory

    # Get the configured Polygon provider
    massive = DataProviderFactory.get("massive")

    # Get list of all currently-available providers
    available = DataProviderFactory.get_available()

    # Get IBKR provider
    ibkr = DataProviderFactory.get("ibkr")

Adding a new provider
--------------------
1. Create a new module in this package that subclasses BaseDataProvider.
2. Register it at the bottom of this file (or in its own module's __init__).
3. Done — no other files need to change.
"""

import logging
from typing import Dict, List, Optional

from app.providers.base import BaseDataProvider

logger = logging.getLogger(__name__)


class DataProviderFactory:
    """
    Registry and factory for all data providers.

    Providers self-register on import.  The factory is a class-level singleton
    (no instantiation needed).
    """

    _providers: Dict[str, BaseDataProvider] = {}

    @classmethod
    def register(cls, provider: BaseDataProvider) -> None:
        """Register a provider instance under its name."""
        cls._providers[provider.name] = provider
        logger.debug(f"DataProviderFactory: Registered provider '{provider.name}'.")

    @classmethod
    def get(cls, name: str) -> BaseDataProvider:
        """
        Return the named provider.

        Raises ValueError if the provider is unknown.
        Note: does *not* check is_available() — callers should do that if
        they want to gracefully degrade.
        """
        if name not in cls._providers:
            raise ValueError(
                f"DataProviderFactory: Unknown provider '{name}'. "
                f"Registered: {list(cls._providers.keys())}"
            )
        return cls._providers[name]

    @classmethod
    def get_or_none(cls, name: str) -> Optional[BaseDataProvider]:
        """Like get() but returns None instead of raising."""
        return cls._providers.get(name)

    @classmethod
    def get_available(cls) -> List[str]:
        """Return names of all providers that are configured and reachable."""
        return [name for name, p in cls._providers.items() if p.is_available()]

    @classmethod
    def all(cls) -> Dict[str, BaseDataProvider]:
        """Return the full provider registry."""
        return dict(cls._providers)


# ---------------------------------------------------------------------------
# Auto-register built-in providers on package import.
# Each provider guards itself — if its config is missing it still registers
# but is_available() returns False.
# ---------------------------------------------------------------------------

from app.providers.massive import MassiveDataProvider  # noqa: E402
from app.providers.ibkr import IBKRDataProvider        # noqa: E402

DataProviderFactory.register(MassiveDataProvider())
DataProviderFactory.register(IBKRDataProvider())

__all__ = [
    "BaseDataProvider",
    "DataProviderFactory",
    "MassiveDataProvider",
    "IBKRDataProvider",
]
