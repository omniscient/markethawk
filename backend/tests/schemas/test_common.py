"""Unit tests for the centralized validation primitives — F-INPUT-02 (#380)."""
from datetime import date
from typing import Optional

import pytest
from pydantic import BaseModel, ConfigDict, ValidationError

from app.schemas.common import (
    BatchDateRange,
    BoundedDict,
    FuturesSymbol,
    HttpsUrl,
    InteractiveDateRange,
    OutcomeDateRange,
    Ticker,
    validate_symbol_for_security_type,
)

# ── Ticker ────────────────────────────────────────────────────────────────────


class _TickerModel(BaseModel):
    ticker: Ticker


@pytest.mark.parametrize("value", ["AAPL", "MSFT", "BRK.B", "BF.B", "BRK-B", "F"])
def test_ticker_accepts_valid(value):
    assert _TickerModel(ticker=value).ticker == value


def test_ticker_uppercases_lowercase_input():
    # to_upper must run before pattern matching, otherwise "aapl" would fail.
    assert _TickerModel(ticker="aapl").ticker == "AAPL"


def test_ticker_strips_whitespace():
    assert _TickerModel(ticker="  aapl  ").ticker == "AAPL"


@pytest.mark.parametrize(
    "value",
    ["../etc", "AAAAAAAAAAAAAAAAAAAA", "TOOLONG", "A1", "", "AB.CD", "123"],
)
def test_ticker_rejects_invalid(value):
    with pytest.raises(ValidationError):
        _TickerModel(ticker=value)


# ── FuturesSymbol ─────────────────────────────────────────────────────────────


class _FuturesModel(BaseModel):
    symbol: FuturesSymbol


@pytest.mark.parametrize("value", ["ES", "NQ", "MES", "MNQ", "GC", "RTY"])
def test_futures_symbol_accepts_valid(value):
    assert _FuturesModel(symbol=value).symbol == value


@pytest.mark.parametrize("value", ["ES.U", "TOOLONG", "ES1", ""])
def test_futures_symbol_rejects_invalid(value):
    with pytest.raises(ValidationError):
        _FuturesModel(symbol=value)


# ── dispatch helper ───────────────────────────────────────────────────────────


def test_dispatch_stk_accepts_ticker_rejects_futures_only_form():
    assert validate_symbol_for_security_type("BRK.B", "STK") == "BRK.B"
    with pytest.raises(ValueError):
        validate_symbol_for_security_type("../x", "STK")


def test_dispatch_fut_rejects_dotted_suffix():
    assert validate_symbol_for_security_type("ES", "FUT") == "ES"
    with pytest.raises(ValueError):
        validate_symbol_for_security_type("ES.U", "FUT")


# ── HttpsUrl ──────────────────────────────────────────────────────────────────


class _UrlModel(BaseModel):
    url: Optional[HttpsUrl] = None


def test_https_url_accepts_https():
    assert _UrlModel(url="https://example.com/hook").url is not None


def test_https_url_rejects_http():
    with pytest.raises(ValidationError):
        _UrlModel(url="http://example.com/hook")


def test_https_url_allows_none():
    assert _UrlModel(url=None).url is None


# ── BoundedDict ───────────────────────────────────────────────────────────────


class _DictModel(BaseModel):
    payload: Optional[BoundedDict] = None


def test_bounded_dict_accepts_small():
    assert _DictModel(payload={"sector": "tech"}).payload == {"sector": "tech"}


def test_bounded_dict_allows_none():
    assert _DictModel(payload=None).payload is None


def test_bounded_dict_rejects_oversized_bytes():
    big = {"k": "x" * (64 * 1024 + 1)}
    with pytest.raises(ValidationError):
        _DictModel(payload=big)


def test_bounded_dict_rejects_too_many_keys():
    many = {str(i): i for i in range(51)}
    with pytest.raises(ValidationError):
        _DictModel(payload=many)


# ── Date-range mixins ─────────────────────────────────────────────────────────


class _Interactive(InteractiveDateRange):
    model_config = ConfigDict(extra="forbid")


class _Batch(BatchDateRange):
    model_config = ConfigDict(extra="forbid")


def test_interactive_range_accepts_within_cap():
    m = _Interactive(start_date=date(2025, 1, 1), end_date=date(2025, 6, 1))
    assert m.start_date == date(2025, 1, 1)


def test_interactive_range_rejects_over_366_days():
    with pytest.raises(ValidationError):
        _Interactive(start_date=date(2020, 1, 1), end_date=date(2026, 1, 1))


def test_interactive_range_rejects_end_before_start():
    with pytest.raises(ValidationError):
        _Interactive(start_date=date(2025, 6, 1), end_date=date(2025, 1, 1))


def test_batch_range_accepts_five_years():
    m = _Batch(start_date=date(2021, 1, 1), end_date=date(2025, 1, 1))
    assert m.end_date == date(2025, 1, 1)


def test_batch_range_rejects_over_1830_days():
    with pytest.raises(ValidationError):
        _Batch(start_date=date(2018, 1, 1), end_date=date(2026, 1, 1))


# ── OutcomeDateRange (Depends model) ──────────────────────────────────────────


def test_outcome_date_range_allows_both_none():
    dr = OutcomeDateRange()
    assert dr.start_date is None and dr.end_date is None


def test_outcome_date_range_rejects_oversized_span():
    with pytest.raises(ValidationError):
        OutcomeDateRange(start_date=date(2020, 1, 1), end_date=date(2026, 1, 1))


def test_outcome_date_range_accepts_partial():
    dr = OutcomeDateRange(start_date=date(2025, 1, 1))
    assert dr.end_date is None
