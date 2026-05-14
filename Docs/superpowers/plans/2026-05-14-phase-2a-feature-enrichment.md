# Phase 2a — Feature Enrichment at Signal Time

**Date**: 2026-05-14  
**Issue**: #21  
**Branch**: `refine/issue-21-feat-phase-2a---feature-enrichment-at-si`

## Goal

Enrich every `ScannerEvent.indicators` JSONB field with a 19-key feature vector captured at signal creation time. No model, no training — pure data collection for Phase 2b statistical discovery. Features span market context (ES/NQ futures), sector momentum (ETF pre-market change), timing, volatility regime (ATR percentile), catalyst enrichment, and TimesFM null placeholders.

## Architecture

Hybrid batch + inline computation following existing codebase patterns:

- **`CatalystParser.batch_analyze()`** gains `latest_article_utc` field (smallest change, done first so downstream tasks have it)
- **`_get_batch_enrichment_data()`** extended to fetch ES/NQ front-month daily bars and sector ETF pre-market bars once per scan run. Return type changes from `Dict[str, Dict]` to a 3-tuple `(ticker_data, market_context_dict, sector_etf_pct_dict)`. Both callers (`run_pre_market_scan` and `run_oversold_bounce_scan`) are updated to unpack the tuple.
- **`run_pre_market_scan()` per-ticker loop** gains timing, volatility regime, sector, catalyst, and TimesFM-placeholder feature computation using already-available `daily_bars`, the new batch dicts, and a single new DB query for the last pre-market bar timestamp.
- **Alembic data migration** seeds the "Sector ETFs" universe (11 SPDR ETFs).
- **`dark-factory/seed_preview.sql`** gains the same universe rows for CI/preview environments.

## Tech Stack

Backend only: Python / SQLAlchemy / Pandas / pytest (no frontend changes, no schema migrations).

## File Structure

| File | Change |
|------|--------|
| `backend/app/services/catalyst_parser.py` | Add `latest_article_utc` to `batch_analyze` result dict |
| `backend/app/services/scanner.py` | Add imports, `_SECTOR_ETF_MAP` constant, extend `_get_batch_enrichment_data`, update both callers, add per-ticker enrichment block |
| `backend/app/alembic/versions/f1a2b3c4d5e6_seed_sector_etfs_universe.py` | New data migration (down_revision: `b5e6f7a8b9c0`) |
| `dark-factory/seed_preview.sql` | Add Sector ETFs universe + 11 ticker rows |
| `backend/tests/services/test_catalyst_parser_enrichment.py` | New — 2 tests for `latest_article_utc` |
| `backend/tests/services/test_feature_enrichment.py` | New — batch query shape tests + full 19-key integration test |
| `backend/tests/services/test_scanner_refactor.py` | Update 7 mock `return_value`s from `{ticker: {}}` to `({ticker: {}}, {}, {})` |

---

## Task 1 — Extend `CatalystParser.batch_analyze()` to return `latest_article_utc`

**Files**: `backend/app/services/catalyst_parser.py`, `backend/tests/services/test_catalyst_parser_enrichment.py`

### Step 1.1 — Write failing test

Create `backend/tests/services/test_catalyst_parser_enrichment.py`:

```python
from datetime import date, datetime
from unittest.mock import MagicMock

from app.services.catalyst_parser import CatalystParser
from app.models.news_article import NewsArticle


def _make_article(ticker, title, published_utc):
    a = NewsArticle()
    a.tickers = [ticker]
    a.title = title
    a.description = ""
    a.published_utc = published_utc
    return a


def test_batch_analyze_returns_latest_article_utc():
    pub_utc = datetime(2025, 3, 10, 8, 0, 0)
    article = _make_article("AAPL", "Apple acquires company", pub_utc)

    db = MagicMock()
    mq = MagicMock()
    mq.filter.return_value = mq
    mq.all.return_value = [article]
    db.query.return_value = mq

    result = CatalystParser.batch_analyze(["AAPL"], date(2025, 3, 10), db)
    assert "latest_article_utc" in result["AAPL"]
    assert result["AAPL"]["latest_article_utc"] == pub_utc


def test_batch_analyze_latest_article_utc_null_when_no_news():
    db = MagicMock()
    mq = MagicMock()
    mq.filter.return_value = mq
    mq.all.return_value = []
    db.query.return_value = mq

    result = CatalystParser.batch_analyze(["AAPL"], date(2025, 3, 10), db)
    assert result["AAPL"]["latest_article_utc"] is None
```

### Step 1.2 — Verify test fails

```bash
docker compose exec -T backend python -m pytest tests/services/test_catalyst_parser_enrichment.py -v 2>&1 | tail -10
```

