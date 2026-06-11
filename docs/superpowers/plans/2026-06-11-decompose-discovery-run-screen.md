# Decompose DiscoveryService.run_screen into Asset-Class Screeners

**Goal:** Extract the stocks and futures screening paths from `DiscoveryService.run_screen` (CC~43, 217 lines) into dedicated `StockScreener` and `FuturesScreener` adapters that self-register at import time, reducing `run_screen()` to a ≤40-line dispatcher. No change to output semantics; adding a new asset class requires only a new adapter file — no branches added to `run_screen()`.

**Issue:** [#287](https://github.com/omniscient/markethawk/issues/287)
**Spec:** `docs/superpowers/specs/2026-06-11-decompose-discovery-run-screen-design.md`
**Date:** 2026-06-11

## Architecture

Self-registration pattern already in production: `pre_market_scan.py` and `oversold_bounce_scan.py` both call `register(ScannerDescriptor(...))` at module level in `scan_orchestrator.py`. The screener adapters mirror this idiom with a simpler function registry (2 entries today, no need for a separate `screener_registry.py` module per architecture memory decision).

The `_SCREENER_REGISTRY` lives at module level in `discovery_service.py` — the dispatch entry point and registry are co-located; a separate file would add indirection for 3 lines of boilerplate.

## Tech Stack

Python 3.11 · SQLAlchemy 2.0 (sync `Session`) · pytest + testcontainers SAVEPOINT `db` fixture

## File Structure

| File | Change |
|---|---|
| `backend/app/services/discovery_service.py` | Add `ScreenerFn`, `_SCREENER_REGISTRY`, `register_screener()`, `_apply_shared_filters()` — keep `run_screen()` body for now |
| `backend/app/services/stock_screener.py` | **New** — `StockScreener` class + `register_screener("stocks", ...)` at module level |
| `backend/app/services/futures_screener.py` | **New** — `FuturesScreener` class + `register_screener("futures", ...)` at module level |
| `backend/tests/services/test_discovery_service.py` | Add `StockScreener` unit tests (6), `FuturesScreener` unit tests (4), integration smoke test (1) |

---

## Task 1 — Registry infrastructure in `discovery_service.py`

Add `_SCREENER_REGISTRY`, `register_screener()`, and `_apply_shared_filters()` to `discovery_service.py`. The `run_screen()` body is **not changed** in this task.

### Files
- `backend/app/services/discovery_service.py`
- `backend/tests/services/test_discovery_service.py`

### Steps

**Step 1.1 — Write the failing import-smoke test**

Append to `backend/tests/services/test_discovery_service.py`:

```python
# ── registry infrastructure ─────────────────────────────────────────────────


def test_register_screener_symbol_importable():
    from app.services.discovery_service import _SCREENER_REGISTRY, register_screener

    assert callable(register_screener)
    assert isinstance(_SCREENER_REGISTRY, dict)
```

**Step 1.2 — Verify test fails**

```bash
pytest backend/tests/services/test_discovery_service.py::test_register_screener_symbol_importable -x
```

Expected: `ImportError: cannot import name '_SCREENER_REGISTRY' from 'app.services.discovery_service'`

**Step 1.3 — Add `Callable` to imports in `discovery_service.py`**

Change the existing typing import line:

```python
# Before
from typing import Any, Dict, List

# After
from typing import Any, Callable, Dict, List
```

**Step 1.4 — Add registry at module level after `logger = logging.getLogger(__name__)`**

```python
ScreenerFn = Callable[[Dict[str, Any], Session], List[Dict[str, Any]]]
_SCREENER_REGISTRY: dict[str, ScreenerFn] = {}


def register_screener(asset_class: str, fn: ScreenerFn) -> None:
    _SCREENER_REGISTRY[asset_class] = fn


def _apply_shared_filters(
    output: List[Dict[str, Any]], criteria: Dict[str, Any]
) -> List[Dict[str, Any]]:
    # No cross-asset filters today; seam for future cross-asset criteria.
    return output
```

**Step 1.5 — Verify import-smoke test passes**

```bash
pytest backend/tests/services/test_discovery_service.py::test_register_screener_symbol_importable -x
```

Expected: `PASSED`

**Step 1.6 — Verify no regressions**

```bash
pytest backend/tests/services/test_discovery_service.py -x
```

Expected: all 3 existing tests pass.

**Step 1.7 — Commit**

```bash
git add backend/app/services/discovery_service.py \
        backend/tests/services/test_discovery_service.py
git commit -m "feat(#287): add screener registry infrastructure to discovery_service"
```

---

## Task 2 — StockScreener adapter (TDD)

Write tests first, then implement `backend/app/services/stock_screener.py`.

### Files
- `backend/tests/services/test_discovery_service.py` (write tests first)
- `backend/app/services/stock_screener.py` (new)

### Steps

**Step 2.1 — Write failing StockScreener tests**

Append to `backend/tests/services/test_discovery_service.py`:

```python
# ── StockScreener unit tests ─────────────────────────────────────────────────
import datetime


def _seed_ticker(db, ticker, **kwargs):
    from app.models.ticker_reference import TickerReference

    row = TickerReference(
        ticker=ticker,
        name=kwargs.get("name", f"{ticker} Inc"),
        market_cap=kwargs.get("market_cap", 1_000_000),
        outstanding_shares=kwargs.get("outstanding_shares", 100_000),
        sector=kwargs.get("sector", "Technology"),
        primary_exchange=kwargs.get("primary_exchange", "XNAS"),
        total_employees=kwargs.get("total_employees", 500),
        sic_code=kwargs.get("sic_code", "7372"),
        description=kwargs.get("description", "A technology company"),
    )
    db.add(row)
    db.flush()
    return row


def _seed_metric(db, ticker, volume=500_000, close_price=150.0):
    from app.models.stock_metric import StockMetric

    row = StockMetric(
        ticker=ticker,
        date=datetime.date(2026, 6, 1),
        close_price=close_price,
        volume=volume,
    )
    db.add(row)
    db.flush()
    return row


def test_stock_screener_no_metric_filters_returns_ticker(db):
    """No metric filters → reference-only query, correct output shape."""
    from app.services.stock_screener import StockScreener

    _seed_ticker(db, "SCRN1", sector="Technology")
    screener = StockScreener()
    results = screener.screen({"asset_classes": ["stocks"]}, db)
    tickers = [r["ticker"] for r in results]
    assert "SCRN1" in tickers
    row = next(r for r in results if r["ticker"] == "SCRN1")
    assert row["asset_class"] == "stocks"
    assert row["volume"] is None  # no metric join → volume is None


def test_stock_screener_min_volume_inner_join(db):
    """min_volume > 0 → inner join; only rows meeting threshold returned."""
    from app.services.stock_screener import StockScreener

    _seed_ticker(db, "VOLHI", market_cap=2_000_000)
    _seed_ticker(db, "VOLLO", market_cap=2_000_000)
    _seed_metric(db, "VOLHI", volume=1_000_000)
    _seed_metric(db, "VOLLO", volume=100)
    screener = StockScreener()
    results = screener.screen({"asset_classes": ["stocks"], "min_volume": 500_000}, db)
    tickers = [r["ticker"] for r in results]
    assert "VOLHI" in tickers
    assert "VOLLO" not in tickers
    hi = next(r for r in results if r["ticker"] == "VOLHI")
    assert hi["volume"] == 1_000_000


def test_stock_screener_market_cap_range(db):
    """min_market_cap / max_market_cap range filters applied correctly."""
    from app.services.stock_screener import StockScreener

    _seed_ticker(db, "CAPBG", market_cap=10_000_000)
    _seed_ticker(db, "CAPSM", market_cap=500)
    screener = StockScreener()
    results = screener.screen(
        {"asset_classes": ["stocks"], "min_market_cap": 1_000_000, "max_market_cap": 50_000_000},
        db,
    )
    tickers = [r["ticker"] for r in results]
    assert "CAPBG" in tickers
    assert "CAPSM" not in tickers


def test_stock_screener_sector_list_filter(db):
    """sector as list filters to matching sectors only."""
    from app.services.stock_screener import StockScreener

    _seed_ticker(db, "SCTK1", sector="Technology")
    _seed_ticker(db, "SCHY1", sector="Healthcare")
    _seed_ticker(db, "SCER1", sector="Energy")
    screener = StockScreener()
    results = screener.screen(
        {"asset_classes": ["stocks"], "sector": ["Technology", "Healthcare"]},
        db,
    )
    tickers = [r["ticker"] for r in results]
    assert "SCTK1" in tickers
    assert "SCHY1" in tickers
    assert "SCER1" not in tickers


def test_stock_screener_primary_exchange_string_filter(db):
    """primary_exchange as string filters correctly."""
    from app.services.stock_screener import StockScreener

    _seed_ticker(db, "EXNY1", primary_exchange="XNYS")
    _seed_ticker(db, "EXNA1", primary_exchange="XNAS")
    screener = StockScreener()
    results = screener.screen(
        {"asset_classes": ["stocks"], "primary_exchange": "XNYS"},
        db,
    )
    tickers = [r["ticker"] for r in results]
    assert "EXNY1" in tickers
    assert "EXNA1" not in tickers


def test_stock_screener_output_field_names(db):
    """Output dict contains all required field names with correct asset_class."""
    from app.services.stock_screener import StockScreener

    _seed_ticker(db, "FLDN1")
    screener = StockScreener()
    results = screener.screen({"asset_classes": ["stocks"]}, db)
    row = next(r for r in results if r["ticker"] == "FLDN1")
    for field in (
        "ticker", "name", "market_cap", "close_price", "volume",
        "sector", "primary_exchange", "employees", "sic_code",
        "description", "asset_class", "data_source",
    ):
        assert field in row, f"Missing output field: {field}"
    assert row["asset_class"] == "stocks"
```

**Step 2.2 — Verify tests fail**

```bash
pytest backend/tests/services/test_discovery_service.py -k "stock_screener" -x
```

Expected: `ModuleNotFoundError: No module named 'app.services.stock_screener'`

**Step 2.3 — Create `backend/app/services/stock_screener.py`**

```python
import logging
from typing import Any, Dict, List

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.stock_metric import StockMetric
from app.models.ticker_reference import TickerReference
from app.services.discovery_service import register_screener

logger = logging.getLogger(__name__)


class StockScreener:
    def screen(self, criteria: Dict[str, Any], db: Session) -> List[Dict[str, Any]]:
        data_source = criteria.get("data_source_stocks", "massive")
        has_metric_filters = "min_volume" in criteria and criteria["min_volume"] > 0

        if has_metric_filters:
            query = db.query(TickerReference, StockMetric).join(
                StockMetric, TickerReference.ticker == StockMetric.ticker
            )
        else:
            query = db.query(TickerReference)

        if "min_market_cap" in criteria and criteria["min_market_cap"] > 0:
            query = query.filter(TickerReference.market_cap >= criteria["min_market_cap"])

        if "max_market_cap" in criteria and criteria["max_market_cap"] > 0:
            query = query.filter(TickerReference.market_cap <= criteria["max_market_cap"])

        if "min_outstanding_shares" in criteria and criteria["min_outstanding_shares"] > 0:
            query = query.filter(
                TickerReference.outstanding_shares >= criteria["min_outstanding_shares"]
            )

        if "sector" in criteria and criteria["sector"]:
            if isinstance(criteria["sector"], list):
                if len(criteria["sector"]) > 0:
                    query = query.filter(TickerReference.sector.in_(criteria["sector"]))
            elif criteria["sector"]:
                query = query.filter(TickerReference.sector == criteria["sector"])

        if "primary_exchange" in criteria and criteria["primary_exchange"]:
            if isinstance(criteria["primary_exchange"], list):
                if len(criteria["primary_exchange"]) > 0:
                    query = query.filter(
                        TickerReference.primary_exchange.in_(criteria["primary_exchange"])
                    )
            elif criteria["primary_exchange"]:
                query = query.filter(
                    TickerReference.primary_exchange == criteria["primary_exchange"]
                )

        if "sic_code" in criteria and criteria["sic_code"]:
            query = query.filter(TickerReference.sic_code == criteria["sic_code"])

        if "description_contains" in criteria and criteria["description_contains"]:
            query = query.filter(
                TickerReference.description.ilike(f"%{criteria['description_contains']}%")
            )

        if "min_employees" in criteria and criteria["min_employees"] > 0:
            query = query.filter(TickerReference.total_employees >= criteria["min_employees"])

        if "max_employees" in criteria and criteria["max_employees"] > 0:
            query = query.filter(TickerReference.total_employees <= criteria["max_employees"])

        if "min_share_class_shares" in criteria and criteria["min_share_class_shares"] > 0:
            query = query.filter(
                TickerReference.share_class_shares_outstanding
                >= criteria["min_share_class_shares"]
            )

        if "max_share_class_shares" in criteria and criteria["max_share_class_shares"] > 0:
            query = query.filter(
                TickerReference.share_class_shares_outstanding
                <= criteria["max_share_class_shares"]
            )

        if has_metric_filters and criteria["min_volume"] > 0:
            query = query.filter(StockMetric.volume >= criteria["min_volume"])

        if settings.LOG_LEVEL == "DEBUG":
            try:
                statement = query.statement.compile(compile_kwargs={"literal_binds": True})
                logger.info(f"🔍 Discovery Screen Query: {statement}")
            except Exception as e:
                logger.error(f"Failed to log debug query: {e}")

        results = query.all()
        output = []
        for row in results:
            if has_metric_filters:
                ref, metric = row
            else:
                ref = row
                metric = None
            output.append(
                {
                    "ticker": ref.ticker,
                    "name": ref.name,
                    "market_cap": ref.market_cap,
                    "close_price": metric.close_price if metric else None,
                    "volume": metric.volume if metric else None,
                    "sector": ref.sector,
                    "primary_exchange": ref.primary_exchange,
                    "employees": ref.total_employees,
                    "sic_code": ref.sic_code,
                    "description": ref.description,
                    "asset_class": "stocks",
                    "data_source": data_source,
                }
            )
        return output


register_screener("stocks", StockScreener().screen)
```

**Step 2.4 — Verify StockScreener tests pass**

```bash
pytest backend/tests/services/test_discovery_service.py -k "stock_screener" -x
```

Expected: 6 tests **PASS**.

**Step 2.5 — Verify no regressions**

```bash
pytest backend/tests/services/test_discovery_service.py -x
```

Expected: all existing tests pass.

**Step 2.6 — Commit**

```bash
git add backend/app/services/stock_screener.py \
        backend/tests/services/test_discovery_service.py
git commit -m "feat(#287): add StockScreener adapter with self-registration"
```

---

## Task 3 — FuturesScreener adapter (TDD)

Write tests first, then implement `backend/app/services/futures_screener.py`.

### Files
- `backend/tests/services/test_discovery_service.py` (write tests first)
- `backend/app/services/futures_screener.py` (new)

### Steps

**Step 3.1 — Write failing FuturesScreener tests**

Append to `backend/tests/services/test_discovery_service.py`:

```python
# ── FuturesScreener unit tests ───────────────────────────────────────────────


def _seed_futures_contract(db, symbol, exchange):
    from app.models.futures_contract import FuturesContract

    row = FuturesContract(
        symbol=symbol,
        exchange=exchange,
        contract_month="20260321",
    )
    db.add(row)
    db.flush()
    return row


def test_futures_screener_csv_string_parsed_upper_strip(db):
    """String CSV futures_symbols uppercased and stripped; found symbol returned."""
    from app.services.futures_screener import FuturesScreener

    _seed_futures_contract(db, "ES", "CME")
    screener = FuturesScreener()
    results = screener.screen(
        {"asset_classes": ["futures"], "futures_symbols": "es, nq"},
        db,
    )
    tickers = [r["ticker"] for r in results]
    assert "ES" in tickers   # found in DB
    assert "NQ" in tickers   # not in DB → placeholder still present


def test_futures_screener_list_symbols_accepted(db):
    """List futures_symbols processed without error; found symbol in output."""
    from app.services.futures_screener import FuturesScreener

    _seed_futures_contract(db, "GC", "COMEX")
    screener = FuturesScreener()
    results = screener.screen(
        {"asset_classes": ["futures"], "futures_symbols": ["GC", "CL"]},
        db,
    )
    tickers = [r["ticker"] for r in results]
    assert "GC" in tickers


def test_futures_screener_found_symbol_has_correct_exchange(db):
    """Found symbol output dict has correct exchange and asset_class."""
    from app.services.futures_screener import FuturesScreener

    _seed_futures_contract(db, "NQ", "CME")
    screener = FuturesScreener()
    results = screener.screen(
        {"asset_classes": ["futures"], "futures_symbols": "NQ"},
        db,
    )
    nq = next(r for r in results if r["ticker"] == "NQ")
    assert nq["primary_exchange"] == "CME"
    assert nq["asset_class"] == "futures"


def test_futures_screener_missing_symbol_placeholder(db):
    """Symbol not in DB produces placeholder with primary_exchange='Unknown'."""
    from app.services.futures_screener import FuturesScreener

    screener = FuturesScreener()
    results = screener.screen(
        {"asset_classes": ["futures"], "futures_symbols": "ZZMISS"},
        db,
    )
    assert len(results) == 1
    assert results[0]["ticker"] == "ZZMISS"
    assert results[0]["primary_exchange"] == "Unknown"
    assert results[0]["asset_class"] == "futures"
    assert "Sync pending" in results[0]["description"]
```

**Step 3.2 — Verify tests fail**

```bash
pytest backend/tests/services/test_discovery_service.py -k "futures_screener" -x
```

Expected: `ModuleNotFoundError: No module named 'app.services.futures_screener'`

**Step 3.3 — Create `backend/app/services/futures_screener.py`**

```python
import logging
from typing import Any, Dict, List

from sqlalchemy.orm import Session

from app.services.discovery_service import register_screener

logger = logging.getLogger(__name__)


class FuturesScreener:
    def screen(self, criteria: Dict[str, Any], db: Session) -> List[Dict[str, Any]]:
        from app.models.futures_contract import FuturesContract

        data_source = criteria.get("data_source_futures", "ibkr")
        futures_input = criteria.get("futures_symbols", "")

        if isinstance(futures_input, str):
            futures_symbols = [s.strip().upper() for s in futures_input.split(",") if s.strip()]
        else:
            futures_symbols = [
                s.strip().upper() for s in futures_input if isinstance(s, str) and s.strip()
            ]

        output: List[Dict[str, Any]] = []
        if not futures_symbols:
            return output

        found_futures = (
            db.query(FuturesContract.symbol, FuturesContract.exchange)
            .filter(FuturesContract.symbol.in_(futures_symbols))
            .distinct()
            .all()
        )
        found_symbols = {f.symbol for f in found_futures}

        for fut in found_futures:
            output.append(
                {
                    "ticker": fut.symbol,
                    "name": f"{fut.symbol} Futures",
                    "market_cap": None,
                    "close_price": None,
                    "volume": None,
                    "sector": "Futures",
                    "primary_exchange": fut.exchange,
                    "employees": None,
                    "sic_code": None,
                    "description": f"Futures contract for {fut.symbol}",
                    "asset_class": "futures",
                    "data_source": data_source,
                }
            )

        for symbol in futures_symbols:
            if symbol not in found_symbols:
                output.append(
                    {
                        "ticker": symbol,
                        "name": f"{symbol} Futures",
                        "market_cap": None,
                        "close_price": None,
                        "volume": None,
                        "sector": "Futures",
                        "primary_exchange": "Unknown",
                        "employees": None,
                        "sic_code": None,
                        "description": f"Requested Futures contract for {symbol} (Sync pending)",
                        "asset_class": "futures",
                        "data_source": data_source,
                    }
                )

        return output


register_screener("futures", FuturesScreener().screen)
```

**Step 3.4 — Verify FuturesScreener tests pass**

```bash
pytest backend/tests/services/test_discovery_service.py -k "futures_screener" -x
```

Expected: 4 tests **PASS**.

**Step 3.5 — Verify no regressions**

```bash
pytest backend/tests/services/test_discovery_service.py -x
```

**Step 3.6 — Commit**

```bash
git add backend/app/services/futures_screener.py \
        backend/tests/services/test_discovery_service.py
git commit -m "feat(#287): add FuturesScreener adapter with self-registration"
```

---

## Task 4 — Integration smoke test + replace `run_screen()` with dispatcher

Write the integration smoke test against the current `run_screen()` (verifies it passes before the replacement), then replace the body with the dispatcher.

### Files
- `backend/tests/services/test_discovery_service.py` (smoke test first)
- `backend/app/services/discovery_service.py` (replace `run_screen()` body)

### Steps

**Step 4.1 — Write integration smoke test**

Append to `backend/tests/services/test_discovery_service.py`:

```python
# ── Integration smoke test ────────────────────────────────────────────────────


def test_run_screen_multi_asset_class_returns_combined_output(db):
    """run_screen with stocks+futures returns combined output with correct asset_class fields."""
    from unittest.mock import patch

    from app.services.discovery_service import DiscoveryService

    _seed_ticker(db, "INTG1")
    _seed_futures_contract(db, "ES", "CME")

    with patch("app.services.discovery_service.RESTClient"):
        service = DiscoveryService(db)
        results = service.run_screen(
            {
                "asset_classes": ["stocks", "futures"],
                "futures_symbols": "ES",
            }
        )

    asset_classes = {r["asset_class"] for r in results}
    assert "stocks" in asset_classes
    assert "futures" in asset_classes
    stock_results = [r for r in results if r["asset_class"] == "stocks"]
    futures_results = [r for r in results if r["asset_class"] == "futures"]
    assert any(r["ticker"] == "INTG1" for r in stock_results)
    assert any(r["ticker"] == "ES" for r in futures_results)
```

**Step 4.2 — Verify integration test passes on current code**

```bash
pytest backend/tests/services/test_discovery_service.py::test_run_screen_multi_asset_class_returns_combined_output -x
```

Expected: **PASS** (current `run_screen()` handles both paths).

**Step 4.3 — Replace `run_screen()` body with dispatcher**

In `backend/app/services/discovery_service.py`, replace the entire body of `run_screen()` (keep the method signature and docstring):

```python
    def run_screen(self, criteria: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Executes a screen based on provided criteria.
        Returns list of matching tickers with their fundamental data.
        """
        import app.services.futures_screener  # noqa: F401 — triggers self-registration
        import app.services.stock_screener  # noqa: F401 — triggers self-registration

        asset_classes = criteria.get("asset_classes", ["stocks"])
        output: List[Dict[str, Any]] = []
        for asset_class in asset_classes:
            screener_fn = _SCREENER_REGISTRY.get(asset_class)
            if screener_fn is not None:
                output.extend(screener_fn(criteria, self.db))
            else:
                logger.warning("No screener registered for asset_class=%r", asset_class)
        return _apply_shared_filters(output, criteria)
```

**Step 4.4 — Verify integration test still passes**

```bash
pytest backend/tests/services/test_discovery_service.py::test_run_screen_multi_asset_class_returns_combined_output -x
```

Expected: **PASS**.

**Step 4.5 — Run full test module**

```bash
pytest backend/tests/services/test_discovery_service.py -v
```

Expected: all 15 tests pass (1 registry smoke + 6 StockScreener + 4 FuturesScreener + 1 integration + 3 legacy = 15).

**Step 4.6 — Verify `run_screen()` line count ≤ 40**

```bash
python3 -c "
import ast, sys
src = open('backend/app/services/discovery_service.py').read()
tree = ast.parse(src)
for node in ast.walk(tree):
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == 'run_screen':
        lines = node.end_lineno - node.lineno + 1
        print(f'run_screen: {lines} lines')
        sys.exit(0 if lines <= 40 else 1)
"
```

Expected output: `run_screen: 14 lines` (or similar ≤40, exit code 0).

**Step 4.7 — Commit**

```bash
git add backend/app/services/discovery_service.py \
        backend/tests/services/test_discovery_service.py
git commit -m "feat(#287): replace run_screen() with ≤40-line dispatcher; wire StockScreener + FuturesScreener"
```
