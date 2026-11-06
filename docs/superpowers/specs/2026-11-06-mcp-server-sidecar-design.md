# MCP Server Sidecar — Read Tools (Roster, Signals, Overview) — Design Spec

**Issue:** #906
**Date:** 2026-11-06
**Status:** Proposed — pending implementation plan

## 1. Overview / Problem Statement

LT-3 is slice 3 of the Long-Term ETF Investing epic (#902): an MCP server sidecar
(`backend/mcp_server/`) that lets an agent on the Docker host authenticate with a static
bearer token and call read-only tools (`list_roster`, `get_etf`, `get_market_overview`,
`refresh_signals`) and resources (`longterm://overview`, `longterm://signals/{ticker}`)
backed by the roster and signal data the epic's earlier slices produce. It is the first
MCP server in this codebase and the first sidecar to publish a host port.

This spec designs the tool layer, auth, process model, and observability now, against
the service-layer interfaces the epic design doc already specifies for #904 (roster/data
path) and #905 (signals/page) — see §6 Assumptions ("Preconditions") for why that is
safe to do before those two land.

## 2. Requirements (from Q&A)

1. `backend/mcp_server/` package, compose service `mcp-server`, copying the
   `live-scanner` service block (image, env, `depends_on`, network, memory limit,
   `volumes: []` with the bind-mount restored in the override file) — not a new
   architectural category, an instance of the sidecar pattern `live-scanner` already
   established (see §6, memory note).
2. Published only on `127.0.0.1:8010:8010`, plain HTTP, no Caddy route, no other
   network exposure.
3. `mcp` Python package (official SDK, FastMCP API), streamable HTTP transport, pinned
   in `backend/requirements.txt`.
4. Static bearer token auth from `MCP_API_TOKEN`: required, >=32 chars, validated at
   process startup exactly like `JWT_SECRET_KEY`. Missing/short token fails the process
   before it serves traffic. A request without a valid token gets 401.
5. The server imports `app.services.long_term.*` directly, opens its own DB session per
   call, and never calls the backend's REST API.
