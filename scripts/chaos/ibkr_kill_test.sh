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
#   CONTAINER_NETWORK          — Docker network name (default: markethawk_default)
#   IBKR_CONTAINER             — IBKR gateway container name (default: stockscanner-ibgateway)

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

# ── Helpers ───────────────────────────────────────────────────────────────────

wait_for_ready() {
  local max=$1 elapsed=0
  info "Waiting for backend ready (max ${max}s)…"
  until curl -sf "$BACKEND_URL/api/ready" 2>/dev/null | \
      python3 -c "import sys,json; d=json.load(sys.stdin); sys.exit(0 if d.get('status')=='ready' else 1)" \
      2>/dev/null; do
    sleep 2; elapsed=$((elapsed + 2))
    if [ $elapsed -ge $max ]; then
      fail "Backend not ready after ${max}s"
      return 1
    fi
  done
  pass "Backend ready"
}

assert_live_data_ok() {
  local expected=$1 actual
  actual=$(curl -sf "$BACKEND_URL/api/ready" 2>/dev/null \
           | python3 -c "import sys,json; d=json.load(sys.stdin); print(str(d['live_data']['ok']).lower())" \
           2>/dev/null || echo "error")
  if [ "$actual" = "$expected" ]; then
    pass "/api/ready live_data.ok=${expected}"
  else
    fail "/api/ready live_data.ok expected=${expected}, got=${actual}"
  fi
}

wait_for_live_data_ok() {
  local expected=$1 timeout=$2 elapsed=0
  info "Waiting for live_data.ok=${expected} (max ${timeout}s)…"
  while [ $elapsed -lt $timeout ]; do
    local actual
    actual=$(curl -sf "$BACKEND_URL/api/ready" 2>/dev/null \
             | python3 -c "import sys,json; d=json.load(sys.stdin); print(str(d['live_data']['ok']).lower())" \
             2>/dev/null || echo "error")
    if [ "$actual" = "$expected" ]; then
      pass "live_data.ok=${expected} confirmed"
      return 0
    fi
    sleep 2; elapsed=$((elapsed + 2))
  done
  fail "live_data.ok=${expected} not reached within ${timeout}s"
  return 1
}

# ── Setup ─────────────────────────────────────────────────────────────────────

info "Starting minimal compose stack…"
export LIVE_SCANNER_MOCK=$MOCK

if [ "$MOCK" = "true" ]; then
  $COMPOSE up -d postgres redis backend live-scanner
else
  $COMPOSE up -d postgres redis backend live-scanner ib-gateway
fi

wait_for_ready 120

info "Seeding SPY to watchlist (ignore errors if already present)…"
curl -sf -X POST "$BACKEND_URL/api/v1/watchlist/" \
  -H "Content-Type: application/json" \
  -d '{"symbol":"SPY","security_type":"STK"}' > /dev/null 2>&1 || true

if [ "$MOCK" = "false" ]; then
  info "Waiting for baseline IBKR connection (max 90s)…"
  wait_for_live_data_ok "true" 90 || true
fi

# ── Mode A: container stop ────────────────────────────────────────────────────

info "=== Failure Mode A: container stop ==="

if [ "$MOCK" = "false" ]; then
  info "Stopping IBKR gateway container…"
  docker stop "$IBKR_CONTAINER"
  sleep 5

  # During outage: live_data.ok should become false
  wait_for_live_data_ok "false" 30 || fail "Mode A: live_data did not show false during outage"

  info "Restoring gateway (Mode A)…"
  docker start "$IBKR_CONTAINER"

  # After restore: live_data.ok should recover
  wait_for_live_data_ok "true" "$RECOVERY_TIMEOUT_S" || fail "Mode A: not recovered within ${RECOVERY_TIMEOUT_S}s"
  pass "Mode A: recovery confirmed"
else
  info "Mock mode: IBKR probe will show false (no gateway running)"
  assert_live_data_ok "false" || true
  info "Mock mode: simulated disconnect/recovery happens internally — Mode A skipped for mock"
  pass "Mode A: mock mode — live_data.ok=false as expected (no live gateway)"
fi

# ── Mode B: network partition ─────────────────────────────────────────────────

if [ "$MOCK" = "false" ]; then
  info "=== Failure Mode B: network partition ==="

  info "Disconnecting IBKR gateway from network…"
  docker network disconnect "$CONTAINER_NETWORK" "$IBKR_CONTAINER" || true

  # Wait for watchdog to detect stale bars (HEARTBEAT_STALE_SECONDS=30, watchdog polls every 10s)
  info "Waiting ${HEARTBEAT_STALE_SECONDS:-30}s for watchdog to detect stale bars…"
  sleep "${HEARTBEAT_STALE_SECONDS:-30}"
  sleep 15  # extra margin for watchdog poll cycle

  assert_live_data_ok "false" || true

  info "Reconnecting IBKR gateway to network…"
  docker network connect "$CONTAINER_NETWORK" "$IBKR_CONTAINER" || true

  wait_for_live_data_ok "true" "$RECOVERY_TIMEOUT_S" || fail "Mode B: not recovered within ${RECOVERY_TIMEOUT_S}s"
  pass "Mode B: recovery confirmed"
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
