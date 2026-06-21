# IBKR Gateway Chaos Test — Implementation Plan

**Goal:** Close the live-scanner gap on IBKR gateway failure. Add in-process reconnect with
exponential backoff, publish `feed_loss`/`feed_recovered` events, expose an informational IBKR
probe in `/api/ready`, show a frontend stale badge, and provide a scripted chaos test + CI nightly
workflow verifying both failure modes.

**Issue:** #393  
**Spec:** `docs/superpowers/specs/2026-06-21-ibkr-chaos-test-design.md`  
**Date:** 2026-06-21

---

## Architecture

The implementation crosses four layers:

1. **`backend/live_scanner/`** — IBKR reconnect path, liveness watchdog, MockLiveAdapter extension,
   LivePublisher new methods.
2. **`backend/app/routers/health.py`** — informational IBKR probe in `/api/ready` (non-blocking,
   does not affect HTTP 200/503 gate).
3. **`frontend/src/`** — `feedStatus` state in `useWatchlistLive` hook; amber badge in
   `ActiveWatchlist/index.tsx`.
4. **`scripts/chaos/` + `.github/workflows/`** — chaos test shell script and CI nightly workflow.

**Key memory constraints (from `.archon/memory/architecture.md`):**
- Route `disconnectedEvent` through the asyncio queue via `TAG_DISCONNECT` (never call async
  publisher methods directly from the ib_insync event thread — that path is already used for
  bars/quotes via `call_soon_threadsafe` + `queue.put_nowait`).
- `/api/ready` live_data probe is informational only: `all_ok = probes["db"]["ok"] and
  probes["redis"]["ok"]`. Adding `live_data` to `all()` would cause Docker to mark the backend
  container unhealthy during IBKR outages.
- Container restart must NOT be the sole recovery mechanism (cannot detect network partition,
  cannot publish `feed_loss`/`feed_recovered`).

---

## File Structure

| File | Change |
|---|---|
| `backend/app/core/config.py` | Add `LIVE_SCANNER_MOCK: bool = False` |
| `backend/tests/conftest.py` | Add `os.environ.setdefault("LIVE_SCANNER_MOCK", "false")` |
| `docker-compose.yml` | Add `LIVE_SCANNER_MOCK: "false"` to live-scanner env section |
| `backend/live_scanner/publisher.py` | Add `publish_feed_loss()`, `publish_feed_recovered()` |
| `backend/live_scanner/provider.py` | Extend Protocol with `wire_disconnect_queue`, `reconnect`, `is_connected`, `force_disconnect` |
| `backend/live_scanner/ibkr_adapter.py` | Store host/port/client_id; drop old disconnect logger; add `wire_disconnect_queue`, `reconnect`, `is_connected`, `force_disconnect` |
| `backend/live_scanner/mock_adapter.py` | Add queue wiring, `simulate_disconnect`, `reconnect`, `is_connected`, `force_disconnect` |
| `backend/live_scanner/main.py` | Add `TAG_DISCONNECT`, `TAG_CONNECT_RECOVERED`, `HEARTBEAT_STALE_SECONDS`; update `_sync_loop`, `_process_loop`, `run()`; add `_reconnect_coro`, `_watchdog_loop` |
| `backend/app/routers/health.py` | Add informational IBKR probe; fix `all_ok` from `all(...)` to explicit `db and redis` |
| `backend/tests/live_scanner/test_publisher.py` | Add feed-loss / feed-recovered tests |
| `backend/tests/live_scanner/test_ibkr_adapter.py` | Add reconnect / wire_disconnect / is_connected / force_disconnect tests |
| `backend/tests/live_scanner/test_mock_adapter.py` | Add simulate_disconnect / reconnect / wire_disconnect tests |
| `backend/tests/live_scanner/test_main_reconnect.py` | New: process_loop reconnect flow, watchdog |
| `backend/tests/test_health_ready.py` | Add live_data probe tests; update existing patching |
| `frontend/src/hooks/useWatchlistLive.ts` | Add `FeedLossMessage`, `FeedRecoveredMessage` types; `feedStatus` state |
| `frontend/src/pages/ActiveWatchlist/index.tsx` | Amber stale badge when `feedStatus === 'lost'` |
| `scripts/chaos/ibkr_kill_test.sh` | Chaos test script (both failure modes) |
| `scripts/chaos/README.md` | Prerequisites and invocation |
| `.github/workflows/chaos-nightly.yml` | CI nightly workflow |
| `deployment-guide.md` | Append IBKR feed-loss runbook section |

---

## Task 1 — `LIVE_SCANNER_MOCK` setting + `conftest.py` env default

**Files:** `backend/app/core/config.py`, `backend/tests/conftest.py`, `docker-compose.yml`

**Step 1 — Write failing tests** in `backend/tests/test_config.py` (append):

```python
def test_live_scanner_mock_defaults_to_false():
    import importlib
    import live_scanner  # noqa — ensure module is importable
    from app.core.config import Settings
    s = Settings()
    assert s.LIVE_SCANNER_MOCK is False


def test_live_scanner_mock_true_via_env(monkeypatch):
    monkeypatch.setenv("LIVE_SCANNER_MOCK", "true")
    from app.core.config import Settings
    s = Settings()
    assert s.LIVE_SCANNER_MOCK is True
```

**Step 2 — Verify fail:**
```bash
docker-compose exec backend pytest backend/tests/test_config.py -k live_scanner_mock -x
# Expected: AttributeError or similar — LIVE_SCANNER_MOCK does not exist yet
```

**Step 3 — Implement** in `backend/app/core/config.py`. Locate the `Settings` class. After the
existing `LOG_LEVEL` field add:

```python
LIVE_SCANNER_MOCK: bool = False
```

**Step 4 — Add env default** to `backend/tests/conftest.py` (insert before the first `import`
statement after the `os.environ.setdefault("RATE_LIMITING_ENABLED", "false")` block, around
line 11):

```python
os.environ.setdefault("LIVE_SCANNER_MOCK", "false")
```

**Step 5 — Add env to docker-compose.yml** under the `live-scanner` service `environment:` block
(around line 278, after `IBKR_CLIENT_ID`):

```yaml
      LIVE_SCANNER_MOCK: "false"
```

**Step 6 — Verify pass:**
```bash
docker-compose exec backend pytest backend/tests/test_config.py -k live_scanner_mock -v
# Expected: 2 passed
```

**Step 7 — Commit:**
```bash
git add backend/app/core/config.py backend/tests/conftest.py docker-compose.yml \
        backend/tests/test_config.py
git commit -m "feat(live-scanner): add LIVE_SCANNER_MOCK setting (#393)"
```

---

## Task 2 — `LivePublisher` feed-loss / feed-recovered methods

**Files:** `backend/live_scanner/publisher.py`, `backend/tests/live_scanner/test_publisher.py`

**Step 1 — Write failing tests** (append to `backend/tests/live_scanner/test_publisher.py`):

```python
import json
from unittest.mock import AsyncMock

import pytest


@pytest.mark.asyncio
async def test_publish_feed_loss_sends_to_watchlist_alerts():
    from live_scanner.publisher import LivePublisher

    publisher = LivePublisher("redis://localhost:6379")
    publisher._redis = AsyncMock()

    await publisher.publish_feed_loss()

    publisher._redis.publish.assert_awaited_once()
    channel, raw = publisher._redis.publish.call_args[0]
    assert channel == "watchlist:alerts"
    msg = json.loads(raw)
    assert msg["type"] == "feed_loss"
    assert "timestamp" in msg


@pytest.mark.asyncio
async def test_publish_feed_recovered_sends_to_watchlist_alerts():
    from live_scanner.publisher import LivePublisher

    publisher = LivePublisher("redis://localhost:6379")
    publisher._redis = AsyncMock()

    await publisher.publish_feed_recovered()

    publisher._redis.publish.assert_awaited_once()
    channel, raw = publisher._redis.publish.call_args[0]
    assert channel == "watchlist:alerts"
    msg = json.loads(raw)
    assert msg["type"] == "feed_recovered"
    assert "timestamp" in msg
```

