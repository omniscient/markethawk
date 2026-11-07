"""Roster data + seed-SQL tests for revision f8f6c8fc1c83 (#904).

The seed helpers run against the test DB (created by Base.metadata.create_all),
so these tests exercise the exact SQL the migration runs.
"""

from collections import Counter
from datetime import date

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.models import LtEtf, MonitoredStock, StockUniverse, StockUniverseTicker
from app.schemas.universe import StockUniverseResponse
from tests.fixtures.lt_etf import load_lt_etf_migration

mig = load_lt_etf_migration()


def test_revision_chains_onto_current_head():
    assert mig.revision == "f8f6c8fc1c83"
    assert mig.down_revision == "e2f3a4b5c6d7"


def test_roster_has_65_unique_tickers_within_20_chars():
    tickers = [r["ticker"] for r in mig.roster_rows()]
    assert len(tickers) == 65
    assert len(set(tickers)) == 65
    assert max(len(t) for t in tickers) <= 20


def test_roster_segment_counts_match_epic_table():
    counts = Counter(r["segment"] for r in mig.roster_rows())
    assert counts == {
        "Broad market": 8,
        "Style & size": 6,
        "Sectors": 20,
        "Bonds & rates": 10,
        "Commodities & miners": 5,
        "International": 6,
        "Crypto": 4,
        "Tech themes": 6,
    }


def test_roster_country_derivation():
    rows = mig.roster_rows()
    ca = [r for r in rows if r["ticker"].endswith(".TO")]
    us = [r for r in rows if not r["ticker"].endswith(".TO")]
    assert len(us) == 46
    assert len(ca) == 19
    for r in ca:
        assert (r["country"], r["currency"], r["exchange"], r["data_source"]) == (
            "CA",
            "CAD",
            "TSX",
            "yfinance",
        )
    for r in us:
        assert (r["country"], r["currency"], r["exchange"], r["data_source"]) == (
            "US",
            "USD",
            "NYSEARCA",
            "massive",
        )


def test_only_spy_is_benchmark_and_every_row_has_a_name():
    rows = mig.roster_rows()
    assert [r["ticker"] for r in rows if r["is_benchmark"]] == ["SPY"]
    assert all(r["name"].strip() for r in rows)


def test_seed_roster_inserts_65_active_rows_idempotently(db: Session):
    conn = db.connection()
    mig.seed_roster(conn)
    mig.seed_roster(conn)  # re-runnable: keyed on ticker

    rows = db.query(LtEtf).all()
    assert len(rows) == 65
    assert all(r.is_active for r in rows)
    assert all(r.tags == [] for r in rows)
    assert all(r.inception_date is None for r in rows)
    assert db.query(LtEtf).filter(LtEtf.ticker == "XIU.TO").one().data_source == (
        "yfinance"
    )


def test_seed_universe_creates_static_universe_with_full_membership(db: Session):
    conn = db.connection()
    mig.seed_roster(conn)
    mig.seed_universe(conn)
    mig.seed_universe(conn)  # re-runnable: keyed on universe name + ticker

    u = db.query(StockUniverse).filter(StockUniverse.name == mig.UNIVERSE_NAME).one()
    assert u.kind == "static"
    assert u.is_active is True
    assert u.criteria == {}

    # Must serialize — /universe/list 500s if uuid/created_at are NULL.
    StockUniverseResponse.model_validate(u, from_attributes=True)

    roster = {r.ticker: r for r in db.query(LtEtf).all()}
    ms = db.query(MonitoredStock).filter(MonitoredStock.universe_id == u.id).all()
    sut = (
        db.query(StockUniverseTicker)
        .filter(StockUniverseTicker.universe_id == u.id)
        .all()
    )
    assert {m.ticker for m in ms} == set(roster)
    assert {t.ticker for t in sut} == set(roster)
    assert len(ms) == 65 and len(sut) == 65
    for m in ms:
        assert m.company_name == roster[m.ticker].name
        assert m.data_source == roster[m.ticker].data_source
        assert m.asset_class == "stocks"
        assert m.is_active is True
        assert m.added_date is not None
    for t in sut:
        assert t.data_source == roster[t.ticker].data_source
        assert t.asset_class == "stocks"


