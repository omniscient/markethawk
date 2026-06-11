# DiscoveryService.run_screen Decomposition — Design

**Date:** 2026-06-11
**Issue:** [#287](https://github.com/omniscient/markethawk/issues/287)
**Status:** Spec Generated

## Overview

`DiscoveryService.run_screen` (`backend/app/services/discovery_service.py`) is 217 lines
with cyclomatic complexity ~43 — the highest in the codebase across three consecutive
architecture reviews (v1, v2, v3). It interleaves two fully independent paths in a single
function: the stocks path (11+ sequential criteria filters on `TickerReference`, optional
`StockMetric` JOIN) and the futures path (symbol parsing, `FuturesContract` lookup,
missing-symbol placeholder generation).

The fix is structural: extract each path into a dedicated screener adapter that
self-registers at import, and reduce `run_screen()` to a ≤40-line dispatcher. This mirrors
the self-registration pattern already in production via `scan_orchestrator.py`.

## Requirements

1. `run_screen()` body ≤ ~40 lines — dispatch loop + shared-filter seam only.
2. `StockScreener` and `FuturesScreener` adapters in separate files, each self-registering
   at import time via a module-level call (mirrors `pre_market_scan.py` / `oversold_bounce_scan.py`).
3. Adding a new asset class means dropping in a new adapter file — no branches added to
   `run_screen()`.
4. Existing screen results unchanged: same output dicts, same field names, same filtering
   semantics (including `min_volume` applied via SQL JOIN inside `StockScreener`).
5. Each screener independently unit-tested (seeded DB rows, exact-output assertions).
6. Multi-asset-class integration smoke test confirms the dispatch-and-collect seam.

## Architecture

### New files

#### `backend/app/services/stock_screener.py`

Contains a `StockScreener` class (or module-level function) that encapsulates the entire
stocks path verbatim from the current `run_screen()`:

- Reads `data_source_stocks` from `criteria`
- Builds a `TickerReference`-only or `TickerReference ⋈ StockMetric` query depending on
  whether `min_volume > 0` — this JOIN decision stays in SQL, not Python post-filtering
- Applies all 11 criteria filters (`min_market_cap`, `max_market_cap`,
  `min_outstanding_shares`, `sector`, `primary_exchange`, `sic_code`,
  `description_contains`, `min_employees`, `max_employees`, `min_share_class_shares`,
  `max_share_class_shares`, `min_volume`)
- Returns a list of output dicts with the existing field shape
- Calls `register_screener("stocks", StockScreener().screen)` at module level so
  importing the module triggers registration

**Signature:** `StockScreener.screen(criteria: Dict[str, Any], db: Session) -> List[Dict[str, Any]]`

#### `backend/app/services/futures_screener.py`

Contains a `FuturesScreener` class that encapsulates the futures path verbatim:

- Parses `futures_symbols` from `criteria` (string CSV or list, upper + strip)
- Queries `FuturesContract` for found symbols, builds the found-set
- Appends found-symbol dicts and missing-symbol placeholder dicts (same shape as today)
- Calls `register_screener("futures", FuturesScreener().screen)` at module level

**Signature:** `FuturesScreener.screen(criteria: Dict[str, Any], db: Session) -> List[Dict[str, Any]]`

### Modified file

#### `backend/app/services/discovery_service.py`

Add a module-level screener registry (3 lines) and replace the 217-line `run_screen()`
body with a ≤40-line dispatcher:

```python
# Module-level registry
ScreenerFn = Callable[[Dict[str, Any], Session], List[Dict[str, Any]]]
_SCREENER_REGISTRY: dict[str, ScreenerFn] = {}


def register_screener(asset_class: str, fn: ScreenerFn) -> None:
    _SCREENER_REGISTRY[asset_class] = fn


def _apply_shared_filters(
    output: List[Dict[str, Any]], criteria: Dict[str, Any]
) -> List[Dict[str, Any]]:
    # Cross-asset metric filters (e.g. min_price) would be applied here.
    # No cross-asset filters exist today; each screener handles its own criteria.
    return output
```

`run_screen()` becomes:

```python
def run_screen(self, criteria: Dict[str, Any]) -> List[Dict[str, Any]]:
    import app.services.stock_screener    # noqa: F401 — triggers self-registration
    import app.services.futures_screener  # noqa: F401 — triggers self-registration

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

The rest of `DiscoveryService` (`sync_fundamental_data`, `update_daily_metrics_snapshot`,
`sync_ticker_details_crawler`) is untouched.

### Test changes

`backend/tests/services/test_discovery_service.py` — add three test groups:

1. **`StockScreener` unit tests** (seeded `TickerReference` + `StockMetric` rows):
   - No metric filters → reference-only query, correct output shape
   - `min_volume` filter → inner join, only rows with sufficient volume returned
   - `min_market_cap` / `max_market_cap` range filter
   - `sector` filter (single value and list)
   - `primary_exchange` filter
   - Output dict has correct field names and `asset_class: "stocks"`

2. **`FuturesScreener` unit tests** (seeded `FuturesContract` rows):
   - String CSV `futures_symbols` parsed correctly (upper, strip)
   - List `futures_symbols` accepted
   - Found symbols produce exchange-correct output dicts
   - Missing symbols produce placeholder dicts (`primary_exchange: "Unknown"`)

3. **Integration smoke test** (seeded rows for both asset classes):
   - `run_screen({"asset_classes": ["stocks", "futures"], ...})` returns combined output
   - Stocks and futures results both present, each with correct `asset_class` field

Follow the fixture and assertion style of `test_futures_decompose.py` — no mocks for the
DB-level screener behavior tests, use the SAVEPOINT `db` fixture and `db.flush()`.

## Alternatives Considered

### A. Inline private methods (no registry)

Extract `_screen_stocks()` and `_screen_futures()` as private methods of `DiscoveryService`.
`run_screen()` calls both and concatenates.

- **Pro:** minimal files added, no registry machinery
- **Con:** violates acceptance criterion — adding a new asset class still means adding a
  branch to `run_screen()`. Does not satisfy "new asset class = new adapter" open/closed
  property. Rejected.

### B. Separate screener_registry.py module

Mirror `scan_orchestrator.py` exactly: a standalone `screener_registry.py` with `_REGISTRY`,
`register()`, `dispatch()`. Screener files import from `screener_registry.py`.
`discovery_service.py` imports from `screener_registry.py`.

- **Pro:** perfect structural symmetry with `scan_orchestrator.py`
- **Con:** adds a third new file for 3 lines of boilerplate. The registry only ever has 2
  entries today; housing it at module level in `discovery_service.py` (the existing dispatch
  point) keeps cohesion higher and file count lower. Selected approach (inline registry)
  achieves the same open/closed property with less indirection.

### C. Protocol / ABC screener interface

Define a `Screener` Protocol, each adapter implements it, `run_screen()` dispatches via a
dict built at class-init time.

- **Pro:** explicit type contract
- **Con:** more verbose, doesn't match the established module-registry idiom already
  in production. Rejected in favour of the proven pattern.

## Open Questions

- No blocking open questions. The `_apply_shared_filters` seam is intentionally empty; if
  a cross-asset metric filter is needed in future, the implementer adds it there.

## Assumptions

- `StockScreener` and `FuturesScreener` extract the current code **verbatim** — no logic
  changes, only relocation. Any refactoring of the criteria filter logic itself is out of
  scope for this ticket.
- The debug-logging block inside the stocks path (lines 237–245 of current
  `discovery_service.py`) moves into `StockScreener` as-is.
- No migration required — no model changes.
- The `discover_and_refresh()` call in `universe_orchestrator.py` (the only production
  caller of `run_screen`) is unchanged; `DiscoveryService.run_screen()` keeps its
  existing public signature.
