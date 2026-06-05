# Circuit Breakers + Outbound Request Timeouts — Design

**Date:** 2026-06-05  
**Status:** Spec generated — pending review  
**Issue:** #205  
**Author:** Brainstormed with Claude (Opus 4.8)

## Problem

The Architecture Quality Report v2 scored Reliability at Circuit Breakers 0/5 and Timeout Handling 2/5. Two gaps drive this:

1. **No circuit breakers.** If Polygon or IBKR becomes slow or returns errors, all callers (Celery scanner tasks, FastAPI routes) continue retrying indefinitely. A slow provider ties up Celery workers and exhausts connection pools.
2. **Implicit timeouts on Polygon.** `MassiveDataProvider._init_client()` calls `RESTClient(settings.POLYGON_API_KEY)` with no timeout arguments. The Polygon SDK has internal defaults (`connect_timeout=10.0`, `read_timeout=10.0`), but these are invisible and untunable without reading the SDK source. The `IBKRDataProvider` already uses `asyncio.wait_for(…, timeout=30/120)` on its async calls; the IBKR side is mostly addressed.

The `stock_data.py` service already degrades gracefully on `ProviderError` (returns empty DataFrame/dict), so the missing layer is the *signalling mechanism* — a way to fail fast when a provider is known-bad instead of waiting out each call.

## Requirements

1. **Explicit Polygon timeouts**: `connect_timeout` and `read_timeout` for `RESTClient` must be set from `Settings` with the current 10.0 s defaults preserved. Values must be tunable via environment variable without code changes.
2. **Circuit breaker for Polygon (MassiveDataProvider)**: All three operations (`get_bars`, `get_snapshots`, `get_ticker_details`) share one breaker. When tripped, raise `ProviderError(is_retryable=False)` so the existing graceful-degradation path in `stock_data.py` handles it.
3. **Circuit breaker for IBKR (IBKRDataProvider)**: Separate breaker wrapping the public futures methods (`get_futures_bars`, `get_futures_contracts`). Same surfacing via `ProviderError`.
4. **Breaker parameters configurable via `Settings`**: `fail_max` (default 5) and `reset_timeout` (default 60 s) for Polygon; `fail_max` (default 3) and `reset_timeout` (default 120 s) for IBKR.
5. **httpx auto-instrumentation**: Add `opentelemetry-instrumentation-httpx` so the existing httpx calls in `tasks/sync.py`, `services/alert_service.py`, and `core/error_tracking.py` show up in Jaeger. Gated on `OTEL_EXPORTER_OTLP_ENDPOINT` being set, matching the existing `setup_otel()` pattern.
6. Polygon SDK (urllib3-based) tracing is **out of scope** — deferred.

## Non-Goals (v1)

- Per-operation-type breakers (fine-grained `get_bars` vs `get_snapshots` breakers). One per provider is sufficient.
- Polygon SDK (`urllib3`) OTel instrumentation — requires separate investigation of the SDK's `trace=True` output format.
- Any changes to the `tasks/sync.py` or `alert_service.py` httpx calls (already have explicit `timeout=30.0`/`10.0`).
- Frontend changes.

## Approach (Recommended: Central `core/circuit_breakers.py` + `pybreaker`)

### Library choice: `pybreaker`

`pybreaker` (≥ 1.0) is the `pybreaker` reference implementation from the *Release It!* circuit breaker pattern:
- Supports both sync and async callables (detects `asyncio.iscoroutinefunction`).
- Half-open state (one trial call before full reset) is built-in.
- No asyncio-specific event loop requirements — works in both FastAPI and Celery contexts.
- Well-maintained, small dependency surface.

### Module: `backend/app/core/circuit_breakers.py` (new)

```python
import pybreaker
from app.core.config import get_settings

def _build_breakers():
    s = get_settings()
    polygon_breaker = pybreaker.CircuitBreaker(
        fail_max=s.CIRCUIT_BREAKER_POLYGON_FAIL_MAX,
        reset_timeout=s.CIRCUIT_BREAKER_POLYGON_RESET_TIMEOUT,
        name="polygon",
    )
    ibkr_breaker = pybreaker.CircuitBreaker(
        fail_max=s.CIRCUIT_BREAKER_IBKR_FAIL_MAX,
        reset_timeout=s.CIRCUIT_BREAKER_IBKR_RESET_TIMEOUT,
        name="ibkr",
    )
    return polygon_breaker, ibkr_breaker

POLYGON_BREAKER, IBKR_BREAKER = _build_breakers()
```

Centralising the instances avoids duplicate definitions and allows tests to reset breaker state in one place.

### New `Settings` fields (`backend/app/core/config.py`)