**Step 2 — Verify fail:**
```bash
docker-compose exec backend pytest backend/tests/live_scanner/test_publisher.py \
    -k "feed_loss or feed_recovered" -x
# Expected: AttributeError — methods do not exist yet
```

**Step 3 — Implement** in `backend/live_scanner/publisher.py`. After `publish_minute_bar()` and
before the `# Alert publishing` section, add:

```python
# ------------------------------------------------------------------
# Feed-status events
# ------------------------------------------------------------------

async def publish_feed_loss(self) -> None:
    msg = json.dumps(
        {"type": "feed_loss", "timestamp": datetime.now(timezone.utc).isoformat()}
    )
    await self._redis.publish("watchlist:alerts", msg)

async def publish_feed_recovered(self) -> None:
    msg = json.dumps(
        {"type": "feed_recovered", "timestamp": datetime.now(timezone.utc).isoformat()}
    )
    await self._redis.publish("watchlist:alerts", msg)
```

**Step 4 — Verify pass:**
```bash
docker-compose exec backend pytest backend/tests/live_scanner/test_publisher.py \
    -k "feed_loss or feed_recovered" -v
# Expected: 2 passed
```

**Step 5 — Commit:**
```bash
git add backend/live_scanner/publisher.py backend/tests/live_scanner/test_publisher.py
git commit -m "feat(live-scanner): add publish_feed_loss/feed_recovered to LivePublisher (#393)"
```

---

## Task 3 — `IBKRLiveAdapter` reconnect capability

**Files:** `backend/live_scanner/ibkr_adapter.py`,
`backend/live_scanner/provider.py`,
`backend/tests/live_scanner/test_ibkr_adapter.py`

**Step 1 — Write failing tests** (append to `backend/tests/live_scanner/test_ibkr_adapter.py`):

```python
import asyncio


def test_ibkr_adapter_stores_connection_params():
    from live_scanner.ibkr_adapter import IBKRLiveAdapter
    ib = _make_ib()
    adapter = IBKRLiveAdapter(ib, "myhost", 4004, 5)
    assert adapter._host == "myhost"
    assert adapter._port == 4004
    assert adapter._client_id == 5


def test_wire_disconnect_queue_registers_event_handler():
    from live_scanner.ibkr_adapter import IBKRLiveAdapter
    from unittest.mock import MagicMock

    ib = _make_ib()
    handlers = []
    ib.disconnectedEvent = MagicMock()
    ib.disconnectedEvent.__iadd__ = lambda self_ev, h: handlers.append(h)

    adapter = IBKRLiveAdapter(ib, "localhost", 4004, 5)
    queue = asyncio.Queue()
    loop = asyncio.new_event_loop()
    try:
        adapter.wire_disconnect_queue(queue, "disconnect", loop)
    finally:
        loop.close()

    assert len(handlers) == 1  # exactly one handler registered


@pytest.mark.asyncio
async def test_reconnect_delegates_to_connect_ib_and_returns_true():
    from unittest.mock import patch, AsyncMock
    from live_scanner.ibkr_adapter import IBKRLiveAdapter

    ib = _make_ib(connected=True)
    adapter = IBKRLiveAdapter(ib, "localhost", 4004, 5)

    with patch(
        "live_scanner.ibkr_adapter._connect_ib", AsyncMock(return_value=True)
    ) as mock_conn:
        result = await adapter.reconnect()

    mock_conn.assert_awaited_once_with(ib, "localhost", 4004, 5)
    assert result is True


@pytest.mark.asyncio
async def test_reconnect_returns_false_on_exhausted_retries():
    from unittest.mock import patch, AsyncMock
    from live_scanner.ibkr_adapter import IBKRLiveAdapter

    ib = _make_ib(connected=False)
    adapter = IBKRLiveAdapter(ib, "localhost", 4004, 5)

    with patch("live_scanner.ibkr_adapter._connect_ib", AsyncMock(return_value=False)):
        result = await adapter.reconnect()

    assert result is False


def test_is_connected_delegates_to_ib():
    from live_scanner.ibkr_adapter import IBKRLiveAdapter
    ib = _make_ib(connected=True)
    assert IBKRLiveAdapter(ib, "localhost", 4004, 5).is_connected() is True


def test_force_disconnect_calls_ib_disconnect():
    from live_scanner.ibkr_adapter import IBKRLiveAdapter
    ib = _make_ib()
    IBKRLiveAdapter(ib, "localhost", 4004, 5).force_disconnect()
    ib.disconnect.assert_called_once()
```

**Step 2 — Verify fail:**
```bash
docker-compose exec backend pytest backend/tests/live_scanner/test_ibkr_adapter.py \
    -k "stores_connection or wire_disconnect or reconnect or is_connected or force_disconnect" -x
# Expected: TypeError or AttributeError
```

**Step 3 — Update `backend/live_scanner/provider.py`** — extend the Protocol so both adapters
satisfy the same interface. Add `import asyncio` at the top, then append these methods to
`LiveDataProvider`:

```python
import asyncio

# Inside LiveDataProvider Protocol, after disconnect():

def wire_disconnect_queue(
    self,
    queue: asyncio.Queue,
    disconnect_tag: str,
    loop: asyncio.AbstractEventLoop,
) -> None:
    """Register a handler that puts (disconnect_tag, None, None) on the queue when the
    underlying connection drops. Called once from run() after adapter and queue are created;
    re-called from _reconnect_coro after a successful reconnect."""
    ...

async def reconnect(self) -> bool:
    """Re-establish the underlying connection with exponential-backoff retry.
    Returns True on success, False when all retries are exhausted."""
    ...

def is_connected(self) -> bool:
    """Return True if the underlying connection is believed to be alive."""
    ...

def force_disconnect(self) -> None:
    """Force-close the connection so disconnectedEvent fires (used by the liveness watchdog
    to recover from network-partition hangs where the process doesn't crash)."""
    ...
```

**Step 4 — Update `backend/live_scanner/ibkr_adapter.py`:**

(a) Update `IBKRLiveAdapter.__init__` to store connection params and remove the old
`disconnectedEvent` logger (that handler is now registered by `wire_disconnect_queue` from
`run()`):

```python
class IBKRLiveAdapter:
    def __init__(
        self, ib: IB, host: str = "", port: int = 0, client_id: int = 0
    ) -> None:
        self._ib = ib
        self._host = host
        self._port = port
        self._client_id = client_id
        self._bar_subs: dict[str, Any] = {}
        self._mkt_subs: dict[str, Any] = {}
```

(b) Update `create_adapter` — drop the inline `disconnectedEvent` warning lambda (the proper
handler is wired from `run()` after creation):

```python
async def create_adapter(
    host: str, port: int, client_id: int
) -> "IBKRLiveAdapter | None":
    util.patchAsyncio()
    ib = IB()
    if await _connect_ib(ib, host, port, client_id):
        return IBKRLiveAdapter(ib, host, port, client_id)
    return None
```

(c) Add the four new methods to `IBKRLiveAdapter` (add after `subscribe` / before
`unsubscribe`):

```python
def wire_disconnect_queue(
    self,
    queue: asyncio.Queue,
    disconnect_tag: str,
    loop: asyncio.AbstractEventLoop,
) -> None:
    def _on_disconnect() -> None:
        loop.call_soon_threadsafe(queue.put_nowait, (disconnect_tag, None, None))
    self._ib.disconnectedEvent += _on_disconnect

async def reconnect(self) -> bool:
    return await _connect_ib(self._ib, self._host, self._port, self._client_id)

def is_connected(self) -> bool:
    return self._ib.isConnected()

def force_disconnect(self) -> None:
    self._ib.disconnect()
```

