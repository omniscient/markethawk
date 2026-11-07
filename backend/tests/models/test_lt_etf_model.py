"""Shape tests for the LT-1a roster model and the two widened/added columns (#904)."""

from sqlalchemy.orm import Session


def test_lt_etf_registered_in_models_package():
    import app.models as models

    assert "LtEtf" in models.__all__
    assert models.LtEtf.__tablename__ == "lt_etf"


def test_lt_etf_column_shapes():
    from app.models import LtEtf

    cols = LtEtf.__table__.c
    assert cols.ticker.type.length == 20
    assert cols.ticker.unique is True
    assert cols.ticker.nullable is False
    assert cols.name.type.length == 255
    assert cols.segment.type.length == 50
    assert cols.country.type.length == 2
    assert cols.currency.type.length == 3
    assert cols.exchange.type.length == 20
    assert cols.exchange.nullable is True
    assert cols.data_source.type.length == 50
    assert cols.inception_date.nullable is True
    assert cols.is_active.nullable is False
    assert cols.is_benchmark.nullable is False


def test_lt_etf_python_defaults_on_insert(db: Session):
    from app.models import LtEtf

    row = LtEtf(
        ticker="VTI",
        name="Vanguard Total Stock Market ETF",
        segment="Broad market",
        country="US",
        currency="USD",
    )
    db.add(row)
    db.flush()
    db.refresh(row)

    assert row.data_source == "massive"
    assert row.is_active is True
    assert row.is_benchmark is False
    assert row.tags == []
    assert row.inception_date is None
    assert row.created_at is not None


def test_stock_universe_kind_column():
    from app.models import StockUniverse

    kind = StockUniverse.__table__.c.kind
    assert kind.type.length == 20
    assert kind.nullable is False
    assert kind.default.arg == "screened"
    assert kind.server_default.arg == "screened"


def test_stock_universe_kind_defaults_to_screened(db: Session):
    from app.models import StockUniverse

    u = StockUniverse(name="Default Kind", criteria={}, is_active=True)
    db.add(u)
    db.flush()
    db.refresh(u)

    assert u.kind == "screened"


def test_stock_aggregate_ticker_widened_to_20():
    from app.models import StockAggregate

    assert StockAggregate.__table__.c.ticker.type.length == 20
