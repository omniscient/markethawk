# LT-1a: ETF Roster Model + Seed, Static Universe Kind, Ticker Widening — Implementation Plan

**Issue:** #904

**Goal:** Add an `lt_etf` roster table seeded with the 65-ETF roster, a `StockUniverse.kind`
column (`screened` default / `static`) with a static `/refresh` path that mirrors active roster
rows, one seeded "Long-Term ETFs" static universe (with first membership), and widen
`stock_aggregates.ticker` to `String(20)`. No data is fetched.

**Architecture:** One new SQLAlchemy model (`LtEtf`) plus two column changes on existing models;
one Alembic revision that creates/seeds the roster, adds `kind`, creates + populates the
"Long-Term ETFs" universe, and widens the ticker column (seed SQL is factored into module-level
helpers so tests can execute the exact same SQL); a `kind == "static"` branch in
`universe_orchestrator.discover_and_refresh()` that swaps the screener call for an active-roster
query and builds static `MonitoredStock` rows without the screener-only fields. The screened
path stays the pre-existing code.

**Tech Stack:** FastAPI, SQLAlchemy 2.0 (sync), Alembic, PostgreSQL 15, pytest (real Postgres via
`tests/conftest.py` `db` fixture — testcontainers / `TEST_DATABASE_URL`).

**Spec:** `docs/superpowers/specs/2026-11-06-lt-etf-roster-model-static-universe-design.md`

---

## Spec deltas (found while planning — implement as written here)

1. **Static rows need their own `MonitoredStock` constructor.** Spec §3.3 says the existing
   loop "tolerates the screener's extra fields being absent". It doesn't: it subscripts
   `res["name"]`, `res["sector"]`, `res["market_cap"]`, `res["close_price"]`, `res["volume"]`
   (`universe_orchestrator.py:57-79`), so a `{ticker, company_name, data_source}` dict would
   raise `KeyError`. The plan keeps the spec's result-dict shape and its
   delete → pair-insert → commit → stats-refresh flow for both kinds, but adds an
   `if is_static:` constructor inside the loop. The static constructor sets only
   ticker/universe/date/active/asset_class/data_source/company_name — the same columns the
   migration's seed SQL writes. The screened constructor stays as it is.
2. **Roster split is 46 US + 19 CA, not "54 US + 11 CA".** Spec §3.1's table (copied verbatim
   from epic §4.1) holds 65 tickers. The per-segment sums (8+6+20+10+5+6+4+6 = 65) are right.
   Counting by country gives 46 US and 19 CA. Tests assert 46/19.
3. **Raw-SQL universe/membership inserts set `uuid`, `created_at`, `updated_at` explicitly.**
   `StockUniverseResponse` (`app/schemas/universe.py:35-43`) requires non-null `uuid` and
   `created_at`. The model fills them Python-side only, and the DB server defaults depend on
   how each table was first created. If the migration leaves them out, `GET /universe/list`
   can return 500. The migration uses `gen_random_uuid()` (built into PG 13+, and the stack
   runs `postgres:15-alpine`) and `now() AT TIME ZONE 'utc'`, which matches the naive-UTC
   `utc_now()`. `monitored_stocks.added_date` uses `(now() AT TIME ZONE 'America/New_York')::date`
   to match `get_market_today()`. That is the spec's "CURRENT_DATE", made tz-correct.
   `monitored_stocks.metadata` is left out, so it falls back to its column default (spec §3.2
   step 5).
4. **Bump the `stock_universes` id sequence before the universe insert.** The spec's
   `INSERT ... SELECT ... WHERE NOT EXISTS` relies on SERIAL `nextval`. Two earlier
   migrations, `c7d8e9f0a1b2` ("Default Universe", id=1) and `b1c2d3e4f5a6` ("Sector ETFs",
   id=2), insert explicit ids, and no migration calls `setval`. On a fresh DB (CI's
   `alembic upgrade head`, the Task 6 throwaway DB) `nextval` therefore returns 1 and the
   insert fails with a duplicate-pkey error. `seed_universe()` first moves the sequence up
   with `setval(seq, GREATEST(MAX(id), last_value, 1))`, which never moves it down, and
   `test_seed_universe_survives_sequence_behind_explicit_ids` covers this case.

**Known limitation (unchanged by this slice, closed by LT-1b):** nothing reads `data_source`
yet, so the nightly `sync_universe_aggregates_nightly` (iterates all active universes) will
request `.TO` tickers from Massive and get empty results. No new failure mode. It is just a
no-op for the 19 CA tickers until LT-1b routes on `data_source`.

## File Structure

| File | Action | Responsibility |
|---|---|---|
| `backend/app/models/lt_etf.py` | Create | `LtEtf` roster ORM model |
| `backend/app/models/__init__.py` | Modify | Import + `__all__` entry for `LtEtf` |
| `backend/app/models/stock_universe.py` | Modify | Add `kind` column |
| `backend/app/models/stock_aggregate.py` | Modify | `ticker` → `String(20)` |
| `backend/app/alembic/versions/f8f6c8fc1c83_add_lt_etf_roster_static_universe.py` | Create | Create + seed `lt_etf`, add `kind`, seed "Long-Term ETFs" universe + membership, widen ticker |
| `backend/app/services/universe_orchestrator.py` | Modify | `kind == "static"` branch in `discover_and_refresh` |
| `backend/tests/fixtures/lt_etf.py` | Create | `load_lt_etf_migration()` helper (imports the revision module by path) |
| `backend/tests/models/test_lt_etf_model.py` | Create | Model/column-shape tests |
| `backend/tests/models/test_lt_etf_roster_migration.py` | Create | Roster-data tests + seed-SQL tests against real Postgres |
| `backend/tests/services/test_universe_orchestrator.py` | Create | Static vs screened `discover_and_refresh` tests |
| `backend/tests/api/test_universe.py` | Modify | Done-when API test: seeded universe → `/refresh` → same tickers; `/list` still 200 |
| `docs/database-schema.md` | Regenerated | Auto-written by `alembic/env.py` after `upgrade` — commit if it changes |

All commands below run from `backend/` unless stated otherwise.

**Commit hygiene (every commit step):** a `ruff-format` pre-commit hook is installed, and
several new lines (some `ROSTER` tuples, long test lines) exceed 88 chars. Before each
`git commit`, run `ruff format <that step's files> && ruff check --fix <that step's files>`.
If the hook still rewrites files and aborts the commit, `git add` the same files again and
re-run the same commit command. Imports in `tests/api/test_universe.py` must stay
isort-ordered: `tests.fixtures.lt_etf` sorts after `tests.fixtures.core`.

