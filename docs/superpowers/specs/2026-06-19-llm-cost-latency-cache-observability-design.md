# LLM Cost, Latency, Cache, and Observability Controls — Design (issue #481)

**Date**: 2026-06-19
**Issue**: [#481](https://github.com/omniscient/markethawk/issues/481) — Add LLM cost, latency, cache, and observability controls
**Parent epic**: [#450](https://github.com/omniscient/markethawk/issues/450) — Optional LLM Narrative and Semantic Intelligence
**Blocks**: #472 integration (provider wiring), not #472 itself

## Problem

MarketHawk is adding optional LLM-generated narratives and semantic intelligence (epic #450). Before any LLM feature is exposed in the UI, the platform needs an instrumentation layer that:

1. Captures runtime cost, latency, cache behavior, and errors with durable audit records and real-time metrics.
2. Enforces configurable per-day cost and per-call latency limits — failing closed without touching deterministic scanner workflows.
3. Exposes provider state (disabled / active / degraded / error) through a dedicated admin surface.

Without this layer, cost/latency overruns from experimental LLM usage are invisible until the monthly bill arrives, and a provider outage bleeds into deterministic scan results.

## Spec Scope

This spec defines the **observability and controls interface only** — the wrapper, metrics, database table, limit-enforcement logic, and status endpoint. It does NOT define:

- The LLM provider client (`anthropic` SDK wiring) — that is #472's domain.
- LLM feature flags and provider selection — also #472.
- Any narrative-generation or embedding logic — those are later issues in #450.

**The spec is independently shippable**: all pieces are implemented against a stub LLM client and do not require #472 to merge first.

## Architecture

### 1. Instrumentation Wrapper (`app/core/llm_instrumentation.py`)

A new module providing a single entry point for every LLM call in the codebase:

```python
def instrument_llm_call(
    *,
    provider: str,          # "anthropic", "openai"
    model: str,             # "claude-sonnet-4-6"
    operation: str,         # "narrative", "embedding", "analyst_qa"
    cache_hit: bool,        # caller resolved from Redis before invoking
    fn: Callable[[], LLMResult],  # zero-arg thunk wrapping the actual SDK call
    db: Session,
) -> LLMResult | None:
```

Where `LLMResult` is a typed dict `{input_tokens: int, output_tokens: int, content: Any}`.

**Execution order inside the wrapper:**

1. **Disabled guard** — read `system_config` key `llm.enabled`. If `"false"` (default), return `None` immediately. Emit `llm_requests_total{status="disabled"}`.
2. **Cache-hit fast path** — if `cache_hit=True`: emit `llm_cache_hits_total` + `llm_cache_requests_total`, write a log row with `status="success", cost_usd=0.0`, return cached content. Cached results bypass the cost guard (no new spend) and the actual call.
3. **Daily cost guard** — query `llm_call_logs` for today's `SUM(cost_usd)`. If ≥ `system_config["llm.max_cost_usd_per_day"]` (default `"10.0"`), return `None`, emit `{status="cost_limit_exceeded"}`, write error log row.
4. **Call with timeout** — invoke `fn()` wrapped in `concurrent.futures.ThreadPoolExecutor` with timeout from `system_config["llm.max_latency_ms"]` (default `"30000"`). On `TimeoutError`: return `None`, emit `{status="latency_limit_exceeded"}`, write error log row.
5. **Cost computation** — read per-model price keys from `system_config` (`llm.cost_per_input_token.{model}`, `llm.cost_per_output_token.{model}`). If price key is missing or unparseable: log warning, set `cost_usd = None` (do not fail the call).
6. **Record** — write `LLMCallLog` row and emit all Prometheus metrics.
7. **On any exception in steps 4–6**: catch, log via `ErrorTracker`, emit `{status="error"}`, write error log row, return `None`.

The wrapper is the single enforcement point. Callers receive `None` for any non-success outcome and fall back to deterministic output.

### 2. Prometheus Metrics (additions to `app/core/metrics.py`)

```python
llm_requests_total = Counter(
    "llm_requests_total",
    "Total LLM API call attempts",
    ["provider", "model", "operation", "status"],
    # status: success | error | disabled | cost_limit_exceeded | latency_limit_exceeded
)

llm_request_latency_seconds = Histogram(
    "llm_request_latency_seconds",
    "LLM API call latency in seconds",
    ["provider", "model", "operation"],
    buckets=[0.1, 0.25, 0.5, 1, 2.5, 5, 10, 20, 30, 60],
)

llm_tokens_total = Counter(
    "llm_tokens_total",
    "Total LLM tokens consumed",
    ["provider", "model", "direction"],  # direction: input | output
)

llm_cost_usd_total = Counter(
    "llm_cost_usd_total",
    "Cumulative LLM cost in USD",
    ["provider", "model"],
)

llm_cache_hits_total = Counter(
    "llm_cache_hits_total",
    "LLM calls served from cache",
    ["provider", "model", "operation"],
)

llm_cache_requests_total = Counter(
    "llm_cache_requests_total",
    "Total LLM calls checked against cache (hits + misses)",
    ["provider", "model", "operation"],
)
```

These follow the same pattern as `polygon_api_calls_total` and `scan_duration_seconds` in the existing `metrics.py`.

### 3. Database Model (`app/models/llm_call_log.py`)

```python
class LLMCallLog(Base):
    __tablename__ = "llm_call_logs"

    id: UUID (PK, default uuid4)
    provider: String(50)      # "anthropic"
    model: String(100)        # "claude-sonnet-4-6"
    operation: String(50)     # "narrative" | "embedding" | "analyst_qa"
    input_tokens: Integer (nullable)
    output_tokens: Integer (nullable)
    cost_usd: Numeric(10, 8) (nullable)  # computed at call time, preserves audit
    latency_ms: Float (nullable)         # null on cache hit or disabled
    cache_hit: Boolean, default False
    status: String(30)        # "success" | "error" | "disabled" | "cost_limit_exceeded" | "latency_limit_exceeded"
    error_message: Text (nullable)
    called_at: DateTime (UTC, default utc_now, indexed)
```

Index: `(called_at)` for efficient daily cost aggregation. `(provider, model, called_at)` composite for per-model breakdowns.

**Storing both raw tokens and `cost_usd`**: `cost_usd` is computed from the prices in effect at call time so the record is a faithful billing snapshot. If prices change, historical records are unaffected. Token counts allow recomputation or verification.

### 4. Admin Status Endpoint (`GET /api/v1/system/llm-status`)

New endpoint in `app/routers/system.py` (or a dedicated `app/routers/llm.py`). Not cached or cached for ≤ 10s to allow near-real-time circuit checks.

**Response shape:**

```json
{
  "provider_state": "disabled",
  "enabled": false,
  "limits": {
    "max_latency_ms": 30000,
    "max_cost_usd_per_day": 10.0
  },
  "today": {
    "total_cost_usd": 0.0,
    "request_count": 0,
    "error_count": 0,
    "cache_hit_count": 0,
    "cache_hit_rate": null
  },
  "last_1h": {
    "request_count": 0,
    "avg_latency_ms": null,
    "error_rate": null
  }
}
```

`provider_state` values: `"disabled"` (default until #472 supplies flags), `"active"`, `"degraded"` (recent errors > threshold), `"error"` (last call failed). Aggregates come from `llm_call_logs` SQL queries (not Prometheus — the DB is the durable source of truth for status).

### 5. `SystemConfig` Keys

| Key | Default | Meaning |
|-----|---------|---------|
| `llm.enabled` | `"false"` | Global LLM on/off; `"false"` until #472 wires a provider |
| `llm.max_latency_ms` | `"30000"` | Per-call timeout in ms |
| `llm.max_cost_usd_per_day` | `"10.0"` | Rolling daily cost ceiling |
| `llm.cost_per_input_token.{model}` | (absent) | Input token price in USD, e.g. `"0.000003"` |
| `llm.cost_per_output_token.{model}` | (absent) | Output token price in USD, e.g. `"0.000015"` |
| `llm.degraded_error_rate_threshold` | `"0.5"` | Error rate (0–1) above which state reports "degraded" |

All keys are string-valued (`system_config.value` is `String`). The wrapper parses them with explicit error handling.

## Alternatives Considered

### A. Prometheus metrics only (no PostgreSQL table)

Simpler — no new model, no migration. But Prometheus counters reset on service restart and cannot answer "how much did we spend last month?" The `cost estimate` acceptance criterion implies a durable billing record, so this approach fails the requirement.

### B. pybreaker circuit-breaker (`LLM_BREAKER` in `circuit_breakers.py`)

The existing `POLYGON_BREAKER` / `IBKR_BREAKER` pattern provides auto-recovery and half-open probing. For LLM this is over-engineered: unlike Polygon (required for scans) or IBKR (required for trading), LLM is optional — the correct failure mode is always "return None and fall back to deterministic output," not "retry after cool-down." A state machine adds complexity and makes tests harder to write deterministically. Simple try/except + configurable limit-check is sufficient.

### C. Extend `GET /api/v1/system/status`

Folding LLM state into the existing system status endpoint is tempting for consolidation. It is rejected because: (1) `/system/status` is cached for 30s and sits on the Dashboard's hot path; (2) checking a degraded LLM provider could add latency or raise errors; (3) a richer LLM payload (per-operation breakdowns, cost today, limit thresholds) would bloat the general status contract.

## Stub Client for Tests

Until #472 is merged, tests use a `StubLLMFn` that returns a hardcoded `LLMResult` synchronously:

```python
def make_stub_llm_fn(input_tokens=100, output_tokens=50, content="stub"):
    def fn():
        return {"input_tokens": input_tokens, "output_tokens": output_tokens, "content": content}
    return fn
```

This makes all acceptance criterion test paths runnable today:
- Metrics emission on success
- Metrics emission on error (stub raises)
- Cache-hit fast path (pass `cache_hit=True`)
- Disabled guard blocks call
- Cost-limit guard blocks call
- Latency-timeout guard blocks call (stub sleeps past timeout)

## Test Coverage Plan

| Test file | Paths covered |
|-----------|---------------|
| `tests/services/test_llm_instrumentation.py` | disabled guard, cost limit, latency timeout, success path metrics, error path metrics, cache-hit path, cost computation with/without price keys |
| `tests/api/test_llm_status.py` | GET /api/v1/system/llm-status shape, aggregates from llm_call_logs, provider_state transitions |

All tests use the transaction-rollback `db` fixture from `conftest.py` (not mocked DB) to exercise real SQL aggregation on `llm_call_logs`.

## Open Questions (non-blocking)

1. **Cache key ownership**: This spec does not define LLM response cache keys — that will be addressed when narrative generation is implemented (#450 sub-issues). The `cache_hit` boolean is caller-provided to the wrapper.
2. **Provider-state "active" signal**: Until #472 lands real health-check logic, `provider_state` is computed from `llm_call_logs` history only (last call status). If no calls have been made today, state defaults to "disabled" when `llm.enabled = false`.
3. **Multi-process cost guard**: The daily cost guard reads `llm_call_logs` per-call. Under high concurrency this could allow momentary over-budget calls (two workers read $9.90 simultaneously, both pass). At LLM call volumes anticipated before broad UI exposure, this is acceptable. If it matters later, a PostgreSQL advisory lock or a Redis atomic counter can guard it.

## Assumptions

- `[ASSUMPTION]` #472 will wire the real Anthropic/OpenAI client by calling `instrument_llm_call()` as its dispatch point. No direct SDK calls outside the wrapper.
- `[ASSUMPTION]` `llm.enabled` defaults to `"false"` in the `system_config` seeding migration, ensuring LLM is off-by-default on fresh deploys.
- `[ASSUMPTION]` LLM call volume before "broad UI exposure" is low enough that a per-call DB write (with a single indexed column) has negligible impact on overall DB pool utilization.
- `[ASSUMPTION]` The Grafana dashboards already provisioned will pick up the new `llm_*` Prometheus metrics automatically via the existing Prometheus scrape config; no dashboard YAML changes are required for basic visibility.
