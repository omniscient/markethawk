"""
Massive Data Provider - Polygon.io implementation.

This wraps the existing Polygon SDK and exposes it through the BaseDataProvider
interface.  All existing stock_data.py code that calls Polygon directly has been
kept functionally identical - it just now lives inside this class.
"""

import logging
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional

from polygon import RESTClient

from app.core.config import settings
from app.providers.base import BaseDataProvider

logger = logging.getLogger(__name__)


class MassiveDataProvider(BaseDataProvider):
    """
    Polygon.io data provider ('Massive' is the internal alias used in this project).

    Supports stocks, options, crypto, and forex data.  This is the primary
    provider for stock scanner operations.
    """

    def __init__(self):
        self._client: Optional[RESTClient] = None
        self._init_client()

    def _init_client(self):
        if settings.POLYGON_API_KEY:
            try:
                self._client = RESTClient(settings.POLYGON_API_KEY)
                logger.info("MassiveDataProvider: Polygon client initialized.")
            except Exception as e:
                logger.error(f"MassiveDataProvider: Failed to init Polygon client: {e}")
                self._client = None
        else:
            logger.warning("MassiveDataProvider: POLYGON_API_KEY not set — provider disabled.")

    # ------------------------------------------------------------------ #
    #  BaseDataProvider interface                                          #
    # ------------------------------------------------------------------ #

    @property
    def name(self) -> str:
        return "massive"

    @property
    def supported_asset_classes(self) -> List[str]:
        return ["stocks"]

    def is_available(self) -> tuple[bool, str]:
        if not settings.POLYGON_API_KEY:
            return False, "Missing POLYGON_API_KEY"
        if not self._client:
            return False, "Polygon client failed to initialize"
        return True, "Ready"

    async def get_historical_bars(
        self,
        symbol: str,
        timespan: str,
        multiplier: int,
        from_date: str,
        to_date: str,
        adjusted: bool = True,
        sort: str = "asc",
        limit: int = 50000,
        **kwargs,
    ) -> List[Dict[str, Any]]:
        """Fetch OHLCV bars from Polygon.io."""
        if not self._client:
            logger.error("MassiveDataProvider: client not initialized.")
            return []

        try:
            aggs = self._client.get_aggs(
                ticker=symbol.upper(),
                multiplier=multiplier,
                timespan=timespan,
                from_=from_date,
                to=to_date,
                adjusted=adjusted,
                sort=sort,
                limit=limit,
            )

            if not aggs:
                return []

            return [
                {
                    "timestamp": datetime.fromtimestamp(agg.timestamp / 1000, tz=timezone.utc),
                    "open": agg.open,
                    "high": agg.high,
                    "low": agg.low,
                    "close": agg.close,
                    "volume": agg.volume,
                    "vwap": getattr(agg, "vwap", None),
                    "transactions": getattr(agg, "transactions", None),
                }
                for agg in aggs
            ]

        except Exception as e:
            logger.error(f"MassiveDataProvider: Error fetching bars for {symbol}: {e}")
            return []

    async def get_ticker_details(self, symbol: str) -> Dict[str, Any]:
        """Fetch fundamental / reference info from Polygon."""
        if not self._client:
            return {}

        try:
            details = self._client.get_ticker_details(symbol.upper())
            if not details:
                return {}

            return {
                "name": details.name,
                "sector": getattr(details, "sic_description", "") or "",
                "industry": getattr(details, "sic_description", "") or "",
                "market_cap": getattr(details, "market_cap", None),
                "description": getattr(details, "description", None),
            }

        except Exception as e:
            logger.error(f"MassiveDataProvider: Error fetching details for {symbol}: {e}")
            return {}

    # ------------------------------------------------------------------ #
    #  Polygon-specific extras (not part of the base interface)           #
    # ------------------------------------------------------------------ #

    def get_client(self) -> Optional[RESTClient]:
        """Return the raw Polygon REST client for Polygon-specific operations."""
        return self._client

    async def get_snapshot_all(self, market_type: str = "stocks"):
        """Fetch a full market snapshot (Polygon-specific — used for pre-market movers)."""
        if not self._client:
            return []
        try:
            return self._client.get_snapshot_all(market_type=market_type) or []
        except Exception as e:
            logger.error(f"MassiveDataProvider: Error fetching snapshot: {e}")
            return []