Expected: `FAILED` — `latest_article_utc` key missing from result dict.

### Step 1.3 — Implement

In `backend/app/services/catalyst_parser.py`:

**Line 53** — change the default empty result:
```python
# Old:
results = {t.upper(): {"tags": [], "summary": None} for t in tickers}
# New:
results = {t.upper(): {"tags": [], "summary": None, "latest_article_utc": None} for t in tickers}
```

**Lines 92–95** — change the per-ticker result assignment:
```python
# Old:
results[ticker] = {
    "tags": list(tags),
    "summary": summary
}
# New:
results[ticker] = {
    "tags": list(tags),
    "summary": summary,
    "latest_article_utc": recent_news[0].published_utc,
}
```

### Step 1.4 — Verify tests pass

```bash
docker compose exec -T backend python -m pytest tests/services/test_catalyst_parser_enrichment.py -v 2>&1 | tail -5
```

Expected: `2 passed`

### Step 1.5 — Commit

```bash
git add backend/app/services/catalyst_parser.py backend/tests/services/test_catalyst_parser_enrichment.py
git commit -m "feat(scanner): extend CatalystParser.batch_analyze to return latest_article_utc"
```

---

## Task 2 — Alembic data migration: seed "Sector ETFs" universe

**Files**: `backend/app/alembic/versions/f1a2b3c4d5e6_seed_sector_etfs_universe.py`

### Step 2.1 — Create migration file

Create `backend/app/alembic/versions/f1a2b3c4d5e6_seed_sector_etfs_universe.py`:

```python
"""seed_sector_etfs_universe

Revision ID: f1a2b3c4d5e6
Revises: b5e6f7a8b9c0
Create Date: 2026-05-14 12:00:00.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'f1a2b3c4d5e6'
down_revision: Union[str, None] = 'b5e6f7a8b9c0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    # Use id=2 + ON CONFLICT (id) DO NOTHING — matches existing seed_preview.sql convention
    # and avoids the lack of a unique constraint on stock_universes.name
    conn.execute(sa.text("""
        INSERT INTO stock_universes (id, name, description, criteria, is_active)
        VALUES (2, :name, :desc, CAST(:criteria AS json), true)
        ON CONFLICT (id) DO NOTHING
    """), {
        "name": "Sector ETFs",
        "desc": "11 SPDR sector ETFs for pre-market momentum context",
        "criteria": '{"type": "sector_etfs"}',
    })

    conn.execute(sa.text("""
        INSERT INTO stock_universe_tickers (universe_id, ticker, asset_class, data_source)
        SELECT 2, v.ticker, 'stocks', 'massive'
        FROM (VALUES
            ('XLK'), ('XLF'), ('XLV'), ('XLY'), ('XLP'),
            ('XLE'), ('XLI'), ('XLB'), ('XLRE'), ('XLU'), ('XLC')
        ) AS v(ticker)
        WHERE NOT EXISTS (
            SELECT 1 FROM stock_universe_tickers sut
            WHERE sut.universe_id = 2 AND sut.ticker = v.ticker
        )
    """))


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(sa.text("DELETE FROM stock_universe_tickers WHERE universe_id = 2"))
    conn.execute(sa.text("DELETE FROM stock_universes WHERE id = 2"))
```

### Step 2.2 — Apply and verify

```bash
docker compose exec -T backend python -m alembic upgrade head 2>&1 | tail -5
```

Expected output:
```
Running upgrade b5e6f7a8b9c0 -> f1a2b3c4d5e6, seed_sector_etfs_universe
```

Verify rows:
```bash
docker compose exec -T backend python -c "
from app.core.database import SessionLocal
from app.models.stock_universe import StockUniverse
from app.models.stock_universe_ticker import StockUniverseTicker
db = SessionLocal()
u = db.query(StockUniverse).filter(StockUniverse.name == 'Sector ETFs').first()
print('universe:', u.id, u.name)
tickers = db.query(StockUniverseTicker).filter(StockUniverseTicker.universe_id == u.id).all()
print('ticker count:', len(tickers), [t.ticker for t in tickers])
"
```

Expected: `universe: <id> Sector ETFs`, `ticker count: 11 ['XLK', 'XLF', ...]`

### Step 2.3 — Verify idempotency

```bash
docker compose exec -T backend python -m alembic downgrade -1 && \
docker compose exec -T backend python -m alembic upgrade head
```

Expected: no errors on second apply; same 11 tickers present.

### Step 2.4 — Commit

```bash
git add backend/app/alembic/versions/f1a2b3c4d5e6_seed_sector_etfs_universe.py
git commit -m "feat(scanner): seed Sector ETFs universe via Alembic data migration"
```

---

## Task 3 — Update `dark-factory/seed_preview.sql`

