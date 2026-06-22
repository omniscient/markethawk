# IBKR Chaos Test

Verifies live-scanner resilience to IBKR gateway failure in two modes:

- **Mode A — container stop** (`docker stop`): clean TCP close; `disconnectedEvent` fires
  immediately → in-process reconnect path activates.
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

# Use a different IBKR container name
IBKR_CONTAINER=my-ibgateway bash scripts/chaos/ibkr_kill_test.sh
```

## Assertions Checked

| Assertion | Mode | Description |
|---|---|---|
| `/api/ready` live_data | A + B | `live_data.ok == false` during outage (HTTP still 200) |
| `/api/ready` recovery | A + B | `live_data.ok == true` after gateway restore within `RECOVERY_TIMEOUT_S` |

Mock mode validates that `live_data.ok=false` when no IBKR gateway is reachable.
Live mode covers both Mode A (container stop) and Mode B (network partition).

## What the Test Verifies

1. **In-process reconnect** — live-scanner does not require a container restart to recover;
   `_reconnect_coro` fires within 5 s and re-subscribes all watchlist symbols.
2. **Network-partition detection** — `_watchdog_loop` detects > 30 s without bars during
   market hours and forces `ib.disconnect()`, which triggers the same reconnect path.
3. **No global unhealthy** — `/api/ready` HTTP status remains 200 during IBKR outage;
   only `live_data.ok` changes.

## What Operators See During an Outage

**Seq** (filter by `live_scanner.ibkr_adapter`):
- `WARNING`: `"IB Gateway disconnected"` (container-stop mode fires immediately)
- `WARNING` from watchdog: `"no bars for Xs during market hours — forcing disconnect"` after ~30–40 s
- Reconnect attempts logged with backoff delays (5 s, 10 s, 20 s, …)

**Grafana** (`ibkr_connection_status` gauge):
- Drops to `0` on disconnect; returns to `1` on recovery
- Alert rule `ibkr_disconnect_2min` fires if outage exceeds 2 minutes

**Frontend (`/watchlist`)**:
- Amber banner: `"Feed stale — IBKR gateway disconnected"` appears next to the Live indicator
- Clears when `feed_recovered` event arrives on `watchlist:alerts`

**`/api/ready`**:
```json
{
  "status": "ready",
  "db": {"ok": true, "latency_ms": 2},
  "redis": {"ok": true, "latency_ms": 1},
  "live_data": {"ok": false, "latency_ms": 3001, "error": "Connection refused"}
}
```
