"""
Rule-based tweet classifier with confidence scoring.

Classifications: CALLOUT | CELEBRATION | UPDATE | RETWEET | UNKNOWN
Confidence: 0.0 – 1.0 (promote to ScannerEvent if CALLOUT and >= threshold)
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone, time as dt_time
from typing import Any, Optional


# Eastern time offset approximation (UTC-5 standard / UTC-4 daylight).
# The classifier only checks pre-market hour window, not exact DST.
_PRE_MARKET_START = dt_time(9, 0)   # 09:00 UTC ≈ 04:00 ET
_PRE_MARKET_END = dt_time(14, 30)   # 14:30 UTC ≈ 09:30 ET

CALLOUT_KEYWORDS = frozenset([
    "watch", "setup", "trigger", "pivot", "entry", "break above", "break below",
    "setting up", "looking at", "eyes on", "stalking", "top watch", "morning watch",
    "on watch", "watchlist", "alert", "scanning", "loading",
])
CALLOUT_ANTI = frozenset([
    "gave you", "told you", "congrats", "nailed it", "profit", "cashed",
    "beautiful move", "runners",
])

CELEBRATION_KEYWORDS = frozenset([
    "gave you", "told you", "congrats", "nailed it", "runners", "profit",
    "cashed", "beautiful move", "we had", "called it", "as called",
])
CELEBRATION_ANTI = frozenset(["watch", "setup", "entry"])

UPDATE_KEYWORDS = frozenset([
    "still holding", "added", "trimmed", "stopped out", "took half",
    "scaling", "partial", "trailing", "moved stop", "breakeven",
])


@dataclass
class ClassificationResult:
    classification: str          # CALLOUT|CELEBRATION|UPDATE|RETWEET|UNKNOWN
    confidence: float            # 0.0 – 1.0
    direction: Optional[str]     # long|short|None
    tickers: list[str] = field(default_factory=list)
    price_levels: dict[str, Any] = field(default_factory=dict)


class TweetClassifier:
    def classify(
        self,
        text: str,
        posted_at: datetime,
        is_retweet: bool = False,
        is_reply: bool = False,
        tickers: Optional[list[str]] = None,
        price_levels: Optional[dict] = None,
        account_config: Optional[dict] = None,
    ) -> ClassificationResult:
        tickers = tickers or []
        price_levels = price_levels or {}

        low = text.lower()

        # Retweet without commentary (short text signals reshare with no opinion)
        if is_retweet and len(text) < 30:
            return ClassificationResult(
                classification="RETWEET",
                confidence=0.95,
                direction=None,
                tickers=tickers,
                price_levels=price_levels,
            )

        classification, base_confidence = self._classify_text(low)
        confidence = self._score_confidence(
            base=base_confidence,
            text=text,
            tickers=tickers,
            price_levels=price_levels,
            posted_at=posted_at,
            classification=classification,
        )
        direction = self._detect_direction(low)

        return ClassificationResult(
            classification=classification,
            confidence=round(confidence, 4),
            direction=direction,
            tickers=tickers,
            price_levels=price_levels,
        )

    def _classify_text(self, low: str) -> tuple[str, float]:
        """Return (classification, base_confidence) based on keyword matching."""
        callout_hits = sum(1 for kw in CALLOUT_KEYWORDS if kw in low)
        callout_anti = sum(1 for kw in CALLOUT_ANTI if kw in low)

        celeb_hits = sum(1 for kw in CELEBRATION_KEYWORDS if kw in low)
        celeb_anti = sum(1 for kw in CELEBRATION_ANTI if kw in low)

        update_hits = sum(1 for kw in UPDATE_KEYWORDS if kw in low)

        if callout_hits > 0 and callout_anti == 0:
            return "CALLOUT", 0.5 + min(0.2, callout_hits * 0.1)

        if celeb_hits > 0 and celeb_anti == 0:
            return "CELEBRATION", 0.5 + min(0.2, celeb_hits * 0.1)

        if update_hits > 0:
            return "UPDATE", 0.5 + min(0.15, update_hits * 0.08)

        return "UNKNOWN", 0.3

    def _score_confidence(
        self,
        base: float,
        text: str,
        tickers: list[str],
        price_levels: dict,
        posted_at: datetime,
        classification: str,
    ) -> float:
        score = base

        if tickers:
            score += 0.1

        if price_levels:
            score += 0.1

        if self._is_pre_market(posted_at):
            score += 0.1

        # Short text is noise
        if len(text) < 20:
            score -= 0.1

        # Multiple conflicting signals
        low = text.lower()
        has_callout = any(kw in low for kw in CALLOUT_KEYWORDS)
        has_celeb = any(kw in low for kw in CELEBRATION_KEYWORDS)
        if has_callout and has_celeb:
            score -= 0.2

        return max(0.0, min(1.0, score))

    def _is_pre_market(self, posted_at: datetime) -> bool:
        if posted_at.tzinfo is None:
            posted_at = posted_at.replace(tzinfo=timezone.utc)
        t = posted_at.astimezone(timezone.utc).time()
        return _PRE_MARKET_START <= t <= _PRE_MARKET_END

    def _detect_direction(self, low: str) -> Optional[str]:
        long_words = ["calls", "break above", "long", "buy", "bull", "upside", "calls on"]
        short_words = ["puts", "break below", "short", "sell", "bear", "downside", "puts on"]

        is_long = any(w in low for w in long_words)
        is_short = any(w in low for w in short_words)

        if is_long and not is_short:
            return "long"
        if is_short and not is_long:
            return "short"
        return None
