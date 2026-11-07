# LT-2: Nightly Total-Return ETF Signals + Read-Only Long-Term Page — Implementation Plan

**Issue:** #905

**Goal:** Add an `etf_signal_daily` table filled nightly (and on demand) from a total-return
close series built in memory from raw daily bars plus `lt_dividend` rows. Expose it through
read endpoints under `/api/v1/long-term`, and render it on a read-only `/long-term` page: a
header strip, on-sale cards, movers, trend split, a sortable/filterable roster table, and a
detail drawer that reuses `StockChart`.

**Architecture:** One new ORM model plus a migration. A new service subpackage
`services/long_term/` holds:
- `signals.py`: pure pandas math, the single per-ticker `compute_signals_for_ticker()`
  upsert, and the roster batch loop.
- `roster.py`: read helpers for the roster, detail, and overview payloads.

Around that sit a new router `routers/long_term.py` with Pydantic schemas in
`schemas/long_term.py`, and one batch Celery task `compute_etf_signals_nightly` with a fixed
02:30 UTC Tue–Sat beat slot. On the frontend: an API module `api/longTerm.ts`, a page package
`pages/LongTerm/` with React Query hooks, a route, and a sidebar entry. No new
service or container.

**Tech Stack:** FastAPI, SQLAlchemy 2.0 (sync), Alembic, PostgreSQL 15, pandas, Celery beat,
pytest (real Postgres via `tests/conftest.py` `db` fixture); React 19 + TypeScript, React
Query v5, Tailwind, lightweight-charts via `StockChart`, vitest + Testing Library.