```python
POLYGON_CONNECT_TIMEOUT: float = 10.0
POLYGON_READ_TIMEOUT: float = 10.0
CIRCUIT_BREAKER_POLYGON_FAIL_MAX: int = 5
CIRCUIT_BREAKER_POLYGON_RESET_TIMEOUT: int = 60
CIRCUIT_BREAKER_IBKR_FAIL_MAX: int = 3
CIRCUIT_BREAKER_IBKR_RESET_TIMEOUT: int = 120
```

### `MassiveDataProvider` changes (`backend/app/providers/massive.py`)

1. Pass timeouts to `RESTClient`:
   ```python
   self._client = RESTClient(
       settings.POLYGON_API_KEY,
       connect_timeout=settings.POLYGON_CONNECT_TIMEOUT,
       read_timeout=settings.POLYGON_READ_TIMEOUT,
   )
   ```

2. Wrap public methods with `POLYGON_BREAKER`:
   ```python
   from app.core.circuit_breakers import POLYGON_BREAKER
   import pybreaker

   # In get_bars():
   try:
       return POLYGON_BREAKER.call(self._get_bars_impl, symbol, ...)
   except pybreaker.CircuitBreakerError as e:
       raise ProviderError(
           f"Polygon circuit breaker open: {e}",
           provider="massive", endpoint="get_bars", is_retryable=False,
       ) from e

   # Same pattern for get_snapshots() and get_ticker_details()
   ```

   Each public method keeps its try/except for `ProviderError` re-raise; the circuit breaker wraps the inner `_impl` helper. Alternatively, the `@POLYGON_BREAKER` decorator form can be used on the helper functions directly.

### `IBKRDataProvider` changes (`backend/app/providers/ibkr.py`)

Async methods support the decorator form because `pybreaker` detects coroutine functions:

```python
from app.core.circuit_breakers import IBKR_BREAKER
import pybreaker

@IBKR_BREAKER
async def get_futures_contracts(self, ...):
    ...  # existing body; pybreaker wraps the coroutine

@IBKR_BREAKER
async def get_futures_bars(self, ...):
    ...
```

On `CircuitBreakerError`, add a top-level catch in each method that re-raises as `ProviderError(is_retryable=False)`.

### OTel httpx instrumentation (`backend/app/core/tracing.py`)

In `setup_otel()`, after the existing `CeleryInstrumentor().instrument()` call:

```python
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
HTTPXClientInstrumentor().instrument()
```

Add to `requirements.txt`:
```
opentelemetry-instrumentation-httpx==0.63b1  # match existing instrumentation pins
```

## Alternatives Considered

### Alternative B: Manual boolean state flag (no external dependency)

A `_circuit_open: bool` flag with `_failure_count` and `_last_failure_time` on each provider. Simpler dependency surface, but reinvents the wheel: no half-open state, no per-call exception classification, harder to test, diverges from industry patterns. Not worth the extra code for an M-sized issue.

### Alternative C: `aiobreaker` (async-native library)

`aiobreaker` is async-first and would be more idiomatic for the IBKR async paths. Drawbacks: much smaller community than `pybreaker`, fewer maintenance guarantees, and requires a separate dependency alongside `pybreaker` if we want to cover the sync Polygon path too (or we accept all-async, which doesn't fit the sync Polygon SDK). `pybreaker` 1.x already supports both sync and async — no need for a second library.

## Deployment Notes

- `pybreaker` circuit breakers are **in-process, not distributed**. Each Celery worker has independent breaker state. If Polygon is failing, worker A may open its breaker while worker B has not yet accumulated enough failures. This is acceptable: the intent is to protect individual workers from blocking, not to coordinate a fleet-wide blackout. A distributed breaker (Redis-backed) is out of scope.
- Breaker state is lost on worker restart. This is intentional — a fresh worker should probe the provider rather than assume it is still down.

## Open Questions (non-blocking)

1. Should tripped breakers publish a metric (e.g., `provider_circuit_open` Gauge) to Prometheus? A listener on `pybreaker.CircuitBreaker` events could drive this. Deferred — low priority for v1.
2. Polygon SDK tracing: the SDK has a `trace=True` constructor param and a `opentelemetry-instrumentation-requests` package that can instrument the underlying urllib3. Defer to a follow-up issue.

## Assumptions

- `pybreaker` 1.x async support (`asyncio.iscoroutinefunction` detection) works correctly in the Python 3.11 environment used in the Docker backend container. **Flag**: verify at implementation time by running a quick async circuit-breaker smoke test.
- The existing graceful-degradation path in `stock_data.py` (catch `ProviderError` → return empty DataFrame) is sufficient; no callers need special handling for the circuit-breaker-open case.
- `opentelemetry-instrumentation-httpx` version `0.63b1` is compatible with the installed `opentelemetry-api==1.42.1` / `opentelemetry-sdk==1.42.1`. **Flag**: confirm pinned version matches `0.63b1` suffix used by other instrumentation packages in `requirements.txt`.