**Files**: `dark-factory/seed_preview.sql`

### Step 3.1 — Implement

In `dark-factory/seed_preview.sql`, add after the existing "Universe tickers" block (after line 38, before the scanner config block):

```sql
-- Universe: Sector ETFs
INSERT INTO stock_universes (id, name, description, criteria, is_active)
VALUES (
  2,
  'Sector ETFs',
  '11 SPDR sector ETFs for pre-market momentum context',
  '{"type": "sector_etfs"}',
  true
)
ON CONFLICT (id) DO NOTHING;

-- Sector ETF universe tickers
INSERT INTO stock_universe_tickers (universe_id, ticker, asset_class, data_source)
VALUES
  (2, 'XLK', 'stocks', 'massive'),
  (2, 'XLF', 'stocks', 'massive'),
  (2, 'XLV', 'stocks', 'massive'),
  (2, 'XLY', 'stocks', 'massive'),
  (2, 'XLP', 'stocks', 'massive'),
  (2, 'XLE', 'stocks', 'massive'),
  (2, 'XLI', 'stocks', 'massive'),
  (2, 'XLB', 'stocks', 'massive'),
  (2, 'XLRE', 'stocks', 'massive'),
  (2, 'XLU', 'stocks', 'massive'),
  (2, 'XLC', 'stocks', 'massive')
ON CONFLICT DO NOTHING;
```

### Step 3.2 — Verify ETF rows present

```bash
grep -c "XLK\|XLF\|XLV\|XLY\|XLP\|XLE\|XLI\|XLB\|XLRE\|XLU\|XLC" dark-factory/seed_preview.sql
```

Expected: `11` (one match per ETF)

### Step 3.3 — Commit

```bash
git add dark-factory/seed_preview.sql
git commit -m "feat(scanner): add Sector ETFs universe to dark-factory seed_preview.sql"
```

---

## Task 4 — Extend `_get_batch_enrichment_data()` with ES/NQ + sector ETF queries

**Files**: `backend/app/services/scanner.py`, `backend/tests/services/test_scanner_refactor.py`, `backend/tests/services/test_feature_enrichment.py`

### Step 4.1 — Write failing test (3-tuple return shape)

Create `backend/tests/services/test_feature_enrichment.py`:

```python
"""Tests for Phase 2a batch enrichment data."""
import pytest
from datetime import date, datetime, timezone, timedelta
from unittest.mock import MagicMock, patch

from app.services.scanner import ScannerService
from app.models.futures_aggregate import FuturesAggregate
from app.models.futures_rollover import FuturesRollover
from app.models.stock_aggregate import StockAggregate


def _make_futures_bar(symbol, contract_month, timestamp_utc, close):
    b = FuturesAggregate()
    b.symbol = symbol
    b.contract_month = contract_month
    b.exchange = "CME"
    b.timestamp = timestamp_utc
    b.timespan = "day"
    b.multiplier = 1
    b.open = close
    b.high = close
    b.low = close
    b.close = close
    b.volume = 1000
    return b


def _make_rollover(symbol, to_contract, roll_date):
    r = FuturesRollover()
    r.symbol = symbol
    r.exchange = "CME"
    r.from_contract = "20260301"
    r.to_contract = to_contract
    r.roll_date = roll_date
    r.detection_method = "volume"
    return r


def _null_db():
    db = MagicMock()
    mq = MagicMock()
    mq.filter.return_value = mq
    mq.order_by.return_value = mq
    mq.limit.return_value = mq
    mq.first.return_value = None
    mq.all.return_value = []
    db.query.return_value = mq
    return db


def test_get_batch_enrichment_data_returns_3_tuple():
    """_get_batch_enrichment_data must return (batch_data, market_context_dict, sector_etf_pct_dict)."""
    event_date = date(2026, 5, 14)
    db = _null_db()

    with patch("app.services.scanner.CatalystParser.batch_analyze", return_value={}):
        result = ScannerService._get_batch_enrichment_data(["AAPL"], event_date, db)

    assert isinstance(result, tuple) and len(result) == 3
    batch_data, market_ctx, etf_pcts = result
    assert isinstance(batch_data, dict)
    assert "es_pct_from_prev_close" in market_ctx
    assert "nq_pct_from_prev_close" in market_ctx
    assert "market_context" in market_ctx
    assert "XLK" in etf_pcts
    assert len(etf_pcts) == 11


def test_market_context_risk_on():
    """When both ES and NQ are up >0.1%, market_context == 'risk_on'."""
    event_date = date(2026, 5, 14)
    contract = "20260620"
    roll_date = date(2026, 5, 1)
    t0 = datetime(2026, 5, 13, 20, 0, 0)
    t1 = datetime(2026, 5, 14, 20, 0, 0)

    es_bars = [_make_futures_bar("ES", contract, t1, 5300), _make_futures_bar("ES", contract, t0, 5000)]
    nq_bars = [_make_futures_bar("NQ", contract, t1, 18800), _make_futures_bar("NQ", contract, t0, 18000)]
    es_rollover = _make_rollover("ES", contract, roll_date)
    nq_rollover = _make_rollover("NQ", contract, roll_date)

    db = MagicMock()
    rollover_calls = [es_rollover, nq_rollover]
    futures_calls = [es_bars, nq_bars]

    def query_side(model):
        mq = MagicMock()
        mq.filter.return_value = mq
        mq.order_by.return_value = mq
        mq.limit.return_value = mq
        mq.all.return_value = []
        mq.first.return_value = None
        if model is FuturesRollover:
            mq.first.side_effect = rollover_calls
        elif model is FuturesAggregate:
            mq.all.side_effect = futures_calls
        return mq

    db.query.side_effect = query_side

    with patch("app.services.scanner.CatalystParser.batch_analyze", return_value={}):
        _, market_ctx, _ = ScannerService._get_batch_enrichment_data(["AAPL"], event_date, db)

    assert market_ctx["market_context"] == "risk_on"
    assert market_ctx["es_pct_from_prev_close"] == pytest.approx(6.0, rel=0.01)


def test_market_context_null_when_no_rollover_data():
    """When no rollover records exist, all market context features are None."""
    db = _null_db()
    with patch("app.services.scanner.CatalystParser.batch_analyze", return_value={}):
        _, market_ctx, _ = ScannerService._get_batch_enrichment_data(["AAPL"], date(2026, 5, 14), db)

    assert market_ctx["es_pct_from_prev_close"] is None
    assert market_ctx["nq_pct_from_prev_close"] is None
    assert market_ctx["market_context"] is None
```

