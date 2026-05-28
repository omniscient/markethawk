"""
TDD tests for the FuturesDataService deep-interface refactor (issue #63).

These tests validate:
  - Exactly two public methods exist on FuturesDataService
  - Neither public method accepts db or exchange parameters
  - timespan/multiplier/from_date/to_date remain on get_continuous_series
  - _resolve_exchange works correctly for known and unknown symbols
  - get_continuous_series returns a DataFrame (session managed internally)
"""

import inspect
from unittest.mock import patch

import pandas as pd
import pytest
from app.services.futures_data import FuturesDataService, _resolve_exchange

# ---------------------------------------------------------------------------
# Public interface contract
# ---------------------------------------------------------------------------


def test_public_interface_has_exactly_two_methods():
    """FuturesDataService must expose exactly 2 public methods."""
    public_methods = [
        name
        for name in dir(FuturesDataService)
        if not name.startswith("_")
        and callable(getattr(FuturesDataService, name))
        and not name.startswith("__")
    ]
    assert set(public_methods) == {"get_continuous_series", "sync_contracts"}, (
        f"Expected exactly {{get_continuous_series, sync_contracts}}, got {set(public_methods)}"
    )


def test_get_continuous_series_has_no_db_param():
    sig = inspect.signature(FuturesDataService.get_continuous_series)
    assert "db" not in sig.parameters


def test_sync_contracts_has_no_db_param():
    sig = inspect.signature(FuturesDataService.sync_contracts)
    assert "db" not in sig.parameters


def test_sync_contracts_has_no_exchange_param():
    sig = inspect.signature(FuturesDataService.sync_contracts)
    assert "exchange" not in sig.parameters


def test_get_continuous_series_keeps_timespan_and_multiplier():
    sig = inspect.signature(FuturesDataService.get_continuous_series)
    assert "timespan" in sig.parameters
    assert "multiplier" in sig.parameters
    assert "from_date" in sig.parameters
    assert "to_date" in sig.parameters


def test_get_continuous_series_has_symbol_as_first_param():
    sig = inspect.signature(FuturesDataService.get_continuous_series)
    params = list(sig.parameters)
    assert params[0] == "symbol"


# ---------------------------------------------------------------------------
# _resolve_exchange
# ---------------------------------------------------------------------------


def test_resolve_exchange_returns_cme_for_es():
    assert _resolve_exchange("ES") == "CME"


def test_resolve_exchange_returns_cme_for_nq():
    assert _resolve_exchange("NQ") == "CME"


def test_resolve_exchange_returns_comex_for_gc():
    assert _resolve_exchange("GC") == "COMEX"


def test_resolve_exchange_returns_nymex_for_cl():
    assert _resolve_exchange("CL") == "NYMEX"


def test_resolve_exchange_returns_cbot_for_zb():
    assert _resolve_exchange("ZB") == "CBOT"


def test_resolve_exchange_raises_for_unknown_symbol():
    with pytest.raises(ValueError, match="ZZZZ"):
        _resolve_exchange("ZZZZ")


def test_resolve_exchange_case_insensitive():
    assert _resolve_exchange("es") == "CME"


# ---------------------------------------------------------------------------
# get_continuous_series — session managed internally
# ---------------------------------------------------------------------------


def test_get_continuous_series_opens_own_session(db):
    """get_continuous_series opens its own DB session and returns a DataFrame."""

    with patch("app.services.futures_data.SessionLocal", return_value=db):
        result = FuturesDataService.get_continuous_series("ZZ")

    assert isinstance(result, pd.DataFrame)


def test_get_continuous_series_returns_empty_for_unknown_symbol(db):
    """Returns empty DataFrame when no data exists."""

    with patch("app.services.futures_data.SessionLocal", return_value=db):
        result = FuturesDataService.get_continuous_series("ZZ")

    assert result.empty
