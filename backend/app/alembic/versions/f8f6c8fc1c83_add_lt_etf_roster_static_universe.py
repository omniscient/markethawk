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
        WHERE NOT EXISTS (
            SELECT 1 FROM stock_universes WHERE name = :name AND kind = 'static'
        )
    """),
        params,
    )
    conn.execute(
        sa.text("""
        INSERT INTO stock_universe_tickers (universe_id, ticker, asset_class,
                                            data_source, created_at)
        SELECT su.id, e.ticker, 'stocks', e.data_source, now() AT TIME ZONE 'utc'
        FROM lt_etf e, stock_universes su
        WHERE e.is_active AND su.name = :name AND su.kind = 'static'
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
        WHERE e.is_active AND su.name = :name AND su.kind = 'static'
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
        sa.Column(
            "data_source",
            sa.String(length=50),
            nullable=False,
            server_default="massive",
        ),
        sa.Column("inception_date", sa.Date(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "is_benchmark", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
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
        WHERE universe_id IN (
            SELECT id FROM stock_universes WHERE name = :name AND kind = 'static'
        )
    """),
        params,
    )
    conn.execute(
        sa.text("""
        DELETE FROM stock_universe_tickers
        WHERE universe_id IN (
            SELECT id FROM stock_universes WHERE name = :name AND kind = 'static'
        )
    """),
        params,
    )
    conn.execute(
        sa.text("DELETE FROM stock_universes WHERE name = :name AND kind = 'static'"),
        params,
    )

    op.drop_column("stock_universes", "kind")
    op.drop_index(op.f("ix_lt_etf_ticker"), table_name="lt_etf")
    op.drop_index(op.f("ix_lt_etf_id"), table_name="lt_etf")
    op.drop_table("lt_etf")
