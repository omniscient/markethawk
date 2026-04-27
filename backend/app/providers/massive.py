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

    def get_historical_bars(
        self,
        symbol: str,
        timespan: str,
        multiplier: int,
        from_date: str,
        to_date: str,
        adjusted: bool = True,
        sort: str = "asc",
        limit: int = 50000,
        paginate: bool = False,
        **kwargs,
    ) -> List[Dict[str, Any]]:
        """
        Fetch OHLCV bars from Polygon.io with automatic pagination.

        Polygon's /v2/aggs endpoint returns at most `limit` bars per call and
        provides no next_url cursor.  When a full page arrives we advance
        `from_` to last_bar.timestamp + 1 ms and fetch again until a partial
        page signals the end of available data.
        """
        if not self._client:
            logger.error("MassiveDataProvider: client not initialized.")
            return []

        def _convert(agg) -> Dict[str, Any]:
            return {
                "timestamp": datetime.fromtimestamp(agg.timestamp / 1000, tz=timezone.utc),
                "open": agg.open,
                "high": agg.high,
                "low": agg.low,
                "close": agg.close,
                "volume": agg.volume,
                "vwap": getattr(agg, "vwap", None),
                "transactions": getattr(agg, "transactions", None),
            }

        try:
            all_bars: List[Dict[str, Any]] = []
            current_from: Any = from_date  # str on first call, int (ms) on subsequent calls

            while True:
                page = self._client.get_aggs(
                    ticker=symbol.upper(),
                    multiplier=multiplier,
                    timespan=timespan,
                    from_=current_from,
                    to=to_date,
                    adjusted=adjusted,
                    sort=sort,
                    limit=limit,
                )

                if not page:
                    break

                all_bars.extend(_convert(agg) for agg in page)

                if not paginate or len(page) < limit:
                    break  # single-page mode, or partial page means no more data

                # Full page: advance past the last bar's millisecond timestamp
                current_from = page[-1].timestamp + 1

            if all_bars:
                logger.debug(
                    f"MassiveDataProvider: {symbol} {timespan} fetched "
                    f"{len(all_bars)} bars in total"
                )
            return all_bars

        except Exception as e:
            # Distinct from the "no bars returned" path so logs disambiguate
            # API errors (rate limit, 5xx, network) from genuinely empty ranges.
            logger.exception(
                f"❌ Polygon fetch FAILED for {symbol} {timespan}×{multiplier} "
                f"({from_date} → {to_date}): {e}"
            )
            return []

    def get_ticker_details(self, symbol: str) -> Dict[str, Any]:
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

    def get_snapshot_all(self, market_type: str = "stocks"):
        """Fetch a full market snapshot (Polygon-specific — used for pre-market movers)."""
        if not self._client:
            return []
        try:
            return self._client.get_snapshot_all(market_type=market_type) or []
        except Exception as e:
            logger.error(f"MassiveDataProvider: Error fetching snapshot: {e}")
            return []

    def get_snapshot_price(self, symbol: str) -> Optional[float]:
        if not self._client:
            return None
        try:
            snap = self._client.get_snapshot_ticker("stocks", symbol)
            if snap and snap.last_trade and snap.last_trade.price is not None:
                return float(snap.last_trade.price)
            if snap and snap.day and snap.day.close is not None:
                return float(snap.day.close)
            return None
        except Exception as exc:
            logger.debug(
                f"MassiveDataProvider: snapshot price unavailable for {symbol}: {exc}"
            )
            return None
