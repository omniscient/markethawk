# Decompose scanner.py / futures_data.py God Modules — Design

**Date:** 2026-06-05
**Status:** Spec generated — pending implementation plan
**Author:** Brainstormed with Claude (Opus 4.8)
**Issue:** [#199](https://github.com/omniscient/markethawk/issues/199)

## Problem

The two worst v1 god modules grew after the #96 router-thinning (which pushed orchestration into the service layer):

- `backend/app/services/scanner.py`: 804 → **1,033 lines** — `run_pre_market_scan` alone spans lines 466–819 (~353 lines), `_get_batch_enrichment_data_impl` is another ~175 lines, all inside a single `ScannerService` class.
- `backend/app/services/futures_data.py`: 1,039 → **1,086 lines** — contracts, data download/gap-fill, rollover detection, and continuous-series stitching all live in one `FuturesDataService` class plus module-level helpers.

Both files score poorly on the Architecture Quality Report v2 complexity-hotspot dimension (regression 3→2).

## Goals

Extract cohesive units from each module into focused sibling files while:

1. Preserving all public interfaces (no caller or test changes required).
2. Keeping all existing tests green.
3. Leaving each resulting file **meaningfully smaller** — targeting ≤400 lines for `scanner.py` and ≤300 lines for each extracted module.

## Non-Goals (v1)

- Changing the behaviour of any scanner or futures logic.
- Restructuring the `ScannerService` API surface or converting static methods to plain functions.
- Introducing `futures/` or `scanner/` subpackages (no precedent in the flat `app/` structure).
- Merging `scanner_query_service.py` into this work (already extracted).

## Delivery Plan: Two Separate PRs

Per Q&A: the two modules are independent decompositions. A single combined PR would produce a >2,100-line diff across two unrelated god modules, making behaviour-preservation hard to review. Two sequential PRs reduce surface area and risk:

| PR | Module | Import sites | Risk |
|----|--------|-------------|------|
| 1 | `scanner.py` | 5 (callers reference one symbol, `ScannerService`) | Lower |
| 2 | `futures_data.py` | 9 (callers reference three symbols: `FuturesDataService`, `SYMBOL_EXCHANGE_MAP`, `_resolve_exchange`) | Higher |

---

## PR 1 — Decompose `scanner.py`

### Current structure (`ScannerService` class, all static methods)

| Lines | Group |
|-------|-------|
| 55–187 | Session metrics — `calculate_day_metrics_from_aggs` (pure, ~55 lines), `calculate_day_metrics` (DB fetch + compute, ~75 lines) |
| 190–245 | Utility helpers — `default_scan_date`, `check_concurrency`, `resolve_date_range`, `count_active_tickers` (~55 lines) |
| 247–433 | Batch enrichment — `_get_batch_enrichment_data` + `_get_batch_enrichment_data_impl` (~175 lines) + `_SECTOR_ETF_MAP` constant |
| 436–463 | `_save_event` — thin 28-line wrapper delegating to `alert_service.save_event` |
| 466–818 | Pre-market scan — `run_pre_market_scan` (~353 lines, core scan loop) |
| 819–1019 | Oversold bounce scan — `run_oversold_bounce_scan` (~200 lines) |
| 1020–1033 | Date wrappers — `run_pre_market_scan_for_date`, `run_oversold_bounce_scan_for_date` |

### New file layout

**`session_metrics.py`** (new, ~135 lines)
- `calculate_day_metrics_from_aggs(aggs) → Dict` — pure computation from aggregate list
- `calculate_day_metrics(ticker, event_date, db) → Dict` — DB fetch + session classification

**`scan_enrichment.py`** (new, ~185 lines)
- `_SECTOR_ETF_MAP`, `_SECTOR_ETF_SYMBOLS` — constants
- `_get_batch_enrichment_data(tickers, event_date, db)` — public dispatch
- `_get_batch_enrichment_data_impl(tickers, event_date, db)` — full implementation (ticker reference, ES/NQ market context, sector ETF changes)

**`pre_market_scan.py`** (extend existing, +~353 lines)
- Add `run_pre_market_scan(tickers, db, event_date, scanner_run) → List[Dict]` as a module-level async function. The existing `_run` adapter stays and calls this function directly instead of delegating through `ScannerService`.

**`oversold_bounce_scan.py`** (extend existing, +~200 lines)
- Add `run_oversold_bounce_scan(tickers, db, event_date, scanner_run) → List[Dict]` as a module-level async function. Same pattern as above.

**`scanner.py`** (reduced, ~275–300 lines)
- `ScannerService` class retained as a **thin facade** with all existing static method names preserved.
- Every method delegates to the extracted module: e.g., `ScannerService.calculate_day_metrics` calls `session_metrics.calculate_day_metrics`.
- Utility helpers (`default_scan_date`, `check_concurrency`, `resolve_date_range`, `count_active_tickers`) and `_save_event` stay as `ScannerService` methods — too small to extract and heavily referenced by the orchestrator and router.
- `run_pre_market_scan` and `run_oversold_bounce_scan` use **lazy imports** inside the method body to delegate (same pattern the registry files already use to call back into `ScannerService`).

### Circular import strategy

Current graph:
```
pre_market_scan.py → (top-level) scan_orchestrator.py
pre_market_scan.py → (lazy) scanner.py
scan_orchestrator.py → (lazy) scanner.py
scanner.py → (no imports from pre_market_scan or scan_orchestrator)
```

After this refactor, if `scanner.py` delegates to `pre_market_scan.py`, it must use a **lazy (function-body) import** to avoid a load-time cycle:

```python
# scanner.py  (inside ScannerService.run_pre_market_scan)
async def run_pre_market_scan(tickers, db, event_date=None, scanner_run=None):
    from app.services.pre_market_scan import run_pre_market_scan as _impl
    return await _impl(tickers, db, event_date=event_date, scanner_run=scanner_run)
```

This mirrors how `scan_orchestrator.enqueue_scan` already lazy-imports `ScannerService`. The result:
```
pre_market_scan.py → (top-level) scan_orchestrator.py
pre_market_scan.py → (no import from scanner.py needed — body is here now)
scan_orchestrator.py → (lazy) scanner.py
scanner.py → (lazy) pre_market_scan.py   ← new, same lazy pattern
```

No top-level cycle is introduced.

### Backward compatibility

All 5 import sites of `scanner.py` reference only `ScannerService` (via `from app.services.scanner import ScannerService` or `from app.services import ScannerService`). Because `ScannerService` is preserved as a facade on the same module, **zero import sites change**. The three test files (`test_scanner_service_methods.py`, `test_scanner_refactor.py`, `test_feature_enrichment.py`) call `ScannerService.<method>` — all calls continue to work unchanged.

---

## PR 2 — Decompose `futures_data.py`

### Current structure

| Lines (approx) | Group |
|----------------|-------|
| 1–86 | Module-level: `SYMBOL_EXCHANGE_MAP`, `_resolve_exchange` |
| 100–206 | Contract catalog — `_sync_contract_catalog` (~85 lines), `sync_contracts` (~15 lines) |
| 209–239 | Continuous series — `get_continuous_series` (public, ~30 lines) |
| 240–454 | Data download — `_download_contract` (~200 lines) |
| 455–620 | History download — `_download_full_history` (~165 lines) |
| 621–762 | Gap fill — `_fill_data_gaps` (~140 lines) |
| 763–853 | Rollover detection (class) — `_detect_rollovers` (~90 lines) |
| 854–974 | Continuous series impl — `_get_continuous_series_with_db` (~120 lines) |
| 975–1086 | Module-level — `_detect_single_rollover` (~24 lines), `_build_time_slices` (~27 lines) |

### New file layout

The issue names three units: **contracts / rollovers / aggregation**. The aggregation group is further split into download and series to keep modules ≤350 lines each.

**`futures_contracts.py`** (new, ~120 lines)
- `SYMBOL_EXCHANGE_MAP` — module constant (re-exported from facade)
- `_resolve_exchange(symbol)` — exchange resolver (re-exported from facade)
- `FuturesContractService._sync_contract_catalog` — IBKR query + upsert to `futures_contracts` table
- `FuturesContractService.sync_contracts` — public entry point

Rationale: `SYMBOL_EXCHANGE_MAP` and `_resolve_exchange` are exchange-resolution concerns; placing them in the contract module avoids circular imports (aggregation and rollovers modules import contract concepts, not the reverse).

**`futures_aggregates.py`** (new, ~520 lines)
- `FuturesAggregatesService._download_contract` — per-contract IBKR bar download
- `FuturesAggregatesService._download_full_history` — full contract history loop
- `FuturesAggregatesService._fill_data_gaps` — gap detection and backfill

**`futures_rollovers.py`** (new, ~160 lines)
- `FuturesRolloversService._detect_rollovers` — class method
- `_detect_single_rollover` — module-level helper
- `_build_time_slices` — module-level helper

**`futures_series.py`** (new, ~160 lines)
- `FutureSeriesService.get_continuous_series` — public interface
- `FutureSeriesService._get_continuous_series_with_db` — DB-backed implementation

**`futures_data.py`** (reduced, re-export facade, ~60–80 lines)
```python
# Preserve all 3 public symbols that callers reference
from app.services.futures_contracts import SYMBOL_EXCHANGE_MAP, _resolve_exchange
from app.services.futures_contracts import FuturesContractService

class FuturesDataService(
    FuturesContractService,
    FuturesAggregatesService,
    FuturesRolloversService,
    FutureSeriesService,
):
    """Backward-compatibility facade — delegates to focused subservices."""
```

Alternatively (simpler and less magic): keep `FuturesDataService` in `futures_data.py` as a thin class that explicitly delegates each public method, and import the implementations from the new modules.

> **Assumption**: The simpler explicit-delegation pattern is preferred over multiple inheritance. The test file `test_futures_data_service.py` calls `FuturesDataService.<method>` — explicit delegation preserves this without any MRO complexity.

### Backward compatibility for 9 import sites

All 9 import sites reference one of three symbols from `futures_data.py`. All three must remain importable from that module after extraction:

| Symbol | Callers | Preserved via |
|--------|---------|--------------|
| `FuturesDataService` | `services/__init__.py`, `tasks/sync.py`, `normalization.py`, `stock_data.py`, `routers/futures.py` | Re-exported class or facade in `futures_data.py` |
| `SYMBOL_EXCHANGE_MAP` | `universe_orchestrator.py` (×2), `routers/stocks.py` | `from .futures_contracts import SYMBOL_EXCHANGE_MAP` in `futures_data.py` |
| `_resolve_exchange` | `routers/futures.py` | `from .futures_contracts import _resolve_exchange` in `futures_data.py` |

**Zero import sites change.**

---

## Alternatives Considered

### Alt 1 — `futures/` subpackage
Create `app/services/futures/__init__.py` with sibling modules inside. Rejected: no subpackages exist anywhere in the `app/` tree. Flat filename prefixing (`futures_contracts.py`, `futures_aggregates.py`) is the established convention (`universe_orchestrator.py`, `universe_export.py`, `universe_stats.py` etc.). Introducing the first nested package adds tooling/import cognitive overhead for marginal organizational benefit.

### Alt 2 — Dissolve `ScannerService` class entirely
Convert all static methods to module-level functions and update callers. Rejected: `ScannerService` is the public API referenced by 5 callers and 3 test files. Dissolving it would require touching all those files, contradicting "no behavioural change / tests stay green." The facade pattern gives the same structural improvement for zero import churn.

### Alt 3 — Single combined PR for both modules
Rejected: the two refactors are fully independent (no shared code), `futures_data.py` has nearly double the import sites and three public symbols to preserve, and a 2,100-line combined diff is hard to review for behaviour preservation. Sequential PRs reduce risk and review burden.

### Alt 4 — Leave utility helpers in `scanner.py` (chosen)
Moving `default_scan_date`, `check_concurrency`, `resolve_date_range`, `count_active_tickers` (~55 lines) to a separate `scanner_utils.py` is possible but the extraction value is low — these are orchestration-state functions tightly coupled to `ScannerService`'s callers. They stay on the facade.

---

## Open Questions (non-blocking)

- **`futures_aggregates.py` line count**: At ~520 lines it is the largest extracted module. If a subsequent audit flags it, `_download_contract` (200 lines) could be further split into `_download_contract_bars` + `_download_contract_upsert`. Not needed for this ticket.
- **`FuturesDataService` inheritance vs. explicit delegation**: The spec recommends explicit delegation; implementer should pick whichever is cleanest once they see the actual method signatures.

---

## Assumptions (flagged)

- **A1**: `calculate_day_metrics_from_aggs` has no callers outside `ScannerService` — confirmed by grep. It can be extracted without re-export since tests call it via `ScannerService`.
- **A2**: The lazy-import pattern for `run_pre_market_scan`/`run_oversold_bounce_scan` is adequate to avoid the load-time cycle. The existing lazy-import on these same paths confirms this is safe.
- **A3**: `_detect_single_rollover` and `_build_time_slices` are module-level functions in `futures_data.py` with no known external callers (they begin with `_`). Moving them to `futures_rollovers.py` does not break any import sites.
- **A4**: Tests import `ScannerService` and `FuturesDataService` by their class name, not by inspecting module internals. The facade pattern preserves this.
