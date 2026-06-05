# Circuit Breakers + Outbound Request Timeouts — Implementation Plan

**Date:** 2026-06-05
**Status:** Plan generated — pending architect review
**Issue:** #205
**Spec:** docs/superpowers/specs/2026-06-05-circuit-breakers-timeout-design.md

## Goal

Add `pybreaker` circuit breakers around the Polygon (`MassiveDataProvider`) and IBKR (`IBKRDataProvider`) providers so a slow or failing external provider fails fast instead of tying up Celery workers. Make Polygon SDK timeouts explicit and configurable in `Settings`. Add httpx OTel auto-instrumentation to surface httpx call latency in Jaeger.

## Architecture

- **Central circuit breaker module** — `backend/app/core/circuit_breakers.py` (new) holds two `pybreaker.CircuitBreaker` instances (`POLYGON_BREAKER`, `IBKR_BREAKER`) built from `Settings` at import time.
- **MassiveDataProvider** (`backend/app/providers/massive.py`) — receives explicit `connect_timeout` and `read_timeout` from `Settings`; the three BaseDataProvider interface methods (`get_bars`, `get_snapshots`, `get_ticker_details`) each extract their Polygon call into a private `_impl` method and wrap via `POLYGON_BREAKER.call()`.
- **IBKRDataProvider** (`backend/app/providers/ibkr.py`) — `get_futures_contracts` and `get_futures_bars` extract their bodies into private `_impl` async methods and wrap via `await IBKR_BREAKER.call()`. `CircuitBreakerError` is caught and converted to `ProviderError(is_retryable=False)` in the public method so the existing graceful-degradation in `stock_data.py` handles it unchanged.
- **Settings** (`backend/app/core/config.py`) — six new fields (two Polygon timeouts, two Polygon breaker params, two IBKR breaker params), all with defaults matching the current implicit values.
- **OTel** (`backend/app/core/tracing.py`) — `HTTPXClientInstrumentor().instrument()` added inside `setup_otel()` after `CeleryInstrumentor().instrument()`, gated on the existing `if not endpoint: return` guard.
- **In-process only** — circuit breaker state is per-worker and is intentionally lost on restart.

## Tech Stack (new dependencies)

| Package | Version | Purpose |
|---------|---------|---------|
| `pybreaker` | `>=1.0` | Circuit breaker for Polygon + IBKR |
| `opentelemetry-instrumentation-httpx` | `==0.63b1` | httpx OTel instrumentation (matches existing `0.63b1` suffix) |

## File Structure

| File | Action |
|------|--------|
| `backend/requirements.txt` | Add `pybreaker>=1.0` and `opentelemetry-instrumentation-httpx==0.63b1` |
| `backend/app/core/config.py` | Add 6 new Settings fields (no validators — plain fields with defaults) |
| `backend/app/core/circuit_breakers.py` | **New** — `POLYGON_BREAKER` and `IBKR_BREAKER` module-level singletons |
| `backend/app/providers/massive.py` | Pass timeouts to `RESTClient`; refactor `get_bars`, `get_snapshots`, `get_ticker_details` |
| `backend/app/providers/ibkr.py` | Refactor `get_futures_bars`, `get_futures_contracts` with IBKR circuit breaker |
| `backend/app/core/tracing.py` | Add `HTTPXClientInstrumentor().instrument()` to `setup_otel()` |
| `backend/tests/core/test_circuit_breakers.py` | **New** — circuit breaker instance tests |
| `backend/tests/core/test_tracing.py` | Add httpx instrumentation test |
| `backend/tests/providers/test_massive_provider.py` | **New** — timeout wiring + circuit breaker tests |
| `backend/tests/providers/test_ibkr_circuit_breaker.py` | **New** — IBKR circuit breaker tests |

---

## Task 1: Add circuit breaker and timeout Settings fields

**Files:** `backend/app/core/config.py`, `backend/tests/core/test_config.py`

No field validators are added — these are plain fields with defaults, so no `conftest.py` changes are needed.

### TDD Steps

**1a. Write the failing tests — append to `backend/tests/core/test_config.py`:**

```python
def test_polygon_timeout_defaults():
    s = Settings()
    assert s.POLYGON_CONNECT_TIMEOUT == 10.0
    assert s.POLYGON_READ_TIMEOUT == 10.0


def test_circuit_breaker_polygon_defaults():
    s = Settings()
    assert s.CIRCUIT_BREAKER_POLYGON_FAIL_MAX == 5
    assert s.CIRCUIT_BREAKER_POLYGON_RESET_TIMEOUT == 60


def test_circuit_breaker_ibkr_defaults():
    s = Settings()
    assert s.CIRCUIT_BREAKER_IBKR_FAIL_MAX == 3
    assert s.CIRCUIT_BREAKER_IBKR_RESET_TIMEOUT == 120


def test_polygon_timeout_env_override():
    s = Settings(POLYGON_CONNECT_TIMEOUT=5.0, POLYGON_READ_TIMEOUT=30.0)
    assert s.POLYGON_CONNECT_TIMEOUT == 5.0
    assert s.POLYGON_READ_TIMEOUT == 30.0
```

**1b. Confirm failure:**
```bash
docker-compose exec backend python -m pytest tests/core/test_config.py -x -q 2>&1 | tail -10
# Expected: AttributeError: 'Settings' object has no attribute 'POLYGON_CONNECT_TIMEOUT'
```

**1c. Implement — add to `backend/app/core/config.py` inside `Settings`, after the `IBKR_TRADING_CLIENT_ID` line:**

