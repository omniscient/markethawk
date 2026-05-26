# Live Scanner Provider Seam — Implementation Plan

**Issue**: [#75 — refactor: abstract live scanner IBKR coupling behind provider seam](https://github.com/omniscient/markethawk/issues/75)
**Date**: 2026-05-26
**Spec**: `Docs/superpowers/specs/2026-05-25-live-scanner-provider-seam-design.md`

## Goal

Introduce a `LiveDataProvider` Protocol seam between `live_scanner/main.py` and ib_insync. Consolidate duplicate session detection into `app/utils/session.py`. Align `publisher.py` DB access with the app's `SessionLocal`. No change to volume calculation logic — the live/batch distinction is intentional and documented.

## Architecture

- **New files**: `live_scanner/provider.py`, `live_scanner/ibkr_adapter.py`, `live_scanner/mock_adapter.py`
- **Modified**: `app/utils/session.py`, `live_scanner/bar_aggregator.py`, `live_scanner/publisher.py`, `live_scanner/main.py`
- **New tests**: `tests/services/test_session_utils.py`, `tests/live_scanner/` (4 test files)
- `_connect_ib` (retry logic) moves into `ibkr_adapter.py` as `create_adapter()` factory — the only way to eliminate all ib_insync imports from `main.py` while preserving retry logic. **Intentional spec deviation**: the spec's Assumptions state "connection management stays in `main.py`", but that assumption is incompatible with Req 8 ("all direct ib_insync imports are eliminated from `main.py`"). Moving `_connect_ib` to `ibkr_adapter.py` satisfies both requirements; the factory pattern preserves the retry logic unchanged.
- `bar_subs`/`mkt_subs` dicts move inside `IBKRLiveAdapter`; `_sync_loop` uses a `subscribed: set` instead
- `_valid_price` helper moves to `ibkr_adapter.py` (only used in subscription callbacks)

## Tech Stack

Backend only: Python 3.11+, pytest, ib_insync (isolated to `ibkr_adapter.py` after this PR)

## File Structure

| Path | Change |
|------|--------|
| `backend/app/utils/session.py` | Add `session_for_ts`, `session_total_minutes`; rewrite `classify_session` as fixed shim |
| `backend/live_scanner/provider.py` | **New** — `LiveDataProvider` Protocol + `BarCallback`/`QuoteCallback` types |
| `backend/live_scanner/mock_adapter.py` | **New** — `MockLiveAdapter` stub |
| `backend/live_scanner/ibkr_adapter.py` | **New** — `IBKRLiveAdapter`, `create_adapter()` factory, `_connect_ib` retry loop |
| `backend/live_scanner/bar_aggregator.py` | Remove local `session_for_ts`/`session_total_minutes`; import from `app.utils.session` |
| `backend/live_scanner/publisher.py` | Replace `create_engine`/`db_url` with `SessionLocal`; remove engine param |
| `backend/live_scanner/main.py` | Accept `LiveDataProvider`; eliminate all ib_insync imports; thin coordinator |
| `backend/tests/services/test_session_utils.py` | **New** — session utility tests |
| `backend/tests/live_scanner/__init__.py` | **New** — package init |
| `backend/tests/live_scanner/test_bar_aggregator_imports.py` | **New** — confirm no local redefinition |
| `backend/tests/live_scanner/test_provider.py` | **New** — Protocol structural compliance |
| `backend/tests/live_scanner/test_mock_adapter.py` | **New** — MockLiveAdapter tests |
| `backend/tests/live_scanner/test_ibkr_adapter.py` | **New** — IBKRLiveAdapter unit tests (mocked IB) |
| `backend/tests/live_scanner/test_publisher.py` | **New** — publisher no longer requires db_url |
| `backend/tests/live_scanner/test_main_imports.py` | **New** — AST check: no Stock/ContFuture/util in main.py |

---

## Tasks

### Task 1 — Extend `app/utils/session.py` with canonical session detection

**Files**: `backend/app/utils/session.py`, `backend/tests/services/test_session_utils.py`

**Step 1a — Write failing tests**

Create `backend/tests/services/test_session_utils.py`:

```python
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import pytest

ET = ZoneInfo("America/New_York")


def _et(h, m=0):
    """UTC datetime corresponding to hour:minute in ET on a known EDT date (2026-05-26)."""
    return datetime(2026, 5, 26, h, m, tzinfo=ET).astimezone(timezone.utc)


class TestSessionForTs:
    def test_pre_market_mid(self):
        from app.utils.session import session_for_ts
        assert session_for_ts(_et(6)) == "pre"

    def test_pre_market_boundary_open(self):
        from app.utils.session import session_for_ts
        assert session_for_ts(_et(4, 0)) == "pre"

    def test_pre_market_boundary_close(self):
        from app.utils.session import session_for_ts
        assert session_for_ts(_et(9, 29)) == "pre"

    def test_regular_open(self):
        from app.utils.session import session_for_ts
        assert session_for_ts(_et(9, 30)) == "regular"

    def test_regular_mid(self):
        from app.utils.session import session_for_ts
        assert session_for_ts(_et(12, 0)) == "regular"

    def test_regular_boundary_close(self):
        from app.utils.session import session_for_ts
        assert session_for_ts(_et(15, 59)) == "regular"

    def test_post_starts_at_1600(self):
        from app.utils.session import session_for_ts
        assert session_for_ts(_et(16, 0)) == "post"

    def test_post_mid(self):
        from app.utils.session import session_for_ts
        assert session_for_ts(_et(17, 30)) == "post"

    def test_closed_overnight(self):
        from app.utils.session import session_for_ts
        assert session_for_ts(_et(2, 0)) == "closed"

    def test_naive_datetime_treated_as_utc(self):
        from app.utils.session import session_for_ts
        # 13:00 UTC = 9:00 ET on 2026-05-26 → pre-market
        naive = datetime(2026, 5, 26, 13, 0)
        assert session_for_ts(naive) == "pre"


class TestSessionTotalMinutes:
    def test_pre(self):
        from app.utils.session import session_total_minutes
        assert session_total_minutes("pre") == 330.0   # 4:00–9:30

    def test_regular(self):
        from app.utils.session import session_total_minutes
        assert session_total_minutes("regular") == 390.0

    def test_post(self):
        from app.utils.session import session_total_minutes
        assert session_total_minutes("post") == 240.0  # 16:00–20:00

    def test_unknown_falls_back_to_regular(self):
        from app.utils.session import session_total_minutes
        assert session_total_minutes("closed") == 390.0


class TestClassifySessionShim:
    def test_pre_market(self):
        from app.utils.session import classify_session
        is_pre, is_post = classify_session(_et(6))
        assert is_pre is True and is_post is False

    def test_regular(self):
        from app.utils.session import classify_session
        is_pre, is_post = classify_session(_et(12))
        assert is_pre is False and is_post is False

    def test_post_at_1600_exact(self):
        from app.utils.session import classify_session
        # Bug fix: 16:00 ET must be post, not missed (old code used m >= 1)
        is_pre, is_post = classify_session(_et(16, 0))
        assert is_pre is False and is_post is True
```

**Step 1b — Verify tests fail**

```bash
cd backend && python -m pytest tests/services/test_session_utils.py -v 2>&1 | tail -10
# Expected: ImportError — cannot import name 'session_for_ts' from 'app.utils.session'
```

**Step 1c — Implement**

Replace the full contents of `backend/app/utils/session.py` with:

```python
"""Trading session classification utilities."""

from datetime import datetime, date, timezone
from zoneinfo import ZoneInfo

_ET = ZoneInfo("America/New_York")

_SESSIONS = [
    ("pre",     4 * 60,       9 * 60 + 30),
    ("regular", 9 * 60 + 30,  16 * 60),
    ("post",    16 * 60,       20 * 60),
]


def session_for_ts(ts: datetime) -> str:
    """Return 'pre', 'regular', 'post', or 'closed' for a UTC or timezone-aware timestamp."""
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    et = ts.astimezone(_ET)
    m = et.hour * 60 + et.minute
    for name, start, end in _SESSIONS:
        if start <= m < end:
            return name
    return "closed"


def session_total_minutes(session: str) -> float:
    """Total minutes in a named session (pre=330, regular=390, post=240)."""
    for name, start, end in _SESSIONS:
        if name == session:
            return float(end - start)
    return 390.0


def classify_session(ts_utc: datetime) -> tuple[bool, bool]:
    """Deprecated. Use session_for_ts() instead. Returns (is_pre, is_post)."""
    session = session_for_ts(ts_utc)
    return session == "pre", session == "post"


def get_market_now() -> datetime:
    """Return the current time in America/New_York."""
    return datetime.now(_ET)


def get_market_today() -> date:
    """Return the current date in America/New_York."""
    return get_market_now().date()
```

**Step 1d — Verify tests pass**

```bash
cd backend && python -m pytest tests/services/test_session_utils.py -v 2>&1 | tail -10
# Expected: 15 passed
```

**Step 1e — Run full suite to confirm no regressions in classify_session callers**

```bash
cd backend && python -m pytest -x -q 2>&1 | tail -20
# Expected: all existing tests pass
```

**Step 1f — Commit**

```bash
git add backend/app/utils/session.py backend/tests/services/test_session_utils.py
git commit -m "feat(session): add session_for_ts/session_total_minutes; fix classify_session 16:00 boundary"
```

---

### Task 2 — Update `bar_aggregator.py` to import from `app.utils.session`

**Files**: `backend/live_scanner/bar_aggregator.py`, `backend/tests/live_scanner/__init__.py`, `backend/tests/live_scanner/test_bar_aggregator_imports.py`

**Step 2a — Write failing test**

Create `backend/tests/live_scanner/__init__.py` (empty file).

Create `backend/tests/live_scanner/test_bar_aggregator_imports.py`:

```python
import live_scanner.bar_aggregator as mod
import app.utils.session as session_mod


def test_session_for_ts_is_from_app_utils():
    """bar_aggregator must use app.utils.session.session_for_ts, not define its own."""
    assert mod.session_for_ts is session_mod.session_for_ts


def test_session_total_minutes_is_from_app_utils():
    assert mod.session_total_minutes is session_mod.session_total_minutes
```

```bash
cd backend && python -m pytest tests/live_scanner/test_bar_aggregator_imports.py -v 2>&1 | tail -10
# Expected: FAILED — bar_aggregator defines its own copies (different function objects)
```

**Step 2b — Implement**

Edit `backend/live_scanner/bar_aggregator.py`. Remove the following three code blocks (match by content, not line numbers):

Remove the `_SESSIONS` constant:
```python
# Session windows expressed as (name, start_minute, end_minute) in ET minutes-from-midnight
_SESSIONS = [
    ("pre",     4 * 60,      9 * 60 + 30),
    ("regular", 9 * 60 + 30, 16 * 60),
    ("post",    16 * 60,     20 * 60),
]
```

Remove `session_for_ts()`:
```python
def session_for_ts(ts: datetime) -> str:
    """Return the trading session name for a UTC timestamp."""
    et = ts.astimezone(ET)
    m = et.hour * 60 + et.minute
    for name, start, end in _SESSIONS:
        if start <= m < end:
            return name
    return "closed"
```

Remove `session_total_minutes()`:
```python
def session_total_minutes(session: str) -> float:
    """Total minutes in a session (used to project full-session volume)."""
    for name, start, end in _SESSIONS:
        if name == session:
            return float(end - start)
    return 390.0  # fallback to regular session length
```

Add this import after the existing stdlib imports:

```python
from app.utils.session import session_for_ts, session_total_minutes
```

Keep `ET = ZoneInfo("America/New_York")` — it is re-exported and used by `publisher.py` via
`from live_scanner.bar_aggregator import MinuteBar, ET`.

The import block at the top of bar_aggregator.py becomes:

```python
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional
from zoneinfo import ZoneInfo

from app.utils.session import session_for_ts, session_total_minutes

ET = ZoneInfo("America/New_York")
```

`conditions.py` imports `session_total_minutes` from `bar_aggregator` — this continues to work
because the imported name is now in `bar_aggregator`'s module namespace. No change to `conditions.py`.

**Step 2c — Verify**

```bash
cd backend && python -m pytest tests/live_scanner/test_bar_aggregator_imports.py -v 2>&1 | tail -10
# Expected: 2 passed

cd backend && python -m pytest -x -q 2>&1 | tail -20
# Expected: all existing tests pass
```

**Step 2d — Commit**

```bash
git add backend/live_scanner/bar_aggregator.py \
        backend/tests/live_scanner/__init__.py \
        backend/tests/live_scanner/test_bar_aggregator_imports.py
git commit -m "refactor(bar_aggregator): import session_for_ts/session_total_minutes from app.utils.session"
```

---

### Task 3 — Create `live_scanner/provider.py` with `LiveDataProvider` Protocol

**Files**: `backend/live_scanner/provider.py`, `backend/tests/live_scanner/test_provider.py`

**Step 3a — Write failing test**

Create `backend/tests/live_scanner/test_provider.py`:

```python
import inspect
import pytest


def test_module_exports_protocol_and_callbacks():
    from live_scanner.provider import LiveDataProvider, BarCallback, QuoteCallback
    assert LiveDataProvider is not None
    assert BarCallback is not None
    assert QuoteCallback is not None


def test_protocol_has_required_methods():
    from live_scanner.provider import LiveDataProvider
    required = {"fetch_seed_data", "subscribe", "unsubscribe", "disconnect"}
    members = {name for name, _ in inspect.getmembers(LiveDataProvider)}
    assert required <= members


def test_conforming_class_is_structurally_compatible():
    from live_scanner.provider import BarCallback, QuoteCallback

    class MinimalAdapter:
        async def fetch_seed_data(self, symbol: str, security_type: str, exchange: str):
            return 0.0, 0.0

        async def subscribe(self, symbol, security_type, exchange,
                            on_bar: BarCallback, on_quote: QuoteCallback):
            pass

        async def unsubscribe(self, symbol: str):
            pass

        async def disconnect(self):
            pass

    # Verify each method is present and async
    adapter = MinimalAdapter()
    for method_name in ("fetch_seed_data", "subscribe", "unsubscribe", "disconnect"):
        method = getattr(adapter, method_name)
        assert inspect.iscoroutinefunction(method), f"{method_name} must be async"
```

```bash
cd backend && python -m pytest tests/live_scanner/test_provider.py -v 2>&1 | tail -10
# Expected: ERROR — no module 'live_scanner.provider'
```

**Step 3b — Implement**

Create `backend/live_scanner/provider.py`:

```python
from typing import Callable, Awaitable, Protocol

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

**Step 3c — Verify**

```bash
cd backend && python -m pytest tests/live_scanner/test_provider.py -v 2>&1 | tail -10
# Expected: 3 passed
```

**Step 3d — Commit**

```bash
git add backend/live_scanner/provider.py backend/tests/live_scanner/test_provider.py
git commit -m "feat(live_scanner): add LiveDataProvider Protocol"
```

---

### Task 4 — Create `live_scanner/mock_adapter.py` with `MockLiveAdapter`

**Files**: `backend/live_scanner/mock_adapter.py`, `backend/tests/live_scanner/test_mock_adapter.py`

**Step 4a — Write failing tests**

Create `backend/tests/live_scanner/test_mock_adapter.py`:

```python
import asyncio
import pytest


@pytest.mark.asyncio
async def test_fetch_seed_data_returns_fixed_defaults():
    from live_scanner.mock_adapter import MockLiveAdapter
    adapter = MockLiveAdapter()
    prior_close, avg_vol = await adapter.fetch_seed_data("AAPL", "STK", "SMART")
    assert prior_close == 100.0
    assert avg_vol == 500_000.0


@pytest.mark.asyncio
async def test_subscribe_accepts_without_emitting_events():
    from live_scanner.mock_adapter import MockLiveAdapter
    adapter = MockLiveAdapter()
    events = []

    async def on_bar(symbol, bar):
        events.append(("bar", symbol))

    async def on_quote(symbol, quote):
        events.append(("quote", symbol))

    await adapter.subscribe("AAPL", "STK", "SMART", on_bar, on_quote)
    assert events == []


@pytest.mark.asyncio
async def test_unsubscribe_is_a_no_op():
    from live_scanner.mock_adapter import MockLiveAdapter
    adapter = MockLiveAdapter()
    await adapter.subscribe("AAPL", "STK", "SMART", lambda *a: None, lambda *a: None)
    await adapter.unsubscribe("AAPL")  # must not raise


@pytest.mark.asyncio
async def test_disconnect_is_a_no_op():
    from live_scanner.mock_adapter import MockLiveAdapter
    adapter = MockLiveAdapter()
    await adapter.disconnect()  # must not raise


def test_mock_adapter_has_all_protocol_methods():
    import inspect
    from live_scanner.mock_adapter import MockLiveAdapter
    required = {"fetch_seed_data", "subscribe", "unsubscribe", "disconnect"}
    for name in required:
        method = getattr(MockLiveAdapter, name)
        assert inspect.iscoroutinefunction(method), f"{name} must be async"
```

```bash
cd backend && python -m pytest tests/live_scanner/test_mock_adapter.py -v 2>&1 | tail -10
# Expected: ERROR — no module 'live_scanner.mock_adapter'
```

**Step 4b — Implement**

Create `backend/live_scanner/mock_adapter.py`:

```python
from live_scanner.provider import BarCallback, QuoteCallback


class MockLiveAdapter:
    """Minimal no-op adapter — satisfies LiveDataProvider for tests without IBKR."""

    async def fetch_seed_data(
        self, symbol: str, security_type: str, exchange: str
    ) -> tuple[float, float]:
        return 100.0, 500_000.0

    async def subscribe(
        self,
        symbol: str,
        security_type: str,
        exchange: str,
        on_bar: BarCallback,
        on_quote: QuoteCallback,
    ) -> None:
        pass

    async def unsubscribe(self, symbol: str) -> None:
        pass

    async def disconnect(self) -> None:
        pass
```

**Step 4c — Verify**

```bash
cd backend && python -m pytest tests/live_scanner/test_mock_adapter.py -v 2>&1 | tail -10
# Expected: 5 passed
```

**Step 4d — Commit**

```bash
git add backend/live_scanner/mock_adapter.py backend/tests/live_scanner/test_mock_adapter.py
git commit -m "feat(live_scanner): add MockLiveAdapter for IBKR-free testing"
```

---

### Task 5 — Create `live_scanner/ibkr_adapter.py` with `IBKRLiveAdapter`

Extracts all IBKR-specific code from `main.py` including the connection retry logic. `main.py` will have zero ib_insync imports after Task 7.

**Files**: `backend/live_scanner/ibkr_adapter.py`, `backend/tests/live_scanner/test_ibkr_adapter.py`

**Step 5a — Write failing tests**

Create `backend/tests/live_scanner/test_ibkr_adapter.py`:

```python
import asyncio
from unittest.mock import AsyncMock, MagicMock
import pytest


def _make_ib(connected=True):
    ib = MagicMock()
    ib.isConnected.return_value = connected
    return ib


@pytest.mark.asyncio
async def test_fetch_seed_data_returns_prior_close_and_avg_volume():
    from live_scanner.ibkr_adapter import IBKRLiveAdapter
    ib = _make_ib()
    bar1 = MagicMock(); bar1.close = 150.0; bar1.volume = 1_000_000
    bar2 = MagicMock(); bar2.close = 152.0; bar2.volume = 1_200_000
    qualified = MagicMock()
    ib.qualifyContractsAsync = AsyncMock(return_value=[qualified])
    ib.reqHistoricalDataAsync = AsyncMock(return_value=[bar1, bar2])

    adapter = IBKRLiveAdapter(ib)
    prior_close, avg_vol = await adapter.fetch_seed_data("AAPL", "STK", "SMART")

    assert prior_close == 152.0
    assert avg_vol == pytest.approx(1_100_000.0)


@pytest.mark.asyncio
async def test_fetch_seed_data_returns_zeros_on_empty_bars():
    from live_scanner.ibkr_adapter import IBKRLiveAdapter
    ib = _make_ib()
    qualified = MagicMock()
    ib.qualifyContractsAsync = AsyncMock(return_value=[qualified])
    ib.reqHistoricalDataAsync = AsyncMock(return_value=[])

    adapter = IBKRLiveAdapter(ib)
    prior_close, avg_vol = await adapter.fetch_seed_data("AAPL", "STK", "SMART")

    assert prior_close == 0.0 and avg_vol == 0.0


@pytest.mark.asyncio
async def test_subscribe_calls_reqRealTimeBars_and_reqMktData():
    from live_scanner.ibkr_adapter import IBKRLiveAdapter
    ib = _make_ib()
    qualified = MagicMock()
    ib.qualifyContractsAsync = AsyncMock(return_value=[qualified])
    ib.reqHistoricalDataAsync = AsyncMock(return_value=[])

    bar_list = MagicMock(); bar_list.updateEvent = MagicMock()
    ticker = MagicMock(); ticker.updateEvent = MagicMock()
    ib.reqRealTimeBars.return_value = bar_list
    ib.reqMktData.return_value = ticker

    adapter = IBKRLiveAdapter(ib)
    await adapter.subscribe("AAPL", "STK", "SMART", AsyncMock(), AsyncMock())

    ib.reqRealTimeBars.assert_called_once()
    ib.reqMktData.assert_called_once()


@pytest.mark.asyncio
async def test_subscribe_skips_when_not_connected():
    from live_scanner.ibkr_adapter import IBKRLiveAdapter
    ib = _make_ib(connected=False)
    adapter = IBKRLiveAdapter(ib)
    await adapter.subscribe("AAPL", "STK", "SMART", AsyncMock(), AsyncMock())
    ib.reqRealTimeBars.assert_not_called()


@pytest.mark.asyncio
async def test_unsubscribe_cancels_both_subscriptions():
    from live_scanner.ibkr_adapter import IBKRLiveAdapter
    ib = _make_ib()
    qualified = MagicMock()
    ib.qualifyContractsAsync = AsyncMock(return_value=[qualified])
    ib.reqHistoricalDataAsync = AsyncMock(return_value=[])
    bar_list = MagicMock(); bar_list.updateEvent = MagicMock()
    ticker = MagicMock(); ticker.updateEvent = MagicMock()
    ib.reqRealTimeBars.return_value = bar_list
    ib.reqMktData.return_value = ticker

    adapter = IBKRLiveAdapter(ib)
    await adapter.subscribe("AAPL", "STK", "SMART", AsyncMock(), AsyncMock())
    await adapter.unsubscribe("AAPL")

    ib.cancelRealTimeBars.assert_called_once_with(bar_list)
    ib.cancelMktData.assert_called_once_with(ticker)


@pytest.mark.asyncio
async def test_unsubscribe_unknown_symbol_is_noop():
    from live_scanner.ibkr_adapter import IBKRLiveAdapter
    adapter = IBKRLiveAdapter(_make_ib())
    await adapter.unsubscribe("UNKNOWN")  # must not raise


@pytest.mark.asyncio
async def test_disconnect_calls_ib_disconnect():
    from live_scanner.ibkr_adapter import IBKRLiveAdapter
    ib = _make_ib()
    adapter = IBKRLiveAdapter(ib)
    await adapter.disconnect()
    ib.disconnect.assert_called_once()
```

```bash
cd backend && python -m pytest tests/live_scanner/test_ibkr_adapter.py -v 2>&1 | tail -15
# Expected: ERROR — no module 'live_scanner.ibkr_adapter'
```

**Step 5b — Implement**

Create `backend/live_scanner/ibkr_adapter.py`:

```python
"""
IBKRLiveAdapter — wraps ib_insync behind the LiveDataProvider Protocol.

All ib_insync imports are confined to this module.
main.py has zero ib_insync imports and calls create_adapter() to get a connected adapter.
"""

import asyncio
import logging
import math
from datetime import datetime, timezone
from typing import Any

from ib_insync import IB, ContFuture, Stock, util

from app.core.config import settings
from live_scanner.provider import BarCallback, QuoteCallback

logger = logging.getLogger(__name__)

HISTORY_DURATION = "10 D"
MAX_CONNECT_RETRIES = 10
RECONNECT_BASE_DELAY = 5   # seconds; doubles per attempt, capped at 60 s


# ── Public factory ─────────────────────────────────────────────────────────


async def create_adapter(
    host: str, port: int, client_id: int
) -> "IBKRLiveAdapter | None":
    """
    Create and connect an IBKRLiveAdapter with exponential-backoff retry.
    Returns None when all retries are exhausted.
    """
    util.patchAsyncio()
    ib = IB()
    ib.disconnectedEvent += lambda: logger.warning(
        "IB Gateway disconnected — will retry subscriptions on next sync cycle"
    )
    if await _connect_ib(ib, host, port, client_id):
        return IBKRLiveAdapter(ib)
    return None


# ── Adapter ────────────────────────────────────────────────────────────────


class IBKRLiveAdapter:
    """
    Implements LiveDataProvider for an ib_insync IB connection.
    Receives a pre-connected IB instance; does not own connection lifecycle.
    """

    def __init__(self, ib: IB) -> None:
        self._ib = ib
        self._bar_subs: dict[str, Any] = {}
        self._mkt_subs: dict[str, Any] = {}

    async def fetch_seed_data(
        self, symbol: str, security_type: str, exchange: str
    ) -> tuple[float, float]:
        """Qualify contract and return (prior_close, avg_daily_volume). (0.0, 0.0) on failure."""
        contract = _build_contract(symbol, security_type, exchange)
        qualified = await _qualify_contract(self._ib, contract, symbol)
        if qualified is None:
            return 0.0, 0.0
        return await _fetch_prior_data(self._ib, qualified, symbol)

    async def subscribe(
        self,
        symbol: str,
        security_type: str,
        exchange: str,
        on_bar: BarCallback,
        on_quote: QuoteCallback,
    ) -> None:
        if not self._ib.isConnected():
            logger.warning(f"IBKRLiveAdapter.subscribe: not connected — skipping {symbol}")
            return

        contract = _build_contract(symbol, security_type, exchange)
        qualified = await _qualify_contract(self._ib, contract, symbol)
        if qualified is None:
            logger.warning(f"IBKRLiveAdapter.subscribe: could not qualify {symbol} — skipping")
            return

        loop = asyncio.get_running_loop()

        def _ib_on_bar(bars, hasNewBar):
            if hasNewBar and bars:
                loop.create_task(on_bar(symbol, bars[-1]))

        bar_list = self._ib.reqRealTimeBars(
            qualified, barSize=5, whatToShow="TRADES", useRTH=False
        )
        bar_list.updateEvent += _ib_on_bar
        self._bar_subs[symbol] = bar_list

        _last_price: list = [0.0]

        def _ib_on_ticker(ticker):
            last = ticker.last
            if not _valid_price(last) or last == _last_price[0]:
                return
            _last_price[0] = last
            loop.create_task(on_quote(symbol, {
                "last": last,
                "bid":  ticker.bid if _valid_price(ticker.bid)  else None,
                "ask":  ticker.ask if _valid_price(ticker.ask)  else None,
                "time": int(datetime.now(timezone.utc).timestamp()),
            }))

        ticker = self._ib.reqMktData(
            qualified, genericTickList="", snapshot=False, regulatorySnapshot=False
        )
        ticker.updateEvent += _ib_on_ticker
        self._mkt_subs[symbol] = ticker

        logger.info(f"IBKRLiveAdapter: subscribed {symbol}")

    async def unsubscribe(self, symbol: str) -> None:
        bar_list = self._bar_subs.pop(symbol, None)
        if bar_list is not None:
            self._ib.cancelRealTimeBars(bar_list)

        ticker = self._mkt_subs.pop(symbol, None)
        if ticker is not None:
            self._ib.cancelMktData(ticker)

        logger.info(f"IBKRLiveAdapter: unsubscribed {symbol}")

    async def disconnect(self) -> None:
        if self._ib.isConnected():
            self._ib.disconnect()


# ── Connection helpers (package-private) ───────────────────────────────────


async def _connect_ib(ib: IB, host: str, port: int, client_id: int) -> bool:
    for attempt in range(MAX_CONNECT_RETRIES):
        _errors: list = []

        def _on_error(reqId, errorCode, errorString, contract):
            logger.warning(f"IB error {errorCode} (reqId={reqId}): {errorString}")
            _errors.append(errorCode)

        ib.errorEvent += _on_error
        try:
            await ib.connectAsync(host=host, port=port, clientId=client_id, timeout=30)
            await asyncio.sleep(0.5)
            if ib.isConnected():
                logger.info(
                    f"Connected to IB Gateway at {host}:{port} (clientId={client_id})"
                )
                return True
            reason = f"error {_errors[-1]}" if _errors else "unknown (clientId may be in use)"
            raise ConnectionError(f"Connection rejected — {reason}")
        except Exception as e:
            delay = min(RECONNECT_BASE_DELAY * (2 ** attempt), 60)
            logger.warning(
                f"Connection attempt {attempt + 1}/{MAX_CONNECT_RETRIES} failed: {e}. "
                f"Retrying in {delay}s…"
            )
            await asyncio.sleep(delay)

    logger.error("Exhausted all connection retries.")
    return False


def _build_contract(symbol: str, security_type: str, exchange: str):
    if security_type == "FUT":
        return ContFuture(symbol=symbol, exchange=exchange, currency="USD")
    return Stock(symbol, "SMART", "USD")


async def _qualify_contract(ib: IB, contract, symbol: str):
    try:
        qualified = await asyncio.wait_for(
            ib.qualifyContractsAsync(contract), timeout=30
        )
        return qualified[0] if qualified else None
    except Exception as e:
        logger.warning(f"_qualify_contract failed for {symbol}: {e}")
        return None


async def _fetch_prior_data(ib: IB, contract, symbol: str) -> tuple[float, float]:
    try:
        bars = await asyncio.wait_for(
            ib.reqHistoricalDataAsync(
                contract,
                endDateTime="",
                durationStr=HISTORY_DURATION,
                barSizeSetting="1 day",
                whatToShow="TRADES",
                useRTH=True,
                formatDate=1,
                keepUpToDate=False,
            ),
            timeout=30,
        )
    except Exception as e:
        logger.warning(f"_fetch_prior_data failed for {symbol}: {e}")
        return 0.0, 0.0

    if not bars:
        return 0.0, 0.0

    prior_close = float(bars[-1].close)
    volumes = [int(b.volume) for b in bars if int(b.volume) > 0]
    avg_vol = sum(volumes) / len(volumes) if volumes else 0.0
    return prior_close, avg_vol


def _valid_price(p) -> bool:
    try:
        return p is not None and not math.isnan(p) and p > 0
    except TypeError:
        return False
```

**Note on `util.patchAsyncio()`**: `create_adapter()` calls `util.patchAsyncio()` as its first action. After Task 7, `run()` must NOT call `util.patchAsyncio()` directly — it is called inside `create_adapter()` only when the IBKR path is taken. The `MockLiveAdapter` test path never calls `create_adapter()`, so `util.patchAsyncio()` is never called in tests (correct — tests should not patch asyncio).

**Step 5c — Verify**

```bash
cd backend && python -m pytest tests/live_scanner/test_ibkr_adapter.py -v 2>&1 | tail -15
# Expected: 7 passed
```

**Step 5d — Commit**

```bash
git add backend/live_scanner/ibkr_adapter.py backend/tests/live_scanner/test_ibkr_adapter.py
git commit -m "feat(live_scanner): add IBKRLiveAdapter and create_adapter factory; consolidate IBKR code"
```

---

### Task 6 — Update `publisher.py` to use `SessionLocal`

**Files**: `backend/live_scanner/publisher.py`, `backend/tests/live_scanner/test_publisher.py`

**Step 6a — Write failing tests**

Create `backend/tests/live_scanner/test_publisher.py`:

```python
import inspect
import pytest


def test_publisher_constructor_has_no_db_url_param():
    from live_scanner.publisher import LivePublisher
    sig = inspect.signature(LivePublisher.__init__)
    assert "db_url" not in sig.parameters, \
        "db_url must be removed from LivePublisher.__init__ — use SessionLocal instead"


def test_publisher_module_uses_session_local_not_create_engine():
    import live_scanner.publisher as pub_mod
    source = inspect.getsource(pub_mod)
    assert "create_engine" not in source, \
        "publisher.py must not call create_engine — use SessionLocal from app.core.database"
    assert "SessionLocal" in source, \
        "publisher.py must import and use SessionLocal"
    assert "from sqlalchemy.orm import Session" not in source, \
        "publisher.py must not import Session from sqlalchemy.orm — it uses SessionLocal() directly"
```

```bash
cd backend && python -m pytest tests/live_scanner/test_publisher.py -v 2>&1 | tail -10
# Expected: 2 FAILED — db_url still present, create_engine still used
```

**Step 6b — Implement**

Edit `backend/live_scanner/publisher.py`:

1. **Replace imports** — remove both `from sqlalchemy import create_engine` and `from sqlalchemy.orm import Session`; add `from app.core.database import SessionLocal`

2. **Change `__init__`** — remove `db_url: str` param and `self._engine = create_engine(...)`:

```python
class LivePublisher:
    def __init__(self, redis_url: str):
        self._redis_url = redis_url
        self._redis: aioredis.Redis | None = None
```

3. **Change `close()`** — remove `self._engine.dispose()` (disposing the shared `SessionLocal` engine from `app.core.database` would break other threads; the publisher must not own that engine):

```python
async def close(self):
    if self._redis:
        await self._redis.aclose()
    # Note: no engine.dispose() — SessionLocal engine is owned by app.core.database
```

4. **Replace all `Session(self._engine)` with `SessionLocal()`** in `_write_scanner_event` (two occurrences):

```python
def _write_scanner_event(self, bar, condition, summary, severity):
    today = bar.minute_ts.astimezone(ET).date()
    score = None
    try:
        with SessionLocal() as cfg_session:
            ranker_cfg = load_ranker_config(cfg_session)
        if ranker_cfg.get("enabled") and ranker_cfg.get("weights"):
            score = compute_signal_quality_score(condition.indicators, ranker_cfg["weights"])
    except Exception:
        logger.debug("LivePublisher: signal ranker config load failed — scoring skipped")

    event = ScannerEvent(
        uuid=uuid_module.uuid4(),
        ticker=bar.symbol,
        event_date=today,
        scanner_type=condition.scanner_type,
        summary=summary,
        severity=severity,
        previous_close=bar.prior_close if bar.prior_close > 0 else None,
        closing_price=bar.close,
        indicators=condition.indicators,
        criteria_met=condition.criteria_met,
        metadata_={"source": "live_scanner", "session": bar.session},
        signal_quality_score=score,
    )

    with SessionLocal() as session:
        try:
            session.add(event)
            session.commit()
            session.refresh(event)
            logger.debug(
                f"LivePublisher: ScannerEvent created — "
                f"{bar.symbol} {condition.scanner_type} {today}"
            )
            return event.id
        except IntegrityError:
            session.rollback()
            logger.debug(
                f"LivePublisher: ScannerEvent already exists for "
                f"{bar.symbol} {condition.scanner_type} {today} — skipping"
            )
            return None
```

**Step 6c — Verify**

```bash
cd backend && python -m pytest tests/live_scanner/test_publisher.py -v 2>&1 | tail -10
# Expected: 2 passed
```

**Step 6d — Commit**

```bash
git add backend/live_scanner/publisher.py backend/tests/live_scanner/test_publisher.py
git commit -m "refactor(publisher): replace custom SQLAlchemy engine with SessionLocal from app.core.database"
```

---

### Task 7 — Refactor `main.py` to accept `LiveDataProvider`, eliminate ib_insync imports

**Files**: `backend/live_scanner/main.py`, `backend/tests/live_scanner/test_main_imports.py`

**Step 7a — Write failing test**

Create `backend/tests/live_scanner/test_main_imports.py`:

```python
import ast
import pathlib


def _parse_main():
    path = pathlib.Path(__file__).parent.parent.parent / "live_scanner" / "main.py"
    return ast.parse(path.read_text()), path


def test_main_has_no_ib_insync_imports():
    """main.py must have zero ib_insync imports — all IBKR code lives in ibkr_adapter.py."""
    tree, _ = _parse_main()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "ib_insync":
            imported = [alias.name for alias in node.names]
            assert False, f"main.py must not import from ib_insync; found: {imported}"
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name != "ib_insync", \
                    "main.py must not import ib_insync directly"


def test_run_accepts_provider_parameter():
    """run() must accept an optional provider argument for testing with MockLiveAdapter."""
    tree, _ = _parse_main()
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "run":
            args = [a.arg for a in node.args.args] + [a.arg for a in node.args.kwonlyargs]
            defaults = node.args.defaults + node.args.kw_defaults
            assert "provider" in args, "run() must have a 'provider' parameter"
            # provider must have a default (None) so it's optional
            assert len(defaults) >= 1, "run(provider) must have a default value (None)"
            return
    assert False, "run() function not found in main.py"


def test_run_does_not_reference_database_url():
    """After publisher.py no longer takes db_url, main.py must not pass DATABASE_URL."""
    src_path = pathlib.Path(__file__).parent.parent.parent / "live_scanner" / "main.py"
    source = src_path.read_text()
    assert "DATABASE_URL" not in source, \
        "main.py must not pass DATABASE_URL — LivePublisher no longer accepts it"
```

```bash
cd backend && python -m pytest tests/live_scanner/test_main_imports.py -v 2>&1 | tail -10
# Expected: FAILED — ib_insync imports (IB, Stock, ContFuture, util) found in main.py
```

**Step 7b — Implement**

Rewrite `backend/live_scanner/main.py` to the following. The key structural changes are:

- Remove all ib_insync imports
- Import `IBKRLiveAdapter`, `create_adapter`, `LiveDataProvider`
- `_subscribe` becomes a thin coordinator that delegates to the provider
- `_unsubscribe` delegates `provider.unsubscribe()`; removes aggregator
- `_sync_loop` uses `provider: LiveDataProvider` and a `subscribed: set` (replaces `bar_subs`/`mkt_subs` args)
- `_connect_ib` removed (now in `ibkr_adapter.py` as `create_adapter`)
- `run()` accepts `provider: LiveDataProvider | None = None`; creates `IBKRLiveAdapter` by default

```python
"""
Live Scanner — entry point.

Hybrid data model:
  - reqRealTimeBars (5 s)  → volume accumulation, OHLCV aggregation, alert logic
  - reqMktData             → sub-second last-price updates for the UI

Run as:
    python -m live_scanner.main
"""

import asyncio
import logging
import sys
from typing import Dict

from app.core.config import settings
from app.core.database import SessionLocal
from app.models.active_watchlist import ActiveWatchlist
from live_scanner.bar_aggregator import BarAggregator
from live_scanner.conditions import check_conditions
from live_scanner.ibkr_adapter import IBKRLiveAdapter, create_adapter
from live_scanner.provider import LiveDataProvider
from live_scanner.publisher import LivePublisher

# ── Logging ────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL, logging.INFO),
    format="%(asctime)s %(levelname)-8s %(name)s  %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("live_scanner")

# ── Constants ──────────────────────────────────────────────────────────────

LIVE_SCANNER_CLIENT_ID = 5
WATCHLIST_SYNC_INTERVAL = 30   # seconds between DB polls

# Queue message tags
TAG_BAR   = "bar"
TAG_QUOTE = "quote"


# ── DB helpers ─────────────────────────────────────────────────────────────

def _db_get_watchlist():
    db = SessionLocal()
    try:
        rows = db.query(ActiveWatchlist).all()
        return [
            {
                "symbol": r.symbol,
                "security_type": r.security_type or "STK",
                "exchange": r.exchange or (
                    "CME" if (r.security_type or "STK") == "FUT" else "SMART"
                ),
            }
            for r in rows
        ]
    finally:
        db.close()


# ── Subscription coordination ──────────────────────────────────────────────

async def _subscribe(
    provider: LiveDataProvider,
    item: Dict[str, str],
    aggregators: Dict[str, BarAggregator],
    queue: asyncio.Queue,
) -> None:
    symbol = item["symbol"]
    logger.info(f"Subscribing to {symbol} ({item['security_type']}:{item['exchange']})")

    prior_close, avg_vol = await provider.fetch_seed_data(
        symbol, item["security_type"], item["exchange"]
    )
    logger.info(f"{symbol}: prior_close={prior_close:.2f}, avg_daily_vol={avg_vol:.0f}")
    aggregators[symbol] = BarAggregator(symbol, prior_close, avg_vol)

    async def on_bar(sym: str, bar) -> None:
        queue.put_nowait((TAG_BAR, sym, bar))

    async def on_quote(sym: str, quote: dict) -> None:
        queue.put_nowait((TAG_QUOTE, sym, quote))

    await provider.subscribe(
        symbol, item["security_type"], item["exchange"],
        on_bar=on_bar, on_quote=on_quote,
    )
    logger.info(f"Real-time bars + market data active for {symbol}")


async def _unsubscribe(
    provider: LiveDataProvider,
    symbol: str,
    aggregators: Dict[str, BarAggregator],
) -> None:
    await provider.unsubscribe(symbol)
    aggregators.pop(symbol, None)
    logger.info(f"Unsubscribed {symbol}")


# ── Core loops ─────────────────────────────────────────────────────────────

async def _sync_loop(
    provider: LiveDataProvider,
    aggregators: Dict[str, BarAggregator],
    queue: asyncio.Queue,
    subscribed: set,
) -> None:
    """Periodically reconcile live subscriptions against the DB watchlist."""
    while True:
        try:
            watchlist = await asyncio.to_thread(_db_get_watchlist)
        except Exception as e:
            logger.error(f"DB watchlist fetch failed: {e}")
            await asyncio.sleep(WATCHLIST_SYNC_INTERVAL)
            continue

        current = {item["symbol"]: item for item in watchlist}

        for symbol in list(subscribed):
            if symbol not in current:
                await _unsubscribe(provider, symbol, aggregators)
                subscribed.discard(symbol)

        for symbol, item in current.items():
            if symbol not in subscribed:
                await _subscribe(provider, item, aggregators, queue)
                subscribed.add(symbol)

        await asyncio.sleep(WATCHLIST_SYNC_INTERVAL)


async def _process_loop(
    queue: asyncio.Queue,
    aggregators: Dict[str, BarAggregator],
    publisher: LivePublisher,
) -> None:
    """Drain the queue. Quotes → fast publish. Bars → aggregation + alerts."""
    while True:
        try:
            tag, symbol, data = await asyncio.wait_for(queue.get(), timeout=5.0)
        except asyncio.TimeoutError:
            continue

        if tag == TAG_QUOTE:
            try:
                await publisher.publish_quote(symbol, data)
            except Exception as e:
                logger.debug(f"publish_quote error for {symbol}: {e}")
            continue

        bar = data
        try:
            await publisher.publish_tick(symbol, bar)
        except Exception as e:
            logger.debug(f"publish_tick error for {symbol}: {e}")

        aggregator = aggregators.get(symbol)
        if aggregator is None:
            continue

        minute_bar = aggregator.update(bar)
        if minute_bar is None:
            continue

        try:
            await publisher.publish_minute_bar(symbol, minute_bar)
        except Exception as e:
            logger.debug(f"publish_minute_bar error for {symbol}: {e}")

        if minute_bar.session != "closed":
            try:
                for condition in check_conditions(minute_bar):
                    await publisher.fire_alert_if_new(minute_bar, condition)
            except Exception as e:
                logger.error(f"Condition/alert error for {symbol}: {e}")


# ── Main entry point ───────────────────────────────────────────────────────

async def run(provider: LiveDataProvider | None = None) -> None:
    publisher = LivePublisher(settings.REDIS_URL)
    await publisher.connect()

    if provider is None:
        provider = await create_adapter(
            settings.IBKR_HOST, settings.IBKR_PORT, LIVE_SCANNER_CLIENT_ID
        )
        if provider is None:
            await publisher.close()
            return

    aggregators: Dict[str, BarAggregator] = {}
    queue: asyncio.Queue = asyncio.Queue(maxsize=2000)
    subscribed: set = set()

    sync_task = asyncio.create_task(
        _sync_loop(provider, aggregators, queue, subscribed),
        name="watchlist-sync",
    )
    process_task = asyncio.create_task(
        _process_loop(queue, aggregators, publisher),
        name="bar-process",
    )

    logger.info("Live scanner started (hybrid: reqMktData + reqRealTimeBars)")

    try:
        await asyncio.gather(sync_task, process_task)
    except (asyncio.CancelledError, KeyboardInterrupt):
        logger.info("Live scanner shutting down…")
    except Exception as e:
        logger.error(f"Live scanner crashed: {e}", exc_info=True)
    finally:
        sync_task.cancel()
        process_task.cancel()
        await provider.disconnect()
        await publisher.close()
        logger.info("Live scanner stopped")


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
```

**Step 7c — Verify**

```bash
cd backend && python -m pytest tests/live_scanner/test_main_imports.py -v 2>&1 | tail -10
# Expected: 2 passed

cd backend && python -m pytest tests/live_scanner/ -v 2>&1 | tail -20
# Expected: all live_scanner tests pass

cd backend && python -m pytest -x -q 2>&1 | tail -20
# Expected: full suite passes
```

**Step 7d — Commit**

```bash
git add backend/live_scanner/main.py backend/tests/live_scanner/test_main_imports.py
git commit -m "refactor(main): accept LiveDataProvider; eliminate all ib_insync imports from main.py"
```

---

## Summary

| Task | Files Changed | Tests Added | Req Satisfied |
|------|--------------|-------------|---------------|
| 1 | `app/utils/session.py` | `test_session_utils.py` (15 cases) | Req 4, 5 |
| 2 | `bar_aggregator.py` | `test_bar_aggregator_imports.py` (2) | Req 7 |
| 3 | `live_scanner/provider.py` | `test_provider.py` (3) | Req 1 |
| 4 | `live_scanner/mock_adapter.py` | `test_mock_adapter.py` (5) | Req 3 |
| 5 | `live_scanner/ibkr_adapter.py` | `test_ibkr_adapter.py` (7) | Req 2 |
| 6 | `live_scanner/publisher.py` | `test_publisher.py` (2) | Req 6 |
| 7 | `live_scanner/main.py` | `test_main_imports.py` (2) | Req 8 |

**Total**: 7 tasks, 36 test cases
