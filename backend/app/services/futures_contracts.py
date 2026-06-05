"""Contract catalog management — extracted from FuturesDataService."""

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.exceptions import ProviderError
from app.models.futures_contract import FuturesContract
from app.providers import DataProviderFactory

logger = logging.getLogger(__name__)

MAX_HISTORY_YEARS = 10

SYMBOL_EXCHANGE_MAP = {
    "ES": "CME",
    "NQ": "CME",
    "MES": "CME",
    "MNQ": "CME",
    "RTY": "CME",
    "GC": "COMEX",
    "SI": "COMEX",
    "CL": "NYMEX",
    "NG": "NYMEX",
    "ZB": "CBOT",
    "ZN": "CBOT",
    "ZF": "CBOT",
}


def _resolve_exchange(symbol: str) -> str:
    """Return the exchange for a known futures symbol, raising ValueError if unknown."""
    exchange = SYMBOL_EXCHANGE_MAP.get(symbol.upper())
    if not exchange:
        raise ValueError(
            f"Unknown futures symbol '{symbol}'. Add it to SYMBOL_EXCHANGE_MAP."
        )
    return exchange


class FuturesContractService:
    """Contract catalog sync — extracted from FuturesDataService."""

    @staticmethod
    async def _sync_contract_catalog(
        db: Session,
        symbol: str,
        exchange: str,
    ) -> List[Dict[str, Any]]:
        """Query IBKR for all contract months (including expired) and cache them."""
        ibkr = DataProviderFactory.get("ibkr")
        available, reason = ibkr.is_available()
        if not available:
            raise ProviderError(
                f"IBKR provider is not available: {reason}",
                provider="ibkr",
                endpoint="_sync_contract_catalog",
                is_retryable=True,
            )

        logger.info(
            f"FuturesDataService: Syncing contract catalog for {symbol} ({exchange})..."
        )
        contracts = await ibkr.get_futures_contracts(
            symbol=symbol,
            exchange=exchange,
            include_expired=True,
        )

        if not contracts:
            raise ProviderError(
                f"IBKR returned no contracts for {symbol} on {exchange}. "
                "TWS may be unreachable or the symbol/exchange is incorrect.",
                provider="ibkr",
                endpoint="get_futures_contracts",
                is_retryable=True,
            )

        # Apply 10-year limit
        cutoff = datetime.now(timezone.utc) - timedelta(days=MAX_HISTORY_YEARS * 365)

        saved = 0
        for c in contracts:
            try:
                expiry_dt = datetime.strptime(c["contract_month"], "%Y%m%d").replace(
                    tzinfo=timezone.utc
                )
            except ValueError:
                continue

            if expiry_dt < cutoff:
                continue

            existing = (
                db.query(FuturesContract)
                .filter(
                    FuturesContract.symbol == symbol,
                    FuturesContract.contract_month == c["contract_month"],
                )
                .first()
            )

            if not existing:
                rec = FuturesContract(
                    symbol=symbol,
                    exchange=exchange.upper(),
                    contract_month=c["contract_month"],
                    expiry_date=datetime.strptime(c["contract_month"], "%Y%m%d").date(),
                    con_id=c.get("con_id"),
                    is_expired=c.get("is_expired", False),
                )
                db.add(rec)
                saved += 1
            else:
                existing.con_id = c.get("con_id") or existing.con_id
                existing.is_expired = c.get("is_expired", existing.is_expired)

        db.commit()
        logger.info(
            f"FuturesDataService: Saved {saved} new contracts for {symbol}. "
            f"Total in catalog: {len(contracts)}."
        )
        return contracts

    @staticmethod
    async def sync_contracts(symbol: str) -> List[Dict[str, Any]]:
        """Refresh the contract catalog for symbol from IBKR."""
        exchange = _resolve_exchange(symbol.upper())
        db = SessionLocal()
        try:
            return await FuturesContractService._sync_contract_catalog(
                db, symbol.upper(), exchange
            )
        finally:
            db.close()