```python
    # ── Polygon HTTP Timeouts ──────────────────────────────────────────────
    POLYGON_CONNECT_TIMEOUT: float = 10.0
    POLYGON_READ_TIMEOUT: float = 10.0

    # ── Circuit Breakers ───────────────────────────────────────────────────
    CIRCUIT_BREAKER_POLYGON_FAIL_MAX: int = 5
    CIRCUIT_BREAKER_POLYGON_RESET_TIMEOUT: int = 60
    CIRCUIT_BREAKER_IBKR_FAIL_MAX: int = 3
    CIRCUIT_BREAKER_IBKR_RESET_TIMEOUT: int = 120
```

**1d. Confirm pass:**
```bash
docker-compose exec backend python -m pytest tests/core/test_config.py -x -q 2>&1 | tail -10
# Expected: all tests pass
```

**1e. Validate backend reload — no regressions:**
```bash
docker-compose logs backend --tail=10
# Expected: no import errors
docker-compose exec backend python -m pytest tests/ -x -q 2>&1 | tail -10
# Expected: all tests pass
```

**1f. Commit:**
```bash
git add backend/app/core/config.py backend/tests/core/test_config.py
git commit -m "feat(config): add Polygon timeout and circuit breaker Settings fields (#205)"
```

---

## Task 2: Create `core/circuit_breakers.py` and add `pybreaker`

**Files:** `backend/requirements.txt`, `backend/app/core/circuit_breakers.py`, `backend/tests/core/test_circuit_breakers.py`

### TDD Steps

**2a. Add `pybreaker>=1.0` to `backend/requirements.txt` — insert after the `prometheus-client` line:**

```
# Circuit Breakers
pybreaker>=1.0
```

**2b. Install in the container:**
```bash
docker-compose exec backend pip install "pybreaker>=1.0"
# Expected: Successfully installed pybreaker-X.X.X
```

**2c. Write the failing test — create `backend/tests/core/test_circuit_breakers.py`:**

```python
# backend/tests/core/test_circuit_breakers.py
"""Tests for centralized pybreaker circuit breaker instances."""
import pybreaker
import pytest


def test_polygon_breaker_is_circuit_breaker():
    from app.core.circuit_breakers import POLYGON_BREAKER
    assert isinstance(POLYGON_BREAKER, pybreaker.CircuitBreaker)


def test_ibkr_breaker_is_circuit_breaker():
    from app.core.circuit_breakers import IBKR_BREAKER
    assert isinstance(IBKR_BREAKER, pybreaker.CircuitBreaker)


def test_polygon_breaker_name():
    from app.core.circuit_breakers import POLYGON_BREAKER
    assert POLYGON_BREAKER.name == "polygon"


def test_ibkr_breaker_name():
    from app.core.circuit_breakers import IBKR_BREAKER
    assert IBKR_BREAKER.name == "ibkr"


def test_polygon_breaker_fail_max_matches_settings():
    from app.core.circuit_breakers import POLYGON_BREAKER
    from app.core.config import settings
    assert POLYGON_BREAKER.fail_max == settings.CIRCUIT_BREAKER_POLYGON_FAIL_MAX


def test_ibkr_breaker_fail_max_matches_settings():
    from app.core.circuit_breakers import IBKR_BREAKER
    from app.core.config import settings
    assert IBKR_BREAKER.fail_max == settings.CIRCUIT_BREAKER_IBKR_FAIL_MAX


def test_polygon_breaker_trips_after_fail_max_failures():
    """After fail_max consecutive failures the circuit opens."""
    from app.core.circuit_breakers import POLYGON_BREAKER

    POLYGON_BREAKER.reset()

    def _always_fail():
        raise RuntimeError("Polygon down")

    for _ in range(POLYGON_BREAKER.fail_max):
        with pytest.raises(RuntimeError):
            POLYGON_BREAKER.call(_always_fail)

    assert POLYGON_BREAKER.current_state == "open"

    with pytest.raises(pybreaker.CircuitBreakerError):
        POLYGON_BREAKER.call(_always_fail)

    POLYGON_BREAKER.reset()


def test_ibkr_breaker_resets_to_closed():
    from app.core.circuit_breakers import IBKR_BREAKER
    IBKR_BREAKER.reset()
    assert IBKR_BREAKER.current_state == "closed"
```

**2d. Confirm failure:**
```bash
docker-compose exec backend python -m pytest tests/core/test_circuit_breakers.py -x -q 2>&1 | tail -10
# Expected: ModuleNotFoundError: No module named 'app.core.circuit_breakers'
```

**2e. Implement — create `backend/app/core/circuit_breakers.py`:**

```python
"""
Centralized circuit breaker instances for external provider calls.

One CircuitBreaker per external provider (coarse-grained). Both instances
are module-level singletons so tests can reset them via POLYGON_BREAKER.reset()
and IBKR_BREAKER.reset() without reimporting.
"""
import pybreaker

from app.core.config import settings

POLYGON_BREAKER: pybreaker.CircuitBreaker = pybreaker.CircuitBreaker(
    fail_max=settings.CIRCUIT_BREAKER_POLYGON_FAIL_MAX,
    reset_timeout=settings.CIRCUIT_BREAKER_POLYGON_RESET_TIMEOUT,
    name="polygon",
)

IBKR_BREAKER: pybreaker.CircuitBreaker = pybreaker.CircuitBreaker(
    fail_max=settings.CIRCUIT_BREAKER_IBKR_FAIL_MAX,
    reset_timeout=settings.CIRCUIT_BREAKER_IBKR_RESET_TIMEOUT,
    name="ibkr",
)
```

**2f. Confirm pass:**
```bash
docker-compose exec backend python -m pytest tests/core/test_circuit_breakers.py -x -q 2>&1 | tail -10
# Expected: 8 tests pass
```

