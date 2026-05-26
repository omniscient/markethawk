"""
TickerExtractor + PriceLevelExtractor.

Extracts cashtag tickers ($AAPL) and associated price levels from tweet text.
"""
from __future__ import annotations

import re
from typing import Any

# Cashtag: $TICKER (1-5 uppercase letters)
_CASHTAG_RE = re.compile(r"\$([A-Z]{1,5})\b")

# Price level with contextual keyword
# e.g. "entry at $185.50", "target 195", "stop @ 180"
_PRICE_RE = re.compile(
    r"(entry|target|stop|above|below|break|trigger|pivot|support|resistance)\s*"
    r"(?:at|@|:|\s)?\s*\$?(\d{1,6}(?:\.\d{1,4})?)",
    re.IGNORECASE,
)

# Exclusion list — index/macro tickers not individual stocks
_EXCLUDED_TICKERS = frozenset([
    "USD", "DXY", "SPX", "VIX", "ES", "NQ", "RTY", "CL", "GC",
    "SPY", "QQQ", "IWM", "DIA", "A", "I", "IT", "AT",
])


class TickerExtractor:
    def extract(self, text: str) -> list[str]:
        matches = _CASHTAG_RE.findall(text)
        seen: set[str] = set()
        result = []
        for t in matches:
            if t not in _EXCLUDED_TICKERS and t not in seen:
                seen.add(t)
                result.append(t)
        return result


class PriceLevelExtractor:
    def extract(self, text: str, tickers: list[str]) -> dict[str, Any]:
        """
        Returns a dict keyed by ticker with price level sub-keys.
        e.g. {"AAPL": {"entry": 185.50, "target": 195.00, "stop": 180.00}}
        """
        matches = _PRICE_RE.findall(text)
        if not matches or not tickers:
            return {}

        # Associate all price levels with the primary ticker (first extracted)
        primary = tickers[0]
        levels: dict[str, float] = {}
        for label, price_str in matches:
            key = label.lower()
            try:
                levels[key] = float(price_str)
            except ValueError:
                continue

        return {primary: levels} if levels else {}