### Step 4.2 — Verify test fails

```bash
docker compose exec -T backend python -m pytest tests/services/test_feature_enrichment.py::test_get_batch_enrichment_data_returns_3_tuple -v 2>&1 | tail -10
```

Expected: `FAILED` — result is a plain dict, not a 3-tuple.

### Step 4.3 — Add imports to `scanner.py`

In `backend/app/services/scanner.py`:

```python
# Old:
from typing import Dict, Any, List
# New:
from typing import Dict, Any, List, Optional, Tuple

# Add after the SystemConfig import line:
from app.models.futures_aggregate import FuturesAggregate
from app.models.futures_rollover import FuturesRollover
```

### Step 4.4 — Add `_SECTOR_ETF_MAP` constant

In `backend/app/services/scanner.py`, add after the imports block, before `class ScannerService`:

```python
_SECTOR_ETF_MAP: Dict[str, str] = {
    "Technology": "XLK",
    "Financials": "XLF",
    "Health Care": "XLV",
    "Consumer Discretionary": "XLY",
    "Consumer Staples": "XLP",
    "Energy": "XLE",
    "Industrials": "XLI",
    "Materials": "XLB",
    "Real Estate": "XLRE",
    "Utilities": "XLU",
    "Communication Services": "XLC",
}
_SECTOR_ETF_SYMBOLS = list(_SECTOR_ETF_MAP.values())
```

### Step 4.5 — Extend `_get_batch_enrichment_data()`

In `backend/app/services/scanner.py`:

**Update the method signature** (line 142):
```python
# Old:
def _get_batch_enrichment_data(tickers: List[str], event_date: date, db: Session) -> Dict[str, Dict[str, Any]]:
# New:
def _get_batch_enrichment_data(
    tickers: List[str], event_date: date, db: Session
) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, Any], Dict[str, Optional[float]]]:
```

**Update the default catalyst fallback** (line ~173):
```python
# Old:
cat = catalyst_batch.get(t_upper, {"tags": [], "summary": None})
# New:
cat = catalyst_batch.get(t_upper, {"tags": [], "summary": None, "latest_article_utc": None})
```

**Add `catalyst_latest_utc` to per-ticker batch_data** (inside the batch_data loop, after `"catalyst_summary"`):
```python
"catalyst_tags": cat.get("tags", []),
"catalyst_summary": cat.get("summary"),
"catalyst_latest_utc": cat.get("latest_article_utc"),  # NEW
```

**Also add `"sector"` to per-ticker batch_data** (after `"catalyst_latest_utc"`):
```python
"sector": ref.sector if ref else None,  # NEW — used by per-ticker sector enrichment
```

