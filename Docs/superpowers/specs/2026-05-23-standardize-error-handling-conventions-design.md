# Standardize Error Handling Conventions Across Modules

**Date:** 2026-05-23  
**Status:** Pending Review  
**Issue:** #64  
**Scope:** `backend/app/exceptions.py` (new), `backend/app/services/*.py`, `backend/app/tasks.py`, `backend/app/providers/ibkr.py`, `backend/app/providers/massive.py`, `backend/app/main.py`, `backend/app/models/scanner.py`, Alembic migration

---

## Problem

Three incompatible error handling patterns exist across the service layer, making it impossible for callers to predict how a module fails:

- **StockDataService** (`stock_data.py`): returns `{"status": "error", ...}` dicts — callers must inspect dict keys
- **FuturesDataService** (`futures_data.py`): raises raw `RuntimeError` — no domain signal in the type
- **ScannerService** (`scanner.py`): catches `Exception` and logs silently — callers never learn which tickers failed
- **DiscoveryService** (`discovery_service.py`): mixed — some paths re-raise, others swallow

Providers are equally inconsistent: `ibkr.py` and `massive.py` raise `RuntimeError`, `ConnectionError`, and `ValueError` with no domain typing, so services must use broad `except Exception` to absorb them.

---

## Goals

1. Define a typed exception hierarchy that all service and provider modules raise at their public boundaries
2. Replace dict-return error patterns and silent swallowing with explicit raises
3. Enable Celery tasks to make retry decisions without pattern-matching on exception message strings
4. Surface per-ticker scan failures as structured data on `ScannerRun` rather than silent log lines
5. Map domain errors to consistent HTTP responses without leaking internal messages

---

## Requirements

### Exception Hierarchy

Define `backend/app/exceptions.py`:

```python
class MarketHawkError(Exception):
    def __init__(self, message: str, is_retryable: bool = False):
        super().__init__(message)
        self.is_retryable = is_retryable

class ScanError(MarketHawkError):
    pass

class DataFetchError(MarketHawkError):
    pass

class ProviderError(MarketHawkError):
    pass
```

`is_retryable` is set at the raise site based on context — `DataFetchError("rate limited", is_retryable=True)` for a 429, `DataFetchError("ticker not found", is_retryable=False)` for a 404. No subclasses in this pass; subclasses (`RateLimitError`, `ProviderTimeoutError`, etc.) are added only when a caller genuinely needs to catch them separately.

### Provider Layer (`providers/ibkr.py`, `providers/massive.py`)

Replace bare `RuntimeError`, `ValueError`, and `ConnectionError` raises at public method boundaries with `ProviderError`. Set `is_retryable=True` for transient failures (IBKR unreachable, Polygon 429/503), `is_retryable=False` for configuration errors (bad symbol, wrong exchange). `providers/ibkr_orders.py` is out of scope.

### StockDataService (`services/stock_data.py`)

`refresh_stock_data()` raises `DataFetchError` on failure instead of returning `{"status": "error", ...}`. The success dict return shape is unchanged. All callers updated in the same PR:
- Router (`routers/stocks.py`): wrap in `try/except DataFetchError`, return appropriate HTTP error
- Celery tasks (`tasks.py`): let `DataFetchError` propagate to Celery retry machinery when `is_retryable=True`; log and swallow when `is_retryable=False`

### FuturesDataService (`services/futures_data.py`)

Replace `raise RuntimeError(...)` with `raise ProviderError(...)` at provider boundary calls. Callers (`tasks.py`) catch `ProviderError` by name.

### ScannerService (`services/scanner.py`)

Per-ticker loop in `run_pre_market_scan()` and `run_oversold_bounce_scan()`:

```python
failed_tickers = []
for ticker in tickers:
    try:
        # existing ticker processing
        ...
    except (ScanError, DataFetchError, ProviderError) as e:
        failed_tickers.append({
            "ticker": ticker,
            "error_type": type(e).__name__,
            "message": str(e),
            "retryable": e.is_retryable,
        })
        logger.warning(f"Ticker {ticker} failed: {e}")
    # unexpected Exception propagates — structural failures abort the scan

# persist failed_tickers on ScannerRun
```