6. Four tools — `list_roster`, `get_etf`, `get_market_overview`, `refresh_signals` — and
   two resources — `longterm://overview`, `longterm://signals/{ticker}` — scoped exactly
   to the epic's slice-3 line (§4.9 of the epic design doc). All other tools listed in
   the epic doc (`list_accounts`, `upsert_positions`, `check_allocation`,
   `create_proposal`, etc.) are out of scope — they belong to slices 4/5 (#907, #908).
7. Tool descriptions are written for an agent reader and must state the on-sale score
   formula, the total-return basis of all return/trend figures, and the `short_history`
   caveat wherever a tool or resource surfaces signals that could be affected.
8. Logging follows the `live-scanner` sidecar precedent; one Prometheus counter per
   tool call, scraped by the existing Prometheus stack.
9. Unit tests against the service layer; one integration test driving the real
   FastMCP/Starlette app in-process, with and without the token.
10. Acceptance: from the Docker host, an MCP client with the token lists tools and gets
    a real `get_market_overview` result; without the token, every call gets 401.

## 3. Architecture / Approach

### 3.1 Package layout

```
backend/mcp_server/
  __init__.py
  main.py          # entry point: python -m mcp_server.main; builds and serves the app
  app.py           # create_app() factory — FastMCP instance + auth middleware, shared
                    # by main.py (uvicorn) and the integration test (ASGI test client)
  auth.py          # bearer-token ASGI middleware + MCP_API_TOKEN startup validation
  tools.py         # tool/resource registration, thin — delegates to app.services.long_term
  metrics.py       # the per-tool-call Prometheus Counter
```

`create_app()` in `app.py` returns the fully wrapped ASGI app (FastMCP's
streamable-HTTP app, with `auth.py`'s middleware applied and `metrics.py`'s
`/metrics` mounted). `main.py` calls `create_app()` and runs it with uvicorn; the
integration test (§3.6) calls the same `create_app()` so the test and the real
process share one middleware stack, never two.

### 3.2 Compose service

Modeled on `live-scanner` (`docker-compose.yml:308-345`):

```yaml
  mcp-server:
    image: ghcr.io/omniscient/markethawk-backend:${IMAGE_TAG:-latest}
    build:
      context: ./backend
      dockerfile: Dockerfile
    container_name: stockscanner-mcp
    command: python -m mcp_server.main
    environment:
      DATABASE_URL: ${DATABASE_URL}
      ENVIRONMENT: ${ENVIRONMENT:-development}
      SEQ_URL: http://seq:5341
      LOG_LEVEL: ${LOG_LEVEL:-INFO}
      PYTHONDONTWRITEBYTECODE: "1"
      # MCP bearer-token auth — required by Settings validator (>=32 chars), sourced from .env
      MCP_API_TOKEN: ${MCP_API_TOKEN}
    ports:
      - "127.0.0.1:8010:8010"
    depends_on:
      postgres:
        condition: service_healthy
    # Bind-mount (./backend:/app:ro) is restored in docker-compose.override.yml for local dev,
    # matching live-scanner's entry.
    volumes: []
    networks:
      - stockscanner-network
    restart: unless-stopped
    deploy:
      resources:
        limits:
          memory: 512M
```

No `redis` dependency (the MCP server doesn't publish to or read from Redis pub/sub —
unlike `live-scanner`, it has no live-streaming responsibility) and no
`IBKR_*`/`POLYGON_API_KEY` vars (it never touches a market-data provider directly; it
only reads already-persisted `app.services.long_term.*` state). This is the one
deliberate deviation from copying `live-scanner`'s block verbatim, and is noted so the
planner doesn't "fix" it back in.

### 3.3 Auth

`MCP_API_TOKEN` gets a pydantic `@field_validator` in `app/core/config.py`, identical in
shape to `JWT_SECRET_KEY`'s (`backend/app/core/config.py:279-287`):

```python
@field_validator("MCP_API_TOKEN")
@classmethod
def validate_mcp_api_token(cls, v: str) -> str:
    if len(v) < 32:
        raise ValueError(
            "MCP_API_TOKEN must be at least 32 characters. "
            "Generate one with: python -c 'import secrets; print(secrets.token_urlsafe(48))'"
        )
    return v
```

This runs at `Settings()` construction (import time), so `mcp-server` fails fast on a
missing/short token before serving a single request — same fail-fast property
`JWT_SECRET_KEY` already has for the main backend.

Request-time enforcement is a pure-ASGI middleware (not `BaseHTTPMiddleware`), mirroring
`AuthMiddleware` at `backend/app/main.py:302-332` (chosen there specifically to avoid a
`BaseHTTPMiddleware` + gzip streaming interaction bug, `backend/app/main.py:297-301`):

```python
class BearerTokenMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["path"] == "/metrics":
            await self.app(scope, receive, send)
            return
        request = Request(scope)
        header = request.headers.get("authorization", "")
        token = header.removeprefix("Bearer ").strip() if header.startswith("Bearer ") else ""
        if token != settings.MCP_API_TOKEN:
            await JSONResponse(status_code=401, content={"detail": "Not authenticated"})(
                scope, receive, send
            )
            return
        await self.app(scope, receive, send)
```

`/metrics` is exempt from the bearer check (matching how Prometheus scrapes the main
backend's `/metrics` without auth today — it's reached only over the internal docker
network, not the published host port). Every other path, including the MCP
`initialize`/`tools/list`/`tools/call` endpoints, requires the token. The comparison is
a single static-token equality check (§7 of the epic design doc: "a single static
bearer token, not per-agent identities" — no per-request HMAC or timing-safe compare is
specified or needed at this scale, consistent with how the rest of the codebase handles
static shared secrets, e.g. `INTERNAL_API_TOKEN`).

### 3.4 Tool layer

Each tool opens its own session via `with SessionLocal() as session:`
(`backend/app/core/database.py`), following the standalone-process precedent in
`backend/live_scanner/publisher.py:241,272` rather than FastAPI's `get_db()` generator
(which only works through `Depends()`). Tools are thin: validate input, open a session,
call into `app.services.long_term.*`, close the session, return a plain dict/Pydantic
model.

| Tool | Service call (epic doc reference) | Returns |
|---|---|---|
| `list_roster(segment?, country?)` | `app.services.long_term.roster` — list active roster rows (optionally filtered), joined with each ticker's latest `etf_signal_daily` row | Roster rows with latest signals |
| `get_etf(ticker, history_days?)` | `app.services.long_term.roster` for the row + `app.services.long_term.signals` for the latest signal row and the stored daily closes / SMA series | Roster row, latest signals, closes + SMA series for charting/reasoning |
| `get_market_overview()` | `app.services.long_term.signals` — on-sale top N (by `on_sale_score`), movers (`ret_1w`/`ret_1m`), trend-split counts by segment (above/below `sma_50`), benchmark (SPY) signals | The "open the page" summary in one call |
| `refresh_signals(tickers?)` | `app.services.long_term.signals.recompute_latest(session, tickers)` — the same plain function the nightly Celery task calls (§3.5) | Recomputed latest signal rows |

Resources mirror two of the tools: `longterm://overview` returns the identical payload
as `get_market_overview()`; `longterm://signals/{ticker}` returns the identical payload
as the signals portion of `get_etf(ticker)`. Both are implemented by calling the same
underlying service functions the tools call — never a second code path.

Every tool/resource docstring states, verbatim or paraphrased: the on-sale score formula
(`100 - mean(pctile_1y, pctile_5y, clamp(50 + pct_from_sma_200, 0, 100))`, dropping
`pctile_5y` when `short_history`), that all returns/SMA/drawdown/percentile figures are
total-return (dividend-adjusted), and that `short_history=true` (history_days < 756, ~3
years) means the agent should discount long-lookback figures for that ticker.

### 3.5 `refresh_signals` and Celery

The MCP server is not a Celery worker: `live-scanner` (the service it's modeled on)
has `depends_on: postgres, redis` but no `celery -A app.core.celery_app:celery_app`
command, no broker config, and never imports `app.core.celery_app` or dispatches a
task — it only talks to the DB and Redis pub/sub directly. `mcp-server` follows the
same rule, one notch further: it doesn't even need the Redis dependency (§3.2).

The signal recompute logic therefore lives in a plain synchronous function,
`app.services.long_term.signals.recompute_latest(session, tickers: list[str] | None =
None) -> list[EtfSignalDaily]`. The nightly Celery task becomes a thin wrapper that
opens a session and calls this function; the `refresh_signals` MCP tool calls the exact
same function with its own session; the REST "recompute" endpoint planned for #905 calls
it too. Celery is used only for the scheduled nightly trigger, never for the on-demand
path — there is one recompute code path with three callers, not three implementations.

A unit test (mirroring `backend/tests/live_scanner/test_main_imports.py`'s AST-based
import guard) asserts `mcp_server/main.py` never imports `app.core.celery_app` or
anything under `app.tasks`, so a future change can't silently reintroduce a Celery
dependency this sidecar's compose block doesn't provision for.

### 3.6 Observability

**Logging.** `mcp_server/main.py` configures stdlib logging exactly like
`backend/live_scanner/main.py:31-36` — `logging.basicConfig(level=settings.LOG_LEVEL,
format="%(asctime)s %(levelname)-8s %(name)s  %(message)s", stream=sys.stdout)`. This
repo has no automatic "all logs → Seq" pipe for sidecars today (confirmed: no compose
service uses a GELF logging driver; the one `seq-gelf` sidecar was for the now-extracted
dark-factory containers per `docs/adr/0011-dark-factory-gelf-logging.md`). "Seq
structured logging like the other sidecars" concretely means matching `live_scanner`'s
stdout-logging pattern, plus calling `ErrorTrackerFactory.get_tracker().log_error(...)`
(`backend/app/core/error_tracking.py`) from the tool-call exception handler so unhandled
tool errors specifically reach Seq's raw-events API, the same mechanism the main
backend's global exception handler uses (`backend/app/main.py:520`).

**Metrics.** One `Counter` in `mcp_server/metrics.py`:

```python
from prometheus_client import Counter

mcp_tool_calls_total = Counter(
    "mcp_tool_calls_total",
    "Total MCP tool calls handled by the long-term MCP server",
    ["tool_name", "status"],
)
```

incremented once per tool invocation with `status` in `{"success", "error"}`. Exposed
via `from prometheus_client import make_asgi_app; app.mount("/metrics", make_asgi_app())`
— the exact pattern `services/tweet-monitor/app/main.py:22,70-71` already uses for a
non-backend sidecar process, using the default global `CollectorRegistry` (no
multiprocess env needed; `mcp-server` is a single process, unlike the gunicorn-fronted
main backend). Add a new scrape job to `monitoring/prometheus/prometheus.yml`:

```yaml
  - job_name: mcp_server
    static_configs:
      - targets: ["mcp-server:8010"]
    metrics_path: /metrics
```

The internal docker-network scrape target (`mcp-server:8010`) is independent of the
host-only port publication (`127.0.0.1:8010:8010`) — `tweet-monitor` already
demonstrates this split (host-published on `127.0.0.1:8001:8000`, scraped internally at
`tweet-monitor:8000`).

### 3.7 Dependencies

`backend/requirements.txt` gets a new section, following the file's existing
`#`-header-grouped, exact-`==`-pin convention:

```
# MCP Server
mcp==<latest stable at implementation time>
```

(Exact version left to the implementer — pin style only is prescribed here, per §5 of
the epic design doc.)

### 3.8 Documentation

`ENV_VARIABLES.md` gets a new row in the top secrets table (`Variable | Purpose |
Example`, alongside `SECRET_KEY`/`JWT_SECRET_KEY` at `:22-23`) — not the lower
`Variable | Default | Purpose` table used for optional/fail-closed-when-empty vars like
`INTERNAL_API_TOKEN` (`:82-83`), because `MCP_API_TOKEN` is required with hard startup
validation, not optional-with-a-default:

```
| `MCP_API_TOKEN` | Bearer token for the long-term MCP server (`mcp-server`, port 8010). **Must be ≥ 32 characters** — startup fails with a `ValidationError` if missing or shorter. Generate with: `python -c "import secrets; print(secrets.token_urlsafe(48))"` | `c7f2a9...` |
```

Also add `MCP_API_TOKEN=` to the root `.env` example and to the preview-env contract
(wherever `JWT_SECRET_KEY` is listed there today, for the same reason: both are
startup-validated required secrets every environment needs a real value for).

### 3.9 Testing

**Unit tests** (`backend/tests/mcp_server/test_tools.py` or similar) call the tool
functions directly against a seeded test DB session (the existing `db`/`db_engine`
testcontainers fixtures in `backend/tests/conftest.py`), asserting on returned shapes
and the on-sale-score/short-history logic, without going through the ASGI layer at all.

**Integration test** (`backend/tests/mcp_server/test_server.py`): no `docker compose
up`, no subprocess. Build the app via `mcp_server.app.create_app()` and drive it with
an ASGI test client (`starlette.testclient.TestClient` or `httpx.ASGITransport`),
matching `backend/tests/conftest.py:106`'s `with TestClient(app) as c:` pattern so the
app's lifespan (the streamable-HTTP session manager needs its lifespan started) runs
correctly. Three cases:
- No `Authorization` header → 401.
- Wrong token → 401.
- Correct `MCP_API_TOKEN` → tools/list returns exactly the four tools; a
  `get_market_overview` call against seeded `etf_signal_daily` rows returns a real
  payload.

The issue's host-level "Done when" check (`127.0.0.1:8010` from an external MCP client)
remains a manual validate-phase step with a real client, not a pytest — consistent with
how this spec's parent command (`CLAUDE.md`'s "Validating Changes Before Committing")
already requires curl-equivalent live verification for new endpoints before commit.

## 4. Alternatives Considered

1. **MCP server dispatches a Celery task for `refresh_signals`.** Rejected: would
   require adding Celery broker connectivity (`CELERY_BROKER_URL`, a `-A
   app.core.celery_app:celery_app` wiring, redis dependency) to a sidecar this issue
   scopes as a lightweight, `live-scanner`-shaped read path. It also doesn't match
   §4.3 of the epic design doc, which already frames the on-demand recompute as calling
   "the function," singular, not enqueueing a task. A plain synchronous function shared
   by both the Celery task and the tool is simpler and has one less moving part for an
   operation cheap enough to run inline (recomputing a handful of rows).
2. **Docker-compose-based integration test (actually starts the compose service and
   hits `127.0.0.1:8010` with a real HTTP client).** Rejected for the automated test
   suite: this repo's backend tests run via `pytest` + `testcontainers[postgres]`, not
   `docker compose`, and no other backend test spins up a sibling compose service to
   test against it. An in-process ASGI test client against the same `create_app()`
   factory the real process uses gives equivalent coverage (auth middleware, tool
   registration, response shapes) without a slow, flaky, CI-unfriendly dependency. The
   literal host-level check from the issue's "Done when" is preserved as a manual
   validate-phase step instead.
3. **Treat `backend/app/services/long_term/*` as not-yet-existing and write this spec's
   tool layer against placeholder/stub interfaces, deferring real integration to a
   later follow-up ticket.** Rejected: the epic design doc (§4.2/§4.3/§4.6) already
   specifies these interfaces in enough detail (table columns, formulas, function
   responsibilities) that building against them now — with a hard precondition that
   implementation waits for #904/#905 to actually land (§6) — produces a real,
   checkable spec instead of a throwaway one that would need a full rewrite once those
   land.

## 5. Open Questions (non-blocking)

- Exact Pydantic response shapes, pagination (if any, for `list_roster`), and error
  codes beyond 401 — left to the builder per §5 of the epic design doc.
- Whether `refresh_signals` without a `tickers` argument recomputes the entire active
  roster or is required to specify at least one ticker — depends on #905's actual
  `recompute_latest` signature once it lands; this spec names the function and its
  intended shared-caller shape but the exact default-arg behavior is #905's call to
  make.
- Exact `mcp` package version pin — left to the implementer at implementation time
  (pin style only is prescribed, §3.7).
- Whether `get_etf`'s `history_days?` parameter has a default and a max cap (to bound
  payload size) — not specified in the issue or epic doc; reasonable default is "match
  whatever `StockChart`'s existing daily-mode history window uses," but this is a minor
  implementation detail, not an architectural one.