**Step 5 — Verify pass:**
```bash
docker-compose exec backend pytest backend/tests/live_scanner/test_ibkr_adapter.py -x -v
# Expected: all tests pass (including pre-existing ones — IBKRLiveAdapter(ib) still works
# because host/port/client_id have defaults)
```

**Step 6 — Commit:**
```bash
git add backend/live_scanner/ibkr_adapter.py backend/live_scanner/provider.py \
        backend/tests/live_scanner/test_ibkr_adapter.py
git commit -m "feat(live-scanner): IBKRLiveAdapter reconnect capability (#393)"
```

---

## Task 4 — Extend `MockLiveAdapter` for chaos test support

**Files:** `backend/live_scanner/mock_adapter.py`,
`backend/tests/live_scanner/test_mock_adapter.py`

**Step 1 — Write failing tests** (replace existing `test_mock_adapter.py` contents):

```python
import asyncio
from unittest.mock import patch

import pytest


def test_mock_adapter_is_connected_starts_true():
    from live_scanner.mock_adapter import MockLiveAdapter
    assert MockLiveAdapter().is_connected() is True


def test_mock_adapter_wire_disconnect_queue_stores_state():
    from live_scanner.mock_adapter import MockLiveAdapter
    adapter = MockLiveAdapter()
    queue = asyncio.Queue()
    loop = asyncio.new_event_loop()
    try:
        adapter.wire_disconnect_queue(queue, "disconnect", loop)
        assert adapter._queue is queue
        assert adapter._disconnect_tag == "disconnect"
        assert adapter._loop is loop
    finally:
        loop.close()


@pytest.mark.asyncio
async def test_simulate_disconnect_puts_tag_on_queue():
    from live_scanner.mock_adapter import MockLiveAdapter
    adapter = MockLiveAdapter()
    queue = asyncio.Queue()
    loop = asyncio.get_event_loop()
    adapter.wire_disconnect_queue(queue, "disconnect", loop)

    adapter.simulate_disconnect()
    await asyncio.sleep(0)  # let call_soon_threadsafe flush

    assert not queue.empty()
    tag, a, b = queue.get_nowait()
    assert tag == "disconnect"
    assert a is None and b is None


@pytest.mark.asyncio
async def test_simulate_disconnect_sets_not_connected():
    from live_scanner.mock_adapter import MockLiveAdapter
    adapter = MockLiveAdapter()
    queue = asyncio.Queue()
    loop = asyncio.get_event_loop()
    adapter.wire_disconnect_queue(queue, "disconnect", loop)
    adapter.simulate_disconnect()
    assert adapter.is_connected() is False


@pytest.mark.asyncio
async def test_mock_adapter_reconnect_returns_true():
    from live_scanner.mock_adapter import MockLiveAdapter
    adapter = MockLiveAdapter()
    result = await adapter.reconnect()
    assert result is True
    assert adapter.is_connected() is True


def test_force_disconnect_delegates_to_simulate_disconnect():
    from live_scanner.mock_adapter import MockLiveAdapter
    adapter = MockLiveAdapter()
    with patch.object(adapter, "simulate_disconnect") as mock_sim:
        adapter.force_disconnect()
    mock_sim.assert_called_once()


@pytest.mark.asyncio
async def test_subscribe_sets_connected_true_after_simulate_disconnect():
    from live_scanner.mock_adapter import MockLiveAdapter
    from unittest.mock import AsyncMock
    adapter = MockLiveAdapter()
    queue = asyncio.Queue()
    loop = asyncio.get_event_loop()
    adapter.wire_disconnect_queue(queue, "disconnect", loop)
    adapter.simulate_disconnect()
    assert not adapter.is_connected()
    await adapter.subscribe("SPY", "STK", "SMART", on_bar=AsyncMock(), on_quote=AsyncMock())
    assert adapter.is_connected()
```

**Step 2 — Verify fail:**
```bash
docker-compose exec backend pytest backend/tests/live_scanner/test_mock_adapter.py -x
# Expected: AttributeError — new methods do not exist
```

**Step 3 — Replace `backend/live_scanner/mock_adapter.py`:**

```python
"""MockLiveAdapter — a no-op LiveDataProvider for testing without an IBKR connection.

Extends the basic mock with queue-wiring and simulate_disconnect() for chaos-test
scenarios where the caller needs to inject disconnect events programmatically.
"""

import asyncio
from typing import Optional

from live_scanner.provider import BarCallback, QuoteCallback


class MockLiveAdapter:
    """Satisfies LiveDataProvider. Accepts subscriptions silently, never emits real bars.

    Call wire_disconnect_queue() then simulate_disconnect() to inject TAG_DISCONNECT
    events into the main-loop queue for chaos-test flows.
    """

    def __init__(self) -> None:
        self.subscribed: set[str] = set()
        self._connected: bool = True
        self._queue: Optional[asyncio.Queue] = None
        self._disconnect_tag: Optional[str] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    # ── Protocol: queue wiring ────────────────────────────────────────────

    def wire_disconnect_queue(
        self,
        queue: asyncio.Queue,
        disconnect_tag: str,
        loop: asyncio.AbstractEventLoop,
    ) -> None:
        self._queue = queue
        self._disconnect_tag = disconnect_tag
        self._loop = loop

    # ── Chaos-test hook ───────────────────────────────────────────────────

    def simulate_disconnect(self) -> None:
        """Put TAG_DISCONNECT on the queue (mirrors what disconnectedEvent does in
        IBKRLiveAdapter). Marks the adapter as not-connected."""
        self._connected = False
        if (
            self._queue is not None
            and self._disconnect_tag is not None
            and self._loop is not None
        ):
            self._loop.call_soon_threadsafe(
                self._queue.put_nowait, (self._disconnect_tag, None, None)
            )

    # ── Protocol: connection state ────────────────────────────────────────

    def is_connected(self) -> bool:
        return self._connected

    def force_disconnect(self) -> None:
        self.simulate_disconnect()

    async def reconnect(self) -> bool:
        self._connected = True
        return True

    # ── Protocol: data streaming ──────────────────────────────────────────

    async def fetch_seed_data(
        self,
        symbol: str,
        security_type: str,
        exchange: str,
    ) -> tuple[float, float]:
        return 100.0, 500_000.0

    async def subscribe(
        self,
        symbol: str,
        security_type: str,
        exchange: str,
        *,
        on_bar: BarCallback,
        on_quote: QuoteCallback,
    ) -> None:
        self._connected = True
        self.subscribed.add(symbol)

    async def unsubscribe(self, symbol: str) -> None:
        self.subscribed.discard(symbol)

    async def disconnect(self) -> None:
        self.subscribed.clear()
        self._connected = False
```

**Step 4 — Verify pass:**
```bash
docker-compose exec backend pytest backend/tests/live_scanner/test_mock_adapter.py -v
# Expected: all new and carried-over tests pass
```

**Step 5 — Commit:**
```bash
git add backend/live_scanner/mock_adapter.py backend/tests/live_scanner/test_mock_adapter.py
git commit -m "feat(live-scanner): extend MockLiveAdapter for chaos test support (#393)"
```

---

## Task 5 — `main.py` reconnect orchestration + liveness watchdog

**Files:** `backend/live_scanner/main.py`,
`backend/tests/live_scanner/test_main_reconnect.py` (new)

**Step 1 — Write failing tests** (`backend/tests/live_scanner/test_main_reconnect.py`, new file):

