# IBKR Gateway Chaos Test — Live-Scanner Degradation and Recovery

**Status:** design
**Date:** 2026-06-21
**Issue:** #393
**Related:** #388 (Polygon↔IBKR failover posture — this test verifies the live path)

## Problem

The live-scanner (clientId=5) streams real-time IBKR bars for every watchlist symbol. What
happens when the IB Gateway container dies mid-stream is currently **undefined-by-testing** and
**broken-by-implementation**:

- `disconnectedEvent` fires a warning log but does not reconnect or resubscribe. All
  active subscriptions go silent. The process stays running but deaf.
- The network-partition case is worse: no `disconnectedEvent` fires at all (TCP hangs
  half-open); the process stalls indefinitely with no signal to the operator.
- No `feed_loss` or `feed_recovered` event is published to `watchlist:alerts` — silence
  is the current behavior.
- `/api/ready` does not reflect live-data degradation (only probes DB and Redis).
- The frontend shows implicit per-symbol staleness (15s grey-out) but no explicit
  gateway-disconnected badge.

This ticket closes those gaps: it specifies a **scripted chaos test** and the **implementation
fixes the test will force**.

## Requirements

From the issue and Q&A:

1. **Both failure modes covered**: `docker stop` (clean TCP close) and network partition
   (`docker network disconnect` — TCP hangs, no disconnect event).
2. **Live-scanner does not crash-loop**: in-process reconnect with exponential backoff;
   container restart (`restart: unless-stopped`) as a backstop only.
3. **Feed-loss event** published to `watchlist:alerts` on disconnect, feed-recovered on
   reconnect — explicit event, not client-side inference.
4. **`/api/ready`** returns a `live_data` field (informational) reflecting IBKR
   reachability — does NOT affect the HTTP 200/503 gate (only DB + Redis do).
5. **Frontend stale badge**: page-level amber badge in `ActiveWatchlist` header when
   `feed_loss` is received; clears on `feed_recovered`.
6. **Recovery within N=60 s** after the gateway is restored.
7. **No duplicate or fabricated bars** around the gap: bars after recovery have
   timestamps after the gap start; no backfill or interpolation.
8. **Test script** under `scripts/chaos/ibkr_kill_test.sh`, documented invocation, green
   on fixed behavior; CI-nightly via new `.github/workflows/chaos-nightly.yml`.
9. **Runbook** section covering what operators see in Seq/Grafana during a feed loss.

## Architecture / Chosen Approach

### 1. In-Process Reconnect-and-Resubscribe

`ibkr_adapter.py` — `IBKRLiveAdapter` gains a reconnect path:

- `disconnectedEvent` is wired to **a TAG on the existing asyncio queue** (`TAG_DISCONNECT`)
  rather than calling async code directly from the ib_insync event thread. The existing pattern
  (`call_soon_threadsafe` + `queue.put_nowait`) is already used for bars/quotes and is safe.
- A new `TAG_CONNECT_RECOVERED` tag signals successful reconnect (for feed_recovered publish).
- `_process_loop` in `main.py` handles these new tags:
  - `TAG_DISCONNECT` → publish `feed_loss`, kick off a reconnect coroutine
  - `TAG_CONNECT_RECOVERED` → re-subscribe all symbols in the `subscribed` set, publish
    `feed_recovered`
- The reconnect coroutine reuses the existing `_connect_ib()` with its backoff
  (`RECONNECT_BASE_DELAY=5s`, capped at 60s, up to `MAX_CONNECT_RETRIES=10`).
- After a successful reconnect, the `subscribed` set is iterated and `_subscribe()` is called
  for each symbol. The `BarAggregator` objects are kept in-place so accumulated session state
  is preserved; the gap window is simply missing bars (correct — not interpolated).

**Liveness watchdog for network partition** (no `disconnectedEvent` fires):

- A new async watchdog task runs alongside `_sync_loop` and `_process_loop`.
- It maintains a `last_bar_received_at` timestamp updated on every `TAG_BAR`.
- During market hours (04:00–20:00 ET), if `last_bar_received_at` is more than
  `HEARTBEAT_STALE_SECONDS = 30` seconds old and `ib.isConnected()` returns True (lying, as
  ib_insync uses cached state), the watchdog forces a disconnect: `ib.disconnect()`, which
  triggers `disconnectedEvent` → enters the reconnect path above.
- Outside market hours the watchdog is dormant (no bars expected).

**Mock adapter env-switch** (`LIVE_SCANNER_MOCK=true`):

- `main.py` checks `settings.LIVE_SCANNER_MOCK` (bool, default `False`).
- When true, uses `MockLiveAdapter` instead of `create_adapter()`. The mock can be extended
  to simulate `TAG_DISCONNECT` events on demand, making the chaos test hermetic in CI
  without requiring live IBKR credentials.
- Add `LIVE_SCANNER_MOCK: false` default to `Settings`; set `true` in the chaos-nightly CI
  workflow when real `IB_USERNAME`/`IB_PASSWORD` secrets are not available.