---

## Task 1: `LtEtf` model + registration

**Files:** `backend/app/models/lt_etf.py` (create), `backend/app/models/__init__.py` (modify),
`backend/tests/models/test_lt_etf_model.py` (create)

- [ ] **Step 1.1 — Write the failing test.** Create `backend/tests/models/test_lt_etf_model.py`:

```python
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
```

- [ ] **Step 1.2 — Verify it fails.**
  `python -m pytest tests/models/test_lt_etf_model.py -v`
  Expected: 3 failures — `AssertionError: assert 'LtEtf' in [...]` / `ImportError: cannot import name 'LtEtf'`.

- [ ] **Step 1.3 — Implement the model.** Create `backend/app/models/lt_etf.py`:

```python
"""
LtEtf SQLAlchemy model.

Long-term ETF roster — the source of truth for the "Long-Term ETFs" static
universe (StockUniverse.kind == "static"). The universe's StockUniverseTicker /
MonitoredStock rows are a mirror rebuilt from active roster rows by /refresh.

data_source values
──────────────────
  massive   — US listings (Polygon/Massive path)
  yfinance  — TSX listings (".TO" suffix); routed by LT-1b, unread in LT-1a
"""

from sqlalchemy import JSON, Boolean, Column, Date, DateTime, Integer, String
from sqlalchemy.dialects.postgresql import JSONB

from app.core.database import Base
from app.utils.time import utc_now


class LtEtf(Base):
    __tablename__ = "lt_etf"

    id = Column(Integer, primary_key=True, index=True)
    ticker = Column(String(20), nullable=False, unique=True, index=True)
    name = Column(String(255), nullable=False)
    segment = Column(String(50), nullable=False)
    country = Column(String(2), nullable=False)  # "US" | "CA"
    currency = Column(String(3), nullable=False)  # "USD" | "CAD"
    exchange = Column(String(20), nullable=True)
    data_source = Column(String(50), nullable=False, default="massive")
    inception_date = Column(Date, nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)
    is_benchmark = Column(Boolean, nullable=False, default=False)
    tags = Column(JSON().with_variant(JSONB, "postgresql"), default=list)
    created_at = Column(DateTime, default=utc_now)

    def __repr__(self) -> str:
        return f"<LtEtf {self.ticker} {self.segment}>"
```

