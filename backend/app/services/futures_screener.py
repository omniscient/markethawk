import logging
from typing import Any, Dict, List

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


class FuturesScreener:
    @staticmethod
    def screen(db: Session, criteria: Dict[str, Any]) -> List[Dict[str, Any]]:
        data_source = criteria.get("data_source_futures", "ibkr")
        futures_input = criteria.get("futures_symbols", "")
        if isinstance(futures_input, str):
            futures_symbols = [
                s.strip().upper() for s in futures_input.split(",") if s.strip()
            ]
        else:
            futures_symbols = [
                s.strip().upper()
                for s in futures_input
                if isinstance(s, str) and s.strip()
            ]

        if not futures_symbols:
            return []

        from app.models.futures_contract import FuturesContract

        found_futures = (
            db.query(FuturesContract.symbol, FuturesContract.exchange)
            .filter(FuturesContract.symbol.in_(futures_symbols))
            .distinct()
            .all()
        )

        found_symbols = {f.symbol for f in found_futures}
        output = []

        for fut in found_futures:
            output.append(
                {
                    "ticker": fut.symbol,
                    "name": f"{fut.symbol} Futures",
                    "market_cap": None,
                    "close_price": None,
                    "volume": None,
                    "sector": "Futures",
                    "primary_exchange": fut.exchange,
                    "employees": None,
                    "sic_code": None,
                    "description": f"Futures contract for {fut.symbol}",
                    "asset_class": "futures",
                    "data_source": data_source,
                }
            )

        for symbol in futures_symbols:
            if symbol not in found_symbols:
                output.append(
                    {
                        "ticker": symbol,
                        "name": f"{symbol} Futures",
                        "market_cap": None,
                        "close_price": None,
                        "volume": None,
                        "sector": "Futures",
                        "primary_exchange": "Unknown",
                        "employees": None,
                        "sic_code": None,
                        "description": f"Requested Futures contract for {symbol} (Sync pending)",
                        "asset_class": "futures",
                        "data_source": data_source,
                    }
                )

        return output


from app.services.discovery_service import register_screener  # noqa: E402

register_screener("futures", FuturesScreener.screen)
