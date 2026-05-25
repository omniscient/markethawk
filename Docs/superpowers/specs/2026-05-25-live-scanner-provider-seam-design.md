# Live Scanner Provider Seam — Design Spec

**Issue**: [#75 — refactor: abstract live scanner IBKR coupling behind provider seam](https://github.com/omniscient/markethawk/issues/75)
**Date**: 2026-05-25
**Status**: Pending Review

## Overview

The live scanner (`backend/live_scanner/`) bypasses the provider abstraction used by the batch scanner. `main.py` imports `ib_insync` directly throughout, session detection is duplicated with a 1-minute boundary drift, and `publisher.py` creates its own SQLAlchemy engine instead of reusing the app's session factory. This refactor places a clean seam between `main.py` and the IBKR-specific implementation, consolidates session detection into a single shared utility, and aligns the publisher's DB access with the rest of the codebase.

**Volume calculations are intentionally NOT merged.** The live scanner projects full-session volume mid-session; the batch scanner measures actual pre-market volume. These differ by design and must remain separate. See CONTEXT.md → "Signal" and "Scanner" for the authoritative documentation of this distinction.

## Requirements

1. A `LiveDataProvider` Protocol defines the streaming data contract: `subscribe`, `unsubscribe`, and `fetch_seed_data`. All IBKR-specific code moves behind this seam.
2. `IBKRLiveAdapter` implements the protocol for the existing IBKR connection.
3. A minimal `MockLiveAdapter` implements the protocol with stub behaviour — no bar emission, fixed seed data — sufficient to instantiate the live scanner without an IBKR connection in tests.
4. Session detection is consolidated into `app/utils/session.py`. The canonical post-market boundary is **16:00 ET** (fixing the 1-minute bug in `classify_session()`).
5. `classify_session()` is kept as a deprecated shim so existing batch-scanner callers are not broken. Its post-market boundary bug is also fixed in the shim.
6. `publisher.py` uses `SessionLocal` from `app.core.database` instead of creating its own engine.
7. `bar_aggregator.py` imports `session_for_ts` and `session_total_minutes` from `app.utils.session` (deletes its own duplicate definitions).
8. `main.py` imports `session_for_ts` only through the BarAggregator; all direct ib_insync imports are eliminated from `main.py`.

## Architecture

### `LiveDataProvider` Protocol — `backend/live_scanner/provider.py`

```python
from typing import Protocol, Callable, Awaitable

BarCallback   = Callable[[str, object], Awaitable[None]]   # (symbol, RealTimeBar-like)
QuoteCallback = Callable[[str, dict],   Awaitable[None]]   # (symbol, {last, bid, ask, time})

class LiveDataProvider(Protocol):
    async def fetch_seed_data(
        self, symbol: str, security_type: str, exchange: str
    ) -> tuple[float, float]:
        """Return (prior_close, avg_daily_volume) to seed BarAggregator."""
        ...

    async def subscribe(
        self,
        symbol: str,
        security_type: str,
        exchange: str,
        on_bar: BarCallback,
        on_quote: QuoteCallback,
    ) -> None:
        """Open real-time subscriptions. Callbacks fire on each incoming event."""
        ...

    async def unsubscribe(self, symbol: str) -> None:
        """Cancel all subscriptions for the symbol."""
        ...

    async def disconnect(self) -> None:
        """Tear down the underlying connection."""
        ...
```

The callbacks receive events asynchronously. This keeps the event-routing logic in `main.py`'s `_process_loop` unchanged — the adapter calls `on_bar` / `on_quote` instead of `queue.put_nowait`.

### `IBKRLiveAdapter` — `backend/live_scanner/ibkr_adapter.py`

Extracts all ib_insync-specific code from `main.py`:

- `__init__(ib: IB)` — takes a connected `IB` instance (connection management stays in `main.py` for now; this adapter is not responsible for reconnect logic)
- `fetch_seed_data` — wraps `ib.reqHistoricalDataAsync` (current `_fetch_prior_data` logic)
- `subscribe` — wraps `ib.reqRealTimeBars` + `ib.reqMktData` (current `_subscribe` logic minus aggregator creation and queue operations)
- `unsubscribe` — wraps `ib.cancelRealTimeBars` + `ib.cancelMktData`
- `disconnect` — calls `ib.disconnect()`

The adapter maintains its own `_bar_subs` and `_mkt_subs` dicts internally; `main.py` no longer holds them directly.

### `MockLiveAdapter` — `backend/live_scanner/mock_adapter.py`

Minimal stub for testing:

```python
class MockLiveAdapter:
    async def fetch_seed_data(self, symbol, security_type, exchange) -> tuple[float, float]:
        return 100.0, 500_000.0  # fixed plausible defaults

    async def subscribe(self, symbol, security_type, exchange, on_bar, on_quote):
        pass  # accepts subscriptions; no events emitted

    async def unsubscribe(self, symbol):
        pass

    async def disconnect(self):
        pass
```

This satisfies the Protocol and allows tests to construct a fully-wired live scanner without IBKR.

### Session Detection — `app/utils/session.py`

Add alongside the existing `classify_session()`:

```python
_ET = ZoneInfo("America/New_York")

_SESSIONS = [
    ("pre",     4 * 60,      9 * 60 + 30),
    ("regular", 9 * 60 + 30, 16 * 60),
    ("post",    16 * 60,     20 * 60),
]

def session_for_ts(ts: datetime) -> str:
    """Return 'pre', 'regular', 'post', or 'closed' for a UTC timestamp."""
    et = ts.astimezone(_ET) if ts.tzinfo else ts.replace(tzinfo=timezone.utc).astimezone(_ET)
    m = et.hour * 60 + et.minute
    for name, start, end in _SESSIONS:
        if start <= m < end:
            return name
    return "closed"

def session_total_minutes(session: str) -> float:
    """Total minutes in a session (for projected-volume calculation)."""
    for name, start, end in _SESSIONS:
        if name == session:
            return float(end - start)
    return 390.0
```

Update `classify_session()` — fix the 1-minute boundary bug in the shim and delegate to `session_for_ts()`:

```python
def classify_session(ts_utc: datetime) -> tuple[bool, bool]:
    """Deprecated. Use session_for_ts() instead. Returns (is_pre, is_post)."""
    session = session_for_ts(ts_utc)
    return session == "pre", session == "post"
```

### Publisher DB — `publisher.py`

Replace the custom engine with the app's session factory:

```python
# Before:
from sqlalchemy import create_engine
class LivePublisher:
    def __init__(self, redis_url: str, db_url: str):
        self._engine = create_engine(db_url, pool_pre_ping=True)

# After:
from app.core.database import SessionLocal
class LivePublisher:
    def __init__(self, redis_url: str):  # db_url parameter removed
        pass  # engine no longer needed
```

All `Session(self._engine)` calls become `SessionLocal()`. Update the `main.py` call site from `LivePublisher(settings.REDIS_URL, settings.DATABASE_URL)` to `LivePublisher(settings.REDIS_URL)`.

The `asyncio.to_thread` pattern for sync DB writes is preserved — the live scanner is a separate process and cannot use the async session without restructuring the entire event loop. This is a one-file change.

### Updated `bar_aggregator.py`

Delete `session_for_ts()` and `session_total_minutes()` from `bar_aggregator.py`. Import them from `app.utils.session` instead. No logic changes.

### Updated `main.py`

- Remove all direct `ib_insync` imports (`IB`, `Stock`, `ContFuture`, `util`)
- Accept a `LiveDataProvider` in `run()` (defaulting to `IBKRLiveAdapter`)
- `_subscribe` becomes a thin coordinator: calls `provider.fetch_seed_data()`, creates `BarAggregator`, calls `provider.subscribe(symbol, ..., on_bar=..., on_quote=...)`
- `_unsubscribe` calls `provider.unsubscribe(symbol)`
- The queue and `_process_loop` are unchanged
- `_connect_ib` and `_build_contract` / `_qualify_contract` move into `IBKRLiveAdapter`

## Alternatives Considered

### A — Full async DB in publisher

Switch `publisher.py` to use `AsyncSession` and eliminate `asyncio.to_thread` entirely. This aligns with the batch scanner's pattern (ARCHITECTURE.md describes an async session factory). **Rejected for this issue**: the live scanner is a standalone asyncio process and `app.core.database` currently exports a sync `SessionLocal`. Converting the publisher to async would require restructuring `_write_scanner_event` into a coroutine, which is a larger change with higher risk for no immediate benefit. The sync-via-thread approach is already working and the DB write is not on the hot path.

### B — Reuse `IBKRDataProvider` (batch provider) for historical seed data

Route `_fetch_prior_data` through the existing `IBKRDataProvider.get_bars()` in `app/providers/ibkr.py`. **Rejected**: `IBKRDataProvider` is a sync class designed for the Celery/batch context; using it from the async live scanner would require `asyncio.to_thread` wrapping and imports across the module boundary. The live adapter using `ib.reqHistoricalDataAsync` directly is simpler and has the same seam guarantee.

### C — Combine subscribe + fetch_seed_data into one call

Have `subscribe()` return seed data so callers don't need a separate `fetch_seed_data()` round-trip. **Rejected**: the BarAggregator must be initialized with seed data *before* the first bar arrives. Combining them would force subscribe() to block until historical data is available, complicating cancellation and reconnect logic.

## Open Questions

- Should the deprecated `classify_session()` emit a `DeprecationWarning` at runtime, or is a docstring note sufficient? (Non-blocking — docstring is fine for now.)
- Should `IBKRLiveAdapter.__init__` accept a pre-connected `IB` instance or manage the connection itself? The current design leaves connection management in `main.py` to preserve the retry logic; this could be revisited later.

## Assumptions

- **`app.core.database.SessionLocal` is sync.** The code confirms this: `SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)`. The ARCHITECTURE.md describes an async factory for the FastAPI app, but the actual module is sync. This assumption may need revisiting if the database module is ever migrated to async.
- **No test suite currently exercises the live scanner.** The mock adapter enables future test coverage but doesn't gate this PR on achieving it.
- **IBKR connection management (retry logic, clientId, `util.patchAsyncio`) stays in `main.py`.** The adapter receives a connected `IB` object rather than owning the connection lifecycle.
