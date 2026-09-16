"""
Centralized input-validation primitives — F-INPUT-02.

Every schema imports its ticker/symbol types, URL types, dict bounds, and
date-range mixins from this one module so validation rules are defined once and
applied uniformly (OWASP A03/A04:2021, CWE-20, CWE-915).

Do NOT re-define ticker patterns, dict-size caps, or date-range limits anywhere
else — extend them here.
"""

import json
from datetime import date
from typing import Annotated, Any, Dict, Optional

from pydantic import (
    AfterValidator,
    AnyUrl,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    StringConstraints,
    model_validator,
)

# ── Ticker / symbol types ─────────────────────────────────────────────────────

# Equity: 1-5 uppercase letters, optional single-letter dotted/hyphenated class
# suffix. Covers AAPL, MSFT, BRK.B, BF.B, BRK-B.
TICKER_PATTERN = r"^[A-Z]{1,5}([.\-][A-Z])?$"

# Futures root symbol: 1-5 uppercase letters only (month/year live in separate
# fields). Covers ES, NQ, MES, MNQ, GC, ZB, RTY.
FUTURES_SYMBOL_PATTERN = r"^[A-Z]{1,5}$"


def _normalize_symbol(v: Any) -> Any:
    """Strip + uppercase BEFORE the pattern check.

    StringConstraints applies ``pattern`` to the raw input (it does not run
    ``to_upper`` first in pydantic 2.x), so a lowercase ``"aapl"`` would fail the
    ``[A-Z]`` pattern. Normalizing in a BeforeValidator keeps lowercase callers
    working, matching the ad-hoc ``.upper()`` the codebase used previously.
    """
    if isinstance(v, str):
        return v.strip().upper()
    return v


Ticker = Annotated[
    str, BeforeValidator(_normalize_symbol), StringConstraints(pattern=TICKER_PATTERN)
]
FuturesSymbol = Annotated[
    str,
    BeforeValidator(_normalize_symbol),
    StringConstraints(pattern=FUTURES_SYMBOL_PATTERN),
]


def validate_symbol_for_security_type(symbol: str, security_type: str) -> str:
    """Apply the ticker or futures-root pattern depending on ``security_type``.

    Used by mixed-type fields (e.g. ActiveWatchlistAdd.symbol) where one field
    accepts both an equity ticker and a futures root. ``symbol`` is assumed to be
    already stripped/uppercased by the caller's field validator.
    """
    import re

    if security_type == "FUT":
        if not re.fullmatch(FUTURES_SYMBOL_PATTERN, symbol):
            raise ValueError(
                f"invalid futures symbol {symbol!r}: must be 1-5 uppercase letters"
            )
    else:  # "STK" and any default
        if not re.fullmatch(TICKER_PATTERN, symbol):
            raise ValueError(
                f"invalid ticker {symbol!r}: must be 1-5 uppercase letters with an "
                "optional single-letter .X/-X class suffix"
            )
    return symbol


# ── URL types ─────────────────────────────────────────────────────────────────


def validate_https(v: Optional[AnyUrl]) -> Optional[AnyUrl]:
    """Reject any URL that is not https. Reusable across https-required fields."""
    if v is not None and v.scheme != "https":
        raise ValueError("URL must use https scheme")
    return v


HttpsUrl = Annotated[AnyUrl, AfterValidator(validate_https)]


# ── Bounded free-form dict ────────────────────────────────────────────────────

_MAX_DICT_BYTES = 64 * 1024  # 64 KB
_MAX_DICT_KEYS = 50


def validate_bounded_dict(v: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Cap a free-form ``Dict[str, Any]`` write field by serialized size and key count.

    ``default=str`` keeps the size probe from itself raising on datetime/Decimal
    values — those are handled downstream.
    """
    if v is None:
        return v
    serialized = json.dumps(v, default=str)
    if len(serialized.encode()) > _MAX_DICT_BYTES:
        raise ValueError(
            f"dict payload exceeds maximum size of {_MAX_DICT_BYTES // 1024} KB"
        )
    if len(v) > _MAX_DICT_KEYS:
        raise ValueError(f"dict has {len(v)} keys; maximum is {_MAX_DICT_KEYS}")
    return v


BoundedDict = Annotated[Dict[str, Any], AfterValidator(validate_bounded_dict)]


# ── Date-range mixins ─────────────────────────────────────────────────────────

_INTERACTIVE_MAX_DAYS = 366  # ad-hoc queries: outcomes, single-ticker scanner range
_BATCH_MAX_DAYS = 1830  # long-running batch: backtest, backfill


def _check_range(start: date, end: date, max_days: int) -> None:
    if end < start:
        raise ValueError("end_date must not be before start_date")
    span = (end - start).days
    if span > max_days:
        raise ValueError(
            f"date range exceeds maximum of {max_days} days (requested {span})"
        )


class InteractiveDateRange(BaseModel):
    """Mixin for interactive endpoints — max 366-day range, start <= end."""

    start_date: date
    end_date: date

    @model_validator(mode="after")
    def _validate_interactive_range(self):
        _check_range(self.start_date, self.end_date, _INTERACTIVE_MAX_DAYS)
        return self


class BatchDateRange(BaseModel):
    """Mixin for batch/historical endpoints — max 1830-day (5-year) range, start <= end."""

    start_date: date
    end_date: date

    @model_validator(mode="after")
    def _validate_batch_range(self):
        _check_range(self.start_date, self.end_date, _BATCH_MAX_DAYS)
        return self


class OutcomeDateRange(BaseModel):
    """Shared ``Depends`` query-param model for outcomes GET endpoints.

    Both bounds optional (callers may pass neither); when both are present the
    366-day interactive cap applies.
    """

    model_config = ConfigDict(extra="ignore")

    start_date: Optional[date] = None
    end_date: Optional[date] = None

    @model_validator(mode="after")
    def _validate(self):
        if self.start_date and self.end_date:
            _check_range(self.start_date, self.end_date, _INTERACTIVE_MAX_DAYS)
        return self