- [ ] **Step 1.4 — Register the model** (memory `[PATTERN]`: every model must be imported in
  `models/__init__.py` or `create_all`/autogenerate won't see it). In
  `backend/app/models/__init__.py`, add the import in alphabetical position (after
  `from app.models.futures_rollover import FuturesRollover`):

```python
from app.models.lt_etf import LtEtf
```

  and append `"LtEtf",` to `__all__` (after `"ReplayTrade",`).

- [ ] **Step 1.5 — Verify it passes.**
  `python -m pytest tests/models/test_lt_etf_model.py -v`
  Expected: `3 passed`.

- [ ] **Step 1.6 — Commit.**
  `git add app/models/lt_etf.py app/models/__init__.py tests/models/test_lt_etf_model.py && git commit -m "feat(models): add LtEtf roster model (#904)"`

---

## Task 2: `StockUniverse.kind` + `StockAggregate.ticker` widening (models)

**Files:** `backend/app/models/stock_universe.py`, `backend/app/models/stock_aggregate.py`,
`backend/tests/models/test_lt_etf_model.py` (extend)

- [ ] **Step 2.1 — Write the failing tests.** Append to `backend/tests/models/test_lt_etf_model.py`:

```python
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
```

- [ ] **Step 2.2 — Verify they fail.**
  `python -m pytest tests/models/test_lt_etf_model.py -v`
  Expected: 3 new failures (`AttributeError: kind` ×2, `assert 10 == 20`).

- [ ] **Step 2.3 — Add `kind`.** In `backend/app/models/stock_universe.py`, after
  `is_active = Column(Boolean, default=True)` add:

```python
    # "screened" — /refresh runs DiscoveryService.run_screen(criteria)
    # "static"   — /refresh mirrors active lt_etf roster rows (criteria unused)
    kind = Column(
        String(20), nullable=False, default="screened", server_default="screened"
    )
```

- [ ] **Step 2.4 — Widen the ticker.** In `backend/app/models/stock_aggregate.py` change
  `ticker = Column(String(10), nullable=False, index=True)` to:

```python
    ticker = Column(String(20), nullable=False, index=True)
```

- [ ] **Step 2.5 — Verify they pass.**
  `python -m pytest tests/models/test_lt_etf_model.py -v`
  Expected: `6 passed`.

- [ ] **Step 2.6 — Commit.**
  `git add app/models/stock_universe.py app/models/stock_aggregate.py tests/models/test_lt_etf_model.py && git commit -m "feat(models): StockUniverse.kind + widen StockAggregate.ticker to 20 (#904)"`

---

## Task 3: Alembic revision — roster seed, `kind`, static universe, ticker widening

**Files:** `backend/app/alembic/versions/f8f6c8fc1c83_add_lt_etf_roster_static_universe.py`
(create), `backend/tests/fixtures/lt_etf.py` (create),
`backend/tests/models/test_lt_etf_roster_migration.py` (create)

Current single head is `e2f3a4b5c6d7` (verified with `ScriptDirectory.get_heads()`); the new
revision's `down_revision` is that. Seeding follows the memory `[AVOID]` entry from #904's
refine: seed in the migration (not app startup), guarded/idempotent, keyed on natural keys
(`ticker`, universe `name`), never a hardcoded id. The revision id `f8f6c8fc1c83` is a
random 12-hex string, per memory `[AVOID]` in `dark-factory-ops.md`: never use a
hex-sequence id like `a1b2c3d4e5f6`, because sibling branches would derive the same id and
collide. Before creating the file, confirm it is still unused:
`ls app/alembic/versions/ | grep -c f8f6c8fc1c83` → `0`. If the head has moved off
`e2f3a4b5c6d7` by implementation time (`python -m alembic heads`), set `down_revision` to the
new head and update `test_revision_chains_onto_current_head` to match.

- [ ] **Step 3.1 — Write the test-loader fixture.** Create `backend/tests/fixtures/lt_etf.py`:

```python
"""Load the LT-1a roster migration module so tests execute its exact seed SQL."""

import importlib.util
from pathlib import Path
from types import ModuleType

MIGRATION_PATH = (
    Path(__file__).resolve().parents[2]
    / "app"
    / "alembic"
    / "versions"
    / "f8f6c8fc1c83_add_lt_etf_roster_static_universe.py"
)


def load_lt_etf_migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "lt_etf_roster_migration", MIGRATION_PATH
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
```

- [ ] **Step 3.2 — Write the failing tests.** Create
  `backend/tests/models/test_lt_etf_roster_migration.py`:

```python
"""Roster data + seed-SQL tests for revision f8f6c8fc1c83 (#904).

The seed helpers run against the test DB (created by Base.metadata.create_all),
so these tests exercise the exact SQL the migration runs.
"""

from collections import Counter

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
    nxt = conn.execute(sa.text("SELECT nextval(CAST(:s AS regclass))"), {"s": seq}).scalar()
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
```

- [ ] **Step 3.3 — Verify they fail.**
  `python -m pytest tests/models/test_lt_etf_roster_migration.py -v`
  Expected: collection error — `FileNotFoundError` for
  `.../f8f6c8fc1c83_add_lt_etf_roster_static_universe.py`.

- [ ] **Step 3.4 — Implement the migration.** Create
  `backend/app/alembic/versions/f8f6c8fc1c83_add_lt_etf_roster_static_universe.py`:

```python
"""add_lt_etf_roster_static_universe

Creates + seeds the lt_etf roster (65 ETFs, epic #902 §4.1), adds
stock_universes.kind ("screened" default / "static"), creates the static
"Long-Term ETFs" universe with its first membership (same roster-to-row mapping
as discover_and_refresh's static branch), and widens stock_aggregates.ticker
to VARCHAR(20). No dependent view on stock_aggregates (the only view,
active_monitored_stocks, is on monitored_stocks).

Revision ID: f8f6c8fc1c83
Revises: e2f3a4b5c6d7
Create Date: 2026-11-07 09:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "f8f6c8fc1c83"
down_revision: Union[str, None] = "e2f3a4b5c6d7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

UNIVERSE_NAME = "Long-Term ETFs"
UNIVERSE_DESCRIPTION = (
    "Static mirror of the active lt_etf roster (long-term ETF investing, #902)"
)

# (ticker, name, segment) — epic #902 §4.1 roster, 46 US + 19 CA = 65.
ROSTER: list[tuple[str, str, str]] = [
    # Broad market
    ("SPY", "SPDR S&P 500 ETF Trust", "Broad market"),
    ("QQQ", "Invesco QQQ Trust", "Broad market"),
    ("DIA", "SPDR Dow Jones Industrial Average ETF Trust", "Broad market"),
    ("IWM", "iShares Russell 2000 ETF", "Broad market"),
    ("VTI", "Vanguard Total Stock Market ETF", "Broad market"),
    ("XIU.TO", "iShares S&P/TSX 60 Index ETF", "Broad market"),
    ("XIC.TO", "iShares Core S&P/TSX Capped Composite Index ETF", "Broad market"),
    ("VFV.TO", "Vanguard S&P 500 Index ETF", "Broad market"),
    # Style & size
    ("VTV", "Vanguard Value ETF", "Style & size"),
    ("VUG", "Vanguard Growth ETF", "Style & size"),
    ("VBR", "Vanguard Small-Cap Value ETF", "Style & size"),
    ("MTUM", "iShares MSCI USA Momentum Factor ETF", "Style & size"),
    ("QUAL", "iShares MSCI USA Quality Factor ETF", "Style & size"),
    ("SCHD", "Schwab U.S. Dividend Equity ETF", "Style & size"),
    # Sectors
    ("XLK", "Technology Select Sector SPDR Fund", "Sectors"),
    ("XLF", "Financial Select Sector SPDR Fund", "Sectors"),
    ("XLE", "Energy Select Sector SPDR Fund", "Sectors"),
    ("XLV", "Health Care Select Sector SPDR Fund", "Sectors"),
    ("XLI", "Industrial Select Sector SPDR Fund", "Sectors"),
    ("XLY", "Consumer Discretionary Select Sector SPDR Fund", "Sectors"),
    ("XLP", "Consumer Staples Select Sector SPDR Fund", "Sectors"),
    ("XLU", "Utilities Select Sector SPDR Fund", "Sectors"),
    ("XLB", "Materials Select Sector SPDR Fund", "Sectors"),
    ("XLRE", "Real Estate Select Sector SPDR Fund", "Sectors"),
    ("XLC", "Communication Services Select Sector SPDR Fund", "Sectors"),
    ("XEG.TO", "iShares S&P/TSX Capped Energy Index ETF", "Sectors"),
    ("XFN.TO", "iShares S&P/TSX Capped Financials Index ETF", "Sectors"),
    ("ZEB.TO", "BMO Equal Weight Banks Index ETF", "Sectors"),
    ("XIT.TO", "iShares S&P/TSX Capped Information Technology Index ETF", "Sectors"),
    ("XMA.TO", "iShares S&P/TSX Capped Materials Index ETF", "Sectors"),
    ("XGD.TO", "iShares S&P/TSX Global Gold Index ETF", "Sectors"),
    ("ZUT.TO", "BMO Equal Weight Utilities Index ETF", "Sectors"),
    ("XRE.TO", "iShares S&P/TSX Capped REIT Index ETF", "Sectors"),
    ("ZPR.TO", "BMO Laddered Preferred Share Index ETF", "Sectors"),
    # Bonds & rates
    ("BND", "Vanguard Total Bond Market ETF", "Bonds & rates"),
    ("TLT", "iShares 20+ Year Treasury Bond ETF", "Bonds & rates"),
    ("IEF", "iShares 7-10 Year Treasury Bond ETF", "Bonds & rates"),
    ("SHY", "iShares 1-3 Year Treasury Bond ETF", "Bonds & rates"),
    ("LQD", "iShares iBoxx $ Investment Grade Corporate Bond ETF", "Bonds & rates"),
    ("HYG", "iShares iBoxx $ High Yield Corporate Bond ETF", "Bonds & rates"),
    ("TIP", "iShares TIPS Bond ETF", "Bonds & rates"),
    ("XBB.TO", "iShares Core Canadian Universe Bond Index ETF", "Bonds & rates"),
    ("XSB.TO", "iShares Core Canadian Short Term Bond Index ETF", "Bonds & rates"),
    ("ZFL.TO", "BMO Long Federal Bond Index ETF", "Bonds & rates"),
    # Commodities & miners
    ("GLD", "SPDR Gold Shares", "Commodities & miners"),
    ("SLV", "iShares Silver Trust", "Commodities & miners"),
    ("USO", "United States Oil Fund", "Commodities & miners"),
    ("DBC", "Invesco DB Commodity Index Tracking Fund", "Commodities & miners"),
    ("GDX", "VanEck Gold Miners ETF", "Commodities & miners"),
    # International
    ("VEA", "Vanguard FTSE Developed Markets ETF", "International"),
    ("VWO", "Vanguard FTSE Emerging Markets ETF", "International"),
    ("EWJ", "iShares MSCI Japan ETF", "International"),
    ("EWZ", "iShares MSCI Brazil ETF", "International"),
    ("XEF.TO", "iShares Core MSCI EAFE IMI Index ETF", "International"),
    ("XEC.TO", "iShares Core MSCI Emerging Markets IMI Index ETF", "International"),
    # Crypto
    ("IBIT", "iShares Bitcoin Trust ETF", "Crypto"),
    ("ETHA", "iShares Ethereum Trust ETF", "Crypto"),
    ("BTCC.TO", "Purpose Bitcoin ETF", "Crypto"),
    ("ETHX.TO", "CI Galaxy Ethereum ETF", "Crypto"),
    # Tech themes
    ("SMH", "VanEck Semiconductor ETF", "Tech themes"),
    ("BOTZ", "Global X Robotics & Artificial Intelligence ETF", "Tech themes"),
    ("AIQ", "Global X Artificial Intelligence & Technology ETF", "Tech themes"),
    ("CIBR", "First Trust NASDAQ Cybersecurity ETF", "Tech themes"),
    ("CLOU", "Global X Cloud Computing ETF", "Tech themes"),
    ("ARKK", "ARK Innovation ETF", "Tech themes"),
]


def roster_rows() -> list[dict]:
    """Expand ROSTER with the mechanically derived columns (".TO" → Canada)."""
    rows = []
    for ticker, name, segment in ROSTER:
        is_ca = ticker.endswith(".TO")
        rows.append(
            {
                "ticker": ticker,
                "name": name,
                "segment": segment,
                "country": "CA" if is_ca else "US",
                "currency": "CAD" if is_ca else "USD",
                # Coarse shared label, not the verified listing venue (e.g. QQQ is
                # Nasdaq) — nothing routes on exchange; data_source drives routing.
                "exchange": "TSX" if is_ca else "NYSEARCA",
                "data_source": "yfinance" if is_ca else "massive",
                "is_benchmark": ticker == "SPY",
            }
        )
    return rows


def seed_roster(conn) -> None:
    """Insert every roster row not already present (keyed on ticker)."""
    rows = roster_rows()
    values_sql = ", ".join(
        f"(:t{i}, :n{i}, :s{i}, :c{i}, :cur{i}, :x{i}, :ds{i}, :b{i})"
        for i in range(len(rows))
    )
    params: dict = {}
    for i, r in enumerate(rows):
        params.update(
            {
                f"t{i}": r["ticker"],
                f"n{i}": r["name"],
                f"s{i}": r["segment"],
                f"c{i}": r["country"],
                f"cur{i}": r["currency"],
                f"x{i}": r["exchange"],
                f"ds{i}": r["data_source"],
                f"b{i}": r["is_benchmark"],
            }
        )
    conn.execute(
        sa.text(f"""
        INSERT INTO lt_etf (ticker, name, segment, country, currency, exchange,
                            data_source, inception_date, is_active, is_benchmark,
                            tags, created_at)
        SELECT v.ticker, v.name, v.segment, v.country, v.currency, v.exchange,
               v.data_source, CAST(NULL AS date), true, v.is_benchmark,
               CAST('[]' AS jsonb), now() AT TIME ZONE 'utc'
        FROM (VALUES {values_sql})
            AS v(ticker, name, segment, country, currency, exchange,
                 data_source, is_benchmark)
        WHERE NOT EXISTS (SELECT 1 FROM lt_etf e WHERE e.ticker = v.ticker)
    """),
        params,
    )


def seed_universe(conn) -> None:
    """Create the static universe (keyed on name) and mirror active roster rows
    into stock_universe_tickers + monitored_stocks — the same mapping as
    universe_orchestrator.discover_and_refresh's static branch."""
    params = {"name": UNIVERSE_NAME, "desc": UNIVERSE_DESCRIPTION}
    # c7d8e9f0a1b2 (id=1) and b1c2d3e4f5a6 (id=2) insert explicit ids without
    # advancing the SERIAL sequence, so on a fresh DB (CI, throwaway) nextval
    # would return 1 and collide. Move the sequence up past MAX(id), never down.
    conn.execute(
        sa.text("""
        SELECT setval(q.s, GREATEST(
            (SELECT COALESCE(MAX(id), 0) FROM stock_universes),
            COALESCE(pg_sequence_last_value(q.s), 0),
            1))
        FROM (SELECT pg_get_serial_sequence('stock_universes', 'id')::regclass AS s) q
    """)
    )
    conn.execute(
        sa.text("""
        INSERT INTO stock_universes (uuid, name, description, criteria, kind,
                                     is_active, created_at, updated_at)
        SELECT gen_random_uuid(), :name, :desc, CAST('{}' AS json), 'static', true,
               now() AT TIME ZONE 'utc', now() AT TIME ZONE 'utc'
        WHERE NOT EXISTS (SELECT 1 FROM stock_universes WHERE name = :name)
    """),
        params,
    )
    conn.execute(
        sa.text("""
        INSERT INTO stock_universe_tickers (universe_id, ticker, asset_class,
                                            data_source, created_at)
        SELECT su.id, e.ticker, 'stocks', e.data_source, now() AT TIME ZONE 'utc'
        FROM lt_etf e, stock_universes su
        WHERE e.is_active AND su.name = :name
        AND NOT EXISTS (SELECT 1 FROM stock_universe_tickers sut
                        WHERE sut.universe_id = su.id AND sut.ticker = e.ticker)
    """),
        params,
    )
    # "metadata" is omitted, so it takes the column's server default: '{}' on a
    # migrated DB, NULL on a create_all-built test DB. ORM-built rows from
    # /refresh get {} from the Python default. Nothing reads it for static
    # universes.
    conn.execute(
        sa.text("""
        INSERT INTO monitored_stocks (ticker, company_name, universe_id, asset_class,
                                      data_source, added_date, is_active, scan_count,
                                      created_at, updated_at)
        SELECT e.ticker, e.name, su.id, 'stocks', e.data_source,
               CAST(now() AT TIME ZONE 'America/New_York' AS date), true, 0,
               now() AT TIME ZONE 'utc', now() AT TIME ZONE 'utc'
        FROM lt_etf e, stock_universes su
        WHERE e.is_active AND su.name = :name
        AND NOT EXISTS (SELECT 1 FROM monitored_stocks ms
                        WHERE ms.universe_id = su.id AND ms.ticker = e.ticker)
    """),
        params,
    )


def upgrade() -> None:
    op.create_table(
        "lt_etf",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("ticker", sa.String(length=20), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("segment", sa.String(length=50), nullable=False),
        sa.Column("country", sa.String(length=2), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("exchange", sa.String(length=20), nullable=True),
        sa.Column("data_source", sa.String(length=50), nullable=False),
        sa.Column("inception_date", sa.Date(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("is_benchmark", sa.Boolean(), nullable=False),
        sa.Column("tags", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_lt_etf_id"), "lt_etf", ["id"], unique=False)
    op.create_index(op.f("ix_lt_etf_ticker"), "lt_etf", ["ticker"], unique=True)

    conn = op.get_bind()
    seed_roster(conn)

    op.add_column(
        "stock_universes",
        sa.Column(
            "kind",
            sa.String(length=20),
            server_default="screened",
            nullable=False,
        ),
    )

    seed_universe(conn)

    op.alter_column(
        "stock_aggregates",
        "ticker",
        existing_type=sa.String(length=10),
        type_=sa.String(length=20),
        existing_nullable=False,
    )


def downgrade() -> None:
    # Narrowing fails if any stock_aggregates.ticker > 10 chars was written since
    # upgrade — acceptable, matching the precedent downgrades (no data-safety
    # guarantee).
    op.alter_column(
        "stock_aggregates",
        "ticker",
        existing_type=sa.String(length=20),
        type_=sa.String(length=10),
        existing_nullable=False,
    )

    conn = op.get_bind()
    params = {"name": UNIVERSE_NAME}
    conn.execute(
        sa.text("""
        DELETE FROM monitored_stocks
        WHERE universe_id IN (SELECT id FROM stock_universes WHERE name = :name)
    """),
        params,
    )
    conn.execute(
        sa.text("""
        DELETE FROM stock_universe_tickers
        WHERE universe_id IN (SELECT id FROM stock_universes WHERE name = :name)
    """),
        params,
    )
    conn.execute(sa.text("DELETE FROM stock_universes WHERE name = :name"), params)

    op.drop_column("stock_universes", "kind")
    op.drop_index(op.f("ix_lt_etf_ticker"), table_name="lt_etf")
    op.drop_index(op.f("ix_lt_etf_id"), table_name="lt_etf")
    op.drop_table("lt_etf")
```

- [ ] **Step 3.5 — Verify the tests pass.**
  `python -m pytest tests/models/test_lt_etf_roster_migration.py -v`
  Expected: `9 passed`.

- [ ] **Step 3.6 — Verify single head.**
  `python -m alembic heads`
  Expected: `f8f6c8fc1c83 (head)` (exactly one line).

- [ ] **Step 3.7 — Commit.**
  `git add app/alembic/versions/f8f6c8fc1c83_add_lt_etf_roster_static_universe.py tests/fixtures/lt_etf.py tests/models/test_lt_etf_roster_migration.py && git commit -m "feat(alembic): seed lt_etf roster + Long-Term ETFs static universe, widen aggregate ticker (#904)"`

---

## Task 4: `discover_and_refresh` static branch

**Files:** `backend/app/services/universe_orchestrator.py`,
`backend/tests/services/test_universe_orchestrator.py` (create)

- [ ] **Step 4.1 — Write the failing tests.** Create
  `backend/tests/services/test_universe_orchestrator.py`:

```python
"""discover_and_refresh: static (roster-mirror) vs screened (DiscoveryService) (#904)."""

from datetime import date
from unittest.mock import patch

from sqlalchemy.orm import Session

from app.models import LtEtf, MonitoredStock, StockUniverse, StockUniverseTicker
from app.services.universe_orchestrator import discover_and_refresh


def _roster(db: Session) -> None:
    db.add_all(
        [
            LtEtf(
                ticker="SPY",
                name="SPDR S&P 500 ETF Trust",
                segment="Broad market",
                country="US",
                currency="USD",
                exchange="NYSEARCA",
                data_source="massive",
                is_benchmark=True,
            ),
            LtEtf(
                ticker="XIU.TO",
                name="iShares S&P/TSX 60 Index ETF",
                segment="Broad market",
                country="CA",
                currency="CAD",
                exchange="TSX",
                data_source="yfinance",
            ),
            LtEtf(
                ticker="ARKK",
                name="ARK Innovation ETF",
                segment="Tech themes",
                country="US",
                currency="USD",
                exchange="NYSEARCA",
                data_source="massive",
                is_active=False,
            ),
        ]
    )
    db.flush()


def _universe(db: Session, kind: str, criteria: dict | None = None) -> StockUniverse:
    u = StockUniverse(
        name=f"{kind} test", criteria=criteria or {}, kind=kind, is_active=True
    )
    db.add(u)
    db.flush()
    return u


def test_static_refresh_mirrors_active_roster_without_screener(db: Session):
    u = _universe(db, "static")
    _roster(db)

    with patch("app.services.discovery_service.DiscoveryService") as ds:
        result = discover_and_refresh(u.id, db)

    ds.assert_not_called()
    assert result["status"] == "completed"
    assert result["added"] == 2

    ms = {
        m.ticker: m
        for m in db.query(MonitoredStock).filter(MonitoredStock.universe_id == u.id)
    }
    assert set(ms) == {"SPY", "XIU.TO"}
    assert ms["XIU.TO"].company_name == "iShares S&P/TSX 60 Index ETF"
    assert ms["XIU.TO"].data_source == "yfinance"
    assert ms["SPY"].data_source == "massive"
    assert all(m.asset_class == "stocks" and m.is_active for m in ms.values())
    assert all(m.sector is None and m.market_cap is None for m in ms.values())

    sut = {
        t.ticker: t.data_source
        for t in db.query(StockUniverseTicker).filter(
            StockUniverseTicker.universe_id == u.id
        )
    }
    assert sut == {"SPY": "massive", "XIU.TO": "yfinance"}

    db.refresh(u)
    assert u.cached_ticker_count == 2
    assert u.stats_refreshed_at is not None


def test_static_refresh_replaces_stale_membership(db: Session):
    u = _universe(db, "static")
    _roster(db)
    db.add(
        MonitoredStock(
            ticker="OLD", universe_id=u.id, added_date=date(2026, 1, 2), is_active=True
        )
    )
    db.add(StockUniverseTicker(universe_id=u.id, ticker="OLD"))
    db.flush()

    discover_and_refresh(u.id, db)

    assert {
        m.ticker
        for m in db.query(MonitoredStock).filter(MonitoredStock.universe_id == u.id)
    } == {"SPY", "XIU.TO"}
    assert {
        t.ticker
        for t in db.query(StockUniverseTicker).filter(
            StockUniverseTicker.universe_id == u.id
        )
    } == {"SPY", "XIU.TO"}


def test_screened_refresh_still_runs_screener(db: Session):
    u = _universe(db, "screened", {"min_price": 5})
    _roster(db)  # roster rows must be ignored for screened universes
    screen = [
        {
            "ticker": "AAPL",
            "name": "Apple Inc.",
            "sector": "Technology",
            "market_cap": 3_000_000_000_000,
            "close_price": 200.0,
            "volume": 1_000_000,
        }
    ]

    with patch("app.services.discovery_service.DiscoveryService") as ds:
        ds.return_value.run_screen.return_value = screen
        result = discover_and_refresh(u.id, db)

    ds.return_value.run_screen.assert_called_once_with({"min_price": 5})
    assert result["added"] == 1
    assert result["message"].endswith("from Discovery Engine.")

    ms = db.query(MonitoredStock).filter(MonitoredStock.universe_id == u.id).one()
    assert ms.ticker == "AAPL"
    assert ms.company_name == "Apple Inc."
    assert ms.sector == "Technology"
    assert ms.stock_metadata["source"] == "discovery_engine"
    assert ms.stock_metadata["close_price"] == 200.0
```

- [ ] **Step 4.2 — Verify they fail.**
  `python -m pytest tests/services/test_universe_orchestrator.py -v`
  Expected: the two static tests fail (the mocked `DiscoveryService` is called; `run_screen`
  returns a `MagicMock`, so `added == 0`). `test_screened_refresh_still_runs_screener`
  passes already. It is the regression guard for the screened path.

- [ ] **Step 4.3 — Implement.** In `backend/app/services/universe_orchestrator.py`:

  (a) Change the models import line to:

```python
from app.models import LtEtf, MonitoredStock, StockUniverse, StockUniverseTicker
```

  (b) Add this helper directly above `def discover_and_refresh`:

```python
def _static_roster_results(db: Session) -> list[dict]:
    """Membership rows for a static universe: every active lt_etf roster row.

    Same mapping as the f8f6c8fc1c83 seed migration, so the seeded membership
    and a later /refresh always produce the same ticker set.
    """
    roster_rows = (
        db.query(LtEtf).filter(LtEtf.is_active == True).order_by(LtEtf.ticker).all()
    )
    return [
        {
            "ticker": r.ticker,
            "company_name": r.name,
            "data_source": r.data_source,
        }
        for r in roster_rows
    ]
```

  (c) Replace the body of `discover_and_refresh` from the docstring through `db.commit()`
  (the first one, before the stats block) with:

```python
    """
    Refresh stocks in a universe.
    Clears MonitoredStock + StockUniverseTicker, then rebuilds membership from
    DiscoveryService.run_screen() (kind="screened") or from active lt_etf roster
    rows (kind="static"), bulk-inserts results, refreshes cached stats.
    Raises UniverseNotFoundError if the universe does not exist.
    """
    from app.services.discovery_service import DiscoveryService

    universe = db.query(StockUniverse).filter(StockUniverse.id == universe_id).first()
    if not universe:
        raise UniverseNotFoundError(universe_id)

    db.query(MonitoredStock).filter(MonitoredStock.universe_id == universe_id).delete()
    db.query(StockUniverseTicker).filter(
        StockUniverseTicker.universe_id == universe_id
    ).delete()

    is_static = universe.kind == "static"
    if is_static:
        results = _static_roster_results(db)
    else:
        service = DiscoveryService(db)
        criteria = universe.criteria or {}
        results = service.run_screen(criteria)

    added_count = 0
    for res in results:
        if is_static:
            # Roster rows carry no price/fundamentals — screener-only columns
            # (sector, market_cap, metadata) stay at their column defaults.
            monitored_stock = MonitoredStock(
                ticker=res["ticker"],
                universe_id=universe_id,
                added_date=get_market_today(),
                is_active=True,
                asset_class="stocks",
                data_source=res["data_source"],
                company_name=res["company_name"],
            )
        else:
            monitored_stock = MonitoredStock(
                ticker=res["ticker"],
                universe_id=universe_id,
                added_date=get_market_today(),
                is_active=True,
                asset_class=res.get("asset_class", "stocks"),
                data_source=res.get("data_source", "massive"),
                company_name=res["name"],
                sector=res["sector"],
                market_cap=res["market_cap"],
                stock_metadata={
                    "source": "discovery_engine",
                    "close_price": res["close_price"],
                    "volume": res["volume"],
                    "primary_exchange": res.get("primary_exchange"),
                    "employees": res.get("employees"),
                    "sic_code": res.get("sic_code"),
                    "description_preview": (res.get("description") or "")[:100]
                    + "..."
                    if res.get("description")
                    else None,
                },
            )
        db.add(monitored_stock)

        stock_ticker = StockUniverseTicker(
            universe_id=universe_id,
            ticker=res["ticker"],
            asset_class=res.get("asset_class", "stocks"),
            data_source=res.get("data_source", "massive"),
            created_at=utc_now(),
        )
        db.add(stock_ticker)
        added_count += 1

    db.commit()
```

  The screened `MonitoredStock(...)` constructor is the existing one, indented one level.
  Its field values must stay the same: run `ruff format` and keep the original expressions.
  The stats block after it stays as it is.

  (d) Replace the final `return` with:

```python
    source = "ETF roster" if is_static else "Discovery Engine"
    return {
        "status": "completed",
        "scanned": "ALL",
        "added": added_count,
        "message": f"Successfully refreshed universe. Added {added_count} assets from {source}.",
    }
```

- [ ] **Step 4.4 — Verify they pass.**
  `python -m pytest tests/services/test_universe_orchestrator.py -v`
  Expected: `3 passed`.

- [ ] **Step 4.5 — Lint/format.**
  `ruff check app/services/universe_orchestrator.py app/models/__init__.py app/models/lt_etf.py app/alembic/versions/f8f6c8fc1c83_add_lt_etf_roster_static_universe.py tests/services/test_universe_orchestrator.py tests/models/ tests/fixtures/lt_etf.py && ruff format --check app/services/universe_orchestrator.py`
  Expected: `All checks passed!` and no files to reformat. If `ruff format --check` complains,
  run `ruff format` on the listed files and re-run step 4.4.

- [ ] **Step 4.6 — Commit.**
  `git add app/services/universe_orchestrator.py tests/services/test_universe_orchestrator.py && git commit -m "feat(universe): static universes refresh from the lt_etf roster (#904)"`

---

## Task 5: Done-when API test — seeded universe ↔ `/refresh` agree; screened unchanged

**Files:** `backend/tests/api/test_universe.py`

- [ ] **Step 5.1 — Write the test.** Append to `backend/tests/api/test_universe.py`
  (and add `from tests.fixtures.lt_etf import load_lt_etf_migration` to the imports):

```python
# ---------------------------------------------------------------------------
# Static "Long-Term ETFs" universe (#904)
# ---------------------------------------------------------------------------


def test_refresh_static_universe_lists_same_tickers_as_seed(db: Session):
    from app.models import LtEtf, StockUniverse

    mig = load_lt_etf_migration()
    conn = db.connection()
    mig.seed_roster(conn)
    mig.seed_universe(conn)
    uid = db.query(StockUniverse).filter(StockUniverse.name == mig.UNIVERSE_NAME).one().id
    roster = {t for (t,) in db.query(LtEtf.ticker).filter(LtEtf.is_active == True)}

    before = client.get(f"/api/v1/universe/{uid}/stocks")
    assert before.status_code == 200
    seeded = {s["ticker"] for s in before.json()}

    refreshed = client.post(f"/api/v1/universe/{uid}/refresh")
    assert refreshed.status_code == 200
    assert refreshed.json()["added"] == 65

    after = client.get(f"/api/v1/universe/{uid}/stocks")
    assert after.status_code == 200
    stocks = after.json()
    assert {s["ticker"] for s in stocks} == seeded == roster
    assert len(roster) == 65
    by_ticker = {s["ticker"]: s for s in stocks}
    assert by_ticker["XIU.TO"]["data_source"] == "yfinance"
    assert by_ticker["SPY"]["data_source"] == "massive"


def test_list_includes_seeded_static_universe(db: Session):
    mig = load_lt_etf_migration()
    conn = db.connection()
    mig.seed_roster(conn)
    mig.seed_universe(conn)

    response = client.get("/api/v1/universe/list?include_stats=false")

    assert response.status_code == 200
    assert mig.UNIVERSE_NAME in {u["name"] for u in response.json()}
```

- [ ] **Step 5.2 — Run the universe API tests.**
  `python -m pytest tests/api/test_universe.py tests/api/test_universe_by_ticker.py -v`
  Expected: all pass, including the existing
  `test_refresh_universe_returns_completed_status` (screened path, real `DiscoveryService`) and
  the two new tests. (Tasks 3–4 have already made the new tests pass. They pin the done-when
  check at the HTTP layer: if either fails, fix the code from Tasks 3–4, not the test.)

- [ ] **Step 5.3 — Commit.**
  `git add tests/api/test_universe.py && git commit -m "test(universe): static Long-Term ETFs universe refresh mirrors seeded roster (#904)"`

---

## Task 6: Migration on a throwaway DB — upgrade, `alembic check`, downgrade, re-upgrade

**Files:** none created; `docs/database-schema.md` may be regenerated by `alembic/env.py`.

**Shell-state rule:** each step below is one self-contained Bash call. Env vars do **not**
persist between tool calls, so Step 6.1 writes them to `/tmp/lt1a.env`, and every later
step starts by sourcing that file and running the guard. Never run `alembic` in this task
without the guard: an inherited `DATABASE_URL` pointing at the dev DB would make
`downgrade -1` revert a real migration.

- [ ] **Step 6.1 — Create a throwaway DB and write the env file.** Target the reachable
  Postgres (dev stack: the `postgres` service; factory: whatever
  `tests/utils/pg_discovery.probe_running_postgres()` returns). The scheme is normalised to
  plain `postgresql://` because `psycopg2.connect` rejects `postgresql+psycopg2://`.

```bash
cd backend
PG_URL=$(python -c "from tests.utils.pg_discovery import probe_running_postgres as p; print(p() or '')")
PG_URL="${PG_URL/postgresql+psycopg2:/postgresql:}"
[ -n "$PG_URL" ] || { echo "no reachable postgres"; exit 1; }
cat > /tmp/lt1a.env <<ENV
export THROWAWAY_URL="${PG_URL%/*}/lt1a_throwaway"
export DATABASE_URL="${PG_URL%/*}/lt1a_throwaway"
export POLYGON_API_KEY=dummy-key-for-ci
export JWT_SECRET_KEY=ci-test-only-not-secret-0123456789abcdef
export REDIS_PASSWORD=ci-redis-dummy-password-0123456789abcdef
ENV
. /tmp/lt1a.env
python - <<'PY'
import os, psycopg2
base = os.environ["THROWAWAY_URL"].rsplit("/", 1)[0] + "/postgres"
c = psycopg2.connect(base); c.autocommit = True
c.cursor().execute("DROP DATABASE IF EXISTS lt1a_throwaway")
c.cursor().execute("CREATE DATABASE lt1a_throwaway")
print("created")
PY
```
  Expected: `created`. If the probe role lacks `CREATEDB` (`permission denied to create
  database`), use the dev stack's superuser instead:
  `docker-compose exec postgres createdb -U postgres lt1a_throwaway`, then edit the two URLs
  in `/tmp/lt1a.env` to that server's credentials.

- [ ] **Step 6.2 — Upgrade from empty to head.**

```bash
cd backend && . /tmp/lt1a.env
case "$DATABASE_URL" in */lt1a_throwaway) ;; *) echo "REFUSING: DATABASE_URL is not the throwaway DB"; exit 1;; esac
python -m alembic upgrade head
```
  Expected: ends with `Running upgrade e2f3a4b5c6d7 -> f8f6c8fc1c83, add_lt_etf_roster_static_universe`, no traceback.

- [ ] **Step 6.3 — Verify seeded state.**

```bash
cd backend && . /tmp/lt1a.env
case "$DATABASE_URL" in */lt1a_throwaway) ;; *) echo "REFUSING: DATABASE_URL is not the throwaway DB"; exit 1;; esac
python - <<'PY'
import os, psycopg2
c = psycopg2.connect(os.environ["DATABASE_URL"]).cursor()
q = lambda s: (c.execute(s), c.fetchall())[1]
print("lt_etf active:", q("SELECT count(*) FROM lt_etf WHERE is_active")[0][0])
print("benchmarks:", q("SELECT ticker FROM lt_etf WHERE is_benchmark"))
print("by source:", sorted(q("SELECT data_source, count(*) FROM lt_etf GROUP BY 1")))
print("universe:", q("SELECT kind, uuid IS NOT NULL, created_at IS NOT NULL FROM stock_universes WHERE name='Long-Term ETFs'"))
print("sut:", q("SELECT count(*) FROM stock_universe_tickers sut JOIN stock_universes su ON su.id=sut.universe_id WHERE su.name='Long-Term ETFs'")[0][0])
print("ms:", q("SELECT count(*) FROM monitored_stocks ms JOIN stock_universes su ON su.id=ms.universe_id WHERE su.name='Long-Term ETFs'")[0][0])
print("other kinds:", q("SELECT DISTINCT kind FROM stock_universes WHERE name <> 'Long-Term ETFs'"))
print("ticker len:", q("SELECT character_maximum_length FROM information_schema.columns WHERE table_name='stock_aggregates' AND column_name='ticker'")[0][0])
PY
```
  Expected:
```
lt_etf active: 65
benchmarks: [('SPY',)]
by source: [('massive', 46), ('yfinance', 19)]
universe: [('static', True, True)]
sut: 65
ms: 65
other kinds: [('screened',)]
ticker len: 20
```
  ("other kinds" is `[('screened',)]` because the Sector ETFs seed `b1c2d3e4f5a6` runs
  earlier in the chain. That proves the pre-existing universe got the `screened` default.)

- [ ] **Step 6.4 — Migration sync check.**

```bash
cd backend && . /tmp/lt1a.env
case "$DATABASE_URL" in */lt1a_throwaway) ;; *) echo "REFUSING: DATABASE_URL is not the throwaway DB"; exit 1;; esac
python -m alembic check
```
  Expected: `No new upgrade operations detected.`

- [ ] **Step 6.5 — Downgrade and re-upgrade (round trip + idempotency).**

```bash
cd backend && . /tmp/lt1a.env
case "$DATABASE_URL" in */lt1a_throwaway) ;; *) echo "REFUSING: DATABASE_URL is not the throwaway DB"; exit 1;; esac
python -m alembic downgrade -1
python -m alembic current
python -m alembic upgrade head
python -m alembic check
```
  Expected: `current` shows `e2f3a4b5c6d7`; the re-upgrade runs `e2f3a4b5c6d7 -> f8f6c8fc1c83`
  without error; `check` prints `No new upgrade operations detected.` Re-run Step 6.3: same
  output (65 / 65 / 65, no duplicates).

- [ ] **Step 6.6 — Drop the throwaway DB and the env file.**

```bash
cd backend && . /tmp/lt1a.env
python - <<'PY'
import os, psycopg2
base = os.environ["THROWAWAY_URL"].rsplit("/", 1)[0] + "/postgres"
c = psycopg2.connect(base); c.autocommit = True
c.cursor().execute("DROP DATABASE IF EXISTS lt1a_throwaway")
print("dropped")
PY
rm -f /tmp/lt1a.env
```
  Expected: `dropped`.

- [ ] **Step 6.7 — Commit the regenerated schema doc if it changed.**
  `git status --short docs/database-schema.md` (from the repo root) — if it shows ` M`, then
  `git add docs/database-schema.md && git commit -m "docs: regenerate database schema for lt_etf + stock_universes.kind (#904)"`.
  If clean, skip.

---

## Task 7: Regression suite + live validation

**Files:** none (validation only; fix-forward commits if anything fails)

- [ ] **Step 7.1 — Run the affected test suites.**
  `python -m pytest tests/models tests/api/test_universe.py tests/api/test_universe_by_ticker.py tests/services/test_universe_orchestrator.py tests/services/test_universe_stats_service.py tests/services/test_discovery_service.py tests/services/test_universe_export_service.py -q`
  Expected: all pass, `0 failed`.

- [ ] **Step 7.2 — Run the full backend suite.**
  `python -m pytest -q -x --ignore=tests/live_scanner`
  Expected: `0 failed`. If anything fails, compare with `main` (`git stash; pytest <that test>; git stash pop`). Fix it only if this change caused it.

- [ ] **Step 7.3 — Live validation (CLAUDE.md "Validating Changes Before Committing").**
  Where the dev stack is available:

```bash
docker-compose exec backend python -m alembic upgrade head
docker-compose logs backend --tail=10          # confirm reload, no traceback
UID_LT=$(curl -s "http://localhost:8000/api/v1/universe/list?include_stats=false" \
  | python -c "import sys,json; print(next(u['id'] for u in json.load(sys.stdin) if u['name']=='Long-Term ETFs'))")
curl -s -X POST -H "X-Requested-With: XMLHttpRequest" \
  "http://localhost:8000/api/v1/universe/$UID_LT/refresh" | python -m json.tool
curl -s "http://localhost:8000/api/v1/universe/$UID_LT/stocks" \
  | python -c "import sys,json; print(len(json.load(sys.stdin)))"
```
  Expected: `/refresh` → `"status": "completed"`, `"added": 65`,
  `"message": "...Added 65 assets from ETF roster."`; stocks count `65`. Then `/refresh` an
  existing screened universe (e.g. id 1) and confirm `"...from Discovery Engine."` still comes
  back. (Auth: the middleware returns 401 without a JWT cookie. Mint one with
  `TOKEN=$(docker-compose exec -T backend python -c "from app.core.auth import create_access_token; print(create_access_token('00000000-0000-0000-0000-000000000001'))")`
  and add `-b "access_token=$TOKEN"` to every `curl` above.) If no dev stack is
  reachable in this environment, record that in the PR body. Tasks 5–6 cover the same checks
  against real Postgres.

- [ ] **Step 7.4 — Final state check.**
  `git log --oneline main..HEAD` — expect the Task 1–6 commits on top of the pre-existing spec/memory/plan commits from refine + plan (`864401e`, `b9c2e31`, the plan-doc commit); `git status` clean.

- [ ] **Step 7.5 — Push** (headless rule: commit **and** push before the turn ends).
  `git push -u origin "$(git branch --show-current)"`
  Expected: the push succeeds and the remote branch is up to date.

---

## Self-review

- Issue line present (`**Issue:** #904`) ✔
- Every spec requirement mapped: R1 → Tasks 1, 3 · R2 → Tasks 2, 3 · R3 → Task 3
  (`seed_universe`), Task 5 · R4 → Task 4 · R5 → Tasks 2, 3, 6.3 · R6 → Task 4
  (`test_screened_refresh_still_runs_screener`), Task 5 (existing refresh test), Task 6.3
  ("other kinds") ✔
- Done-when: 65 active rows (6.3), static universe same tickers after `/refresh` (5.1, 7.3),
  screened unchanged (4.1, 5.2), throwaway DB + `alembic check` (6.2–6.5) ✔
- Out of scope respected: no provider, sync routing, dividends, FX, backfill; no
  `StockUniverseResponse.kind` exposure; "Sector ETFs" not reclassified ✔
- No placeholders: all 65 names, the revision id, and every command are concrete ✔
