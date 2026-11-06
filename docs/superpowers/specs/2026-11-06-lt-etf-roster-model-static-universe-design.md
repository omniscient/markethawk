# LT-1a: ETF Roster Model + Seed, Static Universe Kind, Ticker Column Widening — Design Spec

**Issue:** #904
**Date:** 2026-11-06
**Status:** Proposed — pending implementation plan

## 1. Overview / Problem Statement

Issue #904 is the first of three serial slices (LT-1a/1b/1c) that split the "Roster + data
path" rollout slice of epic #902 (Long-term ETF investing, full design in
`docs/superpowers/specs/2026-11-06-long-term-etf-investing-design.md` §4.9, PR #903 — open,
not yet on `main`, but treated as approved-in-substance for the decisions it states outright).
The owner split the original LT-1 ticket after the first refinement pass because it bundled a
new data provider, two new tables, and a routing change together with the roster/universe work;
this spec covers only the three bullets the owner kept in LT-1a:

1. A new `lt_etf` roster model, migration, and seed of ~65 ETFs.
2. A `StockUniverse.kind` column (`screened`/`static`) and a static-universe `/refresh` path
   that mirrors the roster instead of running the screener.
3. Widening `StockAggregate.ticker` from `String(10)` to `String(20)`.

No new data is fetched in this slice — no provider, no dividends, no FX, no backfill (those are
LT-1b/LT-1c). The roster rows carry a `data_source` value (`massive`/`yfinance`) that nothing
reads yet; it exists so LT-1b's sync-path routing change has a column to read from without a
second migration.

**Done when:** `lt_etf` has ~65 active rows; the "Long-Term ETFs" static universe lists the
same tickers after calling `/refresh` on it; existing screened universes behave unchanged;
migrations apply clean on a throwaway DB and `alembic check` passes.

## 2. Requirements (from Q&A)

1. `lt_etf` table: `ticker` (unique), `name`, `segment`, `country` (`US`/`CA`), `currency`
   (listing currency), `exchange`, `data_source` (`massive`/`yfinance`), `inception_date`,
   `is_active`, `is_benchmark`, `tags`. Seeded with the exact ~65-ticker roster from the epic
   design §4.1 (reproduced in §3.1 below).
2. `StockUniverse.kind` column, `String`, default `"screened"` for all existing rows (including
   the pre-existing "Sector ETFs" universe — its behavior is unchanged by this migration), new
   value `"static"`.
3. One `StockUniverse` row named "Long-Term ETFs", `kind="static"`, created by the same
   migration that creates and seeds `lt_etf` — not by an app-startup step. Its first
   `StockUniverseTicker`/`MonitoredStock` membership is built by that migration too, using the
   same roster-to-row mapping the static `/refresh` branch uses, so the two never disagree.
4. `discover_and_refresh` (`backend/app/services/universe_orchestrator.py`) gains a branch on
   `universe.kind`: `"static"` rebuilds membership from active `lt_etf` rows instead of calling
   `DiscoveryService.run_screen()`. The delete-then-recreate shape, the `MonitoredStock`+
   `StockUniverseTicker` pair-insert, and the cached-stats refresh at the end are all reused
   unchanged for both kinds.