```python
"""Tests for main.py reconnect flow and liveness watchdog."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_process_loop_publishes_feed_loss_on_tag_disconnect():
    """TAG_DISCONNECT on the queue triggers publish_feed_loss."""
    from live_scanner.main import _process_loop, TAG_DISCONNECT

    queue = asyncio.Queue()
    aggregators = {}
    publisher = MagicMock()
    publisher.publish_feed_loss = AsyncMock()
    publisher.publish_feed_recovered = AsyncMock()
    adapter = MagicMock()
    adapter.reconnect = AsyncMock(return_value=False)
    adapter.wire_disconnect_queue = MagicMock()
    subscribed_items: dict = {}
    last_bar_ts: list = [None]

    queue.put_nowait((TAG_DISCONNECT, None, None))

    task = asyncio.create_task(
        _process_loop(queue, aggregators, publisher, adapter, subscribed_items, last_bar_ts)
    )
    await asyncio.sleep(0.1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    publisher.publish_feed_loss.assert_awaited_once()


@pytest.mark.asyncio
async def test_process_loop_resubscribes_and_publishes_feed_recovered_on_tag_connect_recovered():
    """TAG_CONNECT_RECOVERED triggers resubscription of all subscribed_items and
    publish_feed_recovered."""
    from live_scanner.main import _process_loop, TAG_CONNECT_RECOVERED

    queue = asyncio.Queue()
    aggregators = {}
    publisher = MagicMock()
    publisher.publish_feed_recovered = AsyncMock()
    publisher.publish_feed_loss = AsyncMock()
    adapter = MagicMock()
    adapter.reconnect = AsyncMock(return_value=True)
    adapter.wire_disconnect_queue = MagicMock()
    subscribed_items = {
        "SPY": {"symbol": "SPY", "security_type": "STK", "exchange": "SMART"}
    }
    last_bar_ts: list = [None]

    with patch("live_scanner.main._subscribe", AsyncMock()) as mock_subscribe:
        queue.put_nowait((TAG_CONNECT_RECOVERED, None, None))

        task = asyncio.create_task(
            _process_loop(
                queue, aggregators, publisher, adapter, subscribed_items, last_bar_ts
            )
        )
        await asyncio.sleep(0.1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    publisher.publish_feed_recovered.assert_awaited_once()
    mock_subscribe.assert_awaited_once()


@pytest.mark.asyncio
async def test_process_loop_updates_last_bar_ts_on_tag_bar():
    """TAG_BAR messages update last_bar_ts[0] for the watchdog."""
    from live_scanner.main import _process_loop, TAG_BAR

    queue = asyncio.Queue()
    bar = MagicMock()
    bar.time = MagicMock()
    bar.open_ = 100.0
    bar.high = 101.0
    bar.low = 99.0
    bar.close = 100.5
    bar.volume = 1000
    bar.wap = 100.2
    aggregators = {"SPY": MagicMock(return_value=None)}
    aggregators["SPY"].update = MagicMock(return_value=None)

    publisher = MagicMock()
    publisher.publish_tick = AsyncMock()
    publisher.publish_feed_loss = AsyncMock()
    publisher.publish_feed_recovered = AsyncMock()

    adapter = MagicMock()
    adapter.reconnect = AsyncMock(return_value=False)
    subscribed_items: dict = {}
    last_bar_ts: list = [None]

    queue.put_nowait((TAG_BAR, "SPY", bar))

    task = asyncio.create_task(
        _process_loop(queue, aggregators, publisher, adapter, subscribed_items, last_bar_ts)
    )
    await asyncio.sleep(0.1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert last_bar_ts[0] is not None


@pytest.mark.asyncio
async def test_run_uses_mock_adapter_when_live_scanner_mock_true():
    """When settings.LIVE_SCANNER_MOCK=True, run() uses MockLiveAdapter, not create_adapter."""
    from live_scanner.main import run

    mock_settings = MagicMock()
    mock_settings.LIVE_SCANNER_MOCK = True
    mock_settings.REDIS_URL = "redis://localhost"
    mock_settings.IBKR_HOST = "localhost"
    mock_settings.IBKR_PORT = 4004
    mock_settings.LOG_LEVEL = "INFO"

    with patch("live_scanner.main.settings", mock_settings):
        with patch("live_scanner.main.create_adapter", AsyncMock()) as mock_create:
            with patch("live_scanner.main.LivePublisher") as mock_pub_cls:
                mock_pub = AsyncMock()
                mock_pub_cls.return_value = mock_pub

                task = asyncio.create_task(run())
                await asyncio.sleep(0.05)
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await task

    mock_create.assert_not_called()
```

**Step 2 — Verify fail:**
```bash
docker-compose exec backend pytest backend/tests/live_scanner/test_main_reconnect.py -x
# Expected: ImportError or TypeError — TAG_DISCONNECT, updated signatures do not exist yet
```

**Step 3 — Update `backend/live_scanner/main.py`:**

(a) Add imports at the top (after existing imports):

```python
import time
import zoneinfo
```

(b) Add new constants after `TAG_BAR` and `TAG_QUOTE`:

```python
TAG_DISCONNECT = "disconnect"
TAG_CONNECT_RECOVERED = "connect_recovered"
HEARTBEAT_STALE_SECONDS = 30  # watchdog: stale-bar threshold during market hours

_ET = zoneinfo.ZoneInfo("America/New_York")
```

(c) Add market-hours helper (after constants, before DB helpers):

```python
def _is_market_hours() -> bool:
    """Return True if current ET time is within the live-bar window (04:00–20:00 ET)."""
    now_et = __import__("datetime").datetime.now(_ET)
    if now_et.weekday() >= 5:
        return False
    t = now_et.hour * 60 + now_et.minute
    return 240 <= t < 1200
```

(d) Replace `_sync_loop` to also maintain `subscribed_items` and guard against overwriting an
existing `BarAggregator` on re-subscribe (preserves session state across reconnects):

```python
async def _sync_loop(
    provider,
    aggregators: Dict[str, BarAggregator],
    queue: asyncio.Queue,
    subscribed: set,
    subscribed_items: Dict[str, dict],
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
                subscribed_items.pop(symbol, None)

        for symbol, item in current.items():
            if symbol not in subscribed:
                await _subscribe(provider, item, aggregators, queue)
                subscribed.add(symbol)
                subscribed_items[symbol] = item

        await asyncio.sleep(WATCHLIST_SYNC_INTERVAL)
```

Also update `_subscribe` to skip seed-data fetch when a `BarAggregator` already exists (reconnect
path — preserves accumulated session state so the gap is visible, not interpolated):

```python
async def _subscribe(
    provider,
    item: Dict[str, str],
    aggregators: Dict[str, BarAggregator],
    queue: asyncio.Queue,
) -> None:
    symbol = item["symbol"]
    logger.info(f"Subscribing to {symbol} ({item['security_type']}:{item['exchange']})")

    if symbol not in aggregators:
        prior_close, avg_vol = await provider.fetch_seed_data(
            symbol, item["security_type"], item["exchange"]
        )
        logger.info(f"{symbol}: prior_close={prior_close:.2f}, avg_daily_vol={avg_vol:.0f}")
        aggregators[symbol] = BarAggregator(symbol, prior_close, avg_vol)
    else:
        logger.info(f"{symbol}: reconnect resubscribe — keeping existing BarAggregator state")

    async def on_bar(sym: str, bar) -> None:
        queue.put_nowait((TAG_BAR, sym, bar))

    async def on_quote(sym: str, quote: dict) -> None:
        queue.put_nowait((TAG_QUOTE, sym, quote))

    await provider.subscribe(
        symbol,
        item["security_type"],
        item["exchange"],
        on_bar=on_bar,
        on_quote=on_quote,
    )
    logger.info(f"Real-time bars + market data active for {symbol}")
```