def test_seed_universe_skips_inactive_roster_rows(db: Session):
    conn = db.connection()
    mig.seed_roster(conn)
    db.query(LtEtf).filter(LtEtf.ticker == "ARKK").update({"is_active": False})
    db.flush()
    mig.seed_universe(conn)

    u = db.query(StockUniverse).filter(StockUniverse.name == mig.UNIVERSE_NAME).one()
    tickers = {
        m.ticker
        for m in db.query(MonitoredStock).filter(MonitoredStock.universe_id == u.id)
    }
    assert "ARKK" not in tickers
    assert len(tickers) == 64


def test_seed_universe_survives_sequence_behind_explicit_ids(db: Session):
    """Fresh-DB regression: earlier seed migrations insert explicit ids (1, 2)
    without advancing the SERIAL sequence, so a bare INSERT would collide."""
    conn = db.connection()
    seq = conn.execute(
        sa.text("SELECT pg_get_serial_sequence('stock_universes', 'id')")
    ).scalar()
    nxt = conn.execute(
        sa.text("SELECT nextval(CAST(:s AS regclass))"), {"s": seq}
    ).scalar()
    # Rewind so the next nextval() returns `nxt`, then occupy `nxt` explicitly —
    # the exact state c7d8e9f0a1b2/b1c2d3e4f5a6 leave behind on an empty DB.
    conn.execute(
        sa.text("SELECT setval(CAST(:s AS regclass), :v, false)"), {"s": seq, "v": nxt}
    )
    conn.execute(
        sa.text("""
        INSERT INTO stock_universes (id, uuid, name, criteria, kind, is_active,
                                     created_at)
        VALUES (:id, gen_random_uuid(), 'Explicit Id', CAST('{}' AS json),
                'screened', true, now())
    """),
        {"id": nxt},
    )

    mig.seed_roster(conn)
    mig.seed_universe(conn)

    u = db.query(StockUniverse).filter(StockUniverse.name == mig.UNIVERSE_NAME).one()
    assert u.id > nxt


def test_seed_universe_ignores_same_named_user_universe(db: Session):
    """A user-created screened universe that happens to share the name must not
    be adopted: it gets no roster rows and keeps kind='screened'."""
    conn = db.connection()
    user_u = StockUniverse(name=mig.UNIVERSE_NAME, criteria={"min_volume": 1})
    db.add(user_u)
    db.flush()

    mig.seed_roster(conn)
    mig.seed_universe(conn)

    db.refresh(user_u)
    assert user_u.kind == "screened"
    assert (
        db.query(MonitoredStock).filter(MonitoredStock.universe_id == user_u.id).count()
        == 0
    )
    assert (
        db.query(StockUniverseTicker)
        .filter(StockUniverseTicker.universe_id == user_u.id)
        .count()
        == 0
    )

    static_u = (
        db.query(StockUniverse)
        .filter(StockUniverse.name == mig.UNIVERSE_NAME, StockUniverse.kind == "static")
        .one()
    )
    assert static_u.id != user_u.id
    assert (
        db.query(MonitoredStock)
        .filter(MonitoredStock.universe_id == static_u.id)
        .count()
        == 65
    )


def test_remove_static_universe_spares_same_named_user_universe(db: Session):
    """Downgrade cleanup deletes only the static universe and its membership; a
    user universe sharing the name keeps its row and its monitored stocks."""
    conn = db.connection()
    user_u = StockUniverse(name=mig.UNIVERSE_NAME, criteria={"min_volume": 1})
    db.add(user_u)
    db.flush()
    db.add(
        MonitoredStock(
            ticker="AAPL", universe_id=user_u.id, added_date=date(2026, 1, 2)
        )
    )
    db.add(StockUniverseTicker(universe_id=user_u.id, ticker="AAPL"))
    db.flush()

    mig.seed_roster(conn)
    mig.seed_universe(conn)
    mig.remove_static_universe(conn)
    db.expire_all()

    assert db.query(StockUniverse).filter(StockUniverse.kind == "static").count() == 0
    survivors = db.query(StockUniverse).filter(StockUniverse.name == mig.UNIVERSE_NAME)
    assert [u.id for u in survivors] == [user_u.id]
    assert db.query(MonitoredStock).count() == 1
    assert db.query(StockUniverseTicker).count() == 1