**Spec:** `docs/superpowers/specs/2026-11-06-etf-signals-long-term-page-design.md`
(epic design: `docs/superpowers/specs/2026-11-06-long-term-etf-investing-design.md` on
branch `spec/long-term-etf-investing`, PR #903).

---

## Dependency gate (read first)

This slice consumes interfaces built by #904 (LT-1a), #912 (LT-1b), and #913 (LT-1c). None of
them is on `main` as of this plan (2026-11-07). The issue body says "Depends on: #913", and
#913 itself depends on #904 and #912. **Task 0 checks that they have landed.** If any check
fails, the implementer must stop, post an issue comment naming the missing interface, and
end the phase. Do not stub any of the missing pieces, per spec Requirement 1. This plan uses the shapes those slices'
specs and plans pin today:

| Interface | Owner | Shape this plan codes against |
|---|---|---|
| `app.models.LtEtf` (`lt_etf`) | #904 plan Task 1 | `ticker String(20) unique`, `name`, `segment String(50)` (values `"Broad market"`, `"Style & size"`, `"Sectors"`, `"Bonds & rates"`, `"Commodities & miners"`, `"International"`, `"Crypto"`, `"Tech themes"`), `country` (`"US"`/`"CA"`), `currency`, `exchange`, `data_source`, `inception_date`, `is_active`, `is_benchmark`, `tags` (JSON list) |
| `app.models.LtDividend` (`lt_dividend`) | #912 spec §3.5 | `ticker String(20)`, `ex_date Date`, `cash_amount Numeric`, `currency String(3)`, `source String(20)`, unique `(ticker, ex_date)` |
| `stock_aggregates.ticker` widened to `String(20)` | #904 | needed for `.TO` tickers |
| Daily bars for every active roster ticker (`timespan="day"`, `multiplier=1`) | #912 routing + #913 backfill/top-up | ~1250 rows per ticker, fewer for IBIT/ETHA/BTCC.TO/ETHX.TO |
| `backend/app/tasks/long_term.py` | #913 spec §3.3 | holds `sync_lt_dividends_nightly` / `sync_fx_rates_nightly`; this plan **appends** to it |
| Beat slots 02:00 / 02:15 UTC Tue–Sat | #913 spec §3.3 | dividend/FX top-up; signals go at 02:30 so they see that night's dividends |

## Spec deltas and pinned decisions (found while planning — implement as written here)

1. **No bars means no row.** Spec §2 R5 says every active roster ticker gets a row every
   trading day. `close` is `NOT NULL`, so a ticker with **zero** stored daily bars can't
   produce one. `compute_signals_for_ticker` returns `None`. The batch logs it under
   `skipped_no_bars`, and `POST /recompute` answers 409. After #913's backfill this case
   doesn't come up. The done-when SQL check in Task 14 catches it if it does.
2. **The row's `date` is the latest stored bar on or before `as_of`, not `as_of` itself.**
   The nightly run uses `as_of = get_market_today()` (02:30 UTC is still the previous session
   date in New York). On-demand recompute uses the same value. On a weekend or holiday this
   resolves to the last session. If a ticker's feed is stale, its row lands on its own last
   bar date, and the stale ticker shows up in the overview's `stale_tickers` list.
3. **Bar date = UTC calendar date of `StockAggregate.timestamp`.** Massive stores day bars as
   naive UTC of New York midnight (04:00/05:00 UTC, `massive.py:150`). yfinance day bars are
   Toronto midnight, which gives the same UTC date. `tasks/quality.py` already groups day bars
   with `func.date(timestamp)`. Taking `.date()` of the naive UTC timestamp is right for both
   providers and also safe for a provider that stores midnight UTC.
4. **Units.** Every `ret_*`, `pct_from_sma_*`, `drawdown_*_pct`, `atr_14_pct`, and
   `rel_ret_1y_vs_benchmark` is stored in **percent** (`5.2` means +5.2%), the same as the
   epic's `(close / sma - 1) * 100` definitions. `pctile_*` and `on_sale_score` run 0–100.
5. **Calendar-offset returns.** `ret_X = (tr_close_today / tr_close_base - 1) * 100`, where
   `base` is the last bar dated on or before `row_date - offset`. The offsets are
   `1d = DateOffset(days=1)`, `1w = weeks=1`, `1m = months=1`, `3m = months=3`,
   `6m = months=6`, `1y = years=1`. With `days=1`, the base is the previous trading bar. All of
   these are 1-year-gated per spec §3.3: they stay `NULL` until `history_days >= 252`, and
   from then on they "compute normally".
   **Fallback rule:** 252 sessions can fall a few calendar days short of one year, and in the
   synthetic tests they always do. If `row_date - offset` is before the first stored bar, the
   base is the **first stored bar**. Only `ret_1y` can hit this, and only for an ETF's first
   few days past 252 bars. This rule does not add a second calendar-year gate that would leave
   `ret_1y` NULL at 252 bars, which the spec rules out. It never applies under 252 bars,
   because the 252-bar gate returns early.
6. **The total-return series is anchored at the row date.** For each ex-date `e` with
   `first_bar_date < e <= row_date`:
   - `close_prev_ex` is the raw close of the last bar dated before `e`.
   - The factor is `(close_prev_ex - cash_amount) / close_prev_ex`.
   - Every bar dated before `e` is multiplied by the factor, and factors compound.

   The row-date close is therefore unadjusted (`tr[-1] == raw close`). Dividends dated after
   `row_date` are ignored, so a historical recompute stays as-of correct. A dividend is
   skipped, with a warning, if it is ≤ 0 or ≥ `close_prev_ex`. Dividend currency is assumed
   to equal the listing currency; #912 stores both from the same provider.
7. **SMA values are in total-return space** (spec: "all return/SMA/... metrics use the
   total-return close series"). At the row date the TR close equals the raw close, so
   `pct_from_sma_*` is consistent. The drawer's SMA price lines therefore sit slightly below
   a raw-close SMA for dividend payers. That is intended and is stated in the drawer caption.
8. **Percentile rank.** `pct = window.rank(pct=True).iloc[-1]` (average ties), then
   `rank = pct * n` and `pctile = (rank - 1) / (n - 1) * 100`. That is the spec §3.3 formula
   written in terms of the pandas call it names.
9. **Benchmark** = the active `LtEtf` row with `is_benchmark = true`, falling back to `"SPY"`.
   The benchmark's own `rel_ret_1y_vs_benchmark` is `ret_1y - ret_1y = 0.0`. For other
   tickers it is `ret_1y - benchmark_row.ret_1y`, where `benchmark_row` is the benchmark's
   `etf_signal_daily` row **with the same `date`**. It is `NULL` if either side is NULL or that
   row is missing. The batch computes the benchmark first and commits it before the others.
10. **Overview semantics.**
    - Only active roster rows count, each joined to its **latest** signal row.
    - `on_sale` is the top `top_n` (default 8) by `on_sale_score` desc, NULL scores excluded.
    - `movers` holds the best and worst `movers_n` (default 5, spec §3.5) by `ret_1w` and by
      `ret_1m`, NULLs excluded.
    - `trend_split` has one entry per segment (sorted by segment name). Each entry has
      `above` (`above_sma_50 is True`), `below` (`False`), and `unknown` (no signal or NULL)
      ticker lists.
    - `expected_signal_date` is the previous NYSE trading day before today in New York.
      Weekends and `MarketHoliday(exchange="NYSE", event_type="full_close")` are skipped,
      which is the same holiday source as `tasks/quality.py:147`.
    - `is_stale = latest_signal_date is None or latest_signal_date < expected_signal_date`
      (epic §4.8 item 1).
    - `stale_tickers` lists active tickers whose latest signal date is earlier than
      `latest_signal_date`.
11. **Reporting currency** (header strip, epic §4.8 item 1) is read-only in this slice. It
    comes from `SystemConfig` key `long_term_reporting_currency`, default `"CAD"` (epic §7).
    No write path. LT-4 owns editing it.
12. **Ticker path params** accept `.TO` symbols, which `schemas/common.py`'s `Ticker` pattern
    rejects. The router does **not** define a new regex, because `common.py` forbids ad-hoc
    patterns. Instead it takes `Path(min_length=1, max_length=20)`, strips and uppercases the
    value, and validates it against the `lt_etf` roster. Anything not on the roster gets a
    404, which is stricter than a pattern.
13. **Pydantic field named `date`.** In the schema modules, import `datetime as dt` and
    annotate `date: dt.date`. A field named `date` annotated as `date` shadows the type under
    Pydantic v2 and fails at class build.
14. **Celery task module.** Append to `backend/app/tasks/long_term.py` (#913 creates it). If
    Task 0 finds it missing, Task 0 is a stop, not a create. `tasks/__init__.py` gains the
    import and `__all__` entry, and `tests/tasks/test_package_exports.py` gains the name.
15. **Detail drawer extras.** The drawer gets a **Recompute** button wired to
    `POST /etfs/{ticker}/recompute`. That is a derived-data write, in scope per spec R4. It
    also gets a SuperTrend checkbox (default on) for epic §4.8's "`showDoubleSuperTrend`
    toggle". `priceLines` is memoised because `StockChart` re-runs its draw effect whenever
    the array identity changes (`StockChart.tsx:490`).

## File Structure

| File | Action | Responsibility |
|---|---|---|
| `backend/app/models/etf_signal_daily.py` | Create | `EtfSignalDaily` ORM model |
| `backend/app/models/__init__.py` | Modify | import + `__all__` entry |
| `backend/app/alembic/versions/3e9b71c4d2af_add_etf_signal_daily.py` | Create | create table + indexes |
| `backend/app/services/long_term/__init__.py` | Create | package marker + re-exports |
| `backend/app/services/long_term/signals.py` | Create | TR series, indicators, `compute_on_sale_score`, `compute_signal_values`, `compute_signals_for_ticker`, `compute_signals_for_roster` |
| `backend/app/services/long_term/roster.py` | Create | `list_roster`, `get_etf_detail`, `get_market_overview`, `previous_trading_day`, `reporting_currency` |
| `backend/app/schemas/long_term.py` | Create | response models |
| `backend/app/routers/long_term.py` | Create | 4 endpoints under `/api/v1/long-term` |
| `backend/app/routers/__init__.py` | Modify | export `long_term_router` |
| `backend/app/main.py` | Modify | `include_router(long_term_router)` |
| `backend/app/tasks/long_term.py` | Modify (#913 creates) | `compute_etf_signals_nightly` |
| `backend/app/tasks/__init__.py` | Modify | import + `__all__` |
| `backend/app/core/celery_app.py` | Modify | beat entry `compute-etf-signals-nightly` |
| `backend/tests/fixtures/long_term.py` | Create | seed helpers (roster rows, daily bars, dividends, signal rows) |
| `backend/tests/models/test_etf_signal_daily_model.py` | Create | model shape + migration chain |
| `backend/tests/services/test_long_term_signal_math.py` | Create | pure-function tests (no DB) |
| `backend/tests/services/test_long_term_signals_db.py` | Create | `compute_signals_for_ticker` / roster batch against Postgres |
| `backend/tests/services/test_long_term_roster.py` | Create | overview / roster / detail helpers |
| `backend/tests/tasks/test_long_term_signals_task.py` | Create | task wrapper + beat schedule |
| `backend/tests/tasks/test_package_exports.py` | Modify | add task name |
| `backend/tests/api/test_long_term.py` | Create | endpoint tests |
| `frontend/src/api/longTerm.ts` | Create | typed API module |
| `frontend/src/api/longTerm.test.ts` | Create | API module tests |
| `frontend/src/pages/LongTerm/hooks.ts` | Create | React Query hooks |
| `frontend/src/pages/LongTerm/format.ts` | Create | formatting, sorting, price-line helpers |
| `frontend/src/pages/LongTerm/format.test.ts` | Create | helper tests |
| `frontend/src/pages/LongTerm/HeaderStrip.tsx` | Create | §4.8 item 1 |
| `frontend/src/pages/LongTerm/OnSaleCards.tsx` | Create | §4.8 item 2 |
| `frontend/src/pages/LongTerm/Movers.tsx` | Create | §4.8 item 3 |
| `frontend/src/pages/LongTerm/TrendSplit.tsx` | Create | §4.8 item 4 |
| `frontend/src/pages/LongTerm/RosterTable.tsx` | Create | §4.8 item 5 |
| `frontend/src/pages/LongTerm/EtfDetailDrawer.tsx` | Create | §4.8 item 6 |
| `frontend/src/pages/LongTerm/index.tsx` | Create | page composition + selected-ticker state |
| `frontend/src/pages/LongTerm/LongTerm.test.tsx` | Create | page render tests |
| `frontend/src/App.tsx` | Modify | lazy route `/long-term` |
| `frontend/src/components/Layout.tsx` | Modify | sidebar entry "Long-Term" with `LineChart` icon |
| `docs/database-schema.md` | Regenerated | written by `alembic/env.py` after `upgrade`; commit if changed |

Backend commands run from `backend/`, frontend commands from `frontend/`, unless stated.

**Commit hygiene (every commit step):** pre-commit runs `ruff-format`/`ruff`. Before each
backend commit run `ruff format <files> && ruff check --fix <files>`. If a hook rewrites
files and aborts, `git add` them again and repeat the same commit. Frontend commits run
`npx eslint <files>` first.

---

## Task 0: Dependency gate

**Files:** none (read-only checks)

- [ ] **Step 0.1 — Check the consumed interfaces exist.**

```bash
cd backend
python -c "from app.models import LtEtf, LtDividend; print(LtEtf.__tablename__, LtDividend.__tablename__)"
python -c "from app.models.stock_aggregate import StockAggregate; print(StockAggregate.__table__.c.ticker.type.length)"
test -f app/tasks/long_term.py && grep -n "def sync_lt_dividends_nightly" app/tasks/long_term.py
python -m alembic heads
```

Expected: `lt_etf lt_dividend`, then `20`, then a matching `def sync_lt_dividends_nightly`
line, then exactly one head. Record that head id. It becomes `down_revision` in Task 2.

- [ ] **Step 0.2 — Check field names match the table above.**

```bash
python - <<'EOF'
from app.models import LtEtf, LtDividend
need_etf = {"ticker","name","segment","country","currency","exchange","data_source","is_active","is_benchmark","tags"}
need_div = {"ticker","ex_date","cash_amount","currency","source"}
print("etf missing:", need_etf - set(LtEtf.__table__.c.keys()))
print("div missing:", need_div - set(LtDividend.__table__.c.keys()))
EOF
```

Expected: `etf missing: set()` and `div missing: set()`.

- [ ] **Step 0.3 — If any check fails:** stop. Post an issue comment on #905 titled
  "LT-2 blocked: dependency interface missing" that lists the failing check output, and end
  the phase without writing code. Per spec Requirement 1 and Open Question 1, do not stub,
  and do not rename this plan's references to match a guess.

---

## Task 1: `EtfSignalDaily` model + registration

**Files:** `backend/app/models/etf_signal_daily.py` (create), `backend/app/models/__init__.py`
(modify), `backend/tests/models/test_etf_signal_daily_model.py` (create)

- [ ] **Step 1.1 — Write the failing test.** Create
  `backend/tests/models/test_etf_signal_daily_model.py`:

```python
"""Shape tests for the LT-2 signal table (#905)."""

from sqlalchemy import Boolean, Date, DateTime, Integer, Numeric, String

NUMERIC_NULLABLE = [
    "ret_1d",
    "ret_1w",
    "ret_1m",
    "ret_3m",
    "ret_6m",
    "ret_1y",
    "sma_50",
    "sma_200",
    "pct_from_sma_50",
    "pct_from_sma_200",
    "high_52w",
    "drawdown_52w_pct",
    "high_5y",
    "drawdown_5y_pct",
    "pctile_1y",
    "pctile_5y",
    "atr_14_pct",
    "rsi_14",
    "rel_ret_1y_vs_benchmark",
    "on_sale_score",
]
BOOL_NULLABLE = ["above_sma_50", "above_sma_200", "golden_cross"]


def test_registered_in_models_package():
    import app.models as models

    assert "EtfSignalDaily" in models.__all__
    assert models.EtfSignalDaily.__tablename__ == "etf_signal_daily"


def test_always_populated_columns_are_not_null():
    from app.models import EtfSignalDaily

    c = EtfSignalDaily.__table__.c
    assert isinstance(c.ticker.type, String) and c.ticker.type.length == 20
    assert isinstance(c.date.type, Date)
    assert isinstance(c.close.type, Numeric)
    assert isinstance(c.history_days.type, Integer)
    assert isinstance(c.short_history.type, Boolean)
    assert isinstance(c.computed_at.type, DateTime)
    for name in ("ticker", "date", "close", "history_days", "short_history"):
        assert c[name].nullable is False, name


def test_metric_columns_are_nullable_with_expected_types():
    from app.models import EtfSignalDaily

    c = EtfSignalDaily.__table__.c
    for name in NUMERIC_NULLABLE:
        assert isinstance(c[name].type, Numeric), name
        assert c[name].nullable is True, name
    for name in BOOL_NULLABLE:
        assert isinstance(c[name].type, Boolean), name
        assert c[name].nullable is True, name


def test_unique_ticker_date_index_and_date_index():
    from app.models import EtfSignalDaily

    indexes = {ix.name: ix for ix in EtfSignalDaily.__table__.indexes}
    uq = indexes["uq_etf_signal_daily_ticker_date"]
    assert uq.unique is True
    assert [col.name for col in uq.columns] == ["ticker", "date"]
    assert any(
        [col.name for col in ix.columns] == ["date"] for ix in indexes.values()
    )
```

- [ ] **Step 1.2 — Run it, expect failure.**
  `python -m pytest tests/models/test_etf_signal_daily_model.py -q`
  Expected: `ImportError` / `AssertionError: 'EtfSignalDaily' in ...` (4 failed).

- [ ] **Step 1.3 — Implement the model.** Create `backend/app/models/etf_signal_daily.py`:

```python
"""
EtfSignalDaily SQLAlchemy model — nightly total-return signals per roster ETF (#905).

All return/SMA/high/drawdown/percentile columns are derived from the total-return
close series (raw closes + lt_dividend, built in memory, never stored); ATR/RSI use
raw closes. Percent-valued columns are stored in percent (5.2 == +5.2%).
"""

from sqlalchemy import Boolean, Column, Date, DateTime, Integer, Numeric, String
from sqlalchemy.schema import Index

from app.core.database import Base
from app.utils.time import utc_now


class EtfSignalDaily(Base):
    __tablename__ = "etf_signal_daily"

    id = Column(Integer, primary_key=True, index=True)
    ticker = Column(String(20), nullable=False)  # by convention lt_etf.ticker
    date = Column(Date, nullable=False, index=True)
    close = Column(Numeric, nullable=False)  # raw close on `date`

    ret_1d = Column(Numeric, nullable=True)
    ret_1w = Column(Numeric, nullable=True)
    ret_1m = Column(Numeric, nullable=True)
    ret_3m = Column(Numeric, nullable=True)
    ret_6m = Column(Numeric, nullable=True)
    ret_1y = Column(Numeric, nullable=True)

    sma_50 = Column(Numeric, nullable=True)
    sma_200 = Column(Numeric, nullable=True)
    pct_from_sma_50 = Column(Numeric, nullable=True)
    pct_from_sma_200 = Column(Numeric, nullable=True)
    above_sma_50 = Column(Boolean, nullable=True)
    above_sma_200 = Column(Boolean, nullable=True)
    golden_cross = Column(Boolean, nullable=True)

    high_52w = Column(Numeric, nullable=True)
    drawdown_52w_pct = Column(Numeric, nullable=True)
    high_5y = Column(Numeric, nullable=True)
    drawdown_5y_pct = Column(Numeric, nullable=True)
    pctile_1y = Column(Numeric, nullable=True)
    pctile_5y = Column(Numeric, nullable=True)

    atr_14_pct = Column(Numeric, nullable=True)
    rsi_14 = Column(Numeric, nullable=True)
    rel_ret_1y_vs_benchmark = Column(Numeric, nullable=True)

    history_days = Column(Integer, nullable=False)
    short_history = Column(Boolean, nullable=False)
    on_sale_score = Column(Numeric, nullable=True)

    computed_at = Column(DateTime, default=utc_now)

    __table_args__ = (
        Index("uq_etf_signal_daily_ticker_date", "ticker", "date", unique=True),
    )
```

- [ ] **Step 1.4 — Register it.** In `backend/app/models/__init__.py`, add
  `from app.models.etf_signal_daily import EtfSignalDaily` with the other model imports
  (alphabetical position, next to the `e…` imports), and `"EtfSignalDaily",` to `__all__`.
  Per CLAUDE.md's "New Models" checklist, without this `Base.metadata` and autogenerate won't
  see the table.

- [ ] **Step 1.5 — Run, expect pass.**
  `python -m pytest tests/models/test_etf_signal_daily_model.py -q` → `4 passed`.

- [ ] **Step 1.6 — Commit.**
  `git add app/models/etf_signal_daily.py app/models/__init__.py tests/models/test_etf_signal_daily_model.py`
  `git commit -m "feat(long-term): EtfSignalDaily model (#905)"`

---

## Task 2: Alembic migration

**Files:** `backend/app/alembic/versions/3e9b71c4d2af_add_etf_signal_daily.py` (create),
`backend/tests/models/test_etf_signal_daily_model.py` (modify)

Revision id `3e9b71c4d2af` is a random 12-hex id. Do not use a hex-sequence id like
`a1b2c3d4e5f6`, because sibling branches collide on those. Confirm it is unused:
`ls app/alembic/versions | grep -c 3e9b71c4d2af` → `0`. If it isn't, use
`python -c "import uuid; print(uuid.uuid4().hex[:12])"` and rename the file and test to match.

- [ ] **Step 2.1 — Write the failing test.** Append to
  `backend/tests/models/test_etf_signal_daily_model.py`:

```python
def test_migration_is_chained_into_a_single_head_history():
    """Don't pin the global head: later slices (LT-3+) add migrations on top."""
    from pathlib import Path

    from alembic.config import Config
    from alembic.script import ScriptDirectory

    ini = Path(__file__).resolve().parents[2] / "alembic.ini"
    cfg = Config(str(ini))
    # script_location in alembic.ini is cwd-relative; pin it so pytest can run from anywhere
    cfg.set_main_option("script_location", str(ini.parent / "app" / "alembic"))
    script = ScriptDirectory.from_config(cfg)
    rev = script.get_revision("3e9b71c4d2af")
    assert rev is not None
    assert rev.down_revision is not None
    assert script.get_revision(rev.down_revision) is not None  # parent exists
    assert len(script.get_heads()) == 1
    assert "3e9b71c4d2af" in {r.revision for r in script.walk_revisions()}
```

Before relying on that path, check where `alembic.ini` lives with
`ls alembic.ini app/alembic.ini 2>/dev/null`, then adjust `ini` to the existing location.
`python -m alembic heads` from `backend/` works today, so `backend/alembic.ini` is expected.

- [ ] **Step 2.2 — Run, expect failure.**
  `python -m pytest tests/models/test_etf_signal_daily_model.py::test_migration_is_chained_into_a_single_head_history -q`
  → fails with `assert rev is not None`, because revision `3e9b71c4d2af` doesn't exist yet.
  (Depending on the alembic version, `get_revision` may instead raise `CommandError`/
  `ResolutionError` for an unknown id. Either one counts as the expected failure.)

- [ ] **Step 2.3 — Write the migration.** Create
  `backend/app/alembic/versions/3e9b71c4d2af_add_etf_signal_daily.py`. Set `down_revision` to
  the head recorded in Step 0.1. If #904 was the last migration-bearing slice to land, that is
  `f8f6c8fc1c83`. Otherwise it is #912's `lt_dividend`/`fx_rate_daily` revision.

```python
"""add etf_signal_daily (#905)

Revision ID: 3e9b71c4d2af
Revises: <HEAD_FROM_STEP_0_1>
Create Date: 2026-11-07
"""

import sqlalchemy as sa
from alembic import op

revision = "3e9b71c4d2af"
down_revision = "<HEAD_FROM_STEP_0_1>"  # replace with the literal id printed in Step 0.1
branch_labels = None
depends_on = None

_NUMERIC = [
    "ret_1d",
    "ret_1w",
    "ret_1m",
    "ret_3m",
    "ret_6m",
    "ret_1y",
    "sma_50",
    "sma_200",
    "pct_from_sma_50",
    "pct_from_sma_200",
]
_NUMERIC_TAIL = [
    "high_52w",
    "drawdown_52w_pct",
    "high_5y",
    "drawdown_5y_pct",
    "pctile_1y",
    "pctile_5y",
    "atr_14_pct",
    "rsi_14",
    "rel_ret_1y_vs_benchmark",
]


def upgrade() -> None:
    op.create_table(
        "etf_signal_daily",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("ticker", sa.String(length=20), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("close", sa.Numeric(), nullable=False),
        *[sa.Column(name, sa.Numeric(), nullable=True) for name in _NUMERIC],
        sa.Column("above_sma_50", sa.Boolean(), nullable=True),
        sa.Column("above_sma_200", sa.Boolean(), nullable=True),
        sa.Column("golden_cross", sa.Boolean(), nullable=True),
        *[sa.Column(name, sa.Numeric(), nullable=True) for name in _NUMERIC_TAIL],
        sa.Column("history_days", sa.Integer(), nullable=False),
        sa.Column("short_history", sa.Boolean(), nullable=False),
        sa.Column("on_sale_score", sa.Numeric(), nullable=True),
        sa.Column("computed_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_etf_signal_daily_id", "etf_signal_daily", ["id"])
    op.create_index("ix_etf_signal_daily_date", "etf_signal_daily", ["date"])
    op.create_index(
        "uq_etf_signal_daily_ticker_date",
        "etf_signal_daily",
        ["ticker", "date"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_etf_signal_daily_ticker_date", table_name="etf_signal_daily")
    op.drop_index("ix_etf_signal_daily_date", table_name="etf_signal_daily")
    op.drop_index("ix_etf_signal_daily_id", table_name="etf_signal_daily")
    op.drop_table("etf_signal_daily")
```

The `<HEAD_FROM_STEP_0_1>` token is the one value that can only be known at implementation
time. Replace both occurrences with the literal id before running anything. Leave no
angle-bracket token in the file.

- [ ] **Step 2.4 — Run, expect pass.** Same pytest command → `passed`.

- [ ] **Step 2.5 — Apply and check against a live DB.**

```bash
docker-compose exec backend python -m alembic upgrade head
docker-compose exec backend python -m alembic check
docker-compose exec backend python -m alembic downgrade -1
docker-compose exec backend python -m alembic upgrade head
```

Expected:
- `upgrade` logs `Running upgrade <head> -> 3e9b71c4d2af`.
- `check` prints `No new upgrade operations detected.` Only diffs on `etf_signal_daily` matter here. If
  `check` reports pre-existing drift on other tables (already on `main`), note it in the PR
  and don't fix it in this slice. If it reports an index diff on `etf_signal_daily`, align the
  migration's index names with the model; don't change the model.
- `downgrade` and the second `upgrade` both succeed.

- [ ] **Step 2.6 — Commit** (include `docs/database-schema.md` if `env.py` regenerated it):
  `git add app/alembic/versions/3e9b71c4d2af_add_etf_signal_daily.py tests/models/test_etf_signal_daily_model.py ../docs/database-schema.md`
  `git commit -m "feat(long-term): etf_signal_daily migration (#905)"`

---

## Task 3: Test fixtures for the long-term domain

**Files:** `backend/tests/fixtures/long_term.py` (create)

- [ ] **Step 3.1 — Create the helpers.** No test of their own; Tasks 5–9 exercise them.

```python
"""Seed helpers for LT-2 (#905) tests: roster rows, daily bars, dividends, signals."""

from datetime import date, datetime, time

import pandas as pd
from sqlalchemy.orm import Session

from app.models import EtfSignalDaily, LtDividend, LtEtf, StockAggregate

END_DATE = date(2026, 11, 6)  # a Friday


def seed_lt_etf(
    db: Session,
    ticker: str,
    *,
    segment: str = "Broad market",
    country: str = "US",
    is_benchmark: bool = False,
    is_active: bool = True,
) -> LtEtf:
    ca = ticker.endswith(".TO")
    row = LtEtf(
        ticker=ticker,
        name=f"{ticker} Test Fund",
        segment=segment,
        country="CA" if ca else country,
        currency="CAD" if ca else "USD",
        exchange="TSX" if ca else "NYSEARCA",
        data_source="yfinance" if ca else "massive",
        is_active=is_active,
        is_benchmark=is_benchmark,
        tags=[],
    )
    db.add(row)
    db.flush()
    return row


def bar_dates(n: int, end: date = END_DATE) -> list[date]:
    """n consecutive business days ending at `end` (inclusive)."""
    return [d.date() for d in pd.bdate_range(end=end, periods=n)]


def seed_daily_bars(
    db: Session, ticker: str, closes: list[float], end: date = END_DATE
) -> list[date]:
    """Insert one day bar per close, stored like Massive (naive UTC of NY midnight)."""
    dates = bar_dates(len(closes), end)
    db.add_all(
        [
            StockAggregate(
                ticker=ticker,
                timestamp=datetime.combine(d, time(5, 0)),
                multiplier=1,
                timespan="day",
                open=c,
                high=c * 1.01,
                low=c * 0.99,
                close=c,
                volume=1_000_000,
                provider="polygon",
            )
            for d, c in zip(dates, closes)
        ]
    )
    db.flush()
    return dates


def seed_dividend(db: Session, ticker: str, ex_date: date, amount: float) -> None:
    db.add(
        LtDividend(
            ticker=ticker,
            ex_date=ex_date,
            cash_amount=amount,
            currency="CAD" if ticker.endswith(".TO") else "USD",
            source="yfinance" if ticker.endswith(".TO") else "massive",
        )
    )
    db.flush()


def seed_signal(db: Session, ticker: str, day: date, **fields) -> EtfSignalDaily:
    row = EtfSignalDaily(
        ticker=ticker,
        date=day,
        close=fields.pop("close", 100.0),
        history_days=fields.pop("history_days", 1260),
        short_history=fields.pop("short_history", False),
        **fields,
    )
    db.add(row)
    db.flush()
    return row
```

- [ ] **Step 3.2 — Commit.**
  `git add tests/fixtures/long_term.py && git commit -m "test(long-term): seed fixtures (#905)"`

---

## Task 4: Pure signal math (`signals.py`, no DB)

**Files:** `backend/app/services/long_term/__init__.py` (create),
`backend/app/services/long_term/signals.py` (create),
`backend/tests/services/test_long_term_signal_math.py` (create)

- [ ] **Step 4.1 — Write the failing tests.** Create
  `backend/tests/services/test_long_term_signal_math.py`:

```python
"""Pure-function tests for LT-2 signal math (#905). No DB."""

import math
from datetime import date

import pandas as pd
import pytest

from app.services.long_term.signals import (
    BARS_1Y,
    SHORT_HISTORY_BARS,
    build_total_return_closes,
    compute_on_sale_score,
    compute_signal_values,
    percentile_rank_of_last,
)


def _bars(closes, end=date(2026, 11, 6)):
    idx = pd.bdate_range(end=end, periods=len(closes))
    closes = [float(c) for c in closes]
    return pd.DataFrame(
        {
            "open": closes,
            "high": [c * 1.01 for c in closes],
            "low": [c * 0.99 for c in closes],
            "close": closes,
            "volume": [1_000_000] * len(closes),
        },
        index=idx,
    )


# --- total-return series -------------------------------------------------------


def test_total_return_adjusts_only_bars_before_ex_date():
    closes = _bars([100, 102, 101, 103])["close"]
    ex = closes.index[2]  # dividend of 2.0 on the 3rd bar
    tr = build_total_return_closes(closes, [(ex, 2.0)])
    f = (102 - 2.0) / 102
    assert tr.iloc[0] == pytest.approx(100 * f)
    assert tr.iloc[1] == pytest.approx(102 * f)
    assert tr.iloc[2] == pytest.approx(101)
    assert tr.iloc[3] == pytest.approx(103)  # latest close never adjusted


def test_total_return_factors_compound():
    closes = _bars([100, 100, 100, 100])["close"]
    tr = build_total_return_closes(
        closes, [(closes.index[1], 1.0), (closes.index[3], 1.0)]
    )
    assert tr.iloc[0] == pytest.approx(100 * 0.99 * 0.99)
    assert tr.iloc[1] == pytest.approx(100 * 0.99)
    assert tr.iloc[2] == pytest.approx(100 * 0.99)
    assert tr.iloc[3] == pytest.approx(100)


def test_total_return_ignores_out_of_range_and_bad_dividends():
    closes = _bars([100, 101, 102])["close"]
    before_first = closes.index[0] - pd.Timedelta(days=10)
    after_last = closes.index[-1] + pd.Timedelta(days=3)
    tr = build_total_return_closes(
        closes,
        [(before_first, 1.0), (after_last, 1.0), (closes.index[1], 0.0), (closes.index[2], 500.0)],
    )
    assert list(tr) == pytest.approx([100, 101, 102])


# --- percentile ------------------------------------------------------------------


@pytest.mark.parametrize(
    "window,expected",
    [
        ([1, 2, 3, 4, 5], 100.0),
        ([5, 4, 3, 2, 1], 0.0),
        ([3, 1, 2], 50.0),
        ([1, 1, 2, 1], 100 / 3),  # ties average: rank 2 of 4
    ],
)
def test_percentile_rank_rescaled_0_to_100(window, expected):
    got = percentile_rank_of_last(pd.Series(window, dtype=float))
    assert got == pytest.approx(expected, abs=1e-9)


# --- on-sale score ---------------------------------------------------------------


def test_on_sale_score_full_mean():
    # trend term = clamp(50 + -10) = 40 ; mean(10, 20, 40) = 23.33
    assert compute_on_sale_score(10, 20, -10, False) == pytest.approx(100 - 70 / 3)


def test_on_sale_score_drops_pctile_5y_when_short_history():
    assert compute_on_sale_score(10, 20, -10, True) == pytest.approx(75.0)
    assert compute_on_sale_score(10, None, -10, True) == pytest.approx(75.0)


def test_on_sale_score_clamps_trend_term():
    assert compute_on_sale_score(0, 0, 80, False) == pytest.approx(100 - 100 / 3)
    assert compute_on_sale_score(0, 0, -70, False) == pytest.approx(100.0)


def test_on_sale_score_null_when_any_remaining_input_null():
    assert compute_on_sale_score(None, 20, -10, False) is None
    assert compute_on_sale_score(10, None, -10, False) is None
    assert compute_on_sale_score(10, 20, None, False) is None


# --- compute_signal_values --------------------------------------------------------

GATED_1Y = [
    "ret_1d", "ret_1w", "ret_1m", "ret_3m", "ret_6m", "ret_1y",
    "sma_50", "sma_200", "pct_from_sma_50", "pct_from_sma_200",
    "above_sma_50", "above_sma_200", "golden_cross",
    "rsi_14", "atr_14_pct", "high_52w", "drawdown_52w_pct", "pctile_1y",
]
GATED_5Y = ["high_5y", "drawdown_5y_pct", "pctile_5y"]


def test_under_252_bars_only_always_populated_columns():
    v = compute_signal_values(_bars([100 + i for i in range(BARS_1Y - 1)]), [])
    assert v["history_days"] == BARS_1Y - 1
    assert v["short_history"] is True
    assert v["close"] == pytest.approx(100 + BARS_1Y - 2)
    assert v["date"] == date(2026, 11, 6)
    for col in GATED_1Y + GATED_5Y + ["on_sale_score"]:
        assert v[col] is None, col


def test_at_252_bars_1y_and_5y_columns_compute_while_short_history():
    closes = [100 + i * 0.1 for i in range(BARS_1Y)]
    v = compute_signal_values(_bars(closes), [])
    assert v["short_history"] is True
    for col in GATED_1Y + GATED_5Y:
        assert v[col] is not None, col
    assert v["sma_50"] == pytest.approx(sum(closes[-50:]) / 50)
    assert v["sma_200"] == pytest.approx(sum(closes[-200:]) / 200)
    assert v["above_sma_50"] is True and v["golden_cross"] is True
    assert v["pctile_1y"] == pytest.approx(100.0)
    assert v["high_52w"] == pytest.approx(closes[-1])
    assert v["drawdown_52w_pct"] == pytest.approx(0.0)
    # short_history drops pctile_5y from the score: mean(100, clamp(50+pct200))
    expected = compute_on_sale_score(
        v["pctile_1y"], None, v["pct_from_sma_200"], True
    )
    assert v["on_sale_score"] == pytest.approx(expected)


def test_long_history_not_short_and_5y_window_capped_at_1260():
    # 1400 bars: a spike early on that falls outside the 1260-bar window
    closes = [500.0] + [100.0] * (1400 - 2) + [90.0]
    v = compute_signal_values(_bars(closes), [])
    assert v["history_days"] == 1400
    assert v["short_history"] is False
    assert v["high_5y"] == pytest.approx(100.0)  # 500 is outside the 1260 window
    assert v["drawdown_5y_pct"] == pytest.approx(-10.0)
    assert v["pctile_5y"] == pytest.approx(0.0)
    assert SHORT_HISTORY_BARS == 756


def test_calendar_offset_returns():
    closes = [100.0] * 300
    closes[-2] = 99.0  # previous bar
    v = compute_signal_values(_bars(closes), [])
    assert v["ret_1d"] == pytest.approx((100 / 99 - 1) * 100)
    assert v["ret_1y"] == pytest.approx(0.0)


def test_ret_1y_falls_back_to_first_bar_when_252_bars_span_under_a_year():
    closes = [100.0] * (BARS_1Y - 1) + [110.0]
    bars = _bars(closes)
    assert bars.index[-1] - pd.DateOffset(years=1) < bars.index[0]  # < 1 calendar year
    v = compute_signal_values(bars, [])
    assert v["ret_1y"] == pytest.approx(10.0)  # base = first bar (100)


def test_returns_use_total_return_series():
    # flat raw closes, one 1.0 dividend inside the last year → positive TR return
    bars = _bars([100.0] * 300)
    ex = bars.index[-30]
    v = compute_signal_values(bars, [(ex, 1.0)])
    assert v["ret_1y"] == pytest.approx((100 / 99 - 1) * 100)
    assert v["close"] == pytest.approx(100.0)  # raw close stored


def test_rsi_and_atr_are_finite_and_on_raw_closes():
    closes = [100 + math.sin(i / 5) * 5 for i in range(300)]
    v = compute_signal_values(_bars(closes), [])
    assert 0 <= v["rsi_14"] <= 100
    # synthetic bars: high-low = 2% of close, so Wilder ATR% is close to 2
    assert 1.5 < v["atr_14_pct"] < 3.5
```

- [ ] **Step 4.2 — Run, expect failure.**
  `python -m pytest tests/services/test_long_term_signal_math.py -q` →
  `ModuleNotFoundError: No module named 'app.services.long_term'`.

- [ ] **Step 4.3 — Create the package marker.** `backend/app/services/long_term/__init__.py`:

```python
"""Long-term ETF investing services (epic #902)."""
```

(Re-exports are added in Task 6 once both modules exist.)

- [ ] **Step 4.4 — Implement the pure half of `signals.py`.** Create
  `backend/app/services/long_term/signals.py` with the code below. Task 5 appends the DB
  functions to this same file.

```python
"""
Nightly total-return ETF signals (#905, epic #902 §4.3).

One code path produces a signal row: compute_signals_for_ticker(). The nightly
batch (compute_signals_for_roster) and POST /long-term/etfs/{ticker}/recompute
both call it.

Formulas (spec 2026-11-06-etf-signals-long-term-page-design.md §3.1/§3.3):
- Total-return closes are built in memory from raw closes + lt_dividend rows,
  applying (close_prev_ex - dividend) / close_prev_ex cumulatively backwards from
  the latest close; never stored.
- ret_*, SMA, highs, drawdowns, percentiles use total-return closes; ATR14 / RSI14
  (Wilder) use raw bars, matching services/trend_pullback_scan.py.
- Percent-valued outputs are in percent (5.2 == +5.2%).
"""

from __future__ import annotations

import logging
import math
from datetime import date
from typing import Any, Iterable, Optional

import pandas as pd

logger = logging.getLogger(__name__)

BARS_1Y = 252
BARS_5Y = 1260
SHORT_HISTORY_BARS = 756
DEFAULT_BENCHMARK = "SPY"

RETURN_OFFSETS: dict[str, pd.DateOffset] = {
    "ret_1d": pd.DateOffset(days=1),
    "ret_1w": pd.DateOffset(weeks=1),
    "ret_1m": pd.DateOffset(months=1),
    "ret_3m": pd.DateOffset(months=3),
    "ret_6m": pd.DateOffset(months=6),
    "ret_1y": pd.DateOffset(years=1),
}

METRIC_COLUMNS = [
    *RETURN_OFFSETS.keys(),
    "sma_50",
    "sma_200",
    "pct_from_sma_50",
    "pct_from_sma_200",
    "above_sma_50",
    "above_sma_200",
    "golden_cross",
    "high_52w",
    "drawdown_52w_pct",
    "high_5y",
    "drawdown_5y_pct",
    "pctile_1y",
    "pctile_5y",
    "atr_14_pct",
    "rsi_14",
    "on_sale_score",
]


def to_finite_float(value: Any) -> Optional[float]:
    """Plain float, or None for NaN/inf/None (psycopg2 can't bind numpy NaN as NULL)."""
    if value is None:
        return None
    f = float(value)
    return f if math.isfinite(f) else None


def build_total_return_closes(
    closes: pd.Series, dividends: Iterable[tuple[pd.Timestamp, float]]
) -> pd.Series:
    """Return the total-return close series; its last value equals the last raw close.

    `closes` is indexed by an ascending DatetimeIndex. For each ex-date strictly after
    the first bar and on/before the last bar, every bar dated before the ex-date is
    multiplied by (close_prev_ex - amount) / close_prev_ex.
    """
    factor = pd.Series(1.0, index=closes.index)
    if closes.empty:
        return closes.astype(float)
    first, last = closes.index[0], closes.index[-1]
    for ex_date, amount in dividends:
        ex_ts = pd.Timestamp(ex_date)
        if ex_ts <= first or ex_ts > last:
            continue
        prior = closes[closes.index < ex_ts]
        close_prev = float(prior.iloc[-1])
        amount = float(amount)
        if amount <= 0 or close_prev <= 0 or amount >= close_prev:
            logger.warning(
                "long_term.signals: skipping dividend %.4f on %s (prev close %.4f)",
                amount,
                ex_ts.date(),
                close_prev,
            )
            continue
        factor[closes.index < ex_ts] *= (close_prev - amount) / close_prev
    return closes.astype(float) * factor


def percentile_rank_of_last(window: pd.Series) -> Optional[float]:
    """Percentile of the window's last value, rescaled so cheapest == 0, dearest == 100.

    rank(pct=True) uses pandas' default method="average" for ties; rank = pct * n, then
    (rank - 1) / (n - 1) * 100 (spec §3.3).
    """
    n = len(window)
    if n < 2:
        return None
    pct = float(window.rank(pct=True).iloc[-1])
    return (pct * n - 1) / (n - 1) * 100


def compute_on_sale_score(
    pctile_1y: Optional[float],
    pctile_5y: Optional[float],
    pct_from_sma_200: Optional[float],
    short_history: bool,
) -> Optional[float]:
    """100 - mean(pctile_1y, pctile_5y, clamp(50 + pct_from_sma_200, 0, 100)).

    pctile_5y is dropped when short_history. NULL if any remaining input is NULL.
    v1 heuristic (epic §4.3) — kept in one function so it can be swapped.
    """
    trend = (
        None
        if pct_from_sma_200 is None
        else min(max(50.0 + float(pct_from_sma_200), 0.0), 100.0)
    )
    inputs = [pctile_1y, trend] if short_history else [pctile_1y, pctile_5y, trend]
    if any(v is None for v in inputs):
        return None
    return 100.0 - sum(float(v) for v in inputs) / len(inputs)


def _wilder_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    # Same smoothing as services/trend_pullback_scan.py::_calc_rsi
    delta = series.diff()
    up = delta.clip(lower=0)
    down = -delta.clip(upper=0)
    ema_up = up.ewm(com=period - 1, adjust=False).mean()
    ema_down = down.ewm(com=period - 1, adjust=False).mean()
    rs = ema_up / ema_down
    return 100 - (100 / (1 + rs))


def _wilder_atr(bars: pd.DataFrame, period: int = 14) -> pd.Series:
    # Same smoothing as services/trend_pullback_scan.py::_calc_atr (Wilder)
    tr = pd.concat(
        [
            bars["high"] - bars["low"],
            (bars["high"] - bars["close"].shift(1)).abs(),
            (bars["low"] - bars["close"].shift(1)).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr.ewm(com=period - 1, adjust=False).mean()


def _calendar_return(tr: pd.Series, offset: pd.DateOffset) -> Optional[float]:
    """Return vs the last bar on/before row_date - offset; first bar if none (delta 5).

    Only called once history_days >= BARS_1Y, so the first-bar fallback can only
    shorten ret_1y by the few days 252 sessions fall short of a calendar year.
    """
    target = tr.index[-1] - offset
    on_or_before = tr[tr.index <= target]
    base = float(on_or_before.iloc[-1]) if not on_or_before.empty else float(tr.iloc[0])
    if base == 0:
        return None
    return (float(tr.iloc[-1]) / base - 1) * 100


def compute_signal_values(
    bars: pd.DataFrame, dividends: Iterable[tuple[pd.Timestamp, float]]
) -> dict[str, Any]:
    """Compute every etf_signal_daily column except ticker/rel_ret/computed_at.

    `bars`: ascending DatetimeIndex, float columns open/high/low/close/volume, raw
    (unadjusted) prices, last row == the signal date. Must be non-empty.
    """
    raw_close = bars["close"].astype(float)
    history_days = len(bars)
    short_history = history_days < SHORT_HISTORY_BARS
    out: dict[str, Any] = {col: None for col in METRIC_COLUMNS}
    out.update(
        date=bars.index[-1].date(),
        close=float(raw_close.iloc[-1]),
        history_days=history_days,
        short_history=short_history,
    )
    if history_days < BARS_1Y:
        return out

    tr = build_total_return_closes(raw_close, dividends)
    close_tr = float(tr.iloc[-1])

    for col, offset in RETURN_OFFSETS.items():
        out[col] = to_finite_float(_calendar_return(tr, offset))

    sma_50 = float(tr.tail(50).mean())
    sma_200 = float(tr.tail(200).mean())
    out["sma_50"] = sma_50
    out["sma_200"] = sma_200
    out["pct_from_sma_50"] = (close_tr / sma_50 - 1) * 100
    out["pct_from_sma_200"] = (close_tr / sma_200 - 1) * 100
    out["above_sma_50"] = bool(close_tr > sma_50)
    out["above_sma_200"] = bool(close_tr > sma_200)
    out["golden_cross"] = bool(sma_50 > sma_200)

    w1 = tr.tail(BARS_1Y)
    out["high_52w"] = float(w1.max())
    out["drawdown_52w_pct"] = (close_tr / out["high_52w"] - 1) * 100
    out["pctile_1y"] = to_finite_float(percentile_rank_of_last(w1))

    w5 = tr.tail(min(history_days, BARS_5Y))
    out["high_5y"] = float(w5.max())
    out["drawdown_5y_pct"] = (close_tr / out["high_5y"] - 1) * 100
    out["pctile_5y"] = to_finite_float(percentile_rank_of_last(w5))

    atr = to_finite_float(_wilder_atr(bars.astype(float), 14).iloc[-1])
    out["atr_14_pct"] = (
        None if atr is None or raw_close.iloc[-1] == 0 else atr / raw_close.iloc[-1] * 100
    )
    out["atr_14_pct"] = to_finite_float(out["atr_14_pct"])
    out["rsi_14"] = to_finite_float(_wilder_rsi(raw_close, 14).iloc[-1])

    out["on_sale_score"] = to_finite_float(
        compute_on_sale_score(
            out["pctile_1y"], out["pctile_5y"], out["pct_from_sma_200"], short_history
        )
    )
    return out
```

- [ ] **Step 4.5 — Run, expect pass.**
  `python -m pytest tests/services/test_long_term_signal_math.py -q` → `18 passed`.
  If `test_rsi_and_atr_are_finite_and_on_raw_closes` misses the 1.5–3.5 band, print
  `v["atr_14_pct"]`. The bars have `high-low = 2%` of close plus small close-to-close gaps, so
  a value near 2 is expected. Fix the formula, not the band.

- [ ] **Step 4.6 — Commit.**
  `git add app/services/long_term/ tests/services/test_long_term_signal_math.py`
  `git commit -m "feat(long-term): total-return signal math + on-sale score (#905)"`

---

## Task 5: `compute_signals_for_ticker` + roster batch (DB)

**Files:** `backend/app/services/long_term/signals.py` (modify),
`backend/tests/services/test_long_term_signals_db.py` (create)

- [ ] **Step 5.1 — Write the failing tests.** Create
  `backend/tests/services/test_long_term_signals_db.py`:

```python
"""DB tests for compute_signals_for_ticker / compute_signals_for_roster (#905)."""

from datetime import date
from unittest.mock import patch

import pytest
from sqlalchemy.orm import Session

from app.models import EtfSignalDaily
from app.services.long_term import signals as sig
from tests.fixtures.long_term import (
    END_DATE,
    seed_daily_bars,
    seed_dividend,
    seed_lt_etf,
)


def _ramp(n, start=100.0, step=0.05):
    return [start + i * step for i in range(n)]


def test_upsert_is_idempotent_and_row_date_is_latest_bar(db: Session):
    seed_lt_etf(db, "SPY", is_benchmark=True)
    seed_daily_bars(db, "SPY", _ramp(300))
    # as_of on a Sunday resolves to Friday's bar
    first = sig.compute_signals_for_ticker(db, "SPY", date(2026, 11, 8))
    second = sig.compute_signals_for_ticker(db, "SPY", date(2026, 11, 8))
    assert first.id == second.id
    assert first.date == END_DATE
    assert db.query(EtfSignalDaily).filter_by(ticker="SPY").count() == 1


def test_benchmark_rel_return_is_zero(db: Session):
    seed_lt_etf(db, "SPY", is_benchmark=True)
    seed_daily_bars(db, "SPY", _ramp(300))
    row = sig.compute_signals_for_ticker(db, "SPY", END_DATE)
    assert float(row.rel_ret_1y_vs_benchmark) == pytest.approx(0.0)


def test_rel_return_vs_benchmark_same_date(db: Session):
    seed_lt_etf(db, "SPY", is_benchmark=True)
    seed_lt_etf(db, "QQQ")
    seed_daily_bars(db, "SPY", _ramp(300, step=0.05))
    seed_daily_bars(db, "QQQ", _ramp(300, step=0.10))
    spy = sig.compute_signals_for_ticker(db, "SPY", END_DATE)
    qqq = sig.compute_signals_for_ticker(db, "QQQ", END_DATE)
    assert float(qqq.rel_ret_1y_vs_benchmark) == pytest.approx(
        float(qqq.ret_1y) - float(spy.ret_1y)
    )


def test_rel_return_null_when_benchmark_row_missing(db: Session):
    seed_lt_etf(db, "SPY", is_benchmark=True)
    seed_lt_etf(db, "QQQ")
    seed_daily_bars(db, "QQQ", _ramp(300))
    row = sig.compute_signals_for_ticker(db, "QQQ", END_DATE)
    assert row.ret_1y is not None
    assert row.rel_ret_1y_vs_benchmark is None


def test_short_history_ticker_gets_row_with_nulls(db: Session):
    seed_lt_etf(db, "IBIT", segment="Crypto")
    seed_daily_bars(db, "IBIT", _ramp(120))
    row = sig.compute_signals_for_ticker(db, "IBIT", END_DATE)
    assert row.history_days == 120
    assert row.short_history is True
    assert row.close is not None
    assert row.sma_50 is None and row.pctile_5y is None and row.on_sale_score is None


def test_no_bars_returns_none_and_writes_nothing(db: Session):
    seed_lt_etf(db, "XIU.TO")
    assert sig.compute_signals_for_ticker(db, "XIU.TO", END_DATE) is None
    assert db.query(EtfSignalDaily).count() == 0


def test_dividends_after_as_of_are_ignored(db: Session):
    seed_lt_etf(db, "TLT", segment="Bonds & rates")
    dates = seed_daily_bars(db, "TLT", [100.0] * 300)
    seed_dividend(db, "TLT", dates[-30], 1.0)
    as_of = dates[-40]
    row = sig.compute_signals_for_ticker(db, "TLT", as_of)
    assert row.date == as_of
    assert float(row.ret_1y) == pytest.approx(0.0)  # the dividend is in the future


def test_roster_batch_benchmark_first_and_isolates_failures(db: Session):
    seed_lt_etf(db, "QQQ")
    seed_lt_etf(db, "SPY", is_benchmark=True)
    seed_lt_etf(db, "XLE", segment="Sectors")
    seed_lt_etf(db, "OLD", is_active=False)
    seed_lt_etf(db, "XIU.TO")  # no bars
    for t in ("QQQ", "SPY", "XLE", "OLD"):
        seed_daily_bars(db, t, _ramp(300))

    real = sig.compute_signals_for_ticker
    calls: list[str] = []

    def flaky(db_, ticker, as_of):
        calls.append(ticker)
        if ticker == "XLE":
            raise RuntimeError("boom")
        return real(db_, ticker, as_of)

    with patch.object(sig, "compute_signals_for_ticker", side_effect=flaky):
        result = sig.compute_signals_for_roster(db, END_DATE)

    assert calls[0] == "SPY"
    assert "OLD" not in calls
    assert result["computed"] == ["SPY", "QQQ"]
    assert result["failed"] == ["XLE"]
    assert result["skipped_no_bars"] == ["XIU.TO"]
    qqq = db.query(EtfSignalDaily).filter_by(ticker="QQQ").one()
    assert qqq.rel_ret_1y_vs_benchmark is not None
```

- [ ] **Step 5.2 — Run, expect failure.**
  `python -m pytest tests/services/test_long_term_signals_db.py -q` →
  `AttributeError: module 'app.services.long_term.signals' has no attribute 'compute_signals_for_ticker'`.

- [ ] **Step 5.3 — Append the DB half to `signals.py`.** Add these imports at the top of the
  file, below `import pandas as pd`:

```python
from sqlalchemy.orm import Session

from app.models import EtfSignalDaily, LtDividend, LtEtf, StockAggregate
from app.utils.time import utc_now
```

and add `from datetime import date, datetime, time, timedelta` in place of
`from datetime import date`. Then append:

```python
# ── DB access ────────────────────────────────────────────────────────────────


def load_daily_bars(db: Session, ticker: str, as_of: date) -> pd.DataFrame:
    """All stored daily bars for `ticker` dated on/before `as_of`, ascending.

    Bar date = UTC calendar date of the naive-UTC timestamp (Massive stores NY
    midnight as 04:00/05:00 UTC; tasks/quality.py groups by func.date the same way).
    """
    end = datetime.combine(as_of + timedelta(days=1), time.min)
    rows = (
        db.query(
            StockAggregate.timestamp,
            StockAggregate.open,
            StockAggregate.high,
            StockAggregate.low,
            StockAggregate.close,
            StockAggregate.volume,
        )
        .filter(
            StockAggregate.ticker == ticker,
            StockAggregate.timespan == "day",
            StockAggregate.multiplier == 1,
            StockAggregate.timestamp < end,
        )
        .order_by(StockAggregate.timestamp.asc())
        .all()
    )
    if not rows:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
    df = pd.DataFrame(
        {
            "open": [float(r.open) for r in rows],
            "high": [float(r.high) for r in rows],
            "low": [float(r.low) for r in rows],
            "close": [float(r.close) for r in rows],
            "volume": [float(r.volume or 0) for r in rows],
        },
        index=pd.DatetimeIndex([pd.Timestamp(r.timestamp.date()) for r in rows]),
    )
    return df[~df.index.duplicated(keep="last")]


def load_dividends(
    db: Session, ticker: str, as_of: date
) -> list[tuple[pd.Timestamp, float]]:
    rows = (
        db.query(LtDividend.ex_date, LtDividend.cash_amount)
        .filter(LtDividend.ticker == ticker, LtDividend.ex_date <= as_of)
        .order_by(LtDividend.ex_date.asc())
        .all()
    )
    return [(pd.Timestamp(r.ex_date), float(r.cash_amount)) for r in rows]


def benchmark_ticker(db: Session) -> str:
    row = (
        db.query(LtEtf.ticker)
        .filter(LtEtf.is_benchmark.is_(True), LtEtf.is_active.is_(True))
        .order_by(LtEtf.ticker.asc())
        .first()
    )
    return row.ticker if row else DEFAULT_BENCHMARK


def _rel_return_vs_benchmark(
    db: Session, ticker: str, row_date: date, ret_1y: Optional[float], bench: str
) -> Optional[float]:
    if ret_1y is None:
        return None
    if ticker == bench:
        return ret_1y - ret_1y  # 0.0 — no special case, same formula (spec §3.3)
    bench_row = (
        db.query(EtfSignalDaily.ret_1y)
        .filter(EtfSignalDaily.ticker == bench, EtfSignalDaily.date == row_date)
        .first()
    )
    if bench_row is None or bench_row.ret_1y is None:
        return None
    return ret_1y - float(bench_row.ret_1y)


def compute_signals_for_ticker(
    db: Session, ticker: str, as_of: date
) -> Optional[EtfSignalDaily]:
    """Compute and upsert the signal row for `ticker` as of `as_of`.

    THE single code path that produces an etf_signal_daily row (spec §3.2) — used
    by the nightly batch and by POST /long-term/etfs/{ticker}/recompute. Flushes but
    does not commit; the caller owns the transaction. Returns None (no write) when
    the ticker has no stored daily bars on/before `as_of`.
    """
    bars = load_daily_bars(db, ticker, as_of)
    if bars.empty:
        logger.warning("long_term.signals: no daily bars for %s as of %s", ticker, as_of)
        return None
    values = compute_signal_values(bars, load_dividends(db, ticker, as_of))
    values["rel_ret_1y_vs_benchmark"] = to_finite_float(
        _rel_return_vs_benchmark(
            db, ticker, values["date"], values["ret_1y"], benchmark_ticker(db)
        )
    )

    row = (
        db.query(EtfSignalDaily)
        .filter(EtfSignalDaily.ticker == ticker, EtfSignalDaily.date == values["date"])
        .first()
    )
    if row is None:
        row = EtfSignalDaily(ticker=ticker, date=values["date"])
        db.add(row)
    for key, value in values.items():
        if key != "date":
            setattr(row, key, value)
    row.computed_at = utc_now()
    db.flush()
    return row


def compute_signals_for_roster(db: Session, as_of: date) -> dict[str, Any]:
    """Batch over active roster rows, benchmark first; commit per ticker.

    A failure on one ticker is rolled back and logged; the rest still run (spec §2 R2).
    """
    bench = benchmark_ticker(db)
    tickers = [
        r.ticker
        for r in db.query(LtEtf.ticker)
        .filter(LtEtf.is_active.is_(True))
        .order_by(LtEtf.ticker.asc())
        .all()
    ]
    if bench in tickers:
        tickers.remove(bench)
        tickers.insert(0, bench)

    result: dict[str, Any] = {
        "as_of": as_of.isoformat(),
        "computed": [],
        "skipped_no_bars": [],
        "failed": [],
    }
    for ticker in tickers:
        try:
            # SAVEPOINT per ticker: a failure rolls back only this ticker's work, and
            # earlier tickers (benchmark first) stay committed.
            with db.begin_nested():
                row = compute_signals_for_ticker(db, ticker, as_of)
        except Exception as exc:
            logger.error("long_term.signals: %s failed: %s", ticker, exc, exc_info=True)
            result["failed"].append(ticker)
            continue
        db.commit()
        if row is None:
            result["skipped_no_bars"].append(ticker)
        else:
            result["computed"].append(ticker)
    return result
```

`compute_signals_for_roster` must call `compute_signals_for_ticker` through the module
global, not a local alias, so the test's `patch.object` takes effect. The code above does
that.

- [ ] **Step 5.4 — Run, expect pass.**
  `python -m pytest tests/services/test_long_term_signals_db.py tests/services/test_long_term_signal_math.py -q`
  → all passed.
  The per-ticker `with db.begin_nested():` matters here. A bare `db.rollback()` on the
  conftest's savepoint-bound session (and in production) could discard more than the failing
  ticker's work, so keep the nested block. Don't replace it with try/rollback.

- [ ] **Step 5.5 — Commit.**
  `git add app/services/long_term/signals.py tests/services/test_long_term_signals_db.py`
  `git commit -m "feat(long-term): compute_signals_for_ticker upsert + roster batch (#905)"`

---

## Task 6: Read helpers (`roster.py`)

**Files:** `backend/app/services/long_term/roster.py` (create),
`backend/app/services/long_term/__init__.py` (modify),
`backend/tests/services/test_long_term_roster.py` (create)

- [ ] **Step 6.1 — Write the failing tests.** Create
  `backend/tests/services/test_long_term_roster.py`:

```python
"""Tests for long-term roster/overview/detail read helpers (#905)."""

from datetime import date

import pytest
from sqlalchemy.orm import Session

from app.models import MarketHoliday, SystemConfig
from app.services.long_term import roster as svc
from tests.fixtures.long_term import (
    END_DATE,
    seed_daily_bars,
    seed_lt_etf,
    seed_signal,
)


def test_previous_trading_day_skips_weekend_and_nyse_holiday(db: Session):
    assert svc.previous_trading_day(db, date(2026, 11, 9)) == date(2026, 11, 6)  # Mon→Fri
    db.add(MarketHoliday(exchange="NYSE", date=date(2026, 11, 26), event_type="full_close"))
    db.flush()
    assert svc.previous_trading_day(db, date(2026, 11, 27)) == date(2026, 11, 25)


def test_reporting_currency_default_and_override(db: Session):
    assert svc.reporting_currency(db) == "CAD"
    db.add(SystemConfig(key="long_term_reporting_currency", value="USD"))
    db.flush()
    assert svc.reporting_currency(db) == "USD"


def test_list_roster_active_only_latest_signal_and_filters(db: Session):
    seed_lt_etf(db, "SPY", is_benchmark=True)
    seed_lt_etf(db, "XIU.TO")
    seed_lt_etf(db, "OLD", is_active=False)
    seed_signal(db, "SPY", date(2026, 11, 5), on_sale_score=10)
    seed_signal(db, "SPY", END_DATE, on_sale_score=20)

    rows = svc.list_roster(db)
    assert [e.ticker for e, _ in rows] == ["SPY", "XIU.TO"]  # segment, then ticker
    spy_sig = dict((e.ticker, s) for e, s in rows)["SPY"]
    assert spy_sig.date == END_DATE and float(spy_sig.on_sale_score) == 20
    assert dict((e.ticker, s) for e, s in rows)["XIU.TO"] is None

    assert [e.ticker for e, _ in svc.list_roster(db, country="CA")] == ["XIU.TO"]
    assert svc.list_roster(db, segment="Sectors") == []


def test_market_overview_sections(db: Session):
    seed_lt_etf(db, "SPY", is_benchmark=True)
    seed_lt_etf(db, "XLE", segment="Sectors")
    seed_lt_etf(db, "XLK", segment="Sectors")
    seed_lt_etf(db, "IBIT", segment="Crypto")
    seed_lt_etf(db, "XIU.TO")
    seed_signal(db, "SPY", END_DATE, on_sale_score=30, ret_1w=1, ret_1m=2, above_sma_50=True, ret_1y=12)
    seed_signal(db, "XLE", END_DATE, on_sale_score=80, ret_1w=-3, ret_1m=-5, above_sma_50=False)
    seed_signal(db, "XLK", END_DATE, on_sale_score=None, ret_1w=4, ret_1m=6, above_sma_50=True)
    seed_signal(db, "IBIT", date(2026, 11, 4), on_sale_score=50, short_history=True)

    ov = svc.get_market_overview(db, top_n=8, movers_n=2, today=date(2026, 11, 9))

    assert ov["reporting_currency"] == "CAD"
    assert ov["latest_signal_date"] == END_DATE
    assert ov["expected_signal_date"] == END_DATE
    assert ov["is_stale"] is False
    assert ov["stale_tickers"] == ["IBIT"]
    assert ov["benchmark"][0].ticker == "SPY"
    assert [e.ticker for e, _ in ov["on_sale"]] == ["XLE", "IBIT", "SPY"]
    assert [e.ticker for e, _ in ov["movers"]["best_1w"]] == ["XLK", "SPY"]
    assert [e.ticker for e, _ in ov["movers"]["worst_1w"]] == ["XLE", "SPY"]
    split = {s["segment"]: s for s in ov["trend_split"]}
    assert split["Sectors"] == {"segment": "Sectors", "above": ["XLK"], "below": ["XLE"], "unknown": []}
    assert split["Broad market"]["unknown"] == ["XIU.TO"]
    assert split["Crypto"]["unknown"] == ["IBIT"]


def test_overview_stale_when_latest_older_than_previous_trading_day(db: Session):
    seed_lt_etf(db, "SPY", is_benchmark=True)
    seed_signal(db, "SPY", date(2026, 11, 4))
    ov = svc.get_market_overview(db, today=date(2026, 11, 9))
    assert ov["is_stale"] is True


def test_overview_empty_db(db: Session):
    ov = svc.get_market_overview(db, today=date(2026, 11, 9))
    assert ov["latest_signal_date"] is None
    assert ov["is_stale"] is True
    assert ov["on_sale"] == [] and ov["trend_split"] == [] and ov["benchmark"] is None


def test_etf_detail_bars_and_sma_series(db: Session):
    etf = seed_lt_etf(db, "SPY", is_benchmark=True)
    seed_daily_bars(db, "SPY", [100.0 + i for i in range(260)])
    seed_signal(db, "SPY", END_DATE)
    detail = svc.get_etf_detail(db, etf, history_days=30, as_of=END_DATE)
    assert detail["etf"] is etf
    assert detail["signal"].date == END_DATE
    assert len(detail["bars"]) == 30
    assert detail["bars"][-1]["Date"] == "2026-11-06"
    assert detail["bars"][-1]["Close"] == 359.0
    assert len(detail["sma_series"]) == 30
    last = detail["sma_series"][-1]
    assert last["sma_50"] == pytest.approx(sum(100.0 + i for i in range(210, 260)) / 50)
    assert last["close_tr"] == pytest.approx(359.0)


def test_etf_detail_without_bars(db: Session):
    etf = seed_lt_etf(db, "XIU.TO")
    detail = svc.get_etf_detail(db, etf, history_days=30, as_of=END_DATE)
    assert detail["bars"] == [] and detail["sma_series"] == [] and detail["signal"] is None
```

(`MarketHoliday` and `SystemConfig` are both exported from `app.models` today:
`app/models/__init__.py:14,39`.)

- [ ] **Step 6.2 — Run, expect failure.**
  `python -m pytest tests/services/test_long_term_roster.py -q` → `ImportError: cannot import name 'roster'`.

- [ ] **Step 6.3 — Implement.** Create `backend/app/services/long_term/roster.py`:

```python
"""
Read helpers for the long-term roster, ETF detail, and market overview (#905).

All helpers return ORM objects / plain dicts; the router maps them to Pydantic
schemas. Only active roster rows are considered, each joined to its latest
etf_signal_daily row.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import EtfSignalDaily, LtEtf
from app.models.market_holiday import MarketHoliday
from app.models.system_config import SystemConfig
from app.services.long_term.signals import (
    build_total_return_closes,
    load_daily_bars,
    load_dividends,
    to_finite_float,
)
from app.utils.session import get_market_today

REPORTING_CURRENCY_KEY = "long_term_reporting_currency"
DEFAULT_REPORTING_CURRENCY = "CAD"

RosterEntry = tuple[LtEtf, Optional[EtfSignalDaily]]


def reporting_currency(db: Session) -> str:
    row = db.query(SystemConfig).filter(SystemConfig.key == REPORTING_CURRENCY_KEY).first()
    return row.value if row and row.value else DEFAULT_REPORTING_CURRENCY


def previous_trading_day(db: Session, today: date) -> date:
    """Most recent NYSE session strictly before `today` (weekends + full_close skipped)."""
    holidays = {
        r.date
        for r in db.query(MarketHoliday.date).filter(
            MarketHoliday.exchange == "NYSE",
            MarketHoliday.event_type == "full_close",
            MarketHoliday.date < today,
            MarketHoliday.date >= today - timedelta(days=14),
        )
    }
    day = today - timedelta(days=1)
    while day.weekday() >= 5 or day in holidays:
        day -= timedelta(days=1)
    return day


def _latest_signals(db: Session, tickers: list[str]) -> dict[str, EtfSignalDaily]:
    if not tickers:
        return {}
    latest = (
        db.query(
            EtfSignalDaily.ticker.label("ticker"),
            func.max(EtfSignalDaily.date).label("max_date"),
        )
        .filter(EtfSignalDaily.ticker.in_(tickers))
        .group_by(EtfSignalDaily.ticker)
        .subquery()
    )
    rows = (
        db.query(EtfSignalDaily)
        .join(
            latest,
            (EtfSignalDaily.ticker == latest.c.ticker)
            & (EtfSignalDaily.date == latest.c.max_date),
        )
        .all()
    )
    return {r.ticker: r for r in rows}


def list_roster(
    db: Session, segment: Optional[str] = None, country: Optional[str] = None
) -> list[RosterEntry]:
    q = db.query(LtEtf).filter(LtEtf.is_active.is_(True))
    if segment:
        q = q.filter(LtEtf.segment == segment)
    if country:
        q = q.filter(LtEtf.country == country.upper())
    etfs = q.order_by(LtEtf.segment.asc(), LtEtf.ticker.asc()).all()
    signals = _latest_signals(db, [e.ticker for e in etfs])
    return [(e, signals.get(e.ticker)) for e in etfs]


def _ranked(
    entries: list[RosterEntry], attr: str, n: int, descending: bool
) -> list[RosterEntry]:
    """Top n by `attr` (NULLs excluded); ties broken by ticker ascending."""
    have = [(e, s) for e, s in entries if s is not None and getattr(s, attr) is not None]
    sign = -1.0 if descending else 1.0
    have.sort(key=lambda es: (sign * float(getattr(es[1], attr)), es[0].ticker))
    return have[:n]


def get_market_overview(
    db: Session, top_n: int = 8, movers_n: int = 5, today: Optional[date] = None
) -> dict[str, Any]:
    today = today or get_market_today()
    entries = list_roster(db)
    dates = [s.date for _, s in entries if s is not None]
    latest = max(dates) if dates else None
    expected = previous_trading_day(db, today)

    segments: dict[str, dict[str, Any]] = {}
    for etf, s in entries:
        seg = segments.setdefault(
            etf.segment, {"segment": etf.segment, "above": [], "below": [], "unknown": []}
        )
        if s is None or s.above_sma_50 is None:
            seg["unknown"].append(etf.ticker)
        elif s.above_sma_50:
            seg["above"].append(etf.ticker)
        else:
            seg["below"].append(etf.ticker)

    benchmark = next(((e, s) for e, s in entries if e.is_benchmark), None)
    return {
        "reporting_currency": reporting_currency(db),
        "latest_signal_date": latest,
        "expected_signal_date": expected,
        "is_stale": latest is None or latest < expected,
        "stale_tickers": [
            e.ticker for e, s in entries if s is not None and latest and s.date < latest
        ],
        "benchmark": benchmark,
        "on_sale": _ranked(entries, "on_sale_score", top_n, descending=True),
        "movers": {
            "best_1w": _ranked(entries, "ret_1w", movers_n, descending=True),
            "worst_1w": _ranked(entries, "ret_1w", movers_n, descending=False),
            "best_1m": _ranked(entries, "ret_1m", movers_n, descending=True),
            "worst_1m": _ranked(entries, "ret_1m", movers_n, descending=False),
        },
        "trend_split": [segments[k] for k in sorted(segments)],
    }


def get_etf_by_ticker(db: Session, ticker: str) -> Optional[LtEtf]:
    return db.query(LtEtf).filter(LtEtf.ticker == ticker.strip().upper()).first()


def get_etf_detail(
    db: Session, etf: LtEtf, history_days: int, as_of: Optional[date] = None
) -> dict[str, Any]:
    """Roster row + latest signal + last `history_days` raw bars and TR SMA series."""
    as_of = as_of or get_market_today()
    signal = _latest_signals(db, [etf.ticker]).get(etf.ticker)
    bars = load_daily_bars(db, etf.ticker, as_of)
    if bars.empty:
        return {"etf": etf, "signal": signal, "bars": [], "sma_series": []}
    tr = build_total_return_closes(
        bars["close"], load_dividends(db, etf.ticker, bars.index[-1].date())
    )
    sma_50 = tr.rolling(50).mean()
    sma_200 = tr.rolling(200).mean()
    window = bars.tail(history_days)
    return {
        "etf": etf,
        "signal": signal,
        "bars": [
            {
                "Date": idx.strftime("%Y-%m-%d"),
                "Open": float(r["open"]),
                "High": float(r["high"]),
                "Low": float(r["low"]),
                "Close": float(r["close"]),
                "Volume": int(r["volume"]),
            }
            for idx, r in window.iterrows()
        ],
        "sma_series": [
            {
                "date": idx.date(),
                "close_tr": float(tr[idx]),
                "sma_50": to_finite_float(sma_50[idx]),
                "sma_200": to_finite_float(sma_200[idx]),
            }
            for idx in window.index
        ],
    }
```

- [ ] **Step 6.4 — Re-exports.** Replace `backend/app/services/long_term/__init__.py` with:

```python
"""Long-term ETF investing services (epic #902)."""

from app.services.long_term.roster import (
    get_etf_by_ticker,
    get_etf_detail,
    get_market_overview,
    list_roster,
)
from app.services.long_term.signals import (
    compute_on_sale_score,
    compute_signals_for_roster,
    compute_signals_for_ticker,
)

__all__ = [
    "compute_on_sale_score",
    "compute_signals_for_roster",
    "compute_signals_for_ticker",
    "get_etf_by_ticker",
    "get_etf_detail",
    "get_market_overview",
    "list_roster",
]
```

- [ ] **Step 6.5 — Run, expect pass.**
  `python -m pytest tests/services/test_long_term_roster.py tests/services/test_long_term_signals_db.py tests/services/test_long_term_signal_math.py -q`
  → all passed.

- [ ] **Step 6.6 — Commit.**
  `git add app/services/long_term/ tests/services/test_long_term_roster.py`
  `git commit -m "feat(long-term): roster/overview/detail read helpers (#905)"`

---

## Task 7: Pydantic schemas

**Files:** `backend/app/schemas/long_term.py` (create); tests are covered by Task 8's API
tests. Task 7 adds one direct schema test in `backend/tests/api/test_long_term.py`, which
Task 8 then extends.

- [ ] **Step 7.1 — Write the failing test.** Create `backend/tests/api/test_long_term.py`:

```python
"""API tests for /api/v1/long-term (#905). Real Postgres via the db fixture."""

from decimal import Decimal
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.main import app
from tests.fixtures.long_term import END_DATE, seed_daily_bars, seed_lt_etf, seed_signal

client = TestClient(app)


def test_signal_schema_coerces_numeric_and_keeps_nulls(db: Session):
    from app.schemas.long_term import EtfSignal

    row = seed_signal(db, "SPY", END_DATE, close=Decimal("512.34"), ret_1y=Decimal("12.5"))
    out = EtfSignal.model_validate(row).model_dump()
    assert out["close"] == 512.34
    assert out["ret_1y"] == 12.5
    assert out["sma_50"] is None
    assert out["date"] == END_DATE
```

- [ ] **Step 7.2 — Run, expect failure.**
  `python -m pytest tests/api/test_long_term.py -q` → `ModuleNotFoundError: app.schemas.long_term`.

- [ ] **Step 7.3 — Implement.** Create `backend/app/schemas/long_term.py`:

```python
"""Response schemas for /api/v1/long-term (#905).

Returns are total return (dividend-adjusted, in percent); ATR/RSI use raw closes.
`datetime as dt` avoids the Pydantic v2 clash of a field named `date` typed `date`.
"""

import datetime as dt
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


class EtfSignal(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    ticker: str
    date: dt.date
    close: float
    ret_1d: Optional[float] = None
    ret_1w: Optional[float] = None
    ret_1m: Optional[float] = None
    ret_3m: Optional[float] = None
    ret_6m: Optional[float] = None
    ret_1y: Optional[float] = None
    sma_50: Optional[float] = None
    sma_200: Optional[float] = None
    pct_from_sma_50: Optional[float] = None
    pct_from_sma_200: Optional[float] = None
    above_sma_50: Optional[bool] = None
    above_sma_200: Optional[bool] = None
    golden_cross: Optional[bool] = None
    high_52w: Optional[float] = None
    drawdown_52w_pct: Optional[float] = None
    high_5y: Optional[float] = None
    drawdown_5y_pct: Optional[float] = None
    pctile_1y: Optional[float] = None
    pctile_5y: Optional[float] = None
    atr_14_pct: Optional[float] = None
    rsi_14: Optional[float] = None
    rel_ret_1y_vs_benchmark: Optional[float] = None
    history_days: int
    short_history: bool
    on_sale_score: Optional[float] = None
    computed_at: Optional[dt.datetime] = None


class RosterEtf(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    ticker: str
    name: str
    segment: str
    country: str
    currency: str
    exchange: Optional[str] = None
    data_source: str
    is_active: bool
    is_benchmark: bool
    tags: list[str] = Field(default_factory=list)

    @field_validator("tags", mode="before")
    @classmethod
    def _none_to_empty(cls, v):
        return v or []


class RosterEntry(RosterEtf):
    signal: Optional[EtfSignal] = None


class DailyBar(BaseModel):
    """Same keys as frontend StockBarRow (components/ui/StockChart.tsx)."""

    Date: str
    Open: float
    High: float
    Low: float
    Close: float
    Volume: Optional[int] = None


class SmaPoint(BaseModel):
    date: dt.date
    close_tr: float
    sma_50: Optional[float] = None
    sma_200: Optional[float] = None


class EtfDetail(BaseModel):
    etf: RosterEtf
    signal: Optional[EtfSignal] = None
    bars: list[DailyBar]
    sma_series: list[SmaPoint]


class Movers(BaseModel):
    best_1w: list[RosterEntry]
    worst_1w: list[RosterEntry]
    best_1m: list[RosterEntry]
    worst_1m: list[RosterEntry]


class TrendSplitSegment(BaseModel):
    segment: str
    above: list[str]
    below: list[str]
    unknown: list[str]


class MarketOverview(BaseModel):
    reporting_currency: str
    latest_signal_date: Optional[dt.date] = None
    expected_signal_date: dt.date
    is_stale: bool
    stale_tickers: list[str]
    benchmark: Optional[RosterEntry] = None
    on_sale: list[RosterEntry]
    movers: Movers
    trend_split: list[TrendSplitSegment]


def to_roster_entry(etf, signal) -> RosterEntry:
    entry = RosterEntry.model_validate(etf)
    entry.signal = EtfSignal.model_validate(signal) if signal is not None else None
    return entry
```

- [ ] **Step 7.4 — Run, expect pass.** `python -m pytest tests/api/test_long_term.py -q` → `1 passed`.

- [ ] **Step 7.5 — Commit.**
  `git add app/schemas/long_term.py tests/api/test_long_term.py`
  `git commit -m "feat(long-term): response schemas (#905)"`

---

## Task 8: Router + registration

**Files:** `backend/app/routers/long_term.py` (create), `backend/app/routers/__init__.py`
(modify), `backend/app/main.py` (modify), `backend/tests/api/test_long_term.py` (modify)

- [ ] **Step 8.1 — Write the failing tests.** Append to `backend/tests/api/test_long_term.py`:

```python
def _seed_two(db: Session):
    seed_lt_etf(db, "SPY", is_benchmark=True)
    seed_lt_etf(db, "XIU.TO")
    seed_daily_bars(db, "SPY", [100.0 + i * 0.1 for i in range(300)])
    seed_signal(db, "SPY", END_DATE, on_sale_score=40, ret_1w=1.0, ret_1m=2.0, above_sma_50=True)


def test_requires_auth():
    anon = TestClient(app)
    assert anon.get("/api/v1/long-term/roster").status_code == 401


def test_roster_lists_active_with_latest_signal(db: Session):
    _seed_two(db)
    r = client.get("/api/v1/long-term/roster")
    assert r.status_code == 200
    body = r.json()
    assert [e["ticker"] for e in body] == ["SPY", "XIU.TO"]
    assert body[0]["signal"]["on_sale_score"] == 40
    assert body[1]["signal"] is None
    r = client.get("/api/v1/long-term/roster", params={"country": "CA"})
    assert [e["ticker"] for e in r.json()] == ["XIU.TO"]


def test_overview_shape(db: Session):
    _seed_two(db)
    r = client.get("/api/v1/long-term/overview")
    assert r.status_code == 200
    body = r.json()
    for key in (
        "reporting_currency",
        "latest_signal_date",
        "expected_signal_date",
        "is_stale",
        "stale_tickers",
        "benchmark",
        "on_sale",
        "movers",
        "trend_split",
    ):
        assert key in body, key
    assert body["benchmark"]["ticker"] == "SPY"
    assert [e["ticker"] for e in body["on_sale"]] == ["SPY"]
    assert set(body["movers"]) == {"best_1w", "worst_1w", "best_1m", "worst_1m"}


def test_overview_validates_top_n():
    assert client.get("/api/v1/long-term/overview", params={"top_n": 0}).status_code == 422


def test_etf_detail_accepts_tsx_ticker_and_lowercase(db: Session):
    _seed_two(db)
    r = client.get("/api/v1/long-term/etfs/xiu.to")
    assert r.status_code == 200
    assert r.json()["etf"]["ticker"] == "XIU.TO"
    assert r.json()["bars"] == []
    r = client.get("/api/v1/long-term/etfs/SPY", params={"history_days": 30})
    body = r.json()
    assert len(body["bars"]) == 30
    assert set(body["bars"][0]) == {"Date", "Open", "High", "Low", "Close", "Volume"}
    assert len(body["sma_series"]) == 30


def test_etf_detail_unknown_ticker_404(db: Session):
    assert client.get("/api/v1/long-term/etfs/NOPE").status_code == 404


def test_recompute_upserts_and_returns_fresh_row(db: Session):
    seed_lt_etf(db, "SPY", is_benchmark=True)
    seed_daily_bars(db, "SPY", [100.0 + i * 0.1 for i in range(300)])
    with patch("app.routers.long_term.get_market_today", return_value=END_DATE):
        r = client.post("/api/v1/long-term/etfs/SPY/recompute")
    assert r.status_code == 200
    sig = r.json()["signal"]
    assert sig["date"] == END_DATE.isoformat()
    assert sig["history_days"] == 300
    assert sig["rel_ret_1y_vs_benchmark"] == 0.0


def test_recompute_without_bars_is_409(db: Session):
    seed_lt_etf(db, "XIU.TO")
    r = client.post("/api/v1/long-term/etfs/XIU.TO/recompute")
    assert r.status_code == 409


def test_recompute_unknown_ticker_404(db: Session):
    assert client.post("/api/v1/long-term/etfs/NOPE/recompute").status_code == 404
```

`test_recompute_upserts…` patches `get_market_today` so the result doesn't depend on the
wall clock. (`patch` is already
imported at the top of the file from Step 7.1.)

- [ ] **Step 8.2 — Run, expect failure.** `python -m pytest tests/api/test_long_term.py -q`
  → the new tests fail with 404 (router not mounted). `test_requires_auth` may already pass.

- [ ] **Step 8.3 — Implement the router.** Create `backend/app/routers/long_term.py`:

```python
"""
Long-term ETF investing — read endpoints + on-demand signal recompute (#905).

Same cookie auth / CSRF as every other router (global middleware). "Read-only"
means no user-input writes; POST /etfs/{ticker}/recompute only re-derives the
signal row from bars already stored (idempotent upsert, refresh-stats precedent).
"""

from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas.long_term import (
    EtfDetail,
    EtfSignal,
    MarketOverview,
    RosterEntry,
    RosterEtf,
    to_roster_entry,
)
from app.services.long_term import (
    compute_signals_for_ticker,
    get_etf_by_ticker,
    get_etf_detail,
    get_market_overview,
    list_roster,
)
from app.utils.session import get_market_today

router = APIRouter(prefix="/api/v1/long-term", tags=["long-term"])

# Roster tickers include TSX ".TO" symbols, which schemas.common.Ticker rejects; the
# path param is validated against the lt_etf roster instead (unknown → 404).
TickerPath = Annotated[str, Path(min_length=1, max_length=20)]


def _etf_or_404(db: Session, ticker: str):
    etf = get_etf_by_ticker(db, ticker)
    if etf is None:
        raise HTTPException(status_code=404, detail="ETF not in long-term roster")
    return etf


def _detail_response(detail: dict) -> EtfDetail:
    return EtfDetail(
        etf=RosterEtf.model_validate(detail["etf"]),
        signal=(
            EtfSignal.model_validate(detail["signal"]) if detail["signal"] is not None else None
        ),
        bars=detail["bars"],
        sma_series=detail["sma_series"],
    )


@router.get("/roster", response_model=list[RosterEntry])
def get_roster(
    segment: Optional[str] = Query(None, max_length=50),
    country: Optional[str] = Query(None, min_length=2, max_length=2),
    db: Session = Depends(get_db),
):
    """Active roster rows, each with its latest signal row (null if none yet)."""
    return [to_roster_entry(e, s) for e, s in list_roster(db, segment, country)]


@router.get("/overview", response_model=MarketOverview)
def get_overview(
    top_n: int = Query(8, ge=1, le=50),
    movers_n: int = Query(5, ge=1, le=20),
    db: Session = Depends(get_db),
):
    """Header strip + on-sale top N + movers + trend split + benchmark, in one call."""
    ov = get_market_overview(db, top_n=top_n, movers_n=movers_n)
    entry = lambda es: to_roster_entry(*es)  # noqa: E731
    return MarketOverview(
        reporting_currency=ov["reporting_currency"],
        latest_signal_date=ov["latest_signal_date"],
        expected_signal_date=ov["expected_signal_date"],
        is_stale=ov["is_stale"],
        stale_tickers=ov["stale_tickers"],
        benchmark=entry(ov["benchmark"]) if ov["benchmark"] else None,
        on_sale=[entry(es) for es in ov["on_sale"]],
        movers={k: [entry(es) for es in v] for k, v in ov["movers"].items()},
        trend_split=ov["trend_split"],
    )


@router.get("/etfs/{ticker}", response_model=EtfDetail)
def get_etf(
    ticker: TickerPath,
    history_days: int = Query(1260, ge=20, le=1830),
    db: Session = Depends(get_db),
):
    """Roster row + latest signals + raw daily bars and total-return SMA series."""
    etf = _etf_or_404(db, ticker)
    return _detail_response(get_etf_detail(db, etf, history_days))


@router.post("/etfs/{ticker}/recompute", response_model=EtfDetail)
def recompute_etf(
    ticker: TickerPath,
    history_days: int = Query(1260, ge=20, le=1830),
    db: Session = Depends(get_db),
):
    """Synchronously recompute + upsert the latest signal row, return the fresh detail."""
    etf = _etf_or_404(db, ticker)
    as_of = get_market_today()
    row = compute_signals_for_ticker(db, etf.ticker, as_of)
    if row is None:
        raise HTTPException(status_code=409, detail="No daily bars stored for this ETF")
    db.commit()
    return _detail_response(get_etf_detail(db, etf, history_days, as_of=as_of))
```

Replace the `entry = lambda` with a small module-level `def _entry(es)` if ruff flags E731
despite the noqa.

- [ ] **Step 8.4 — Register.** In `backend/app/routers/__init__.py` add
  `from app.routers.long_term import router as long_term_router` (alphabetical, after
  `live_data`) and `"long_term_router",` to `__all__`. In `backend/app/main.py`, add
  `long_term_router,` to the `from app.routers import (...)` block (alphabetical) and
  `app.include_router(long_term_router)` after `app.include_router(data_quality_router)`.

- [ ] **Step 8.5 — Run, expect pass.** `python -m pytest tests/api/test_long_term.py -q` → all passed.

- [ ] **Step 8.6 — Commit.**
  `git add app/routers/long_term.py app/routers/__init__.py app/main.py tests/api/test_long_term.py`
  `git commit -m "feat(long-term): /api/v1/long-term read + recompute endpoints (#905)"`

---

## Task 9: Nightly Celery task + beat schedule

**Files:** `backend/app/tasks/long_term.py` (modify), `backend/app/tasks/__init__.py`
(modify), `backend/app/core/celery_app.py` (modify),
`backend/tests/tasks/test_long_term_signals_task.py` (create),
`backend/tests/tasks/test_package_exports.py` (modify)

- [ ] **Step 9.1 — Write the failing tests.** Create
  `backend/tests/tasks/test_long_term_signals_task.py`:

```python
"""Tests for compute_etf_signals_nightly (#905)."""

from datetime import date
from unittest.mock import MagicMock, patch


def test_task_name_and_beat_slot():
    from app.core.celery_app import celery_app
    from app.tasks.long_term import compute_etf_signals_nightly

    assert compute_etf_signals_nightly.name == "app.tasks.compute_etf_signals_nightly"
    entry = celery_app.conf.beat_schedule["compute-etf-signals-nightly"]
    assert entry["task"] == "app.tasks.compute_etf_signals_nightly"
    sched = entry["schedule"]
    assert sched.hour == {2} and sched.minute == {30}
    assert sched.day_of_week == {2, 3, 4, 5, 6}  # Tue–Sat, after 01:30 bar sync


def test_task_runs_roster_batch_for_market_today_and_closes_session():
    import app.tasks.long_term as mod

    db = MagicMock()
    result = {"as_of": "2026-11-06", "computed": ["SPY"], "skipped_no_bars": [], "failed": []}
    with (
        patch("app.tasks.long_term.SessionLocal", return_value=db),
        patch("app.tasks.long_term.get_market_today", return_value=date(2026, 11, 6)),
        patch("app.tasks.long_term.compute_signals_for_roster", return_value=result) as batch,
    ):
        out = mod.compute_etf_signals_nightly.run()

    batch.assert_called_once_with(db, date(2026, 11, 6))
    assert out == result
    db.close.assert_called_once()


def test_task_accepts_explicit_as_of():
    import app.tasks.long_term as mod

    db = MagicMock()
    with (
        patch("app.tasks.long_term.SessionLocal", return_value=db),
        patch("app.tasks.long_term.compute_signals_for_roster", return_value={}) as batch,
    ):
        mod.compute_etf_signals_nightly.run(as_of="2026-10-30")

    batch.assert_called_once_with(db, date(2026, 10, 30))
```

In `backend/tests/tasks/test_package_exports.py`, add `"compute_etf_signals_nightly",` to
`PUBLIC_TASKS` under a `# long-term` comment. If `SUBMODULE_TASKS` already has an
`"app.tasks.long_term"` key (added by #913), append the name there too. Otherwise add
`"app.tasks.long_term": ["compute_etf_signals_nightly"],`.

- [ ] **Step 9.2 — Run, expect failure.**
  `python -m pytest tests/tasks/test_long_term_signals_task.py tests/tasks/test_package_exports.py -q`
  → `ImportError: cannot import name 'compute_etf_signals_nightly'`.

- [ ] **Step 9.3 — Implement the task.** Append to `backend/app/tasks/long_term.py`, which
  #913 created. Add these imports to its import block, skipping any already present:

```python
import time as _time
from datetime import date

from app.core.celery_app import celery_app
from app.core.database import SessionLocal
from app.core.metrics import celery_task_duration_seconds, celery_tasks_total
from app.services.long_term.signals import compute_signals_for_roster
from app.utils.session import get_market_today
```

Then append:

```python
@celery_app.task(bind=True, max_retries=0, name="app.tasks.compute_etf_signals_nightly")
def compute_etf_signals_nightly(self, as_of: str | None = None):
    """
    Nightly etf_signal_daily computation for every active Long-Term roster ETF (#905).

    One batch (not fan-out): ~65 fixed tickers, benchmark first, per-ticker failures
    logged and skipped. Beat slot 02:30 UTC Tue–Sat — a fixed offset after the 01:30
    bar top-up and #913's 02:00/02:15 dividend/FX top-ups (no task chaining exists).
    `as_of` (YYYY-MM-DD) recomputes a past day; default is today in New York.
    """
    _task_name = "compute_etf_signals_nightly"
    _start = _time.monotonic()
    db = SessionLocal()
    try:
        day = date.fromisoformat(as_of) if as_of else get_market_today()
        result = compute_signals_for_roster(db, day)
        logger.info(
            "📈 ETF signals %s: %d computed, %d no bars, %d failed",
            day,
            len(result.get("computed", [])),
            len(result.get("skipped_no_bars", [])),
            len(result.get("failed", [])),
        )
        celery_tasks_total.labels(task_name=_task_name, status="success").inc()
        return result
    except Exception:
        celery_tasks_total.labels(task_name=_task_name, status="failure").inc()
        raise
    finally:
        celery_task_duration_seconds.labels(task_name=_task_name).observe(
            _time.monotonic() - _start
        )
        db.close()
```

If the file has no module-level `logger`, add
`import logging` / `logger = logging.getLogger(__name__)`.

- [ ] **Step 9.4 — Export it.** In `backend/app/tasks/__init__.py`, add
  `compute_etf_signals_nightly` to the existing `from app.tasks.long_term import (...)` block
  (#913 adds that block). If the block is missing, add
  `from app.tasks.long_term import compute_etf_signals_nightly` in alphabetical module order,
  after `app.tasks.explanations`. Add `"compute_etf_signals_nightly",` to `__all__` under a
  `# long-term` comment. `include=["app.tasks"]` only registers tasks that this package
  imports.

- [ ] **Step 9.5 — Beat entry.** In `backend/app/core/celery_app.py`'s `beat_schedule`,
  directly after #913's `"sync-fx-rates-nightly"` entry (or after
  `"sync-universe-aggregates-nightly"` if #913 placed its entries elsewhere), add:

```python
    # LT-2 ETF signals: 02:30 UTC Tue–Sat — after 01:30 bar top-up and the
    # 02:00/02:15 dividend/FX top-ups, before the 03:00 staleness sweep (#905)
    "compute-etf-signals-nightly": {
        "task": "app.tasks.compute_etf_signals_nightly",
        "schedule": crontab(minute="30", hour="2", day_of_week="2-6"),
    },
```

- [ ] **Step 9.6 — Run, expect pass.**
  `python -m pytest tests/tasks/test_long_term_signals_task.py tests/tasks/test_package_exports.py -q`
  → all passed.

- [ ] **Step 9.7 — Full backend regression.**
  `python -m pytest -q -x` → no failures. Pay attention to the existing
  `tests/services/test_regime_service.py` beat tests and the #913 long-term task tests.

- [ ] **Step 9.8 — Commit.**
  `git add app/tasks/long_term.py app/tasks/__init__.py app/core/celery_app.py tests/tasks/test_long_term_signals_task.py tests/tasks/test_package_exports.py`
  `git commit -m "feat(long-term): compute_etf_signals_nightly batch task + 02:30 beat slot (#905)"`

---

## Task 10: Backend live validation (CLAUDE.md "Validating Changes")

**Files:** none

- [ ] **Step 10.1 — Reload + migrate.**
  `docker-compose restart backend celery-worker celery-beat && docker-compose logs backend --tail=10`
  → `Application startup complete`, no traceback.
  `docker-compose exec backend python -m alembic current` → `3e9b71c4d2af (head)`.

- [ ] **Step 10.2 — Compute signals for the real roster** (synchronous run in the backend
  container):

```bash
docker-compose exec backend python -c "
from app.tasks.long_term import compute_etf_signals_nightly
r = compute_etf_signals_nightly.run()
print(len(r['computed']), 'computed;', 'no bars:', r['skipped_no_bars'], 'failed:', r['failed'])
"
```

Expected: about 65 computed, an empty `failed` list, and an empty `no bars` list. If
`no bars` is non-empty, #913's backfill hasn't covered those tickers. Report it in the PR, and
don't paper over it.

- [ ] **Step 10.3 — Done-when check: a row for every active ticker on the latest day.**

```bash
docker-compose exec backend python -c "
from sqlalchemy import func
from app.core.database import SessionLocal
from app.models import EtfSignalDaily, LtEtf
db = SessionLocal()
latest = db.query(func.max(EtfSignalDaily.date)).scalar()
active = {t for (t,) in db.query(LtEtf.ticker).filter(LtEtf.is_active.is_(True))}
have = {t for (t,) in db.query(EtfSignalDaily.ticker).filter(EtfSignalDaily.date == latest)}
print('latest', latest, 'active', len(active), 'missing', sorted(active - have))
"
```

Expected: `missing []`. Any ticker listed is either stale at the source (its last bar is older)
or has no bars. Name it in the PR description.

- [ ] **Step 10.4 — Curl every endpoint** (cookie auth: log in first).

```bash
curl -s -c /tmp/mh.cookies -X POST http://localhost:8000/api/auth/login \
  -H "Content-Type: application/json" -H "X-Requested-With: XMLHttpRequest" \
  -d '{"username":"'"$ADMIN_USERNAME"'","password":"'"$ADMIN_PASSWORD"'"}' >/dev/null
curl -s -b /tmp/mh.cookies http://localhost:8000/api/v1/long-term/overview | python -m json.tool | head -40
curl -s -b /tmp/mh.cookies "http://localhost:8000/api/v1/long-term/roster?country=CA" | python -m json.tool | head -30
curl -s -b /tmp/mh.cookies "http://localhost:8000/api/v1/long-term/etfs/XIU.TO?history_days=30" | python -m json.tool | head -30
curl -s -b /tmp/mh.cookies -X POST -H "X-Requested-With: XMLHttpRequest" \
  http://localhost:8000/api/v1/long-term/etfs/SPY/recompute | python -m json.tool | grep -E '"(date|rel_ret_1y_vs_benchmark|on_sale_score)"'
curl -s -o /dev/null -w '%{http_code}\n' http://localhost:8000/api/v1/long-term/roster
```

Check the login body/field names against `app/routers/auth.py` before running. Use whatever
credential env vars `DEVELOPMENT.md` documents for the dev stack. Expected:
- overview: `is_stale: false`, 8 `on_sale` entries, a `trend_split` entry per segment
- roster: 19 CA rows, each with a `signal`
- XIU.TO detail: 30 bars
- SPY recompute: `"rel_ret_1y_vs_benchmark": 0.0`
- the last call, made without a cookie: `401`

- [ ] **Step 10.5 — Spot-check total return against a reference.** For SPY, compare
  `ret_1y` with a published 1-year total return as of the same date (e.g. the fund
  page or `yfinance` `auto_adjust=True` closes, via a one-off shell computation). It should
  agree within ~0.3 percentage points (epic §5: "must match a standard total-return index
  within rounding"). Record both numbers in the PR description.

---

## Task 11: Frontend API module

**Files:** `frontend/src/api/longTerm.ts` (create), `frontend/src/api/longTerm.test.ts` (create)

- [ ] **Step 11.1 — Write the failing test.** Create `frontend/src/api/longTerm.test.ts`:

```ts
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { fetchEtfDetail, fetchOverview, fetchRoster, recomputeEtf } from './longTerm';

const mocks = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }));

vi.mock('./client', () => ({
  apiClient: {
    get: (...args: unknown[]) => mocks.get(...args),
    post: (...args: unknown[]) => mocks.post(...args),
  },
}));

describe('longTerm API', () => {
  beforeEach(() => vi.clearAllMocks());

  it('fetches the roster with filters as params', async () => {
    mocks.get.mockResolvedValueOnce({ data: [] });
    await fetchRoster({ segment: 'Sectors', country: 'CA' });
    expect(mocks.get).toHaveBeenCalledWith('/long-term/roster', {
      params: { segment: 'Sectors', country: 'CA' },
    });
  });

  it('fetches the overview', async () => {
    mocks.get.mockResolvedValueOnce({ data: { is_stale: false } });
    const ov = await fetchOverview();
    expect(mocks.get).toHaveBeenCalledWith('/long-term/overview');
    expect(ov.is_stale).toBe(false);
  });

  it('URL-encodes TSX tickers for detail and recompute', async () => {
    mocks.get.mockResolvedValueOnce({ data: {} });
    mocks.post.mockResolvedValueOnce({ data: {} });
    await fetchEtfDetail('XIU.TO');
    await recomputeEtf('XIU.TO');
    expect(mocks.get).toHaveBeenCalledWith('/long-term/etfs/XIU.TO');
    expect(mocks.post).toHaveBeenCalledWith('/long-term/etfs/XIU.TO/recompute');
  });
});
```

(`encodeURIComponent('XIU.TO')` is `XIU.TO`, because `.` is unreserved.)

- [ ] **Step 11.2 — Run, expect failure.** `npx vitest run src/api/longTerm.test.ts` →
  `Failed to resolve import "./longTerm"`.

- [ ] **Step 11.3 — Implement.** Create `frontend/src/api/longTerm.ts`:

```ts
import { apiClient } from './client';

// ---- Types (mirror backend/app/schemas/long_term.py) ---------------------- //
// Returns are total return (dividend-adjusted) in percent; ATR/RSI use raw closes.

export interface EtfSignal {
  ticker: string;
  date: string;
  close: number;
  ret_1d: number | null;
  ret_1w: number | null;
  ret_1m: number | null;
  ret_3m: number | null;
  ret_6m: number | null;
  ret_1y: number | null;
  sma_50: number | null;
  sma_200: number | null;
  pct_from_sma_50: number | null;
  pct_from_sma_200: number | null;
  above_sma_50: boolean | null;
  above_sma_200: boolean | null;
  golden_cross: boolean | null;
  high_52w: number | null;
  drawdown_52w_pct: number | null;
  high_5y: number | null;
  drawdown_5y_pct: number | null;
  pctile_1y: number | null;
  pctile_5y: number | null;
  atr_14_pct: number | null;
  rsi_14: number | null;
  rel_ret_1y_vs_benchmark: number | null;
  history_days: number;
  short_history: boolean;
  on_sale_score: number | null;
  computed_at: string | null;
}

export interface RosterEtf {
  ticker: string;
  name: string;
  segment: string;
  country: 'US' | 'CA' | string;
  currency: string;
  exchange: string | null;
  data_source: string;
  is_active: boolean;
  is_benchmark: boolean;
  tags: string[];
}

export interface RosterEntry extends RosterEtf {
  signal: EtfSignal | null;
}

export interface DailyBar {
  Date: string;
  Open: number;
  High: number;
  Low: number;
  Close: number;
  Volume: number | null;
}

export interface SmaPoint {
  date: string;
  close_tr: number;
  sma_50: number | null;
  sma_200: number | null;
}

export interface EtfDetail {
  etf: RosterEtf;
  signal: EtfSignal | null;
  bars: DailyBar[];
  sma_series: SmaPoint[];
}

export interface TrendSplitSegment {
  segment: string;
  above: string[];
  below: string[];
  unknown: string[];
}

export interface MarketOverview {
  reporting_currency: string;
  latest_signal_date: string | null;
  expected_signal_date: string;
  is_stale: boolean;
  stale_tickers: string[];
  benchmark: RosterEntry | null;
  on_sale: RosterEntry[];
  movers: {
    best_1w: RosterEntry[];
    worst_1w: RosterEntry[];
    best_1m: RosterEntry[];
    worst_1m: RosterEntry[];
  };
  trend_split: TrendSplitSegment[];
}

export interface RosterFilters {
  segment?: string;
  country?: string;
}

// ---- API calls ------------------------------------------------------------ //

export const fetchRoster = async (filters: RosterFilters = {}): Promise<RosterEntry[]> => {
  const response = await apiClient.get('/long-term/roster', { params: filters });
  return response.data;
};

export const fetchOverview = async (): Promise<MarketOverview> => {
  const response = await apiClient.get('/long-term/overview');
  return response.data;
};

export const fetchEtfDetail = async (ticker: string): Promise<EtfDetail> => {
  const response = await apiClient.get(`/long-term/etfs/${encodeURIComponent(ticker)}`);
  return response.data;
};

export const recomputeEtf = async (ticker: string): Promise<EtfDetail> => {
  const response = await apiClient.post(`/long-term/etfs/${encodeURIComponent(ticker)}/recompute`);
  return response.data;
};
```

- [ ] **Step 11.4 — Run, expect pass.** `npx vitest run src/api/longTerm.test.ts` → `3 passed`.

- [ ] **Step 11.5 — Commit.**
  `git add src/api/longTerm.ts src/api/longTerm.test.ts && git commit -m "feat(long-term): frontend API module (#905)"`

---

## Task 12: Page helpers + hooks

**Files:** `frontend/src/pages/LongTerm/format.ts` (create),
`frontend/src/pages/LongTerm/format.test.ts` (create),
`frontend/src/pages/LongTerm/hooks.ts` (create)

- [ ] **Step 12.0 — Read the dataviz skill** (issue requirement, before any chart or card
  styling). Invoke the `dataviz` skill and apply its guidance:
  - colour: signed values use the existing `financial-green`/`financial-red` tokens, never
    colour alone. Signs (`+`/`−`) and labels stay on every number.
  - the two SMA price lines need distinct, labelled hues.
  - no new chart library.

  The SMA hues below are `#38bdf8` and `#f59e0b`, which `utils/replayChartOverlays.ts`
  already uses on the same dark chart. Adjust them only if the skill's contrast check
  rejects them.

- [ ] **Step 12.1 — Write the failing test.** Create `frontend/src/pages/LongTerm/format.test.ts`:

```ts
import { describe, expect, it } from 'vitest';
import { buildSmaPriceLines, fmtPct, sortRoster } from './format';
import type { EtfSignal, RosterEntry } from '../../api/longTerm';

const sig = (over: Partial<EtfSignal>): EtfSignal =>
  ({ ticker: 'X', date: '2026-11-06', close: 1, history_days: 1260, short_history: false,
     on_sale_score: null, ret_1y: null, sma_50: null, sma_200: null, ...over } as EtfSignal);

const entry = (ticker: string, signal: EtfSignal | null): RosterEntry => ({
  ticker, name: ticker, segment: 'Sectors', country: 'US', currency: 'USD', exchange: null,
  data_source: 'massive', is_active: true, is_benchmark: false, tags: [], signal,
});

describe('format helpers', () => {
  it('formats signed percents and nulls', () => {
    expect(fmtPct(5.234)).toBe('+5.2%');
    expect(fmtPct(-1.05, 2)).toBe('-1.05%');
    expect(fmtPct(null)).toBe('—');
  });

  it('sorts by a signal column with nulls last in both directions', () => {
    const rows = [entry('A', sig({ on_sale_score: 10 })), entry('B', null), entry('C', sig({ on_sale_score: 90 }))];
    expect(sortRoster(rows, 'on_sale_score', 'desc').map((r) => r.ticker)).toEqual(['C', 'A', 'B']);
    expect(sortRoster(rows, 'on_sale_score', 'asc').map((r) => r.ticker)).toEqual(['A', 'C', 'B']);
    expect(sortRoster(rows, 'ticker', 'desc').map((r) => r.ticker)).toEqual(['C', 'B', 'A']);
  });

  it('builds SMA50/SMA200 price lines only for present values', () => {
    expect(buildSmaPriceLines(sig({ sma_50: 100, sma_200: 90 }))).toEqual([
      { value: 100, color: '#38bdf8', label: 'SMA50' },
      { value: 90, color: '#f59e0b', label: 'SMA200' },
    ]);
    expect(buildSmaPriceLines(sig({ sma_50: 100 }))).toHaveLength(1);
    expect(buildSmaPriceLines(null)).toEqual([]);
  });
});
```

- [ ] **Step 12.2 — Run, expect failure.** `npx vitest run src/pages/LongTerm/format.test.ts` → import error.

- [ ] **Step 12.3 — Implement `format.ts`.**

```ts
import type { EtfSignal, RosterEntry } from '../../api/longTerm';

export const fmtPct = (v: number | null | undefined, digits = 1): string =>
  v == null ? '—' : `${v > 0 ? '+' : ''}${v.toFixed(digits)}%`;

export const fmtNum = (v: number | null | undefined, digits = 1): string =>
  v == null ? '—' : v.toFixed(digits);

export const signClass = (v: number | null | undefined): string => {
  if (v == null) return 'text-gray-500';
  if (v > 0) return 'text-financial-green';
  if (v < 0) return 'text-financial-red';
  return 'text-gray-300';
};

export type SignalSortKey =
  | 'on_sale_score' | 'ret_1d' | 'ret_1w' | 'ret_1m' | 'ret_3m' | 'ret_6m' | 'ret_1y'
  | 'rel_ret_1y_vs_benchmark' | 'pct_from_sma_50' | 'pct_from_sma_200'
  | 'drawdown_52w_pct' | 'drawdown_5y_pct' | 'pctile_1y' | 'pctile_5y'
  | 'atr_14_pct' | 'rsi_14' | 'close';
export type SortKey = 'ticker' | 'name' | 'segment' | 'country' | SignalSortKey;
export type SortDir = 'asc' | 'desc';

const TEXT_KEYS: ReadonlySet<SortKey> = new Set(['ticker', 'name', 'segment', 'country']);

export function sortRoster(rows: RosterEntry[], key: SortKey, dir: SortDir): RosterEntry[] {
  const sign = dir === 'asc' ? 1 : -1;
  return [...rows].sort((a, b) => {
    if (TEXT_KEYS.has(key)) {
      const k = key as 'ticker' | 'name' | 'segment' | 'country';
      return sign * a[k].localeCompare(b[k]);
    }
    const av = a.signal ? (a.signal[key as SignalSortKey] as number | null) : null;
    const bv = b.signal ? (b.signal[key as SignalSortKey] as number | null) : null;
    if (av == null && bv == null) return a.ticker.localeCompare(b.ticker);
    if (av == null) return 1; // nulls last regardless of direction
    if (bv == null) return -1;
    return sign * (av - bv) || a.ticker.localeCompare(b.ticker);
  });
}

export const SMA50_COLOR = '#38bdf8';
export const SMA200_COLOR = '#f59e0b';

export function buildSmaPriceLines(
  signal: EtfSignal | null | undefined,
): Array<{ value: number; color: string; label: string }> {
  if (!signal) return [];
  const lines: Array<{ value: number; color: string; label: string }> = [];
  if (signal.sma_50 != null) lines.push({ value: signal.sma_50, color: SMA50_COLOR, label: 'SMA50' });
  if (signal.sma_200 != null) lines.push({ value: signal.sma_200, color: SMA200_COLOR, label: 'SMA200' });
  return lines;
}

export const ON_SALE_FORMULA =
  'on_sale_score = 100 − mean(pctile_1y, pctile_5y, clamp(50 + % from SMA200, 0, 100)); ' +
  'pctile_5y is dropped when history < 3 years. Higher = cheaper vs. its own history.';
```

- [ ] **Step 12.4 — Implement `hooks.ts`.**

```ts
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  fetchEtfDetail,
  fetchOverview,
  fetchRoster,
  recomputeEtf,
  type RosterFilters,
} from '../../api/longTerm';

const STALE_MS = 5 * 60_000; // signals change once a night

export const longTermKeys = {
  all: ['long-term'] as const,
  overview: ['long-term', 'overview'] as const,
  roster: (filters: RosterFilters) => ['long-term', 'roster', filters] as const,
  etf: (ticker: string) => ['long-term', 'etf', ticker] as const,
};

export const useLongTermOverview = () =>
  useQuery({ queryKey: longTermKeys.overview, queryFn: fetchOverview, staleTime: STALE_MS });

export const useLongTermRoster = (filters: RosterFilters) =>
  useQuery({
    queryKey: longTermKeys.roster(filters),
    queryFn: () => fetchRoster(filters),
    staleTime: STALE_MS,
  });

export const useEtfDetail = (ticker: string | null, isOpen: boolean) =>
  useQuery({
    queryKey: longTermKeys.etf(ticker ?? ''),
    queryFn: () => fetchEtfDetail(ticker as string),
    enabled: isOpen && !!ticker,
    staleTime: STALE_MS,
  });

export const useRecomputeEtf = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: recomputeEtf,
    onSuccess: (data) => {
      qc.setQueryData(longTermKeys.etf(data.etf.ticker), data);
      qc.invalidateQueries({ queryKey: longTermKeys.overview });
      qc.invalidateQueries({ queryKey: ['long-term', 'roster'] });
    },
  });
};
```

- [ ] **Step 12.5 — Run, expect pass.** `npx vitest run src/pages/LongTerm/format.test.ts` → `3 passed`.

- [ ] **Step 12.6 — Commit.**
  `git add src/pages/LongTerm/format.ts src/pages/LongTerm/format.test.ts src/pages/LongTerm/hooks.ts`
  `git commit -m "feat(long-term): page helpers and React Query hooks (#905)"`

---

## Task 13: Page sections, drawer, route, sidebar

**Files:** `frontend/src/pages/LongTerm/{HeaderStrip,OnSaleCards,Movers,TrendSplit,RosterTable,EtfDetailDrawer,index}.tsx`
(create), `frontend/src/pages/LongTerm/LongTerm.test.tsx` (create), `frontend/src/App.tsx`,
`frontend/src/components/Layout.tsx` (modify)

- [ ] **Step 13.1 — Write the failing page test.** Create
  `frontend/src/pages/LongTerm/LongTerm.test.tsx`:

```tsx
import { describe, expect, it, vi } from 'vitest';
import { fireEvent, screen } from '@testing-library/react';
import { renderWithQuery } from '../../test-utils/renderWithQuery';
import LongTerm from './index';
import type { MarketOverview, RosterEntry } from '../../api/longTerm';

const spy: RosterEntry = {
  ticker: 'SPY', name: 'SPDR S&P 500', segment: 'Broad market', country: 'US', currency: 'USD',
  exchange: 'NYSEARCA', data_source: 'massive', is_active: true, is_benchmark: true, tags: [],
  signal: {
    ticker: 'SPY', date: '2026-11-06', close: 600, ret_1d: 0.1, ret_1w: 1, ret_1m: 2, ret_3m: 3,
    ret_6m: 4, ret_1y: 12.3, sma_50: 590, sma_200: 560, pct_from_sma_50: 1.7, pct_from_sma_200: 7.1,
    above_sma_50: true, above_sma_200: true, golden_cross: true, high_52w: 610, drawdown_52w_pct: -1.6,
    high_5y: 610, drawdown_5y_pct: -1.6, pctile_1y: 95, pctile_5y: 98, atr_14_pct: 1.1, rsi_14: 60,
    rel_ret_1y_vs_benchmark: 0, history_days: 1260, short_history: false, on_sale_score: 3.1,
    computed_at: null,
  },
};
const ibit: RosterEntry = { ...spy, ticker: 'IBIT', name: 'iShares Bitcoin', segment: 'Crypto',
  is_benchmark: false, signal: { ...spy.signal!, ticker: 'IBIT', short_history: true, on_sale_score: 70 } };

const overview: MarketOverview = {
  reporting_currency: 'CAD', latest_signal_date: '2026-11-06', expected_signal_date: '2026-11-06',
  is_stale: false, stale_tickers: [], benchmark: spy, on_sale: [ibit, spy],
  movers: { best_1w: [spy], worst_1w: [ibit], best_1m: [spy], worst_1m: [ibit] },
  trend_split: [{ segment: 'Broad market', above: ['SPY'], below: [], unknown: [] }],
};

const { detailHook } = vi.hoisted(() => ({
  detailHook: vi.fn<(ticker: string | null, isOpen: boolean) => { data: undefined; isLoading: boolean }>(
    () => ({ data: undefined, isLoading: false }),
  ),
}));

vi.mock('./hooks', () => ({
  useLongTermOverview: () => ({ data: overview, isLoading: false, isError: false }),
  useLongTermRoster: () => ({ data: [spy, ibit], isLoading: false, isError: false }),
  useEtfDetail: (ticker: string | null, isOpen: boolean) => detailHook(ticker, isOpen),
  useRecomputeEtf: () => ({ mutate: vi.fn(), isPending: false }),
}));

vi.mock('../../components/ui/StockChart', () => ({
  default: () => <div data-testid="stock-chart" />,
}));

describe('LongTerm page', () => {
  it('renders header strip with currency, signal date and benchmark 1y return', () => {
    renderWithQuery(<LongTerm />);
    expect(screen.getByText('CAD')).toBeInTheDocument();
    expect(screen.getAllByText('2026-11-06').length).toBeGreaterThan(0);
    expect(screen.getByText(/Benchmark SPY 1Y/i)).toBeInTheDocument();
    expect(screen.getAllByText('+12.3%').length).toBeGreaterThan(0);
    expect(screen.queryByText(/signals stale/i)).not.toBeInTheDocument();
  });

  it('renders on-sale cards with a short-history badge', () => {
    renderWithQuery(<LongTerm />);
    expect(screen.getByRole('heading', { name: /on sale now/i })).toBeInTheDocument();
    expect(screen.getAllByText(/short history/i).length).toBeGreaterThan(0);
  });

  it('opens the detail drawer when a roster row is clicked', () => {
    renderWithQuery(<LongTerm />);
    fireEvent.click(screen.getByRole('row', { name: /IBIT/ }));
    expect(detailHook).toHaveBeenLastCalledWith('IBIT', true);
  });
});
```

- [ ] **Step 13.2 — Run, expect failure.** `npx vitest run src/pages/LongTerm/LongTerm.test.tsx` → `Failed to resolve import "./index"`.

- [ ] **Step 13.3 — `HeaderStrip.tsx`** (epic §4.8 item 1):

```tsx
import React from 'react';
import { AlertTriangle } from 'lucide-react';
import type { MarketOverview } from '../../api/longTerm';
import { fmtPct, signClass } from './format';

const Stat: React.FC<{ label: string; children: React.ReactNode }> = ({ label, children }) => (
  <div className="bg-gray-950 border border-gray-800 rounded-lg px-4 py-3">
    <p className="text-[10px] uppercase tracking-widest text-gray-500 font-bold">{label}</p>
    <div className="text-lg font-bold text-financial-light mt-1">{children}</div>
  </div>
);

const HeaderStrip: React.FC<{ overview: MarketOverview }> = ({ overview }) => {
  const benchRet = overview.benchmark?.signal?.ret_1y ?? null;
  return (
    <section className="space-y-3">
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <Stat label="Reporting currency">{overview.reporting_currency}</Stat>
        <Stat label="Last signal date">{overview.latest_signal_date ?? '—'}</Stat>
        <Stat label={`Benchmark ${overview.benchmark?.ticker ?? 'SPY'} 1Y (total return)`}>
          <span className={signClass(benchRet)}>{fmtPct(benchRet)}</span>
        </Stat>
        <Stat label="Expected signal date">{overview.expected_signal_date}</Stat>
      </div>
      {overview.is_stale && (
        <div className="flex items-center gap-2 rounded-lg border border-financial-yellow/40 bg-financial-yellow/10 px-4 py-2 text-sm text-financial-yellow">
          <AlertTriangle className="h-4 w-4" />
          Signals stale — latest {overview.latest_signal_date ?? 'none'}, expected {overview.expected_signal_date}.
        </div>
      )}
      {overview.stale_tickers.length > 0 && (
        <p className="text-xs text-gray-400">
          Behind the latest date: {overview.stale_tickers.join(', ')}
        </p>
      )}
      <p className="text-xs text-gray-500">
        All returns are total return (dividends reinvested), in the ETF's listing currency.
      </p>
    </section>
  );
};

export default HeaderStrip;
```

- [ ] **Step 13.4 — `OnSaleCards.tsx`** (item 2: segment, score, 52w drawdown, distance from
  SMA200, short-history badge; formula documented):

```tsx
import React from 'react';
import type { RosterEntry } from '../../api/longTerm';
import { fmtNum, fmtPct, ON_SALE_FORMULA, signClass } from './format';

export const ShortHistoryBadge: React.FC = () => (
  <span className="rounded border border-financial-yellow/40 px-1.5 py-0.5 text-[10px] uppercase tracking-wide text-financial-yellow">
    short history
  </span>
);

const OnSaleCards: React.FC<{ entries: RosterEntry[]; onSelect: (ticker: string) => void }> = ({
  entries,
  onSelect,
}) => (
  <section>
    <h2 className="text-lg font-semibold text-financial-light">On sale now</h2>
    <p className="text-xs text-gray-500 mb-3">{ON_SALE_FORMULA}</p>
    {entries.length === 0 ? (
      <p className="text-sm text-gray-500">No scored ETFs yet.</p>
    ) : (
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        {entries.map((e) => (
          <button
            key={e.ticker}
            type="button"
            onClick={() => onSelect(e.ticker)}
            className="text-left bg-gray-950 border border-gray-800 hover:border-financial-blue rounded-lg p-3 space-y-1"
          >
            <div className="flex items-center justify-between">
              <span className="font-bold text-financial-light">{e.ticker}</span>
              {e.signal?.short_history && <ShortHistoryBadge />}
            </div>
            <p className="text-xs text-gray-500">{e.segment}</p>
            <p className="text-2xl font-bold text-financial-light">{fmtNum(e.signal?.on_sale_score, 0)}</p>
            <p className="text-xs text-gray-400">
              52w DD <span className={signClass(e.signal?.drawdown_52w_pct)}>{fmtPct(e.signal?.drawdown_52w_pct)}</span>
              {' · '}vs SMA200{' '}
              <span className={signClass(e.signal?.pct_from_sma_200)}>{fmtPct(e.signal?.pct_from_sma_200)}</span>
            </p>
          </button>
        ))}
      </div>
    )}
  </section>
);

export default OnSaleCards;
```

- [ ] **Step 13.5 — `Movers.tsx`** (item 3):

```tsx
import React from 'react';
import type { MarketOverview, RosterEntry } from '../../api/longTerm';
import { fmtPct, signClass } from './format';

const List: React.FC<{
  title: string;
  rows: RosterEntry[];
  field: 'ret_1w' | 'ret_1m';
  onSelect: (t: string) => void;
}> = ({ title, rows, field, onSelect }) => (
  <div className="bg-gray-950 border border-gray-800 rounded-lg p-3">
    <h3 className="text-xs uppercase tracking-widest text-gray-500 font-bold mb-2">{title}</h3>
    {rows.length === 0 ? (
      <p className="text-sm text-gray-500">—</p>
    ) : (
      <ul className="space-y-1">
        {rows.map((r) => (
          <li key={r.ticker}>
            <button type="button" onClick={() => onSelect(r.ticker)} className="flex w-full justify-between text-sm hover:text-financial-blue">
              <span className="text-financial-light">{r.ticker}</span>
              <span className={signClass(r.signal?.[field])}>{fmtPct(r.signal?.[field])}</span>
            </button>
          </li>
        ))}
      </ul>
    )}
  </div>
);

const Movers: React.FC<{ movers: MarketOverview['movers']; onSelect: (t: string) => void }> = ({ movers, onSelect }) => (
  <section>
    <h2 className="text-lg font-semibold text-financial-light mb-3">Movers</h2>
    <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
      <List title="Best 1W" rows={movers.best_1w} field="ret_1w" onSelect={onSelect} />
      <List title="Worst 1W" rows={movers.worst_1w} field="ret_1w" onSelect={onSelect} />
      <List title="Best 1M" rows={movers.best_1m} field="ret_1m" onSelect={onSelect} />
      <List title="Worst 1M" rows={movers.worst_1m} field="ret_1m" onSelect={onSelect} />
    </div>
  </section>
);

export default Movers;
```

- [ ] **Step 13.6 — `TrendSplit.tsx`** (item 4: compact two-column list by segment):

```tsx
import React from 'react';
import type { TrendSplitSegment } from '../../api/longTerm';

const TrendSplit: React.FC<{ segments: TrendSplitSegment[] }> = ({ segments }) => (
  <section>
    <h2 className="text-lg font-semibold text-financial-light mb-3">Trend split (vs SMA50)</h2>
    <div className="overflow-x-auto border border-gray-800 rounded-lg">
      <table className="min-w-full text-sm">
        <thead className="bg-gray-950 text-xs uppercase text-gray-500">
          <tr>
            <th className="px-3 py-2 text-left">Segment</th>
            <th className="px-3 py-2 text-left">▲ Above SMA50</th>
            <th className="px-3 py-2 text-left">▼ Below SMA50</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-800">
          {segments.map((s) => (
            <tr key={s.segment}>
              <td className="px-3 py-2 text-gray-300">
                {s.segment}{' '}
                <span className="text-gray-500">({s.above.length}/{s.above.length + s.below.length})</span>
              </td>
              <td className="px-3 py-2 text-financial-green">{s.above.join(', ') || '—'}</td>
              <td className="px-3 py-2 text-financial-red">
                {s.below.join(', ') || '—'}
                {s.unknown.length > 0 && (
                  <span className="block text-xs text-gray-500">no data: {s.unknown.join(', ')}</span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  </section>
);

export default TrendSplit;
```

- [ ] **Step 13.7 — `RosterTable.tsx`** (item 5: filter by segment/country, sortable on every
  signal column, click opens drawer):

```tsx
import React, { useMemo, useState } from 'react';
import type { RosterEntry } from '../../api/longTerm';
import { ShortHistoryBadge } from './OnSaleCards';
import { fmtNum, fmtPct, signClass, sortRoster, type SortDir, type SortKey } from './format';

type Col = { key: SortKey; label: string; kind: 'text' | 'pct' | 'num' };

const COLUMNS: Col[] = [
  { key: 'ticker', label: 'Ticker', kind: 'text' },
  { key: 'name', label: 'Name', kind: 'text' },
  { key: 'segment', label: 'Segment', kind: 'text' },
  { key: 'country', label: 'Ctry', kind: 'text' },
  { key: 'on_sale_score', label: 'On-sale', kind: 'num' },
  { key: 'ret_1d', label: '1D', kind: 'pct' },
  { key: 'ret_1w', label: '1W', kind: 'pct' },
  { key: 'ret_1m', label: '1M', kind: 'pct' },
  { key: 'ret_3m', label: '3M', kind: 'pct' },
  { key: 'ret_6m', label: '6M', kind: 'pct' },
  { key: 'ret_1y', label: '1Y', kind: 'pct' },
  { key: 'rel_ret_1y_vs_benchmark', label: '1Y vs SPY', kind: 'pct' },
  { key: 'pct_from_sma_50', label: 'vs SMA50', kind: 'pct' },
  { key: 'pct_from_sma_200', label: 'vs SMA200', kind: 'pct' },
  { key: 'drawdown_52w_pct', label: 'DD 52w', kind: 'pct' },
  { key: 'drawdown_5y_pct', label: 'DD 5y', kind: 'pct' },
  { key: 'pctile_1y', label: 'Pctl 1y', kind: 'num' },
  { key: 'pctile_5y', label: 'Pctl 5y', kind: 'num' },
  { key: 'atr_14_pct', label: 'ATR%', kind: 'num' },
  { key: 'rsi_14', label: 'RSI', kind: 'num' },
];

interface Props {
  rows: RosterEntry[];
  segments: string[];
  segment: string;
  country: string;
  onSegmentChange: (v: string) => void;
  onCountryChange: (v: string) => void;
  onSelect: (ticker: string) => void;
}

const RosterTable: React.FC<Props> = ({ rows, segments, segment, country, onSegmentChange, onCountryChange, onSelect }) => {
  const [sortKey, setSortKey] = useState<SortKey>('on_sale_score');
  const [sortDir, setSortDir] = useState<SortDir>('desc');
  const sorted = useMemo(() => sortRoster(rows, sortKey, sortDir), [rows, sortKey, sortDir]);

  const toggleSort = (key: SortKey) => {
    if (key === sortKey) setSortDir(sortDir === 'asc' ? 'desc' : 'asc');
    else {
      setSortKey(key);
      setSortDir(COLUMNS.find((c) => c.key === key)?.kind === 'text' ? 'asc' : 'desc');
    }
  };

  const cell = (r: RosterEntry, c: Col) => {
    if (c.kind === 'text') {
      const v = r[c.key as 'ticker' | 'name' | 'segment' | 'country'];
      return c.key === 'ticker' ? (
        <span className="flex items-center gap-1 font-semibold text-financial-light">
          {v}
          {r.signal?.short_history && <ShortHistoryBadge />}
        </span>
      ) : (
        v
      );
    }
    const v = r.signal ? (r.signal[c.key as keyof typeof r.signal] as number | null) : null;
    return c.kind === 'pct' ? <span className={signClass(v)}>{fmtPct(v)}</span> : fmtNum(v);
  };

  return (
    <section>
      <div className="flex flex-wrap items-center justify-between gap-3 mb-3">
        <h2 className="text-lg font-semibold text-financial-light">Roster</h2>
        <div className="flex gap-2">
          <select aria-label="Segment filter" value={segment} onChange={(e) => onSegmentChange(e.target.value)}
            className="bg-gray-900 border border-gray-700 rounded px-2 py-1 text-sm text-gray-200">
            <option value="">All segments</option>
            {segments.map((s) => <option key={s} value={s}>{s}</option>)}
          </select>
          <select aria-label="Country filter" value={country} onChange={(e) => onCountryChange(e.target.value)}
            className="bg-gray-900 border border-gray-700 rounded px-2 py-1 text-sm text-gray-200">
            <option value="">All countries</option>
            <option value="US">US</option>
            <option value="CA">CA</option>
          </select>
        </div>
      </div>
      <div className="overflow-x-auto border border-gray-800 rounded-lg">
        <table className="min-w-full text-sm whitespace-nowrap">
          <thead className="bg-gray-950 text-xs uppercase text-gray-500">
            <tr>
              {COLUMNS.map((c) => (
                <th key={c.key} className="px-3 py-2 text-left">
                  <button type="button" onClick={() => toggleSort(c.key)} className="hover:text-gray-200">
                    {c.label}
                    {sortKey === c.key ? (sortDir === 'asc' ? ' ▲' : ' ▼') : ''}
                  </button>
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-800">
            {sorted.map((r) => (
              <tr key={r.ticker} aria-label={r.ticker} onClick={() => onSelect(r.ticker)}
                className="cursor-pointer hover:bg-gray-800/50">
                {COLUMNS.map((c) => (
                  <td key={c.key} className="px-3 py-2 text-gray-300">{cell(r, c)}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
};

export default RosterTable;
```

- [ ] **Step 13.8 — `EtfDetailDrawer.tsx`** (item 6: `Modal` + `StockChart` daily mode,
  SuperTrend toggle, SMA50/200 price lines, full signal row):

```tsx
import React, { useMemo, useState } from 'react';
import { RefreshCw } from 'lucide-react';
import Modal from '../../components/ui/Modal';
import StockChart from '../../components/ui/StockChart';
import type { EtfSignal } from '../../api/longTerm';
import { useEtfDetail, useRecomputeEtf } from './hooks';
import { buildSmaPriceLines, fmtNum, fmtPct } from './format';

const SIGNAL_FIELDS: Array<{ key: keyof EtfSignal; label: string; kind: 'pct' | 'num' | 'bool' | 'text' }> = [
  { key: 'date', label: 'Date', kind: 'text' },
  { key: 'close', label: 'Close (raw)', kind: 'num' },
  { key: 'on_sale_score', label: 'On-sale score', kind: 'num' },
  { key: 'ret_1d', label: 'Return 1D', kind: 'pct' },
  { key: 'ret_1w', label: 'Return 1W', kind: 'pct' },
  { key: 'ret_1m', label: 'Return 1M', kind: 'pct' },
  { key: 'ret_3m', label: 'Return 3M', kind: 'pct' },
  { key: 'ret_6m', label: 'Return 6M', kind: 'pct' },
  { key: 'ret_1y', label: 'Return 1Y', kind: 'pct' },
  { key: 'rel_ret_1y_vs_benchmark', label: '1Y vs SPY', kind: 'pct' },
  { key: 'sma_50', label: 'SMA50 (TR)', kind: 'num' },
  { key: 'sma_200', label: 'SMA200 (TR)', kind: 'num' },
  { key: 'pct_from_sma_50', label: 'vs SMA50', kind: 'pct' },
  { key: 'pct_from_sma_200', label: 'vs SMA200', kind: 'pct' },
  { key: 'above_sma_50', label: 'Above SMA50', kind: 'bool' },
  { key: 'above_sma_200', label: 'Above SMA200', kind: 'bool' },
  { key: 'golden_cross', label: 'Golden cross', kind: 'bool' },
  { key: 'high_52w', label: 'High 52w (TR)', kind: 'num' },
  { key: 'drawdown_52w_pct', label: 'Drawdown 52w', kind: 'pct' },
  { key: 'high_5y', label: 'High 5y (TR)', kind: 'num' },
  { key: 'drawdown_5y_pct', label: 'Drawdown 5y', kind: 'pct' },
  { key: 'pctile_1y', label: 'Percentile 1y', kind: 'num' },
  { key: 'pctile_5y', label: 'Percentile 5y', kind: 'num' },
  { key: 'atr_14_pct', label: 'ATR14 % (raw)', kind: 'num' },
  { key: 'rsi_14', label: 'RSI14 (raw)', kind: 'num' },
  { key: 'history_days', label: 'History (bars)', kind: 'text' },
  { key: 'short_history', label: 'Short history', kind: 'bool' },
];

const render = (s: EtfSignal, f: (typeof SIGNAL_FIELDS)[number]): string => {
  const v = s[f.key];
  if (v == null) return '—';
  if (f.kind === 'pct') return fmtPct(v as number, 2);
  if (f.kind === 'num') return fmtNum(v as number, 2);
  if (f.kind === 'bool') return v ? 'Yes' : 'No';
  return String(v);
};

interface Props {
  ticker: string | null;
  isOpen: boolean;
  onClose: () => void;
}

const EtfDetailDrawer: React.FC<Props> = ({ ticker, isOpen, onClose }) => {
  const [superTrend, setSuperTrend] = useState(true);
  const { data, isLoading } = useEtfDetail(ticker, isOpen);
  const recompute = useRecomputeEtf();
  const priceLines = useMemo(() => buildSmaPriceLines(data?.signal), [data?.signal]);

  return (
    <Modal isOpen={isOpen} onClose={onClose} size="xl"
      title={data ? `${data.etf.ticker} — ${data.etf.name}` : ticker ?? ''}>
      {isLoading || !data ? (
        <p className="text-sm text-gray-500">Loading…</p>
      ) : (
        <div className="space-y-4">
          <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-gray-400">
            <span>{data.etf.segment} · {data.etf.country} · {data.etf.currency}</span>
            <div className="flex items-center gap-3">
              <label className="flex items-center gap-1">
                <input type="checkbox" checked={superTrend} onChange={(e) => setSuperTrend(e.target.checked)} />
                SuperTrend
              </label>
              <button type="button" disabled={recompute.isPending}
                onClick={() => ticker && recompute.mutate(ticker)}
                className="flex items-center gap-1 rounded border border-gray-700 px-2 py-1 hover:border-financial-blue disabled:opacity-50">
                <RefreshCw className={`h-3 w-3 ${recompute.isPending ? 'animate-spin' : ''}`} />
                Recompute
              </button>
            </div>
          </div>
          {data.bars.length === 0 ? (
            <p className="text-sm text-gray-500">No daily bars stored yet.</p>
          ) : (
            <div className="border border-gray-800 rounded-lg overflow-hidden bg-gray-950">
              <StockChart data={data.bars} type="candlestick" timespan="day" height={380}
                symbol={data.etf.ticker} showDoubleSuperTrend={superTrend} priceLines={priceLines} />
            </div>
          )}
          <p className="text-xs text-gray-500">
            Candles are raw closes; SMA lines and all returns use the total-return (dividend-adjusted) series.
          </p>
          {data.signal ? (
            <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
              {SIGNAL_FIELDS.map((f) => (
                <div key={f.key} className="bg-gray-950 border border-gray-800 rounded px-3 py-2">
                  <p className="text-[10px] uppercase tracking-widest text-gray-500">{f.label}</p>
                  <p className="text-sm font-semibold text-financial-light">{render(data.signal!, f)}</p>
                </div>
              ))}
            </div>
          ) : (
            <p className="text-sm text-gray-500">No signal row computed yet.</p>
          )}
        </div>
      )}
    </Modal>
  );
};

export default EtfDetailDrawer;
```

Check the `StockChart` `data` prop type. `DailyBar` is structurally a subset of `StockBarRow`
(all of `Date/Open/High/Low/Close/Volume` are optional there), so this should type-check
without a cast. If `tsc` complains, import `type StockBarRow` and pass
`data.bars as StockBarRow[]`.

- [ ] **Step 13.9 — `index.tsx`** (composition; `useState<string | null>` selected ticker,
  the same pattern as `Universes.tsx` + `UniverseDetailsModal`):

```tsx
import React, { useCallback, useMemo, useState } from 'react';
import { LineChart } from 'lucide-react';
import HeaderStrip from './HeaderStrip';
import OnSaleCards from './OnSaleCards';
import Movers from './Movers';
import TrendSplit from './TrendSplit';
import RosterTable from './RosterTable';
import EtfDetailDrawer from './EtfDetailDrawer';
import { useLongTermOverview, useLongTermRoster } from './hooks';

const LongTerm: React.FC = () => {
  const [selectedTicker, setSelectedTicker] = useState<string | null>(null);
  const [segment, setSegment] = useState('');
  const [country, setCountry] = useState('');
  const filters = useMemo(
    () => ({ ...(segment ? { segment } : {}), ...(country ? { country } : {}) }),
    [segment, country],
  );
  const overview = useLongTermOverview();
  const roster = useLongTermRoster(filters);
  const segments = useMemo(
    () => (overview.data?.trend_split ?? []).map((s) => s.segment),
    [overview.data?.trend_split],
  );
  const closeDrawer = useCallback(() => setSelectedTicker(null), []);

  return (
    <div className="space-y-6 p-6">
      <div className="flex items-center gap-2">
        <LineChart className="h-6 w-6 text-financial-blue" />
        <h1 className="text-2xl font-bold text-financial-light">Long-Term</h1>
      </div>

      {overview.isLoading ? (
        <p className="text-sm text-gray-500">Loading overview…</p>
      ) : overview.isError || !overview.data ? (
        <p className="text-sm text-financial-red">Could not load the long-term overview.</p>
      ) : (
        <>
          <HeaderStrip overview={overview.data} />
          <OnSaleCards entries={overview.data.on_sale} onSelect={setSelectedTicker} />
          <Movers movers={overview.data.movers} onSelect={setSelectedTicker} />
          <TrendSplit segments={overview.data.trend_split} />
        </>
      )}

      {roster.isError ? (
        <p className="text-sm text-financial-red">Could not load the roster.</p>
      ) : (
        <RosterTable
          rows={roster.data ?? []}
          segments={segments}
          segment={segment}
          country={country}
          onSegmentChange={setSegment}
          onCountryChange={setCountry}
          onSelect={setSelectedTicker}
        />
      )}

      <EtfDetailDrawer ticker={selectedTicker} isOpen={!!selectedTicker} onClose={closeDrawer} />
    </div>
  );
};

export default LongTerm;
```

- [ ] **Step 13.10 — Route + sidebar.** In `frontend/src/App.tsx`, add
  `const LongTerm = lazy(() => import('./pages/LongTerm'));` after the `Replay` lazy import,
  and `<Route path="/long-term" element={<LongTerm />} />` after the `/replay` route. In
  `frontend/src/components/Layout.tsx`, add `LineChart,` to the `lucide-react` import list and
  `{ name: 'Long-Term', href: '/long-term', icon: LineChart },` to `navigation`, directly
  after the `Universes` entry. `TrendingUp` is already taken by Pre-market Movers (spec §3.6).

- [ ] **Step 13.11 — Run tests, type check, lint.**

```bash
npx vitest run src/pages/LongTerm src/api/longTerm.test.ts
npx tsc --noEmit
npx tsc -p tsconfig.app.json --noEmit
npm run lint
```

Expected: all vitest tests pass, both `tsc` invocations print nothing (exit 0), and eslint
reports 0 problems. The project's `build` script uses `tsc -p tsconfig.app.json`, so run both
to match CLAUDE.md's gate and the build. If the `getByRole('row', { name: /IBIT/ })`
query is ambiguous, scope it with `within(screen.getByRole('table', …))`. There are two
tables (trend split and roster), and only the roster rows carry `aria-label`.

- [ ] **Step 13.12 — Commit.**
  `git add src/pages/LongTerm src/App.tsx src/components/Layout.tsx`
  `git commit -m "feat(long-term): read-only /long-term page with detail drawer (#905)"`

---

## Task 14: End-to-end verification + PR notes

**Files:** none

- [ ] **Step 14.1 — Browser check** (CLAUDE.md: UI changes are verified in the browser). Open
  `http://localhost:3333/long-term` while logged in and confirm:
  1. The "Long-Term" sidebar entry shows the line-chart icon and is highlighted.
  2. The header shows `CAD`, the latest signal date, and SPY's 1Y total return. There is no
     stale banner after Task 10.
  3. Eight on-sale cards appear, with a "short history" badge on IBIT/ETHA/BTCC.TO/ETHX.TO
     if they rank.
  4. All four movers lists are filled.
  5. The trend split has one row per segment.
  6. The roster filters work: CA gives 19 rows; Sectors gives 20 rows across both countries.
  7. Clicking any column header sorts it, with nulls last.
  8. Clicking `XIU.TO` opens the drawer with daily candles, the SuperTrend overlay, and the
     two labelled SMA lines. Unticking SuperTrend removes the overlay. Recompute succeeds and
     refreshes the stat grid.

- [ ] **Step 14.2 — Final suite.** From `backend/`, run `python -m pytest -q`. From
  `frontend/`, run `npm test`. Both must be green.

- [ ] **Step 14.3 — PR description must record:**
  - the `down_revision` chosen in Task 2
  - Task 10.3's `missing` list
  - Task 10.5's SPY total-return comparison
  - any ticker in `skipped_no_bars`
  - the spec deltas above (1–15), so the reviewer sees the pinned decisions

---

## Self-review

- **Issue line:** `**Issue:** #905` sits directly under the title. ✔
- **Spec coverage:**
  - §3.1 table/columns/indexes → Tasks 1–2
  - §3.2 single service function + `services/long_term/{signals,roster}.py` → Tasks 4–6
  - §3.3 percentile/NULL gating/on-sale/benchmark → Task 4 tests + Task 5 rel-return
    tests
  - §3.4 batch task, 02:30 Tue–Sat, sync recompute → Tasks 8–9
  - §3.5 four endpoints, movers = 5, cookie auth → Tasks 7–8 (`test_requires_auth`)
  - §3.6 route, sidebar `LineChart`, `api/longTerm.ts`, `pages/LongTerm/`, Modal +
    StockChart drawer with `showDoubleSuperTrend` + SMA50/200 `priceLines`, dataviz skill
    → Tasks 11–13
  - acceptance: rows for every active ticker (Task 10.3), page renders real data
    (Task 14.1), `npx tsc --noEmit` (13.11), curl verification (10.4)
- **Out of scope respected:** no MCP server, no Portfolio/Proposals tabs, no `lt_account`
  or similar models, and no write path for the reporting currency.
- **Memory lessons baked in:**
  - the new model is registered in `models/__init__.py` (Step 1.4)
  - the new task is imported in `tasks/__init__.py` so `include=["app.tasks"]` finds it
    (Step 9.4)
  - a random 12-hex alembic revision id, never a hex-sequence id (Task 2)
  - durable state lives in Postgres only, no Redis (all of it)
  - no new container (all of it)
- **Placeholders:** the only deferred value is `down_revision`
  (`<HEAD_FROM_STEP_0_1>`). It can't be known until the dependency migrations merge. Step 0.1
  produces it, and Step 2.3 says to replace it with the literal. Step 2.1's chain test (parent
  exists, single head) fails if it is wrong, and it doesn't pin the global head, so later
  migrations won't break it.