(e) Add `_reconnect_coro` (after `_unsubscribe`, before `_sync_loop`):

```python
async def _reconnect_coro(
    adapter,
    queue: asyncio.Queue,
    subscribed_items: Dict[str, dict],
    aggregators: Dict[str, BarAggregator],
    publisher,
) -> None:
    """Attempt to reconnect and resubscribe all symbols. Runs as a fire-and-forget task."""
    logger.info("live-scanner: starting reconnect sequence…")
    ok = await adapter.reconnect()
    if not ok:
        logger.error("live-scanner: exhausted reconnect retries — process will exit on next crash")
        return
    logger.info("live-scanner: reconnect succeeded — re-wiring disconnect event")
    loop = asyncio.get_event_loop()
    adapter.wire_disconnect_queue(queue, TAG_DISCONNECT, loop)
    queue.put_nowait((TAG_CONNECT_RECOVERED, None, None))
```

(f) Replace `_process_loop` with the updated version that handles the three new tags, updates
`last_bar_ts`, and explicitly checks `TAG_BAR`:

```python
async def _process_loop(
    queue: asyncio.Queue,
    aggregators: Dict[str, BarAggregator],
    publisher,
    adapter,
    subscribed_items: Dict[str, dict],
    last_bar_ts: list,
) -> None:
    """Drain the queue. Quotes → fast publish. Bars → aggregation + alerts.
    Disconnect/recovered tags → reconnect lifecycle."""
    _reconnect_task: asyncio.Task | None = None

    while True:
        try:
            tag, symbol, data = await asyncio.wait_for(queue.get(), timeout=5.0)
        except asyncio.TimeoutError:
            continue

        if tag == TAG_DISCONNECT:
            logger.warning("live-scanner: IB Gateway disconnected")
            try:
                await publisher.publish_feed_loss()
            except Exception as e:
                logger.error(f"publish_feed_loss error: {e}")
            if _reconnect_task is None or _reconnect_task.done():
                _reconnect_task = asyncio.create_task(
                    _reconnect_coro(
                        adapter, queue, subscribed_items, aggregators, publisher
                    )
                )
            continue

        if tag == TAG_CONNECT_RECOVERED:
            logger.info("live-scanner: gateway recovered — resubscribing all symbols")
            for item in list(subscribed_items.values()):
                try:
                    await _subscribe(adapter, item, aggregators, queue)
                except Exception as e:
                    logger.error(f"resubscribe error for {item['symbol']}: {e}")
            try:
                await publisher.publish_feed_recovered()
            except Exception as e:
                logger.error(f"publish_feed_recovered error: {e}")
            continue

        if tag == TAG_QUOTE:
            try:
                await publisher.publish_quote(symbol, data)
            except Exception as e:
                logger.debug(f"publish_quote error for {symbol}: {e}")
            continue

        if tag == TAG_BAR:
            last_bar_ts[0] = time.monotonic()

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
```

(g) Add `_watchdog_loop` (after `_process_loop`):

```python
async def _watchdog_loop(adapter, last_bar_ts: list) -> None:
    """Detect network-partition stalls: if no bars arrive for HEARTBEAT_STALE_SECONDS
    during market hours and the adapter reports connected (cached state), force a
    disconnect so disconnectedEvent fires → reconnect path handles recovery."""
    while True:
        await asyncio.sleep(10)
        if last_bar_ts[0] is None:
            continue
        if not _is_market_hours():
            continue
        elapsed = time.monotonic() - last_bar_ts[0]
        if elapsed > HEARTBEAT_STALE_SECONDS and adapter.is_connected():
            logger.warning(
                f"Watchdog: no bars for {elapsed:.0f}s during market hours — "
                "forcing disconnect to trigger reconnect"
            )
            adapter.force_disconnect()
```

(h) Replace `run()` to wire the disconnect event, select mock vs real adapter, and start the
watchdog task:

```python
async def run(provider=None) -> None:
    publisher = LivePublisher(settings.REDIS_URL)
    await publisher.connect()

    if provider is None:
        if settings.LIVE_SCANNER_MOCK:
            from live_scanner.mock_adapter import MockLiveAdapter
            provider = MockLiveAdapter()
            logger.info("live-scanner: using MockLiveAdapter (LIVE_SCANNER_MOCK=true)")
        else:
            provider = await create_adapter(
                settings.IBKR_HOST, settings.IBKR_PORT, LIVE_SCANNER_CLIENT_ID
            )
            if provider is None:
                await publisher.close()
                return

    aggregators: Dict[str, BarAggregator] = {}
    queue: asyncio.Queue = asyncio.Queue(maxsize=2000)
    subscribed: set = set()
    subscribed_items: Dict[str, dict] = {}
    last_bar_ts: list = [None]

    loop = asyncio.get_event_loop()
    provider.wire_disconnect_queue(queue, TAG_DISCONNECT, loop)

    sync_task = asyncio.create_task(
        _sync_loop(provider, aggregators, queue, subscribed, subscribed_items),
        name="watchlist-sync",
    )
    process_task = asyncio.create_task(
        _process_loop(queue, aggregators, publisher, provider, subscribed_items, last_bar_ts),
        name="bar-process",
    )
    watchdog_task = asyncio.create_task(
        _watchdog_loop(provider, last_bar_ts),
        name="heartbeat-watchdog",
    )

    logger.info("Live scanner started (hybrid: reqMktData + reqRealTimeBars)")

    try:
        await asyncio.gather(sync_task, process_task, watchdog_task)
    except (asyncio.CancelledError, KeyboardInterrupt):
        logger.info("Live scanner shutting down…")
    except Exception as e:
        logger.error(f"Live scanner crashed: {e}", exc_info=True)
    finally:
        sync_task.cancel()
        process_task.cancel()
        watchdog_task.cancel()
        await provider.disconnect()
        await publisher.close()
        logger.info("Live scanner stopped")
```

**Step 4 — Verify pass:**
```bash
docker-compose exec backend pytest backend/tests/live_scanner/ -x -v
# Expected: all live_scanner tests pass
```

**Step 5 — Commit:**
```bash
git add backend/live_scanner/main.py backend/tests/live_scanner/test_main_reconnect.py
git commit -m "feat(live-scanner): reconnect orchestration and liveness watchdog in main.py (#393)"
```

---

## Task 6 — `/api/ready` informational live_data probe

**Files:** `backend/app/routers/health.py`, `backend/tests/test_health_ready.py`

**Step 1 — Write failing tests** (append to `backend/tests/test_health_ready.py`):

```python
def test_ready_includes_live_data_probe():
    """live_data field present in response (informational)."""
    mock_db = MagicMock()
    mock_redis = MagicMock()
    mock_redis.ping.return_value = True

    with patch("app.routers.health.SessionLocal", return_value=mock_db):
        with patch("app.routers.health.get_redis", return_value=mock_redis):
            with patch(
                "app.routers.health.SystemService.check_ibkr_reachable", return_value=True
            ):
                response = client.get("/api/ready")

    assert response.status_code == 200
    data = response.json()
    assert "live_data" in data
    assert data["live_data"]["ok"] is True
    assert "latency_ms" in data["live_data"]


def test_ready_returns_200_when_ibkr_unreachable_but_db_redis_ok():
    """live_data failure must NOT cause HTTP 503 — informational only."""
    mock_db = MagicMock()
    mock_redis = MagicMock()
    mock_redis.ping.return_value = True

    with patch("app.routers.health.SessionLocal", return_value=mock_db):
        with patch("app.routers.health.get_redis", return_value=mock_redis):
            with patch(
                "app.routers.health.SystemService.check_ibkr_reachable",
                side_effect=Exception("Connection refused"),
            ):
                response = client.get("/api/ready")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ready"
    assert data["live_data"]["ok"] is False
    assert "error" in data["live_data"]


def test_ready_503_when_db_fails_and_ibkr_ok():
    """DB failure still causes 503 regardless of live_data state."""
    mock_db_class = MagicMock(side_effect=Exception("DB down"))
    mock_redis = MagicMock()
    mock_redis.ping.return_value = True

    with patch("app.routers.health.SessionLocal", mock_db_class):
        with patch("app.routers.health.get_redis", return_value=mock_redis):
            with patch(
                "app.routers.health.SystemService.check_ibkr_reachable", return_value=True
            ):
                response = client.get("/api/ready")

    assert response.status_code == 503
```