**2g. Full test suite — no regressions:**
```bash
docker-compose exec backend python -m pytest tests/ -x -q 2>&1 | tail -10
# Expected: all tests pass
docker-compose logs backend --tail=10
# Expected: no import errors
```

**2h. Commit:**
```bash
git add backend/requirements.txt backend/app/core/circuit_breakers.py backend/tests/core/test_circuit_breakers.py
git commit -m "feat(core): add circuit_breakers.py with POLYGON_BREAKER and IBKR_BREAKER (#205)"
```

---

## Task 3: Wrap `MassiveDataProvider` with explicit timeouts and circuit breaker

**Files:** `backend/app/providers/massive.py`, `backend/tests/providers/test_massive_provider.py`

The three BaseDataProvider interface methods (`get_bars`, `get_snapshots`, `get_ticker_details`) are refactored to extract the inner Polygon call into a private `_impl` method, then wrap via `POLYGON_BREAKER.call()`. The public method catches `CircuitBreakerError` → `ProviderError(is_retryable=False)`. All callers in `stock_data.py` wrap provider calls in `except Exception` so this new `ProviderError` path degrades gracefully without any changes to service-layer code.

### TDD Steps

**3a. Write the failing tests — create `backend/tests/providers/test_massive_provider.py`:**

```python
# backend/tests/providers/test_massive_provider.py
"""Tests for MassiveDataProvider timeout wiring and circuit breaker integration."""
from unittest.mock import MagicMock, patch

import pybreaker
import pytest

from app.core.config import Settings
from app.exceptions import ProviderError
from app.providers.massive import MassiveDataProvider


def _make_provider(client=None):
    p = MassiveDataProvider.__new__(MassiveDataProvider)
    p._client = client or MagicMock()
    return p


# ── Timeout wiring ────────────────────────────────────────────────────────────

def test_init_client_passes_connect_timeout():
    """_init_client() must forward POLYGON_CONNECT_TIMEOUT to RESTClient."""
    mock_settings = Settings(
        DATABASE_URL="postgresql://test:test@localhost/test",
        POLYGON_API_KEY="test-key",
        JWT_SECRET_KEY="test-jwt-secret-key-for-unit-tests-only-aaa",
        POLYGON_CONNECT_TIMEOUT=7.5,
        POLYGON_READ_TIMEOUT=10.0,
    )
    with patch("app.providers.massive.settings", mock_settings), \
         patch("app.providers.massive.RESTClient") as mock_client:
        MassiveDataProvider()
        call_kwargs = mock_client.call_args.kwargs
        assert call_kwargs["connect_timeout"] == 7.5


def test_init_client_passes_read_timeout():
    """_init_client() must forward POLYGON_READ_TIMEOUT to RESTClient."""
    mock_settings = Settings(
        DATABASE_URL="postgresql://test:test@localhost/test",
        POLYGON_API_KEY="test-key",
        JWT_SECRET_KEY="test-jwt-secret-key-for-unit-tests-only-aaa",
        POLYGON_CONNECT_TIMEOUT=10.0,
        POLYGON_READ_TIMEOUT=25.0,
    )
    with patch("app.providers.massive.settings", mock_settings), \
         patch("app.providers.massive.RESTClient") as mock_client:
        MassiveDataProvider()
        call_kwargs = mock_client.call_args.kwargs
        assert call_kwargs["read_timeout"] == 25.0


# ── Circuit breaker: get_bars ─────────────────────────────────────────────────

def test_get_bars_raises_provider_error_when_circuit_open():
    """Tripped Polygon circuit → ProviderError(is_retryable=False) from get_bars."""
    from app.core.circuit_breakers import POLYGON_BREAKER
    POLYGON_BREAKER.reset()
    p = _make_provider()

    with patch.object(p, "_get_bars_impl", side_effect=RuntimeError("Polygon down")):
        for _ in range(POLYGON_BREAKER.fail_max):
            with pytest.raises((ProviderError, RuntimeError)):
                p.get_bars("AAPL", "minute", 1, "2026-01-01", "2026-01-31")

    with pytest.raises(ProviderError) as exc_info:
        p.get_bars("AAPL", "minute", 1, "2026-01-01", "2026-01-31")

    assert exc_info.value.is_retryable is False
    POLYGON_BREAKER.reset()


def test_get_bars_raises_retryable_provider_error_on_non_circuit_failure():
    """Transient Polygon failures (circuit closed) raise ProviderError(is_retryable=True)."""
    from app.core.circuit_breakers import POLYGON_BREAKER
    POLYGON_BREAKER.reset()
    p = _make_provider()
    p._client.get_aggs.side_effect = RuntimeError("transient error")

    with pytest.raises(ProviderError) as exc_info:
        p.get_bars("AAPL", "minute", 1, "2026-01-01", "2026-01-31")

    assert exc_info.value.is_retryable is True
    POLYGON_BREAKER.reset()


# ── Circuit breaker: get_ticker_details ───────────────────────────────────────

def test_get_ticker_details_raises_provider_error_when_circuit_open():
    """Tripped Polygon circuit → ProviderError(is_retryable=False) from get_ticker_details."""
    from app.core.circuit_breakers import POLYGON_BREAKER
    POLYGON_BREAKER.reset()
    p = _make_provider()

    with patch.object(p, "_get_ticker_details_impl", side_effect=RuntimeError("Polygon down")):
        for _ in range(POLYGON_BREAKER.fail_max):
            with pytest.raises(Exception):
                p.get_ticker_details("AAPL")

    with pytest.raises(ProviderError) as exc_info:
        p.get_ticker_details("AAPL")

    assert exc_info.value.is_retryable is False
    POLYGON_BREAKER.reset()


def test_get_ticker_details_returns_empty_dict_on_transient_error():
    """Non-circuit Polygon errors in get_ticker_details degrade to {} (existing behaviour)."""
    from app.core.circuit_breakers import POLYGON_BREAKER
    POLYGON_BREAKER.reset()
    p = _make_provider()
    p._client.get_ticker_details.side_effect = RuntimeError("transient")

    result = p.get_ticker_details("AAPL")
    assert result == {}
    POLYGON_BREAKER.reset()


# ── Circuit breaker: get_snapshots ────────────────────────────────────────────

def test_get_snapshots_raises_provider_error_when_circuit_open():
    """Tripped Polygon circuit → ProviderError(is_retryable=False) from get_snapshots."""
    from app.core.circuit_breakers import POLYGON_BREAKER
    POLYGON_BREAKER.reset()
    p = _make_provider()

    with patch.object(p, "_fetch_snapshots_raw", side_effect=RuntimeError("Polygon down")):
        for _ in range(POLYGON_BREAKER.fail_max):
            with pytest.raises(Exception):
                p.get_snapshots()

    with pytest.raises(ProviderError) as exc_info:
        p.get_snapshots()

    assert exc_info.value.is_retryable is False
    POLYGON_BREAKER.reset()


def test_get_snapshots_returns_empty_list_on_transient_error():
    """Non-circuit Polygon errors in get_snapshots degrade to [] (existing behaviour)."""
    from app.core.circuit_breakers import POLYGON_BREAKER
    POLYGON_BREAKER.reset()
    p = _make_provider()
    p._client.get_snapshot_all.side_effect = RuntimeError("transient")

    result = p.get_snapshots()
    assert result == []
    POLYGON_BREAKER.reset()
```