**Replace `return batch_data` with the extended block**:
```python
        # 5. ES/NQ market context — front-month contract via rollover table
        market_context_dict: Dict[str, Any] = {
            "es_pct_from_prev_close": None,
            "nq_pct_from_prev_close": None,
            "market_context": None,
        }
        _ET_batch = ZoneInfo("America/New_York")
        event_end_utc = (
            datetime.combine(event_date, datetime.max.time(), tzinfo=_ET_batch)
            .astimezone(timezone.utc).replace(tzinfo=None)
        )
        for symbol in ("ES", "NQ"):
            rollover = (
                db.query(FuturesRollover)
                .filter(
                    FuturesRollover.symbol == symbol,
                    FuturesRollover.roll_date <= event_date,
                )
                .order_by(desc(FuturesRollover.roll_date))
                .first()
            )
            if rollover is None:
                continue
            bars = (
                db.query(FuturesAggregate)
                .filter(
                    FuturesAggregate.symbol == symbol,
                    FuturesAggregate.contract_month == rollover.to_contract,
                    FuturesAggregate.timespan == "day",
                    FuturesAggregate.timestamp <= event_end_utc,
                )
                .order_by(desc(FuturesAggregate.timestamp))
                .limit(2)
                .all()
            )
            if len(bars) < 2:
                continue
            today_close = float(bars[0].close)
            prev_close = float(bars[1].close)
            if prev_close == 0:
                continue
            pct = round((today_close - prev_close) / prev_close * 100, 4)
            key = "es_pct_from_prev_close" if symbol == "ES" else "nq_pct_from_prev_close"
            market_context_dict[key] = pct

        es_pct = market_context_dict["es_pct_from_prev_close"]
        nq_pct = market_context_dict["nq_pct_from_prev_close"]
        if es_pct is not None and nq_pct is not None:
            if es_pct > 0.1 and nq_pct > 0.1:
                market_context_dict["market_context"] = "risk_on"
            elif es_pct < -0.1 and nq_pct < -0.1:
                market_context_dict["market_context"] = "risk_off"
            else:
                market_context_dict["market_context"] = "neutral"

        # 6. Sector ETF pre-market % changes vs prior daily close
        sector_etf_pct_dict: Dict[str, Optional[float]] = {s: None for s in _SECTOR_ETF_SYMBOLS}
        etf_day_start_et = datetime.combine(event_date, datetime.min.time(), tzinfo=_ET_batch)
        etf_day_start_utc = etf_day_start_et.astimezone(timezone.utc).replace(tzinfo=None)
        etf_day_end_utc = (etf_day_start_et + timedelta(days=1)).astimezone(timezone.utc).replace(tzinfo=None)
        etf_hist_start_utc = (etf_day_start_et - timedelta(days=5)).astimezone(timezone.utc).replace(tzinfo=None)

        etf_daily = (
            db.query(StockAggregate)
            .filter(
                StockAggregate.ticker.in_(_SECTOR_ETF_SYMBOLS),
                StockAggregate.timespan == "day",
                StockAggregate.timestamp >= etf_hist_start_utc,
                StockAggregate.timestamp < etf_day_start_utc,
            )
            .order_by(StockAggregate.ticker, desc(StockAggregate.timestamp))
            .all()
        )
        etf_prev_closes: Dict[str, float] = {}
        for bar in etf_daily:
            if bar.ticker not in etf_prev_closes:
                etf_prev_closes[bar.ticker] = float(bar.close)

        etf_pm = (
            db.query(StockAggregate)
            .filter(
                StockAggregate.ticker.in_(_SECTOR_ETF_SYMBOLS),
                StockAggregate.timespan == "minute",
                StockAggregate.is_pre_market == True,
                StockAggregate.timestamp >= etf_day_start_utc,
                StockAggregate.timestamp < etf_day_end_utc,
            )
            .order_by(StockAggregate.ticker, StockAggregate.timestamp.asc())
            .all()
        )
        etf_last_bar: Dict[str, StockAggregate] = {}
        for bar in etf_pm:
            etf_last_bar[bar.ticker] = bar  # ascending order → last bar wins

        for etf_sym in _SECTOR_ETF_SYMBOLS:
            if etf_sym in etf_last_bar and etf_sym in etf_prev_closes:
                current = float(etf_last_bar[etf_sym].close)
                prev = etf_prev_closes[etf_sym]
                if prev > 0:
                    sector_etf_pct_dict[etf_sym] = round((current - prev) / prev * 100, 4)

        return batch_data, market_context_dict, sector_etf_pct_dict
```

### Step 4.6 — Update `run_pre_market_scan` caller (line ~276)

```python
# Old:
enrichment_batch = await asyncio.to_thread(
    ScannerService._get_batch_enrichment_data, tickers, event_date, db
)
# New:
enrichment_batch, market_context_dict, sector_etf_pct_dict = await asyncio.to_thread(
    ScannerService._get_batch_enrichment_data, tickers, event_date, db
)
```

