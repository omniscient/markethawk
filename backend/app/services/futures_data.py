"""
Futures Data Service — backward-compatibility facade.

All implementation lives in focused sibling modules:
  futures_contracts.py  — SYMBOL_EXCHANGE_MAP, _resolve_exchange, FuturesContractService
  futures_aggregates.py — FuturesAggregatesService (download + gap-fill)
  futures_rollovers.py  — FuturesRolloversService, _detect_single_rollover, _build_time_slices
  futures_series.py     — FutureSeriesService (continuous series assembly)

All 9 import sites referencing FuturesDataService, SYMBOL_EXCHANGE_MAP, or
_resolve_exchange continue to work without modification.
"""

from typing import Optional

import pandas as pd

from app.core.database import SessionLocal  # retained: test patch target
from app.services.futures_aggregates import FuturesAggregatesService
from app.services.futures_contracts import (
    SYMBOL_EXCHANGE_MAP,  # noqa: F401 — re-exported for 3 callers: universe_orchestrator (×2), routers/stocks
    FuturesContractService,
    _resolve_exchange,
)
from app.services.futures_rollovers import FuturesRolloversService
from app.services.futures_series import FutureSeriesService


class FuturesDataService:
    """Backward-compatibility facade — explicit delegation to focused subservices."""

    # Private methods use staticmethod() class-attribute assignments (no session mgmt).
    # sync_contracts and get_continuous_series are explicit method bodies so that
    # patch("app.services.futures_data.SessionLocal", ...) intercepts their SessionLocal
    # calls. If they were staticmethod() delegations, SessionLocal would be called from
    # futures_contracts.py / futures_series.py namespaces — outside the patched module.

    # Contracts
    _sync_contract_catalog = staticmethod(FuturesContractService._sync_contract_catalog)

    @staticmethod
    async def sync_contracts(symbol: str):
        """Sync contract catalog. SessionLocal called from this module's namespace
        so patch("app.services.futures_data.SessionLocal", ...) intercepts it."""
        exchange = _resolve_exchange(symbol.upper())
        db = SessionLocal()
        try:
            return await FuturesContractService._sync_contract_catalog(
                db, symbol.upper(), exchange
            )
        finally:
            db.close()

    # Series (public interface first — most callers use this)
    @staticmethod
    def get_continuous_series(
        symbol: str,
        timespan: str = "day",
        multiplier: int = 1,
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
    ) -> pd.DataFrame:
        """Assemble continuous series. SessionLocal called from this module's namespace
        so patch("app.services.futures_data.SessionLocal", ...) intercepts it."""
        db = SessionLocal()
        try:
            return FutureSeriesService._get_continuous_series_with_db(
                db=db,
                symbol=symbol,
                timespan=timespan,
                multiplier=multiplier,
                from_date=from_date,
                to_date=to_date,
            )
        finally:
            db.close()

    _get_continuous_series_with_db = staticmethod(
        FutureSeriesService._get_continuous_series_with_db
    )

    # Aggregates
    _download_contract = staticmethod(FuturesAggregatesService._download_contract)
    _download_full_history = staticmethod(
        FuturesAggregatesService._download_full_history
    )
    _fill_data_gaps = staticmethod(FuturesAggregatesService._fill_data_gaps)

    # Rollovers
    _detect_rollovers = staticmethod(FuturesRolloversService._detect_rollovers)