**3b. Confirm failure:**
```bash
docker-compose exec backend python -m pytest tests/providers/test_massive_provider.py -x -q 2>&1 | tail -10
# Expected: AttributeError — _get_bars_impl, _get_ticker_details_impl, _fetch_snapshots_raw don't exist yet
```

**3c-i. Update imports in `backend/app/providers/massive.py` — add after existing imports:**

```python
import pybreaker

from app.core.circuit_breakers import POLYGON_BREAKER
```

**3c-ii. Update `_init_client()` to pass explicit timeouts — replace the `RESTClient(...)` call:**

```python
    def _init_client(self):
        if settings.POLYGON_API_KEY:
            try:
                self._client = RESTClient(
                    settings.POLYGON_API_KEY,
                    connect_timeout=settings.POLYGON_CONNECT_TIMEOUT,
                    read_timeout=settings.POLYGON_READ_TIMEOUT,
                )
                logger.info("MassiveDataProvider: Polygon client initialized.")
            except Exception as e:
                logger.error(f"MassiveDataProvider: Failed to init Polygon client: {e}")
                self._client = None
        else:
            logger.warning(
                "MassiveDataProvider: POLYGON_API_KEY not set — provider disabled."
            )
```

**3c-iii. Refactor `get_bars()` — extract `_get_bars_impl` and wrap with POLYGON_BREAKER:**

Add `_get_bars_impl` as a new private method immediately before `get_bars`. Move the existing pagination loop body into it (the `_convert` helper + the `while True:` loop with all its logic). The existing `try/except Exception` in `get_bars` becomes the non-circuit-breaker handler in the public method:

```python
    def _get_bars_impl(
        self,
        symbol: str,
        timespan: str,
        multiplier: int,
        from_date: str,
        to_date: str,
        adjusted: bool,
        sort: str,
        limit: int,
        paginate: bool,
    ) -> List[Dict[str, Any]]:
        """Polygon pagination loop — called via POLYGON_BREAKER.call() in get_bars()."""
        def _convert(agg) -> Dict[str, Any]:
            return {
                "timestamp": datetime.fromtimestamp(
                    agg.timestamp / 1000, tz=timezone.utc
                ),
                "open": agg.open,
                "high": agg.high,
                "low": agg.low,
                "close": agg.close,
                "volume": agg.volume,
                "vwap": getattr(agg, "vwap", None),
                "transactions": getattr(agg, "transactions", None),
            }

        all_bars: List[Dict[str, Any]] = []
        current_from: Any = from_date  # str on first call, int (ms) on subsequent calls

        while True:
            polygon_api_calls_total.labels(endpoint="aggs").inc()
            page = self._client.get_aggs(
                ticker=symbol.upper(),
                multiplier=multiplier,
                timespan=timespan,
                from_=current_from,
                to=to_date,
                adjusted=adjusted,
                sort=sort,
                limit=limit,
            )

            if not page:
                break

            all_bars.extend(_convert(agg) for agg in page)

            if not paginate or len(page) < limit:
                break  # single-page mode, or partial page means no more data

            current_from = page[-1].timestamp + 1

        if all_bars:
            logger.debug(
                f"MassiveDataProvider: {symbol} {timespan} fetched "
                f"{len(all_bars)} bars in total"
            )
        return all_bars

    def get_bars(
        self,
        symbol: str,
        timespan: str,
        multiplier: int,
        from_date: str,
        to_date: str,
        adjusted: bool = True,
        sort: str = "asc",
        limit: int = 50000,
        paginate: bool = False,
        **kwargs,
    ) -> List[Dict[str, Any]]:
        """
        Fetch OHLCV bars from Polygon.io with automatic pagination.

        Polygon's /v2/aggs endpoint returns at most `limit` bars per call and
        provides no next_url cursor.  When a full page arrives we advance
        `from_` to last_bar.timestamp + 1 ms and fetch again until a partial
        page signals the end of available data.
        """
        if not self._client:
            logger.error("MassiveDataProvider: client not initialized.")
            return []

        try:
            return POLYGON_BREAKER.call(
                self._get_bars_impl,
                symbol, timespan, multiplier, from_date, to_date,
                adjusted, sort, limit, paginate,
            )
        except pybreaker.CircuitBreakerError as e:
            raise ProviderError(
                f"Polygon circuit breaker open: {e}",
                provider="massive",
                endpoint="get_bars",
                is_retryable=False,
            ) from e
        except Exception as e:
            logger.exception(
                f"❌ Polygon fetch FAILED for {symbol} {timespan}×{multiplier} "
                f"({from_date} → {to_date}): {e}"
            )
            raise ProviderError(
                f"Polygon fetch failed for {symbol} {timespan}×{multiplier}: {e}",
                provider="massive",
                endpoint="get_aggs",
                is_retryable=True,
            ) from e
```