Silent `except Exception: pass` blocks (lines 258-259, 302-303 — market context enrichment) are replaced with named catches or explicit re-raises with logging.

### ScannerRun Model (`models/scanner.py`)

Add `failed_tickers` nullable JSONB column:

```python
failed_tickers = Column(JSONB, nullable=True, default=None)
```

Generate and apply migration. `error_message` (existing Text column) stays as the run-level failure string when the scan aborts entirely; `failed_tickers` holds the structured partial-failure list when the scan completes with per-ticker errors.

### DiscoveryService (`services/discovery_service.py`)

Inconsistent patterns normalized: all paths either re-raise (after logging + rollback) or explicitly swallow with a comment. No bare `except Exception` without a documented reason.

### FastAPI Global Handler (`main.py`)

Register a `MarketHawkError` handler before the existing `Exception` catch-all in `create_app()`:

```python
@app.exception_handler(MarketHawkError)
async def markethawk_error_handler(request: Request, exc: MarketHawkError):
    status_code = 503 if exc.is_retryable else 422
    return JSONResponse(
        status_code=status_code,
        content={"error": str(exc), "retryable": exc.is_retryable},
    )
```

FastAPI resolves handlers most-specific-first, so typed `MarketHawkError` instances hit this handler and unexpected exceptions fall through to the existing `Exception` handler with its Seq error tracking intact. Individual router `try/except` blocks are not cleaned up in this PR.

---

## Approach

**Single-pass migration**: define the exception hierarchy, migrate providers first (the bottom of the call stack), then services, then update callers (tasks + routers), then add the FastAPI handler, then the migration + model column. All changes ship in one PR so the hierarchy is consistent from day one — a partial migration would leave some callers unable to predict error types, which is the same problem the issue is trying to solve.

---

## Alternatives Considered

### Richer Subclass Hierarchy (Rejected)

Add `RateLimitError`, `ProviderTimeoutError`, `TickerNotFoundError`, etc. as subclasses under the three top-level types. Rejected as premature — no caller currently needs to catch these separately. Adding subclasses is non-breaking; they can be introduced incrementally when a specific catch site appears.

### `ibkr_orders.py` In Scope (Rejected)

`ibkr_orders.py` is only consumed by `auto_trade_service.py`, which is not listed in the issue scope. Including it widens the blast radius without adding value to the stated goals.

### Reuse `error_message` Column for Per-Ticker Failures (Rejected)

Storing JSON-encoded per-ticker failures in the existing `error_message` Text column loses type clarity and creates the same "inspect the string to know the shape" problem the issue is fixing. A dedicated `failed_tickers JSONB` column with nullable default is a single-statement migration.

### Versioned Method (`refresh_stock_data_v2`) (Rejected)

Adding a parallel method to avoid touching callers delays the honest interface and leaves two code paths to maintain. The actual caller surface is small (one router line, two Celery call sites that discard the return value) — a direct in-place migration is clean and fits size: M.

---

## Open Questions

- **HTTP status mapping edge case**: `ProviderError(is_retryable=False)` maps to 422, but a provider being permanently misconfigured might be better expressed as 502 Bad Gateway. The `is_retryable` flag covers the Celery retry path; HTTP status nuance can be revisited when specific router callers are cleaned up.
- **`run_oversold_bounce_scan` failed_tickers**: The spec applies the same per-ticker collection pattern to this scan as to `run_pre_market_scan`. If `oversold_bounce` uses a different `ScannerRun` record, confirm the model column is accessible from its writer path.

---

## Assumptions

- `ibkr_orders.py` remains out of scope for this PR
- Individual router `try/except` blocks are a follow-on cleanup, not required here
- The success dict return from `refresh_stock_data()` is unchanged (callers that use the returned metadata continue to work)
- HTTP 503 for retryable errors and 422 for non-retryable is a reasonable starting point; per-subclass overrides are a follow-on
- The `failed_tickers` JSONB column stores a JSON array of `{ticker, error_type, message, retryable}` objects; schema is not validated by a Pydantic model in this pass