### Step 4.7 — Update `run_oversold_bounce_scan` caller (line ~401)

```python
# Old:
enrichment_batch = await asyncio.to_thread(
    ScannerService._get_batch_enrichment_data, tickers, event_date, db
)
# New:
enrichment_batch, _, _ = await asyncio.to_thread(
    ScannerService._get_batch_enrichment_data, tickers, event_date, db
)
```

### Step 4.8 — Fix existing mocks in `test_scanner_refactor.py`

First, confirm the exact count of mocks to update:

```bash
grep -n "_get_batch_enrichment_data" backend/tests/services/test_scanner_refactor.py
```

Then replace **every** occurrence of:
```python
patch.object(ScannerService, '_get_batch_enrichment_data', return_value={ticker: {}})
```
with:
```python
patch.object(ScannerService, '_get_batch_enrichment_data', return_value=({ticker: {}}, {}, {}))
```

Use the grep output to find all occurrences; do not rely on hardcoded line numbers.

### Step 4.9 — Verify all tests pass

```bash
docker compose exec -T backend python -m pytest tests/services/test_scanner_refactor.py tests/services/test_feature_enrichment.py -v 2>&1 | tail -20
```

Expected: all tests pass.

### Step 4.10 — Commit

```bash
git add backend/app/services/scanner.py \
        backend/tests/services/test_scanner_refactor.py \
        backend/tests/services/test_feature_enrichment.py
git commit -m "feat(scanner): extend _get_batch_enrichment_data with ES/NQ market context and sector ETF batch queries"
```

---

## Task 5 — Add per-ticker feature enrichment in `run_pre_market_scan()`

**Files**: `backend/app/services/scanner.py`, `backend/tests/services/test_feature_enrichment.py`

### Step 5.1 — Write failing test (19-key integration test)

Add to `backend/tests/services/test_feature_enrichment.py`:

```python
import asyncio
from app.models.system_config import SystemConfig


def _make_daily_bar_full(ticker, timestamp_utc, close, volume=1_000_000):
    b = StockAggregate()
    b.ticker = ticker
    b.timestamp = timestamp_utc
    b.timespan = "day"
    b.multiplier = 1
    b.open = close
    b.high = close * 1.02
    b.low = close * 0.98
    b.close = close
    b.volume = volume
    b.is_pre_market = False
    b.is_after_market = False
    return b


def _make_pm_bar(ticker, timestamp_utc, close=100.0):
    b = StockAggregate()
    b.ticker = ticker
    b.timestamp = timestamp_utc
    b.timespan = "minute"
    b.multiplier = 1
    b.open = close
    b.high = close * 1.01
    b.low = close * 0.99
    b.close = close
    b.volume = 50_000
    b.is_pre_market = True
    b.is_after_market = False
    return b


PHASE_2A_FEATURE_KEYS = [
    "es_pct_from_prev_close", "nq_pct_from_prev_close", "market_context",
    "sector", "sector_etf", "sector_etf_pct_change",
    "minutes_since_premarket_open", "day_of_week", "is_monday", "is_friday",
    "atr_percentile_rank", "volatility_regime",
    "has_news_catalyst", "catalyst_tag_count", "catalyst_recency_hours",
    "price_direction", "price_confidence", "price_forecast_4h", "price_forecast_1d",
]


def test_run_pre_market_scan_indicators_contain_all_feature_keys():
    """All 19 Phase 2a feature keys must appear in indicators after a detected signal."""
    ticker = "NVDA"
    event_date = date(2026, 5, 14)  # Wednesday

    base_utc = datetime(2026, 4, 15, 20, 0, 0)
    daily_bars = [
        _make_daily_bar_full(ticker, base_utc + timedelta(days=i), 100.0 + i * 0.1)
        for i in range(25)
    ]
    # 8:30 AM UTC = 4:30 AM ET on 2026-05-14
    pm_bar = _make_pm_bar(ticker, datetime(2026, 5, 14, 8, 30, 0), close=105.0)

    db = MagicMock()

    def query_side(model):
        mq = MagicMock()
        mq.filter.return_value = mq
        mq.order_by.return_value = mq
        mq.limit.return_value = mq
        mq.first.return_value = pm_bar
        if model is SystemConfig:
            mq.all.return_value = []
        elif model is StockAggregate:
            mq.all.return_value = daily_bars
            mq.scalar.return_value = 5_000_000  # 5x avg volume → triggers spike criterion
        else:
            mq.all.return_value = []
            mq.scalar.return_value = 5_000_000
        return mq

    db.query.side_effect = query_side

    batch_enrichment = {
        "NVDA": {
            "market_cap": 2_000_000_000_000,
            "outstanding_shares": 24_000_000_000,
            "recent_split_date": None,
            "catalyst_tags": ["earnings_beat"],
            "catalyst_summary": "NVDA beats estimates",
            "catalyst_latest_utc": datetime(2026, 5, 14, 3, 0, 0),
            "sector": "Technology",
        }
    }
    market_ctx = {
        "es_pct_from_prev_close": 0.3,
        "nq_pct_from_prev_close": 0.2,
        "market_context": "risk_on",
    }
    etf_pcts = {s: None for s in ["XLK", "XLF", "XLV", "XLY", "XLP", "XLE", "XLI", "XLB", "XLRE", "XLU", "XLC"]}
    etf_pcts["XLK"] = 0.4

    saved = {}

    def capture_save(**kwargs):
        saved.update(kwargs.get("indicators", {}))
        return {"id": 1}

    with patch.object(ScannerService, '_get_batch_enrichment_data',
                      return_value=(batch_enrichment, market_ctx, etf_pcts)), \
         patch.object(ScannerService, 'calculate_day_metrics', return_value={
             "closing_price": 106.0, "pre_market_close": 105.0,
             "opening_price": 101.0, "regular_high": 107.0, "regular_low": 99.0,
         }), \
         patch.object(ScannerService, '_save_event', side_effect=capture_save):
        asyncio.run(ScannerService.run_pre_market_scan([ticker], db, event_date=event_date))

    assert saved, "_save_event was never called — signal not detected"
    for key in PHASE_2A_FEATURE_KEYS:
        assert key in saved, f"missing feature key: {key}"

    assert saved["es_pct_from_prev_close"] == 0.3
    assert saved["market_context"] == "risk_on"
    assert saved["sector"] == "Technology"
    assert saved["sector_etf"] == "XLK"
    assert saved["sector_etf_pct_change"] == 0.4
    assert saved["day_of_week"] == 2        # Wednesday
    assert saved["is_monday"] is False
    assert saved["is_friday"] is False
    assert saved["minutes_since_premarket_open"] == pytest.approx(30.0, abs=1.0)  # 4:30 AM ET
    assert saved["has_news_catalyst"] is True
    assert saved["catalyst_tag_count"] == 1
    assert saved["price_direction"] is None   # TimesFM deferred
    assert saved["price_confidence"] is None
    assert saved["price_forecast_4h"] is None
    assert saved["price_forecast_1d"] is None
```