### 2. Feed-Loss / Feed-Recovered Events

New `LivePublisher` methods:

```python
async def publish_feed_loss(self) -> None:
    msg = json.dumps({"type": "feed_loss", "timestamp": datetime.now(timezone.utc).isoformat()})
    await self._redis.publish("watchlist:alerts", msg)

async def publish_feed_recovered(self) -> None:
    msg = json.dumps({"type": "feed_recovered", "timestamp": datetime.now(timezone.utc).isoformat()})
    await self._redis.publish("watchlist:alerts", msg)
```

These are **not** `ScannerEvent` rows — they are transient system-level events with no
`ticker` or DB write. They share the `watchlist:alerts` channel so the existing WS path
delivers them to the frontend automatically.

### 3. `/api/ready` Live-Data Field

`backend/app/routers/health.py` — add an informational `live_data` probe:

```python
# IBKR probe — informational only, does not affect all_ok / HTTP status
t0 = time.monotonic()
try:
    ok = SystemService.check_ibkr_reachable(settings.IBKR_HOST, settings.IBKR_PORT)
    probes["live_data"] = {"ok": ok, "latency_ms": int((time.monotonic() - t0) * 1000)}
except Exception as exc:
    probes["live_data"] = {"ok": False, "latency_ms": int((time.monotonic() - t0) * 1000),
                           "error": str(exc)}

# all_ok considers only db and redis (live_data is non-fatal)
all_ok = probes["db"]["ok"] and probes["redis"]["ok"]
```

Response during outage (HTTP 200):
```json
{
  "status": "ready",
  "db": {"ok": true, "latency_ms": 2},
  "redis": {"ok": true, "latency_ms": 1},
  "live_data": {"ok": false, "latency_ms": 3001, "error": "Connection refused"}
}
```

`check_ibkr_reachable()` already exists in `SystemService` (`system_service.py:41`). Use it
directly with a short timeout so the probe doesn't slow down the healthcheck.

### 4. Frontend Stale Badge

`frontend/src/hooks/useWatchlistLive.ts`:

- Extend the `LiveMessage` union with `FeedLossMessage` / `FeedRecoveredMessage` types.
- Add `feedStatus: 'live' | 'lost'` to the hook's returned state (default `'live'`).
- `ws.onmessage` sets `feedStatus` to `'lost'` on `feed_loss`, `'live'` on `feed_recovered`.

`frontend/src/pages/ActiveWatchlist/index.tsx`:

- Add an amber banner below the existing `Wifi`/`WifiOff` indicator when
  `feedStatus === 'lost'`:
  ```tsx
  {feedStatus === 'lost' && (
    <span className="inline-block text-xs px-1.5 py-0.5 rounded border border-amber-500
                     text-amber-400 bg-amber-950">
      Feed stale — IBKR gateway disconnected
    </span>
  )}
  ```
- Do **not** modify `AlertBadges.tsx` — it is per-symbol scanner-alert rendering, not a
  global feed-status component.

The existing per-symbol 15s staleness (grey price, drop in live-pulse dot) is complementary
and remains unchanged.

### 5. Chaos Test Script

`scripts/chaos/ibkr_kill_test.sh`:

```
Usage: bash scripts/chaos/ibkr_kill_test.sh [--mock]

Brings up a minimal compose subset, runs both failure modes (container-stop and
network-partition), asserts degradation and recovery, then tears down.

Environment:
  IB_USERNAME / IB_PASSWORD  — required unless --mock is passed
  RECOVERY_TIMEOUT_S         — default 60; assertion window for stream resume
```

**Test sequence per failure mode:**

1. `docker compose up -d postgres redis ib-gateway live-scanner backend`
2. Wait for `backend` to be healthy (poll `/api/ready` until DB+Redis ok, max 120s).
3. Seed one watchlist symbol (e.g. SPY) via `POST /api/v1/watchlist/` from fixture data.
4. Wait for a live bar on Redis `watchlist:live_data` channel (baseline confirmation, max 60s).
5. **Failure injection:**
   - Mode A: `docker stop stockscanner-ibgateway`
   - Mode B: `docker network disconnect stockscanner-network stockscanner-ibgateway`
6. **During outage assertions** (poll for up to 30s):
   - `redis-cli subscribe watchlist:alerts` receives a message with `"type":"feed_loss"`.
   - `curl /api/ready` returns HTTP 200 with `live_data.ok == false`.
7. **Restore:**
   - Mode A: `docker start stockscanner-ibgateway`
   - Mode B: `docker network connect stockscanner-network stockscanner-ibgateway`
8. **Recovery assertions** (poll for up to `RECOVERY_TIMEOUT_S=60`):
   - `redis-cli subscribe watchlist:alerts` receives `"type":"feed_recovered"`.
   - New bars arrive on `watchlist:live_data` with timestamps after the gap start.
   - `curl /api/ready` returns `live_data.ok == true`.