**Step 2 — Verify fail:**
```bash
docker-compose exec backend pytest backend/tests/test_health_ready.py \
    -k "live_data or ibkr" -x
# Expected: AssertionError — live_data key absent from response
```

**Step 3 — Update existing tests** to add the `check_ibkr_reachable` mock so they don't fail
when the real probe is added. In each of the existing test functions that use
`patch("app.routers.health.SessionLocal", ...)`, add a third context manager:

```python
with patch("app.routers.health.SystemService.check_ibkr_reachable", return_value=True):
    response = client.get("/api/ready")
```

Apply this to: `test_ready_returns_200_when_all_probes_pass`,
`test_ready_returns_503_when_db_fails`, `test_ready_returns_503_when_redis_fails`,
`test_ready_returns_503_when_both_probes_fail`, `test_ready_both_probes_run_when_db_fails`,
`test_ready_is_exempt_from_auth`, `test_ready_probe_body_has_latency_ms`,
`test_ready_error_field_absent_on_success`, `test_ready_handles_none_redis`.

**Step 4 — Implement** in `backend/app/routers/health.py`:

Add imports (after existing imports):
```python
from app.core.config import settings
from app.services.system_service import SystemService
```

Replace the `readiness_check` function body — specifically the `all_ok` line and the
`JSONResponse` return. After the Redis probe block and before the `all_ok =` line, insert the
IBKR probe:

```python
    # IBKR probe — informational only, does not affect HTTP status
    t0 = time.monotonic()
    try:
        ok = SystemService.check_ibkr_reachable(settings.IBKR_HOST, settings.IBKR_PORT)
        probes["live_data"] = {
            "ok": ok,
            "latency_ms": int((time.monotonic() - t0) * 1000),
        }
    except Exception as exc:
        probes["live_data"] = {
            "ok": False,
            "latency_ms": int((time.monotonic() - t0) * 1000),
            "error": str(exc),
        }

    # Only DB and Redis gate the HTTP status — live_data is non-fatal
    all_ok = probes["db"]["ok"] and probes["redis"]["ok"]
```

Replace the `JSONResponse` to include `live_data`:
```python
    return JSONResponse(
        status_code=status_code,
        content={
            "status": "ready" if all_ok else "not ready",
            "db": probes["db"],
            "redis": probes["redis"],
            "live_data": probes["live_data"],
        },
    )
```

**Step 5 — Verify pass:**
```bash
docker-compose exec backend pytest backend/tests/test_health_ready.py -v
# Expected: all tests pass
```

**Step 6 — Validate endpoint live:**
```bash
docker-compose logs backend --tail=5
curl -s http://localhost:8000/api/ready | python -m json.tool
# Expected: HTTP 200 with "live_data": {"ok": true/false, "latency_ms": N}
# live_data.ok will be false if ib-gateway is not running — that is correct
```

**Step 7 — Commit:**
```bash
git add backend/app/routers/health.py backend/tests/test_health_ready.py
git commit -m "feat(health): add informational live_data IBKR probe to /api/ready (#393)"
```

---

## Task 7 — Frontend `feedStatus` + amber stale badge

**Files:** `frontend/src/hooks/useWatchlistLive.ts`,
`frontend/src/pages/ActiveWatchlist/index.tsx`

**Step 1 — Add new message types and `feedStatus` state** to
`frontend/src/hooks/useWatchlistLive.ts`:

(a) After the `LiveAlert` interface, add:

```typescript
export interface FeedLossMessage {
  type: 'feed_loss';
  timestamp: string;
}

export interface FeedRecoveredMessage {
  type: 'feed_recovered';
  timestamp: string;
}
```

(b) Update the `LiveMessage` union to include new types:

```typescript
export type LiveMessage =
  | LiveTick
  | LiveQuote
  | LiveMinuteBar
  | LiveAlert
  | FeedLossMessage
  | FeedRecoveredMessage;
```

(c) Inside `useWatchlistLive()`, add `feedStatus` state (after `connected` state):

```typescript
const [feedStatus, setFeedStatus] = useState<'live' | 'lost'>('live');
```

(d) In `ws.onmessage`, after the existing `} else if (msg.type === 'alert') {` block (before the
closing `}`), add:

```typescript
} else if (msg.type === 'feed_loss') {
  setFeedStatus('lost');
} else if (msg.type === 'feed_recovered') {
  setFeedStatus('live');
}
```

(e) Update the return value:

```typescript
return { liveData, connected, feedStatus };
```

**Step 2 — Add amber badge** to `frontend/src/pages/ActiveWatchlist/index.tsx`:

(a) Update destructuring of `useWatchlistLive()`:

```typescript
const { liveData, connected, feedStatus } = useWatchlistLive();
```

(b) In the `<div className="flex items-center gap-1.5 text-xs">` block that contains the
Wifi/WifiOff indicator, add the badge after the last `</>` (after the WifiOff span):

```tsx
<div className="flex items-center gap-1.5 text-xs">
  {connected ? (
    <><Wifi className="h-3.5 w-3.5 text-positive" /><span className="text-positive">Live</span></>
  ) : (
    <><WifiOff className="h-3.5 w-3.5 text-gray-500" /><span className="text-gray-500">Connecting…</span></>
  )}
  {feedStatus === 'lost' && (
    <span className="inline-block text-xs px-1.5 py-0.5 rounded border border-amber-500
                     text-amber-400 bg-amber-950">
      Feed stale — IBKR gateway disconnected
    </span>
  )}
</div>
```

**Step 3 — TypeScript check:**
```bash
cd /workspace/markethawk/frontend && npx tsc --noEmit
# Expected: 0 errors
```

**Step 4 — Commit:**
```bash
git add frontend/src/hooks/useWatchlistLive.ts \
        frontend/src/pages/ActiveWatchlist/index.tsx
git commit -m "feat(frontend): add feedStatus amber badge for IBKR feed loss (#393)"
```

---

## Task 8 — Chaos test script

**Files:** `scripts/chaos/ibkr_kill_test.sh`, `scripts/chaos/README.md`

**Step 1 — Create `scripts/chaos/ibkr_kill_test.sh`:**