**3c-iv. Refactor `get_ticker_details()` — extract `_get_ticker_details_impl` and wrap:**

```python
    def _get_ticker_details_impl(self, symbol: str) -> Dict[str, Any]:
        """Raw Polygon call — called via POLYGON_BREAKER.call() in get_ticker_details()."""
        polygon_api_calls_total.labels(endpoint="ticker_details").inc()
        details = self._client.get_ticker_details(symbol.upper())
        if not details:
            return {}
        return {
            "name": details.name,
            "sector": getattr(details, "sic_description", "") or "",
            "industry": getattr(details, "sic_description", "") or "",
            "market_cap": getattr(details, "market_cap", None),
            "description": getattr(details, "description", None),
        }

    def get_ticker_details(self, symbol: str) -> Dict[str, Any]:
        """Fetch fundamental / reference info from Polygon."""
        if not self._client:
            return {}
        try:
            return POLYGON_BREAKER.call(self._get_ticker_details_impl, symbol)
        except pybreaker.CircuitBreakerError as e:
            raise ProviderError(
                f"Polygon circuit breaker open: {e}",
                provider="massive",
                endpoint="get_ticker_details",
                is_retryable=False,
            ) from e
        except Exception as e:
            logger.error(
                f"MassiveDataProvider: Error fetching details for {symbol}: {e}"
            )
            return {}
```

**3c-v. Refactor `get_snapshots()` — extract `_fetch_snapshots_raw` and wrap only the Polygon call:**

```python
    def _fetch_snapshots_raw(self) -> list:
        """Raw Polygon snapshot call — called via POLYGON_BREAKER.call() in get_snapshots()."""
        polygon_api_calls_total.labels(endpoint="snapshot_all").inc()
        return self._client.get_snapshot_all(market_type="stocks") or []

    def get_snapshots(
        self, symbols: Optional[List[str]] = None
    ) -> List[Dict[str, Any]]:
        """
        Fetch market snapshots from Polygon and return normalized dicts.

        Normalization (volume extraction, change_pct, prev_close) lives here
        so callers never need to inspect raw Polygon snapshot objects.
        """
        if not self._client:
            return []
        try:
            raw = POLYGON_BREAKER.call(self._fetch_snapshots_raw)
        except pybreaker.CircuitBreakerError as e:
            raise ProviderError(
                f"Polygon circuit breaker open: {e}",
                provider="massive",
                endpoint="get_snapshots",
                is_retryable=False,
            ) from e
        except Exception as e:
            logger.error(f"MassiveDataProvider: Error fetching snapshots: {e}")
            return []

        # Build a lookup set for optional symbol filtering
        filter_set = {s.upper() for s in symbols} if symbols else None

        results: List[Dict[str, Any]] = []
        for s in raw:
            if not hasattr(s, "ticker") or not hasattr(s, "prev_day"):
                continue
            if filter_set and s.ticker not in filter_set:
                continue

            day_vol = getattr(s.day, "volume", 0) or 0
            min_acc_vol = getattr(s.min, "accumulated_volume", 0) or 0
            volume = max(day_vol, min_acc_vol)

            prev_close = getattr(s.prev_day, "close", 0) or getattr(s.prev_day, "c", 0)
            if prev_close == 0:
                continue

            current_price = (
                getattr(s.min, "close", 0)
                or getattr(s.last_trade, "price", 0)
                or getattr(s.last_trade, "p", 0)
            )
            if current_price == 0:
                continue

            results.append(
                {
                    "ticker": s.ticker,
                    "price": float(current_price),
                    "change_pct": float(getattr(s, "todays_change_percent", 0) or 0),
                    "change_value": float(getattr(s, "todays_change", 0) or 0),
                    "volume": int(volume),
                    "prev_close": float(prev_close),
                }
            )

        return results
```

**3d. Confirm new tests pass:**
```bash
docker-compose exec backend python -m pytest tests/providers/test_massive_provider.py -x -q 2>&1 | tail -10
# Expected: all 8 tests pass
```

**3e. Confirm pagination regression tests still pass:**
```bash
docker-compose exec backend python -m pytest tests/providers/test_get_historical_bars_pagination.py -x -q 2>&1 | tail -10
# Expected: all tests pass (pagination behavior preserved in _get_bars_impl)
```

**3f. Full test suite:**
```bash
docker-compose exec backend python -m pytest tests/ -x -q 2>&1 | tail -10
# Expected: all tests pass
docker-compose logs backend --tail=10
# Expected: "Polygon client initialized" — no import errors
```