5. `StockAggregate.ticker` widened from `String(10)` to `String(20)` via a direct
   `op.alter_column`; no dependent DB view exists on `stock_aggregates` (confirmed by grep — the
   repo's only view, `active_monitored_stocks`, is defined on `monitored_stocks`), so no
   view drop/recreate is needed.
6. Existing screened universes (including "Sector ETFs") must behave identically after this
   migration: `kind` defaults to `"screened"`, and the `discover_and_refresh` branch for
   `"screened"` is the untouched, pre-existing code path.

## 3. Architecture / Approach

### 3.1 `lt_etf` model and seed data

New file `backend/app/models/lt_etf.py`:

```python
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
```

`ticker` is `String(20)` (matching the widened `StockAggregate.ticker`, not the
`StockUniverseTicker`/`MonitoredStock` `String(50)` — 20 is enough for the longest roster ticker,
`BOTZ`/`XIU.TO`-shaped strings, with headroom). `tags` follows the repo's existing JSON-with-JSONB-variant
convention for list-shaped columns (`NewsArticle.tickers`, `MonitoredStock.stock_metadata`) — no
Postgres `ARRAY` column exists anywhere in this codebase, so introducing one here would be a new
pattern for no benefit. `exchange` is `String(20)`, matching `MarketHoliday.exchange`,
`FuturesContract.exchange`, and `ActiveWatchlist.exchange` — all `String(20)`.

Register in `backend/app/models/__init__.py`: one `from app.models.lt_etf import LtEtf` line
plus an `__all__` entry, matching every other model.

**Seed data (~65 rows, from epic design §4.1):** one row per ticker below. `country`/`currency`/
`data_source` are mechanically derived: `.TO` suffix → `country="CA"`, `currency="CAD"`,
`data_source="yfinance"`, `exchange="TSX"`; everything else → `country="US"`, `currency="USD"`,
`data_source="massive"`, `exchange="NYSEARCA"`. The `"NYSEARCA"` label is a deliberately coarse,
single shared value for every US row — it is not the precise listing venue for each ticker (e.g.
`QQQ` actually lists on Nasdaq) — because nothing in this slice or in LT-1b/1c reads `exchange`
for routing or filtering; only `data_source` drives routing. A one-line comment in the migration
says so, so a future reader doesn't mistake it for verified data. `is_benchmark=true` only for
`SPY`; everything else `false`. `is_active=true` for all seeded rows. `inception_date` is left
`NULL` for all rows — the epic design lists inception date as a roster column but no inception
dates are given in the design doc or the issue, and researching 65 historical listing dates has
no bearing on this slice's done-when checks; a later slice can backfill it without a schema
change. `tags` is `[]` for all rows — the epic's cross-country grouping tags (e.g. `"energy"`,
`"gold"`) are called out as "not used in 1a, just stored," and inventing tag values now that no
code reads risks them being wrong when LT-4's constraint feature actually consumes them.

| Segment | US tickers | CA tickers (`.TO`) |
|---|---|---|
| Broad market | SPY*, QQQ, DIA, IWM, VTI | XIU.TO, XIC.TO, VFV.TO |
| Style & size | VTV, VUG, VBR, MTUM, QUAL, SCHD | — |
| Sectors | XLK, XLF, XLE, XLV, XLI, XLY, XLP, XLU, XLB, XLRE, XLC | XEG.TO, XFN.TO, ZEB.TO, XIT.TO, XMA.TO, XGD.TO, ZUT.TO, XRE.TO, ZPR.TO |
| Bonds & rates | BND, TLT, IEF, SHY, LQD, HYG, TIP | XBB.TO, XSB.TO, ZFL.TO |
| Commodities & miners | GLD, SLV, USO, DBC, GDX | — |
| International | VEA, VWO, EWJ, EWZ | XEF.TO, XEC.TO |
| Crypto | IBIT, ETHA | BTCC.TO, ETHX.TO |
| Tech themes | SMH, BOTZ, AIQ, CIBR, CLOU, ARKK | — |

(*`SPY` is `is_benchmark=true`.) This is 65 tickers (54 US + 11 CA): 8+6+20+10+5+6+4+6 by
segment. `name` is each fund's standard long name (e.g. "SPDR S&P 500 ETF Trust" for `SPY`),
filled in at implementation time — the epic design doesn't spell out full names, and typing them
exactly is mechanical, not a design decision.

### 3.2 Migration: create `lt_etf`, seed it, create and populate the static universe

One new Alembic revision does all three things, following the repo's two closest precedents:
`b5e6f7a8b9c0_seed_timesfm_system_config.py`-style guarded raw-SQL seeding, and
`b1c2d3e4f5a6_seed_sector_etfs_universe.py`, which already seeds a static-ticker-list
`StockUniverse` (`"Sector ETFs"`, 11 SPDR tickers) entirely via raw `sa.text()` SQL with a
matching `downgrade()`. This migration goes further than that precedent in one way: the Sector
ETFs migration never populated `monitored_stocks`, only `stock_universe_tickers` — this
migration must populate both, because LT-1a's done-when check requires the static universe's
`MonitoredStock` rows to exist too (`discover_and_refresh` always writes both tables together for
every other universe, and the static branch must not special-case away half of that).

`upgrade()`:

1. `op.create_table("lt_etf", ...)` + `op.create_index` on `ticker` (unique).
2. Guarded, idempotent seed: `INSERT INTO lt_etf (...) SELECT * FROM (VALUES (...), (...), ...)
   AS v(...) WHERE NOT EXISTS (SELECT 1 FROM lt_etf WHERE lt_etf.ticker = v.ticker)` — one
   statement for all ~65 rows, keyed on `ticker`, re-runnable without duplicating rows.
3. `op.add_column("stock_universes", sa.Column("kind", sa.String(length=20),
   server_default="screened", nullable=False))` — matches the exact shape of the precedent
   `op.add_column(..., "asset_class", sa.String(length=50), server_default="stocks",
   nullable=False)` in `39cb3da5ccb4_add_asset_class_to_universe_models.py`. `server_default`
   backfills every existing row (including "Sector ETFs") to `"screened"` with no separate
   `UPDATE`.
4. Create the "Long-Term ETFs" universe, guarded by name (not the Sector ETFs migration's
   hardcoded `id=2`/`ON CONFLICT(id)` shortcut, which is fragile — this migration looks the row
   up by name instead of assuming an id):
   `INSERT INTO stock_universes (name, description, criteria, kind, is_active) SELECT
   'Long-Term ETFs', ..., '{}'::json, 'static', true WHERE NOT EXISTS (SELECT 1 FROM
   stock_universes WHERE name = 'Long-Term ETFs')`. `criteria` is `{}` — static universes don't
   use it, but the column is `NOT NULL`.
5. Build first membership from `lt_etf WHERE is_active`, into both tables, joining the
   universe by name to get its id:
   ```sql
   INSERT INTO stock_universe_tickers (universe_id, ticker, asset_class, data_source)
   SELECT su.id, e.ticker, 'stocks', e.data_source
   FROM lt_etf e, stock_universes su
   WHERE e.is_active AND su.name = 'Long-Term ETFs'
   AND NOT EXISTS (SELECT 1 FROM stock_universe_tickers sut
                   WHERE sut.universe_id = su.id AND sut.ticker = e.ticker)

   INSERT INTO monitored_stocks (ticker, company_name, universe_id, asset_class, data_source,
                                  added_date, is_active)
   SELECT e.ticker, e.name, su.id, 'stocks', e.data_source, CURRENT_DATE, true
   FROM lt_etf e, stock_universes su
   WHERE e.is_active AND su.name = 'Long-Term ETFs'
   AND NOT EXISTS (SELECT 1 FROM monitored_stocks ms
                   WHERE ms.universe_id = su.id AND ms.ticker = e.ticker)
   ```
   Screener-only `MonitoredStock` columns (`sector`, `industry`, `market_cap`, `stock_metadata`)
   are left at their column defaults (`NULL`/`{}`) — the roster has no price or fundamentals
   data, since nothing is fetched in this slice.
6. `op.alter_column("stock_aggregates", "ticker", type_=sa.String(length=20),
   existing_type=sa.String(length=10))` — direct widening, same shape as the precedent
   `fa2957d31876_expand_column_lengths.py` used for `monitored_stocks.ticker`/
   `stock_universe_tickers.ticker`, minus the view drop/recreate that migration needed (that
   view, `active_monitored_stocks`, depends on `monitored_stocks`, not `stock_aggregates`).