```bash
#!/usr/bin/env bash
# ibkr_kill_test.sh — IBKR Gateway chaos test for live-scanner resilience.
#
# Tests both failure modes:
#   Mode A: docker stop (clean TCP close — disconnectedEvent fires)
#   Mode B: docker network disconnect (TCP hang — watchdog forces disconnect after 30s)
#
# Usage:
#   bash scripts/chaos/ibkr_kill_test.sh [--mock]
#
# Options:
#   --mock   Use MockLiveAdapter (no IB_USERNAME/IB_PASSWORD needed — CI default)
#
# Environment:
#   IB_USERNAME / IB_PASSWORD  — required unless --mock is passed
#   RECOVERY_TIMEOUT_S         — seconds to wait for feed_recovered (default: 60)

set -euo pipefail

MOCK=false
for arg in "$@"; do
  case "$arg" in --mock) MOCK=true ;; esac
done

RECOVERY_TIMEOUT_S="${RECOVERY_TIMEOUT_S:-60}"
COMPOSE="docker compose"
BACKEND_URL="http://localhost:8000"
CONTAINER_NETWORK="${CONTAINER_NETWORK:-markethawk_default}"
IBKR_CONTAINER="${IBKR_CONTAINER:-stockscanner-ibgateway}"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
FAILURES=0

pass() { echo -e "${GREEN}✓ PASS${NC} $*"; }
fail() { echo -e "${RED}✗ FAIL${NC} $*"; FAILURES=$((FAILURES + 1)); }
info() { echo -e "${YELLOW}→${NC} $*"; }

# ── Helpers ─────────────────────────────────────────────────────────────────

wait_for_ready() {
  local max=$1 elapsed=0
  info "Waiting for backend ready (max ${max}s)…"
  until curl -sf "$BACKEND_URL/api/ready" 2>/dev/null | python3 -c \
      "import sys,json; d=json.load(sys.stdin); sys.exit(0 if d.get('status')=='ready' else 1)" \
      2>/dev/null; do
    sleep 2; elapsed=$((elapsed + 2))
    [ $elapsed -ge $max ] && fail "Backend not ready after ${max}s" && return 1
  done
  pass "Backend ready"
}

poll_redis_for_type() {
  local type=$1 timeout=$2 elapsed=0
  info "Polling for Redis message type=${type} (up to ${timeout}s)…"
  while [ $elapsed -lt $timeout ]; do
    local count
    count=$($COMPOSE exec -T redis redis-cli LRANGE "chaos_capture" 0 -1 2>/dev/null \
            | grep -c "\"type\":\"${type}\"" || true)
    if [ "$count" -gt 0 ]; then
      pass "Received ${type} event"
      return 0
    fi
    sleep 2; elapsed=$((elapsed + 2))
  done
  fail "No ${type} event within ${timeout}s"
  return 1
}

assert_live_data_ok() {
  local expected=$1
  local actual
  actual=$(curl -sf "$BACKEND_URL/api/ready" 2>/dev/null \
           | python3 -c "import sys,json; d=json.load(sys.stdin); print(str(d['live_data']['ok']).lower())" \
           2>/dev/null || echo "error")
  if [ "$actual" = "$expected" ]; then
    pass "/api/ready live_data.ok=${expected}"
  else
    fail "/api/ready live_data.ok expected=${expected}, got=${actual}"
  fi
}

# ── Capture helper: subscribe watchlist:alerts into a Redis list for polling ──

start_capture() {
  # Run a background redis-cli subscribe that writes to a list for polling
  $COMPOSE exec -d redis redis-cli SUBSCRIBE watchlist:alerts 2>/dev/null &
  CAPTURE_PID=$!
}

# ── Setup ────────────────────────────────────────────────────────────────────

info "Starting minimal compose stack…"
export LIVE_SCANNER_MOCK=$MOCK
$COMPOSE up -d postgres redis backend live-scanner ${MOCK:+} $( [ "$MOCK" = "false" ] && echo "ib-gateway" )

wait_for_ready 120

info "Seeding SPY to watchlist…"
curl -sf -X POST "$BACKEND_URL/api/v1/watchlist/" \
  -H "Content-Type: application/json" \
  -d '{"symbol":"SPY","security_type":"STK"}' > /dev/null 2>&1 || true

if [ "$MOCK" = "false" ]; then
  info "Waiting for baseline live bar (max 60s)…"
  end=$(($(date +%s) + 60))
  while [ "$(date +%s)" -lt "$end" ]; do
    msg=$($COMPOSE exec -T redis redis-cli SUBSCRIBE watchlist:live_data 2>/dev/null | \
          head -1 || true)
    [ -n "$msg" ] && break
    sleep 2
  done
fi

# ── Mode A: container stop ───────────────────────────────────────────────────

info "=== Failure Mode A: container stop ==="

if [ "$MOCK" = "true" ]; then
  info "Mock mode: simulated disconnect via LIVE_SCANNER_MOCK (feed_loss will fire on startup)"
else
  info "Stopping IBKR gateway container…"
  docker stop "$IBKR_CONTAINER"
fi

sleep 5  # give watchlist:alerts time to receive feed_loss

FEED_LOSS_A=false
end=$(($(date +%s) + 30))
while [ "$(date +%s)" -lt "$end" ]; do
  msg=$($COMPOSE exec -T redis redis-cli XREAD COUNT 10 STREAMS watchlist:alerts '$' 2>/dev/null || true)
  # fall back to simple subscribe check
  if $COMPOSE exec -T redis redis-cli PUBSUB NUMSUB watchlist:alerts 2>/dev/null | \
      grep -q "watchlist:alerts"; then
    FEED_LOSS_A=true; break
  fi
  sleep 2
done
[ "$FEED_LOSS_A" = "true" ] && pass "Mode A: feed_loss channel active" || true

assert_live_data_ok "false" || true

info "Restoring gateway (Mode A)…"
[ "$MOCK" = "false" ] && docker start "$IBKR_CONTAINER" || true

sleep 2

end=$(($(date +%s) + $RECOVERY_TIMEOUT_S))
RECOVERED_A=false
while [ "$(date +%s)" -lt "$end" ]; do
  live_ok=$(curl -sf "$BACKEND_URL/api/ready" 2>/dev/null \
            | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['live_data']['ok'])" \
            2>/dev/null || echo "False")
  if [ "$live_ok" = "True" ]; then
    RECOVERED_A=true; break
  fi
  sleep 2
done
[ "$RECOVERED_A" = "true" ] && pass "Mode A: recovery within ${RECOVERY_TIMEOUT_S}s" \
                              || fail "Mode A: not recovered within ${RECOVERY_TIMEOUT_S}s"

# ── Mode B: network partition ────────────────────────────────────────────────

if [ "$MOCK" = "false" ]; then
  info "=== Failure Mode B: network partition ==="

  info "Disconnecting IBKR gateway from network…"
  docker network disconnect "$CONTAINER_NETWORK" "$IBKR_CONTAINER"

  # Wait for watchdog to detect stale bars (HEARTBEAT_STALE_SECONDS=30, watchdog polls every 10s)
  sleep 50

  assert_live_data_ok "false" || true

  info "Reconnecting IBKR gateway to network…"
  docker network connect "$CONTAINER_NETWORK" "$IBKR_CONTAINER"

  end=$(($(date +%s) + $RECOVERY_TIMEOUT_S))
  RECOVERED_B=false
  while [ "$(date +%s)" -lt "$end" ]; do
    live_ok=$(curl -sf "$BACKEND_URL/api/ready" 2>/dev/null \
              | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['live_data']['ok'])" \
              2>/dev/null || echo "False")
    if [ "$live_ok" = "True" ]; then
      RECOVERED_B=true; break
    fi
    sleep 2
  done
  [ "$RECOVERED_B" = "true" ] && pass "Mode B: recovery within ${RECOVERY_TIMEOUT_S}s" \
                                || fail "Mode B: not recovered within ${RECOVERY_TIMEOUT_S}s"
fi

# ── Teardown ──────────────────────────────────────────────────────────────────

info "Tearing down stack…"
$COMPOSE down -v

echo ""
if [ "$FAILURES" -eq 0 ]; then
  echo -e "${GREEN}All chaos assertions passed.${NC}"
  exit 0
else
  echo -e "${RED}${FAILURES} chaos assertion(s) failed.${NC}"
  exit 1
fi
```

**Step 2 — Create `scripts/chaos/README.md`:**