**3g. Commit:**
```bash
git add backend/app/providers/massive.py backend/tests/providers/test_massive_provider.py
git commit -m "feat(providers): wrap MassiveDataProvider with explicit timeouts and Polygon circuit breaker (#205)"
```

---

## Task 4: Wrap `IBKRDataProvider` futures methods with IBKR circuit breaker

**Files:** `backend/app/providers/ibkr.py`, `backend/tests/providers/test_ibkr_circuit_breaker.py`

`get_futures_contracts` and `get_futures_bars` are each refactored: their entire bodies move into private `_impl` async methods, and the public methods become thin wrappers that call `await IBKR_BREAKER.call(self._impl, ...)` and convert `CircuitBreakerError` to `ProviderError(is_retryable=False)`. pybreaker 1.x detects coroutine functions via `asyncio.iscoroutinefunction` and returns an awaitable from `.call()`.

### TDD Steps

**4a. Write the failing tests — create `backend/tests/providers/test_ibkr_circuit_breaker.py`:**

```python
# backend/tests/providers/test_ibkr_circuit_breaker.py
"""Tests for IBKRDataProvider circuit breaker wrapping."""
import asyncio
from unittest.mock import AsyncMock, patch

import pybreaker
import pytest

from app.core.circuit_breakers import IBKR_BREAKER
from app.exceptions import ProviderError
from app.providers.ibkr import IBKRDataProvider


def _make_provider():
    return IBKRDataProvider.__new__(IBKRDataProvider)


def test_get_futures_contracts_raises_provider_error_when_circuit_open():
    """Tripped IBKR circuit → ProviderError(is_retryable=False) from get_futures_contracts."""
    IBKR_BREAKER.reset()
    p = _make_provider()

    async def _run():
        with patch.object(
            p,
            "_get_futures_contracts_impl",
            new=AsyncMock(side_effect=RuntimeError("IBKR down")),
        ):
            for _ in range(IBKR_BREAKER.fail_max):
                with pytest.raises(Exception):
                    await p.get_futures_contracts("ES", "CME")

        with pytest.raises(ProviderError) as exc_info:
            await p.get_futures_contracts("ES", "CME")

        assert exc_info.value.is_retryable is False

    asyncio.run(_run())
    IBKR_BREAKER.reset()


def test_get_futures_bars_raises_provider_error_when_circuit_open():
    """Tripped IBKR circuit → ProviderError(is_retryable=False) from get_futures_bars."""
    IBKR_BREAKER.reset()
    p = _make_provider()

    async def _run():
        with patch.object(
            p,
            "_get_futures_bars_impl",
            new=AsyncMock(side_effect=RuntimeError("IBKR down")),
        ):
            for _ in range(IBKR_BREAKER.fail_max):
                with pytest.raises(Exception):
                    await p.get_futures_bars("ES", "CME", "20260101")

        with pytest.raises(ProviderError) as exc_info:
            await p.get_futures_bars("ES", "CME", "20260101")

        assert exc_info.value.is_retryable is False

    asyncio.run(_run())
    IBKR_BREAKER.reset()


def test_ibkr_breaker_resets_to_closed():
    IBKR_BREAKER.reset()
    assert IBKR_BREAKER.current_state == "closed"
```

**4b. Confirm failure:**
```bash
docker-compose exec backend python -m pytest tests/providers/test_ibkr_circuit_breaker.py -x -q 2>&1 | tail -10
# Expected: AttributeError — _get_futures_contracts_impl / _get_futures_bars_impl don't exist
```

**4c-i. Add imports to `backend/app/providers/ibkr.py` — after existing imports:**

```python
import pybreaker

from app.core.circuit_breakers import IBKR_BREAKER
```

**4c-ii. Rename `get_futures_contracts` → `_get_futures_contracts_impl` (add underscore, rename body, keep entire content unchanged). Then add the new public `get_futures_contracts` wrapper immediately after:**

```python
    async def _get_futures_contracts_impl(
        self,
        symbol: str,
        exchange: str,
        include_expired: bool = True,
    ) -> List[Dict[str, Any]]:
        """Inner implementation — called via IBKR_BREAKER.call() in get_futures_contracts()."""
        # [existing body of get_futures_contracts verbatim — no changes]
        if not IB_INSYNC_AVAILABLE:
            return []

        ib = await self._get_connection()
        if not ib:
            raise ProviderError(
                "IBKR connection not available",
                provider="ibkr",
                endpoint="get_futures_contracts",
                is_retryable=True,
            )

        template = Future(symbol=symbol.upper(), exchange=exchange.upper())
        template.includeExpired = include_expired

        try:
            details: List[ContractDetails] = await asyncio.wait_for(
                ib.reqContractDetailsAsync(template),
                timeout=30,
            )
        except Exception as e:
            logger.error(
                f"IBKRDataProvider: get_futures_contracts failed for {symbol}: {e}"
            )
            raise ProviderError(
                f"get_futures_contracts failed for {symbol}: {e}",
                provider="ibkr",
                endpoint="reqContractDetails",
                is_retryable=True,
            ) from e

        now = datetime.now(timezone.utc)
        contracts = []
        for cd in details:
            c = cd.contract
            expiry_str = c.lastTradeDateOrContractMonth
            if not expiry_str:
                continue
            expiry_8 = expiry_str.ljust(8, "0")[:8]
            try:
                expiry_dt = datetime.strptime(expiry_8, "%Y%m%d").replace(
                    tzinfo=timezone.utc
                )
            except ValueError:
                continue
            contracts.append(
                {
                    "contract_month": expiry_8,
                    "expiry": expiry_dt.strftime("%Y-%m-%d"),
                    "con_id": c.conId,
                    "exchange": c.exchange or exchange.upper(),
                    "is_expired": expiry_dt < now,
                }
            )
        contracts.sort(key=lambda x: x["contract_month"])
        logger.info(
            f"IBKRDataProvider: Found {len(contracts)} contract months for {symbol}"
        )
        return contracts

    async def get_futures_contracts(
        self,
        symbol: str,
        exchange: str,
        include_expired: bool = True,
    ) -> List[Dict[str, Any]]:
        """
        Return all available contract months for a futures symbol.

        Each dict contains:
            {
                "contract_month": "YYYYMMDD",
                "expiry":         "YYYY-MM-DD",
                "con_id":         int,
                "exchange":       str,
                "is_expired":     bool,
            }
        """
        try:
            return await IBKR_BREAKER.call(
                self._get_futures_contracts_impl, symbol, exchange, include_expired
            )
        except pybreaker.CircuitBreakerError as e:
            raise ProviderError(
                f"IBKR circuit breaker open: {e}",
                provider="ibkr",
                endpoint="get_futures_contracts",
                is_retryable=False,
            ) from e
```