### Step 5.2 — Verify test fails

```bash
docker compose exec -T backend python -m pytest tests/services/test_feature_enrichment.py::test_run_pre_market_scan_indicators_contain_all_feature_keys -v 2>&1 | tail -15
```

Expected: `FAILED` — `AssertionError: missing feature key: es_pct_from_prev_close` (or similar).

### Step 5.3 — Add `time` to datetime import

In `backend/app/services/scanner.py`, line 7:
```python
# Old:
from datetime import datetime, date, timedelta, timezone
# New:
from datetime import datetime, date, time, timedelta, timezone
```

### Step 5.4 — Insert feature enrichment block into `run_pre_market_scan()`

In `backend/app/services/scanner.py`, locate the block that sets `indicators["float_rotation_pct"]` (around line 364). Insert the following block **immediately after** the `float_rotation_pct` block and **before** the `event_dict = ScannerService._save_event(...)` call:

```python
                    # --- Phase 2a feature enrichment ---

                    # Market context (pre-computed batch-level, zero cost here)
                    indicators["es_pct_from_prev_close"] = market_context_dict.get("es_pct_from_prev_close")
                    indicators["nq_pct_from_prev_close"] = market_context_dict.get("nq_pct_from_prev_close")
                    indicators["market_context"] = market_context_dict.get("market_context")

                    # Sector features
                    _sector = enrichment.get("sector")
                    _sector_etf = _SECTOR_ETF_MAP.get(_sector) if _sector else None
                    indicators["sector"] = _sector
                    indicators["sector_etf"] = _sector_etf
                    indicators["sector_etf_pct_change"] = (
                        sector_etf_pct_dict.get(_sector_etf) if _sector_etf else None
                    )

                    # Timing features — derived from last pre-market bar, never datetime.now()
                    _last_pre = (
                        db.query(StockAggregate)
                        .filter(
                            StockAggregate.ticker == ticker,
                            StockAggregate.timespan == "minute",
                            StockAggregate.is_pre_market == True,
                            StockAggregate.timestamp >= day_start_utc,
                            StockAggregate.timestamp < day_end_utc,
                        )
                        .order_by(desc(StockAggregate.timestamp))
                        .first()
                    )
                    if _last_pre:
                        _bar_ts = _last_pre.timestamp
                        if _bar_ts.tzinfo is None:
                            _bar_ts = _bar_ts.replace(tzinfo=timezone.utc)
                        _bar_ts_et = _bar_ts.astimezone(_ET)
                        _pm_open_et = datetime.combine(event_date, time(4, 0), tzinfo=_ET)
                        indicators["minutes_since_premarket_open"] = round(
                            (_bar_ts_et - _pm_open_et).total_seconds() / 60, 2
                        )
                        indicators["day_of_week"] = _bar_ts_et.weekday()
                        indicators["is_monday"] = _bar_ts_et.weekday() == 0
                        indicators["is_friday"] = _bar_ts_et.weekday() == 4
                    else:
                        indicators["minutes_since_premarket_open"] = None
                        indicators["day_of_week"] = None
                        indicators["is_monday"] = False
                        indicators["is_friday"] = False

                    # Volatility regime — ATR_10 percentile rank within 60-day window
                    _atr_rank: Optional[float] = None
                    _vol_regime: Optional[str] = None
                    if len(daily_bars) >= 11:
                        _df = pd.DataFrame([{
                            "H": float(b.high), "L": float(b.low), "C": float(b.close)
                        } for b in daily_bars])
                        _df["tr"] = pd.DataFrame({
                            "a": _df["H"] - _df["L"],
                            "b": (_df["H"] - _df["C"].shift(1)).abs(),
                            "c": (_df["L"] - _df["C"].shift(1)).abs(),
                        }).max(axis=1)
                        _df["atr10"] = _df["tr"].rolling(window=10).mean()
                        _window = _df["atr10"].dropna().tail(60)
                        if len(_window) >= 10:
                            _rank_pct = _window.rank(pct=True).iloc[-1]
                            _atr_rank = round(_rank_pct * 100, 2)
                            if _rank_pct < 0.25:
                                _vol_regime = "compressed"
                            elif _rank_pct > 0.75:
                                _vol_regime = "expanded"
                            else:
                                _vol_regime = "normal"
                    indicators["atr_percentile_rank"] = _atr_rank
                    indicators["volatility_regime"] = _vol_regime

                    # Catalyst enrichment features
                    _cat_tags = enrichment.get("catalyst_tags", [])
                    _cat_latest = enrichment.get("catalyst_latest_utc")
                    indicators["has_news_catalyst"] = bool(_cat_tags)
                    indicators["catalyst_tag_count"] = len(_cat_tags)
                    if _cat_latest is not None and _last_pre is not None:
                        _ref_ts = _last_pre.timestamp
                        if _ref_ts.tzinfo is None:
                            _ref_ts = _ref_ts.replace(tzinfo=timezone.utc)
                        if _cat_latest.tzinfo is None:
                            _cat_latest = _cat_latest.replace(tzinfo=timezone.utc)
                        indicators["catalyst_recency_hours"] = round(
                            (_ref_ts - _cat_latest).total_seconds() / 3600, 2
                        )
                    else:
                        indicators["catalyst_recency_hours"] = None

                    # TimesFM price forecast keys (deferred — Phase 1 dependency #20)
                    indicators["price_direction"] = None
                    indicators["price_confidence"] = None
                    indicators["price_forecast_4h"] = None
                    indicators["price_forecast_1d"] = None
```