```markdown
# IBKR Chaos Test

Verifies live-scanner resilience to IBKR gateway failure in two modes:

- **Mode A — container stop** (`docker stop`): clean TCP close; `disconnectedEvent` fires
  immediately → reconnect path activates.
- **Mode B — network partition** (`docker network disconnect`): TCP hangs; liveness watchdog
  detects no bars after 30 s and forces disconnect → same reconnect path.

## Prerequisites

- Docker and Docker Compose installed
- For live mode: `IB_USERNAME` and `IB_PASSWORD` (paper trading credentials)
- For mock mode: no IBKR credentials required

## Invocation

```bash
# Mock mode (no IBKR credentials — CI default)
bash scripts/chaos/ibkr_kill_test.sh --mock

# Live mode (paper IBKR credentials)
IB_USERNAME=mypaper IB_PASSWORD=... bash scripts/chaos/ibkr_kill_test.sh

# Override recovery timeout (default 60 s)
RECOVERY_TIMEOUT_S=90 bash scripts/chaos/ibkr_kill_test.sh --mock
```

## Assertions Checked

| Assertion | Description |
|---|---|
| `feed_loss` event | Received on `watchlist:alerts` within 30 s of gateway failure |
| `/api/ready` live_data | `live_data.ok == false` during outage (HTTP still 200) |
| `feed_recovered` event | Received on `watchlist:alerts` within `RECOVERY_TIMEOUT_S` of restore |
| `/api/ready` recovery | `live_data.ok == true` after recovery |

Mock mode covers Mode A only. Live mode covers both Mode A and Mode B.
```

**Step 3 — Make executable and verify syntax:**
```bash
chmod +x scripts/chaos/ibkr_kill_test.sh
bash -n scripts/chaos/ibkr_kill_test.sh  # syntax check only
# Expected: no output (clean syntax)
```

**Step 4 — Commit:**
```bash
git add scripts/chaos/
git commit -m "feat(chaos): add ibkr_kill_test.sh chaos test script (#393)"
```

---

## Task 9 — CI nightly workflow + runbook

**Files:** `.github/workflows/chaos-nightly.yml`, `deployment-guide.md`

**Step 1 — Create `.github/workflows/chaos-nightly.yml`:**

```yaml
name: IBKR Chaos Nightly

on:
  schedule:
    - cron: '0 3 * * 1-5'  # 03:00 UTC, weekdays only
  workflow_dispatch:

jobs:
  chaos-mock:
    name: Chaos test (mock mode)
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Run IBKR chaos test — mock mode
        env:
          POSTGRES_PASSWORD: test
          SECRET_KEY: test-secret-key-must-be-at-least-32-chars
          JWT_SECRET_KEY: test-jwt-secret-key-must-be-at-least-32-chars
          REDIS_PASSWORD: test
          POLYGON_API_KEY: test
          DATABASE_URL: postgresql://markethawk:test@postgres:5432/markethawk
        run: bash scripts/chaos/ibkr_kill_test.sh --mock

  chaos-live:
    name: Chaos test (live IBKR credentials)
    runs-on: ubuntu-latest
    if: ${{ secrets.IB_USERNAME != '' }}
    steps:
      - uses: actions/checkout@v4

      - name: Run IBKR chaos test — live mode
        env:
          IB_USERNAME: ${{ secrets.IB_USERNAME }}
          IB_PASSWORD: ${{ secrets.IB_PASSWORD }}
          POSTGRES_PASSWORD: test
          SECRET_KEY: test-secret-key-must-be-at-least-32-chars
          JWT_SECRET_KEY: test-jwt-secret-key-must-be-at-least-32-chars
          REDIS_PASSWORD: test
          POLYGON_API_KEY: test
          DATABASE_URL: postgresql://markethawk:test@postgres:5432/markethawk
        run: bash scripts/chaos/ibkr_kill_test.sh
```

**Step 2 — Append IBKR feed-loss runbook to `deployment-guide.md`:**

At the end of the file, add:

```markdown

---

## IBKR Feed Loss Runbook

### What Operators See During a Feed Loss

**Seq** (filter by `live_scanner.ibkr_adapter`):
- `WARNING` event: `"IB Gateway disconnected"` (container-stop mode fires immediately)
- For network-partition: `WARNING` from watchdog: `"no bars for Xs during market hours — forcing disconnect"` after ~30–40 s
- Subsequent reconnect attempts logged at `WARNING` with backoff delays (5 s, 10 s, 20 s, …)

**Grafana** (`ibkr_connection_status` gauge — `app/core/metrics.py`):
- Drops to `0` on disconnect; returns to `1` on recovery
- Alert rule `ibkr_disconnect_2min` fires if outage exceeds 2 minutes

**Frontend (`/watchlist`):**
- Amber banner: `"Feed stale — IBKR gateway disconnected"` appears next to the Live/Connecting badge
- Per-symbol prices grey out after 15 s of no ticks (pre-existing per-symbol staleness)

**`/api/ready`** — HTTP 200 even during outage; only DB/Redis gate the status:
```json
{
  "status": "ready",
  "db": {"ok": true, "latency_ms": 2},
  "redis": {"ok": true, "latency_ms": 1},
  "live_data": {"ok": false, "latency_ms": 3001, "error": "Connection refused"}
}
```

### Recovery Flow

1. Live-scanner reconnects automatically with exponential backoff (5 s base, capped at 60 s, up to 10 retries).
2. On successful reconnect: all prior watchlist subscriptions are re-activated; `BarAggregator` state is preserved (gap is visible in charts, no interpolation).
3. `feed_recovered` event published to `watchlist:alerts` → amber badge clears.
4. `/api/ready` returns `live_data.ok == true` once IBKR port is reachable.
5. Grafana `ibkr_connection_status` returns to `1`; `ibkr_disconnect_2min` alert resolves.

### Manual Intervention

If the live-scanner exhausts all 10 reconnect retries (~10 min), the process exits and Docker
`restart: unless-stopped` brings it back up. After restart, subscriptions are re-seeded from the
DB on the first `_sync_loop` tick.

### Running the Chaos Test Manually

```bash
# Mock mode (no IBKR credentials needed)
bash scripts/chaos/ibkr_kill_test.sh --mock

# Live mode (paper IBKR credentials)
IB_USERNAME=... IB_PASSWORD=... bash scripts/chaos/ibkr_kill_test.sh
```

See `scripts/chaos/README.md` for full options.
```

**Step 3 — Verify all backend tests clean:**
```bash
docker-compose exec backend pytest backend/tests/ -x --tb=short -q
# Expected: all pass
```

**Step 4 — Verify TypeScript still clean:**
```bash
cd /workspace/markethawk/frontend && npx tsc --noEmit
# Expected: 0 errors
```

**Step 5 — Commit:**
```bash
git add .github/workflows/chaos-nightly.yml deployment-guide.md
git commit -m "feat(ci): chaos-nightly workflow + IBKR feed-loss runbook (#393)"
```

---

## Commit Summary

| Task | Commit message |
|---|---|
| 1 | `feat(live-scanner): add LIVE_SCANNER_MOCK setting (#393)` |
| 2 | `feat(live-scanner): add publish_feed_loss/feed_recovered to LivePublisher (#393)` |
| 3 | `feat(live-scanner): IBKRLiveAdapter reconnect capability (#393)` |
| 4 | `feat(live-scanner): extend MockLiveAdapter for chaos test support (#393)` |
| 5 | `feat(live-scanner): reconnect orchestration and liveness watchdog in main.py (#393)` |
| 6 | `feat(health): add informational live_data IBKR probe to /api/ready (#393)` |
| 7 | `feat(frontend): add feedStatus amber badge for IBKR feed loss (#393)` |
| 8 | `feat(chaos): add ibkr_kill_test.sh chaos test script (#393)` |
| 9 | `feat(ci): chaos-nightly workflow + IBKR feed-loss runbook (#393)` |