**4c-iii. Rename `get_futures_bars` → `_get_futures_bars_impl` (keep entire body unchanged). Add the new public `get_futures_bars` wrapper immediately after:**

```python
    async def _get_futures_bars_impl(
        self,
        symbol: str,
        exchange: str,
        contract_month: str,
        timespan: str = "day",
        multiplier: int = 1,
        what_to_show: str = "TRADES",
        use_rth: bool = False,
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Inner implementation — called via IBKR_BREAKER.call() in get_futures_bars()."""
        # [existing body of get_futures_bars verbatim — no changes]
        if not IB_INSYNC_AVAILABLE:
            return []

        ib = await self._get_connection()
        if not ib:
            raise ProviderError(
                "IBKR connection not available",
                provider="ibkr",
                endpoint="get_futures_bars",
                is_retryable=True,
            )

        bar_size = self._resolve_bar_size(timespan, multiplier)

        contract = Future(
            symbol=symbol.upper(),
            lastTradeDateOrContractMonth=contract_month,
            exchange=exchange.upper(),
        )
        contract.includeExpired = True

        try:
            qualified = await asyncio.wait_for(
                ib.qualifyContractsAsync(contract),
                timeout=30,
            )
            if not qualified:
                raise ProviderError(
                    f"Could not qualify {symbol} {contract_month}",
                    provider="ibkr",
                    endpoint="qualifyContracts",
                    is_retryable=False,
                )
            contract = qualified[0]
        except asyncio.TimeoutError as e:
            raise ProviderError(
                f"qualifyContracts timed out for {symbol} {contract_month}",
                provider="ibkr",
                endpoint="qualifyContracts",
                is_retryable=True,
            ) from e
        except ProviderError:
            raise
        except Exception as e:
            raise ProviderError(
                f"qualify failed for {symbol} {contract_month}: {e}",
                provider="ibkr",
                endpoint="qualifyContracts",
                is_retryable=True,
            ) from e

        return await self._fetch_bars_chunked(
            contract=contract,
            bar_size=bar_size,
            from_date=from_date,
            to_date=to_date,
            what_to_show=what_to_show,
            use_rth=use_rth,
        )

    async def get_futures_bars(
        self,
        symbol: str,
        exchange: str,
        contract_month: str,
        timespan: str = "day",
        multiplier: int = 1,
        what_to_show: str = "TRADES",
        use_rth: bool = False,
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Fetch OHLCV bars for a specific futures contract month.

        Args:
            symbol:         Root symbol, e.g. "ES".
            exchange:       Exchange, e.g. "CME", "COMEX".
            contract_month: YYYYMMDD string (lastTradeDateOrContractMonth).
            timespan:       Bar size ("day", "hour", "minute", etc.).
            multiplier:     Bar multiplier.
            what_to_show:   IBKR data type ("TRADES", "MIDPOINT", etc.).
            use_rth:        If True, only regular trading hours.
            from_date:      Start date "YYYY-MM-DD". If None, uses max lookback.
            to_date:        End date "YYYY-MM-DD". If None, uses today.
        """
        try:
            return await IBKR_BREAKER.call(
                self._get_futures_bars_impl,
                symbol, exchange, contract_month, timespan, multiplier,
                what_to_show, use_rth, from_date, to_date,
            )
        except pybreaker.CircuitBreakerError as e:
            raise ProviderError(
                f"IBKR circuit breaker open: {e}",
                provider="ibkr",
                endpoint="get_futures_bars",
                is_retryable=False,
            ) from e
```

**4d. Confirm new tests pass:**
```bash
docker-compose exec backend python -m pytest tests/providers/test_ibkr_circuit_breaker.py -x -q 2>&1 | tail -10
# Expected: 3 tests pass
```

**4e. Confirm existing IBKR sync interface tests still pass:**
```bash
docker-compose exec backend python -m pytest tests/providers/test_ibkr_provider.py -x -q 2>&1 | tail -10
# Expected: all pass (sync interface unchanged)
```

**4f. Full test suite:**
```bash
docker-compose exec backend python -m pytest tests/ -x -q 2>&1 | tail -10
# Expected: all tests pass
docker-compose logs backend --tail=10
# Expected: no import errors
```

**4g. Commit:**
```bash
git add backend/app/providers/ibkr.py backend/tests/providers/test_ibkr_circuit_breaker.py
git commit -m "feat(providers): wrap IBKRDataProvider futures methods with IBKR circuit breaker (#205)"
```

---

## Task 5: Add httpx OTel auto-instrumentation

