"""
Unit tests for FuturesScreener adapter.

Seeds FuturesContract rows directly into the test DB and asserts exact
output from FuturesScreener.screen().
"""

import datetime

from sqlalchemy.orm import Session

from app.models.futures_contract import FuturesContract


def _make_contract(symbol: str, exchange: str = "CME") -> FuturesContract:
    return FuturesContract(
        symbol=symbol,
        exchange=exchange,
        contract_month="20260321",
        expiry_date=datetime.date(2026, 3, 21),
    )


# ── FuturesScreener.screen — no symbols ───────────────────────────────────


def test_futures_screener_empty_symbols_returns_empty(db: Session):
    """Empty futures_symbols yields empty result without DB query."""
    from app.services.futures_screener import FuturesScreener

    results = FuturesScreener.screen(
        db, {"futures_symbols": "", "asset_classes": ["futures"]}
    )
    assert results == []


def test_futures_screener_missing_key_returns_empty(db: Session):
    """Missing futures_symbols key yields empty result."""
    from app.services.futures_screener import FuturesScreener

    results = FuturesScreener.screen(db, {"asset_classes": ["futures"]})
    assert results == []


# ── FuturesScreener.screen — found symbols ────────────────────────────────


def test_futures_screener_found_symbol(db: Session):
    """Known symbol returns correct dict with exchange from DB."""
    from app.services.futures_screener import FuturesScreener

    db.add(_make_contract("ES", exchange="CME"))
    db.flush()

    results = FuturesScreener.screen(
        db, {"futures_symbols": "ES", "asset_classes": ["futures"]}
    )
    assert len(results) == 1
    r = results[0]
    assert r["ticker"] == "ES"
    assert r["name"] == "ES Futures"
    assert r["primary_exchange"] == "CME"
    assert r["asset_class"] == "futures"
    assert r["sector"] == "Futures"
    assert r["market_cap"] is None


def test_futures_screener_found_symbol_list_input(db: Session):
    """futures_symbols can be a list of strings."""
    from app.services.futures_screener import FuturesScreener

    db.add(_make_contract("NQ", exchange="CME"))
    db.flush()

    results = FuturesScreener.screen(
        db, {"futures_symbols": ["NQ"], "asset_classes": ["futures"]}
    )
    assert len(results) == 1
    assert results[0]["ticker"] == "NQ"


# ── FuturesScreener.screen — missing symbols (placeholder) ────────────────


def test_futures_screener_missing_symbol_creates_placeholder(db: Session):
    """Unknown symbol gets a placeholder with exchange=Unknown."""
    from app.services.futures_screener import FuturesScreener

    results = FuturesScreener.screen(
        db, {"futures_symbols": "NEWX", "asset_classes": ["futures"]}
    )
    assert len(results) == 1
    r = results[0]
    assert r["ticker"] == "NEWX"
    assert r["primary_exchange"] == "Unknown"
    assert "Sync pending" in r["description"]
    assert r["asset_class"] == "futures"


def test_futures_screener_mixed_found_and_missing(db: Session):
    """Found symbols get exchange from DB; missing symbols get placeholders."""
    from app.services.futures_screener import FuturesScreener

    db.add(_make_contract("GC", exchange="COMEX"))
    db.flush()

    results = FuturesScreener.screen(
        db, {"futures_symbols": "GC,GHOST", "asset_classes": ["futures"]}
    )
    assert len(results) == 2
    by_ticker = {r["ticker"]: r for r in results}
    assert by_ticker["GC"]["primary_exchange"] == "COMEX"
    assert by_ticker["GHOST"]["primary_exchange"] == "Unknown"


# ── FuturesScreener self-registers ────────────────────────────────────────


def test_futures_screener_self_registers():
    """Importing futures_screener registers 'futures' in the discovery registry."""
    import app.services.futures_screener  # noqa: F401
    from app.services.discovery_service import _SCREENER_REGISTRY

    assert "futures" in _SCREENER_REGISTRY