### Step 5.5 — Verify new tests pass

```bash
docker compose exec -T backend python -m pytest tests/services/test_feature_enrichment.py -v 2>&1 | tail -15
```

Expected: all tests pass.

### Step 5.6 — Run full test suite for regressions

```bash
docker compose exec -T backend python -m pytest tests/ -v 2>&1 | tail -30
```

Expected: all tests pass (no new failures).

### Step 5.7 — Confirm backend reloaded and logs clean

```bash
docker compose logs backend --tail=20
```

Expected: no import errors or tracebacks.

### Step 5.8 — Commit

```bash
git add backend/app/services/scanner.py backend/tests/services/test_feature_enrichment.py
git commit -m "feat(scanner): add Phase 2a feature enrichment to run_pre_market_scan indicators"
```

---

## Summary

| Task | Files changed | Steps |
|------|--------------|-------|
| 1 — CatalystParser `latest_article_utc` | 2 | 5 |
| 2 — Alembic seed migration | 1 | 4 |
| 3 — seed_preview.sql update | 1 | 3 |
| 4 — Batch query extension + tuple refactor | 3 | 10 |
| 5 — Per-ticker enrichment loop | 2 | 8 |
| **Total** | **7** | **30** |

All features degrade to `null` when their data source is unavailable. Existing scanner pass/fail criteria are unchanged. `run_oversold_bounce_scan` is unmodified beyond unpacking the new 3-tuple return.