**Files:** `backend/requirements.txt`, `backend/app/core/tracing.py`, `backend/tests/core/test_tracing.py`

Follows the existing pattern exactly: lazy import inside `setup_otel()` (only runs when endpoint is set), same `0.63b1` version suffix as other instrumentation packages.

### TDD Steps

**5a. Write the failing test — append to `backend/tests/core/test_tracing.py`:**

```python
def test_setup_otel_instruments_httpx_when_endpoint_set():
    """setup_otel() must call HTTPXClientInstrumentor().instrument() when OTel is active."""
    from unittest.mock import MagicMock, patch

    with patch("opentelemetry.exporter.otlp.proto.grpc.trace_exporter.OTLPSpanExporter"), \
         patch("opentelemetry.instrumentation.sqlalchemy.SQLAlchemyInstrumentor"), \
         patch("opentelemetry.instrumentation.celery.CeleryInstrumentor"), \
         patch("opentelemetry.instrumentation.httpx.HTTPXClientInstrumentor") as mock_httpx_cls:

        mock_instance = MagicMock()
        mock_httpx_cls.return_value = mock_instance

        from app.core.tracing import setup_otel
        setup_otel(endpoint="http://jaeger:4317", service_name="test", engine=None)

        mock_httpx_cls.assert_called_once()
        mock_instance.instrument.assert_called_once()
```

**5b. Confirm failure:**
```bash
docker-compose exec backend python -m pytest tests/core/test_tracing.py::test_setup_otel_instruments_httpx_when_endpoint_set -x -q 2>&1 | tail -10
# Expected: ImportError (package not installed) or AssertionError (not wired yet)
```

**5c. Add to `backend/requirements.txt` — after `opentelemetry-instrumentation-celery==0.63b1`:**

```
opentelemetry-instrumentation-httpx==0.63b1
```

**5d. Install in the container:**
```bash
docker-compose exec backend pip install opentelemetry-instrumentation-httpx==0.63b1
# Expected: Successfully installed opentelemetry-instrumentation-httpx-0.63b1
```

**5e. Update `backend/app/core/tracing.py` — add `HTTPXClientInstrumentor().instrument()` inside `setup_otel()` after `CeleryInstrumentor().instrument()`:**

```python
    from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
    HTTPXClientInstrumentor().instrument()
```

Full updated `setup_otel()` (the new line is the last two lines before the closing brace):

```python
def setup_otel(endpoint: str, service_name: str, engine: Optional[object]) -> None:
    """Configure the global OTel TracerProvider.

    When *endpoint* is empty this function returns immediately, leaving the
    default no-op tracer in place.  Auto-instrumentation for FastAPI,
    SQLAlchemy, Celery, and httpx is applied inline; callers must pass the
    FastAPI app via ``instrument_fastapi`` after calling this function.
    """
    if not endpoint:
        return

    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
    from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
    from opentelemetry.instrumentation.celery import CeleryInstrumentor
    from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor

    resource = Resource.create({"service.name": service_name})
    provider = TracerProvider(resource=resource)
    provider.add_span_processor(
        BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint, insecure=True))
    )
    trace.set_tracer_provider(provider)

    if engine is not None:
        SQLAlchemyInstrumentor().instrument(engine=engine)

    CeleryInstrumentor().instrument()
    HTTPXClientInstrumentor().instrument()
```

**5f. Confirm all tracing tests pass:**
```bash
docker-compose exec backend python -m pytest tests/core/test_tracing.py -x -q 2>&1 | tail -10
# Expected: all tests pass (including the new httpx test)
```

**5g. Full test suite:**
```bash
docker-compose exec backend python -m pytest tests/ -x -q 2>&1 | tail -10
# Expected: all tests pass
docker-compose logs backend --tail=10
# Expected: no import errors
```

**5h. Commit:**
```bash
git add backend/requirements.txt backend/app/core/tracing.py backend/tests/core/test_tracing.py
git commit -m "feat(tracing): add httpx OTel auto-instrumentation (#205)"
```

---

## Verification Checklist

After all tasks, run the full validation:

```bash
# 1. Backend is healthy
docker-compose logs backend --tail=20

# 2. All tests pass
docker-compose exec backend python -m pytest tests/ -q 2>&1 | tail -20

# 3. pybreaker import works in the running backend
docker-compose exec backend python -c "
from app.core.circuit_breakers import POLYGON_BREAKER, IBKR_BREAKER
from app.providers.massive import MassiveDataProvider
from app.providers.ibkr import IBKRDataProvider
print('POLYGON_BREAKER:', POLYGON_BREAKER.name, 'fail_max:', POLYGON_BREAKER.fail_max)
print('IBKR_BREAKER:', IBKR_BREAKER.name, 'fail_max:', IBKR_BREAKER.fail_max)
print('All imports OK')
"
# Expected output:
# POLYGON_BREAKER: polygon fail_max: 5
# IBKR_BREAKER: ibkr fail_max: 3
# All imports OK

# 4. Settings fields are present
docker-compose exec backend python -c "
from app.core.config import settings
print('POLYGON_CONNECT_TIMEOUT:', settings.POLYGON_CONNECT_TIMEOUT)
print('POLYGON_READ_TIMEOUT:', settings.POLYGON_READ_TIMEOUT)
print('CB_POLYGON_FAIL_MAX:', settings.CIRCUIT_BREAKER_POLYGON_FAIL_MAX)
print('CB_IBKR_FAIL_MAX:', settings.CIRCUIT_BREAKER_IBKR_FAIL_MAX)
"
# Expected: 10.0, 10.0, 5, 3

# 5. Health endpoint still responds
curl -s http://localhost:8000/api/health | python -m json.tool
```