`downgrade()`: delete the membership rows for the "Long-Term ETFs" universe from both tables,
delete the universe row, drop the `kind` column, drop `lt_etf`, and narrow
`stock_aggregates.ticker` back to `String(10)` (only safe if no row written during the upgrade
window exceeds 10 chars — acceptable for a downgrade path with no data-safety guarantee, matching
the precedent migrations' downgrades).

### 3.3 `discover_and_refresh` static branch

`backend/app/services/universe_orchestrator.py`, immediately after the existing
`StockUniverse` lookup (~line 46) and before the `DiscoveryService` call:

```python
if universe.kind == "static":
    roster_rows = db.query(LtEtf).filter(LtEtf.is_active == True).all()
    results = [
        {
            "ticker": r.ticker,
            "company_name": r.name,
            "data_source": r.data_source,
        }
        for r in roster_rows
    ]
else:
    service = DiscoveryService(db)
    results = service.run_screen(universe.criteria or {})
```

The rest of the function — the delete-then-bulk-insert of `MonitoredStock`/`StockUniverseTicker`
(lines 56-90), the commit, and the cached-stats recompute (94-101) — is reused unchanged for both
branches, since `results` has the same shape either way (the loop already tolerates the
screener's extra fields like `sector`/`market_cap` being absent — it only reads the keys it
needs and leaves the rest at column defaults). This guarantees the migration's one-time seed
(§3.2 step 5) and a later `/refresh` call always produce an identical ticker set, because both
build membership from the same `lt_etf` rows with the same field mapping.

The router (`POST /{universe_id}/refresh`, `backend/app/routers/universe.py:306-316`) is
unchanged — no request/response shape change, still synchronous, matching every other universe's
`/refresh` call today.

### 3.4 `StockAggregate.ticker` widening

Covered in the migration (§3.2 step 6). No application code reads `StockAggregate.ticker`'s
length as a constraint (no `len(ticker) <= 10` checks found), so this is a pure schema change
with no code-side follow-up.

## 4. Alternatives Considered

- **App-startup seeding instead of a migration.** Rejected: the repo has never seeded data at
  startup (the FastAPI `lifespan` in `backend/app/main.py` only resets orphaned quality reports,
  clears Redis sync keys, and starts the websocket manager), and a startup step would re-run its
  existence check on every boot instead of once. The migration-based precedent
  (`b1c2d3e4f5a6_seed_sector_etfs_universe.py`) already does exactly this for a smaller static
  universe; extending it is less surprising than introducing a second seeding mechanism.
- **A Python `Enum` type or DB `CHECK` constraint for `StockUniverse.kind`.** Rejected: no model
  in this codebase uses `sa.Enum` or `CheckConstraint` (grepped `backend/app/models/*.py` —
  zero matches); every categorical column in this repo is a plain `String` with an
  application-level contract. Matching that is lower-friction than introducing the first enum
  type for a two-value column.
- **Researching the exact per-ticker listing exchange.** Rejected for this slice: `exchange` is
  not read by anything in LT-1a, LT-1b, or LT-1c's stated scope (routing is by `data_source`).
  Spending effort on per-ticker accuracy nothing consumes is waste; a coarse, clearly-labeled
  value is corrected later if a slice ever needs it (e.g. a per-exchange holiday calendar).
- **Extending `StockUniverseTicker`/`MonitoredStock` directly instead of a separate `lt_etf`
  table.** Rejected: the issue and epic design both specify a dedicated roster table as the
  "source of truth," with the universe as a "mirror" rebuilt by `/refresh`. Folding roster-only
  fields (`segment`, `is_benchmark`, `tags`, `inception_date`) into the universe-membership
  tables would pollute those generic tables with long-term-investing-specific columns that every
  screened universe's rows would carry `NULL` for.

## 5. Open Questions (non-blocking)

- Exact `name` strings and `inception_date` values for all 65 roster rows are left to the
  implementer to fill in mechanically at write time (§3.1) — not a design decision, just
  unfinished data entry in this doc.
- Whether `lt_etf.currency`/`country` should eventually become FK-validated against a lookup
  table of ISO codes is not addressed; today every other currency/country-shaped column in this
  repo (none exist yet) would set precedent either way, so this is deferred until a second
  consumer appears.

## 6. Assumptions (flagged)

- PR #903's epic design is treated as approved-in-substance for the decisions it states outright
  (static universe via `kind`, roster as source of truth, no new data fetch in this slice); this
  spec only resolves the LT-1a-specific implementation gaps the issue's narrowed scope left open.
- `stock_aggregates` has no dependent DB view — confirmed directly in this refinement pass (not
  just inherited from the epic doc's recon) by grepping every `CREATE VIEW`/`CREATE OR REPLACE
  VIEW` in `backend/app/alembic/versions/`; the repo's only view, `active_monitored_stocks`, is
  defined on `monitored_stocks`.
- The pre-existing "Sector ETFs" universe keeps its current `/refresh` behavior (screener path,
  using its stored `criteria`) under the new `kind="screened"` default — this slice does not
  reclassify it to `"static"` even though it was itself seeded via a static ticker list in a
  migration, because the issue's scope is about the new roster/universe only, and reclassifying
  an unrelated existing universe is a behavior change nobody asked for here.
- Yahoo-suffix tickers (`.TO`) fit within `lt_etf.ticker String(20)` and the widened
  `stock_aggregates.ticker String(20)` — the longest roster ticker (`BOTZ`, `ETHX.TO`, etc.) is
  well under 20 characters; this was checked against the full roster list in §3.1, not assumed.