## 6. Assumptions (flagged)

- **Preconditions (blocking).** This spec is written and committed now, while #904 and
  #905 are still at `spec-pending-review` and the epic's design doc (PR #903) is still
  awaiting Frank's approval — normal for this project's serial-rollout refine process
  (the scheduler's dependency ordering, not the refine phase, is what prevents #906
  from being planned or implemented early; see Q&A). This ticket **must not be planned
  or implemented before #904 and #905 merge** — neither `backend/app/services/long_term/`
  nor any `lt_*` model exists in this repo yet, and this spec designs against the
  interfaces the epic doc specifies for those slices. If the merged #904/#905 code
  differs from the design doc in a way that changes a tool's inputs/outputs, the
  implementer adapts this spec's tool layer to what actually shipped rather than
  building shims or stub data to match this document literally. It also **must not be
  planned or implemented before epic #902 / PR #903 is approved** — the epic is
  explicitly "awaiting owner approval of the design before planning," and this spec is
  a forward-looking design artifact for the scheduler's serial queue, not a signal that
  implementation should start now.
- **Memory `[AVOID]` on new containers.** `.archon/memory/architecture.md` carries a
  `[AVOID]` entry against introducing new Docker containers where an existing service
  could be extended. This ticket's sidecar is treated as an explicit, already-approved
  exception: `live-scanner` already established the "additional sidecar process" shape
  as an accepted category in this codebase (the same memory file's `[PATTERN]` sibling
  entry lists it as one of the stack's existing services), and the epic design doc
  records this as a decision made directly with the repo owner (§4.7, "decided with
  Frank"). The MCP server is one more instance of that already-accepted category, not
  a novel expansion of the deployment surface.
- **`refresh_signals` cost.** Recomputing signal rows for a handful of tickers (or the
  full ~65-ticker roster) synchronously, in a single tool call, is assumed to be fast
  enough to run inline within a normal MCP tool-call timeout. If #905's actual
  implementation makes a full-roster recompute expensive (e.g. because of yfinance
  rate limits on the Canadian path), `refresh_signals` may need a `tickers` cap or an
  async job-status pattern — deferred to whoever implements #906, once #905's real
  performance characteristics are known.
- **No Redis dependency.** Diverging from a literal copy of `live-scanner`'s compose
  block, `mcp-server` omits the `redis` dependency and connection, since nothing in
  this ticket's scope reads or writes Redis. Flagged explicitly (§3.2) so the planner
  doesn't "correct" this back to match `live-scanner` exactly.