9. **Gap integrity assertion**: verify no bars arrived on `watchlist:live_data` with
   timestamps inside the outage window (no interpolated bars).
10. `docker compose down -v`.

`scripts/chaos/README.md` documents prerequisites and invocation.

### 6. CI Nightly Workflow

`.github/workflows/chaos-nightly.yml`:

```yaml
on:
  schedule:
    - cron: '0 3 * * 1-5'   # 03:00 UTC, weekdays
  workflow_dispatch:

jobs:
  chaos:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@...
      - name: Run IBKR chaos test (mock mode)
        env:
          POSTGRES_PASSWORD: test
          SECRET_KEY: test-secret-key-must-be-at-least-32-chars
          JWT_SECRET_KEY: test-jwt-secret-key-must-be-at-least-32-chars
        run: bash scripts/chaos/ibkr_kill_test.sh --mock
```

When `IB_USERNAME` / `IB_PASSWORD` secrets are configured in the repository, the workflow
runs without `--mock` using real IBKR paper credentials. The mock mode is the default for
forks and PRs where secrets are absent.

### 7. Runbook

Added as a section in `docs/superpowers/specs/` (or `deployment-guide.md` as part of the
implementation):

**What operators see during a feed loss:**

- **Seq**: `LOG_LEVEL=WARNING` from `live_scanner.ibkr_adapter` — "IB Gateway disconnected"
  event followed by reconnect attempts (log every backoff cycle).
- **Grafana**: `ibkr_connection_status` gauge (`app/core/metrics.py`) drops to 0.
  The existing Grafana alerting rule `ibkr_disconnect_2min` fires if outage exceeds 2 min.
- **Frontend**: amber "Feed stale — IBKR gateway disconnected" badge on ActiveWatchlist.
- **`/api/ready`**: `live_data.ok == false` (HTTP still 200; DB/Redis still healthy).

**Recovery**:

- In-process reconnect logs successive attempts with backoff delays.
- On reconnect, `feed_recovered` event appears on `watchlist:alerts` → badge clears.
- Grafana `ibkr_connection_status` returns to 1; alert resolves.

## Alternatives Considered

**A: Container restart as sole recovery mechanism**

`restart: unless-stopped` already set; add `deploy.restart_policy.max_attempts=5`.
Rejected because:
- Cannot satisfy network-partition failure mode (process doesn't crash, just hangs).
- Cannot publish `feed_loss`/`feed_recovered` events as distinct from cold start.
- Recovery time is longer (container teardown, re-seed historical data via `fetch_seed_data`,
  re-subscribe all symbols), making the N=60s recovery assertion harder to meet.
- Loses `BarAggregator` in-memory state, increasing gap-bar noise.

**B: Client-side staleness inference (no explicit feed_loss event)**

The frontend already does this (15s grey-out). Rejected because the issue explicitly states
"a feed-loss event is published on `watchlist:alerts` — silence is a fail."

**C: Separate `/api/v1/system/live-status` endpoint for IBKR health**

`GET /api/v1/system/status` already exposes `ibkr_reachable` (30s cache). A second dedicated
endpoint adds surface area without benefit. Adding an informational field to the existing
`/api/ready` is minimal and directly testable from the chaos script.

**D: Python pytest + Docker SDK**

Better assertion ergonomics but adds `docker` pip dependency (not in `requirements.txt`),
breaks the pattern that `pytest` only runs against a postgres sidecar (no Docker socket in
the existing CI job), and misfit with `tests/scripts/` (report-tooling only). Shell script
matches existing ops-script style (`scripts/backup.sh`, `scripts/codeindex.sh`).

## Open Questions

- **IB_USERNAME / IB_PASSWORD in CI**: When real paper credentials are available as GitHub
  secrets, the nightly workflow can run without `--mock` and cover the full ib_insync path.
  The spec uses `--mock` as the default. Paper-credential CI coverage is deferred until
  secrets are configured.
- **`HEARTBEAT_STALE_SECONDS`**: 30s default (≈6 missed 5-second bars). Tune in the plan
  if market microstructure shows bursty gaps > 30s for illiquid symbols.

## Assumptions

- `restart: unless-stopped` remains on `live-scanner` (confirmed in `docker-compose.yml`).
- `check_ibkr_reachable()` accepts explicit `host`/`port` args; current signature is
  `check_ibkr_reachable()` with no args — the plan will verify and update the call site
  if needed.
- The mock adapter (`MockLiveAdapter`) will be extended to support simulating a disconnect
  event so the chaos test can run without live IBKR credentials.
- `LIVE_SCANNER_MOCK` env var is added to `Settings` with `bool` type and `False` default;
  `LIVE_SCANNER_MOCK=false` is added to `docker-compose.override.yml` for explicitness.
- Recovery N=60s is achievable given `_connect_ib`'s first retry fires at 5s — the
  reconnect succeeds on first or second attempt when the gateway is fully up.
- No changes to `ScannerEvent`, `BarAggregator`, or the batch scanner path.
