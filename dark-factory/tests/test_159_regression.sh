#!/usr/bin/env bash
# Regression test for the #159 dispatch loop.
# Simulates: unlabelled Backlog issue, failing dispatch, N cycles → Blocked.
# Run: bash dark-factory/tests/test_159_regression.sh
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

STATE_FILE=$(mktemp /tmp/159-state-XXXXXX.json)
echo '{}' > "$STATE_FILE"
export STATE_FILE

# Stub credentials to satisfy the validation block (runs before SCHEDULER_SOURCE_ONLY guard)
export GH_TOKEN="${GH_TOKEN:-stub-token}"
export CLAUDE_CODE_OAUTH_TOKEN="${CLAUDE_CODE_OAUTH_TOKEN:-stub-token}"

STUB_LOG=$(mktemp /tmp/159-stubs-XXXXXX.log)
DISPATCH_CALLS=0

# Source scheduler functions first so our stubs override the real definitions.
# scheduler.sh defines is_issue_running() at line ~86; exporting stubs before source
# would be clobbered. Define and export stubs AFTER source.
SCHEDULER_SOURCE_ONLY=1 source "$SCRIPT_DIR/../scheduler.sh"

# Override external commands with stubs (defined after source to win the override race)
gh()               { echo "gh $*"               >> "$STUB_LOG"; return 0; }
set_board_status() { echo "set_board_status $*" >> "$STUB_LOG"; return 0; }
docker() {
  echo "docker $*" >> "$STUB_LOG"
  if echo "$*" | grep -q "compose.*run"; then
    DISPATCH_CALLS=$((DISPATCH_CALLS+1))
    return 1   # simulate failing docker compose run
  fi
  return 0
}
is_issue_running() { return 1; }

PASSED=0; FAILED=0
assert_eq() {
  local desc="$1" expected="$2" actual="$3"
  if [ "$expected" = "$actual" ]; then
    echo "  PASS: $desc"; PASSED=$((PASSED+1))
  else
    echo "  FAIL: $desc — expected='$expected' got='$actual'" >&2; FAILED=$((FAILED+1))
  fi
}

echo "=== #159 Regression: unlabelled Backlog issue, failing dispatch ==="
echo ""

# Phase 1: unlabelled issue is never dispatched (opt-in gate)
echo "--- Phase 1: Opt-in gate blocks unlabelled issue ---"
echo '{}' > "$STATE_FILE"; > "$STUB_LOG"; DISPATCH_CALLS=0

ITEM_UNLABELLED='{"content":{"number":159,"type":"Issue"},"labels":["needs-triage"],"status":"Backlog"}'
has_opt_in_refine_label "$ITEM_UNLABELLED" \
  && assert_eq "unlabelled issue blocked by opt-in gate" "dispatched" "dispatched" \
  || assert_eq "unlabelled issue blocked by opt-in gate" "skipped" "skipped"
assert_eq "no dispatch calls for unlabelled item" "0" "$DISPATCH_CALLS"

# Phase 2: labelled issue with failing dispatch trips to Blocked within MAX retries
echo ""
echo "--- Phase 2: Failing dispatch trips to Blocked within ${REFINE_MAX_RETRIES:-3} retries ---"
echo '{}' > "$STATE_FILE"; > "$STUB_LOG"; DISPATCH_CALLS=0
MAX="${REFINE_MAX_RETRIES:-3}"
ISSUE="159"

CYCLES=0
while [ "$CYCLES" -le "$MAX" ]; do
  RETRIES=$(get_retry_count "${ISSUE}:refine")
  if [ "$RETRIES" -ge "$MAX" ]; then
    trip_to_blocked "$ISSUE" "refine" "retry limit reached in regression test"
    break
  fi
  increment_retry "${ISSUE}:refine"
  dispatch "Refine issue #${ISSUE}" || true
  CYCLES=$((CYCLES+1))
done

assert_eq "dispatch attempted exactly ${MAX} times" "$MAX" "$DISPATCH_CALLS"
assert_eq "retry counter reset to 0 after trip"     "0"    "$(get_retry_count "${ISSUE}:refine")"
assert_eq "set_board_status called (→ Blocked)"      "1" \
  "$(grep -c "set_board_status ${ISSUE}" "$STUB_LOG" || echo 0)"
assert_eq "needs-discussion label added" "1" \
  "$(grep -c -- '--add-label needs-discussion' "$STUB_LOG" || echo 0)"

# Phase 3: tripped issue is skipped on next cycle (has needs-discussion)
echo ""
echo "--- Phase 3: Tripped issue skipped by dispatch loops ---"
ITEM_TRIPPED='{"content":{"number":159,"type":"Issue"},"labels":["needs-discussion"],"status":"Blocked"}'
has_skip_label "$ITEM_TRIPPED" \
  && assert_eq "tripped issue skipped (has needs-discussion)" "skipped" "skipped" \
  || assert_eq "tripped issue skipped (has needs-discussion)" "skipped" "dispatched"

# Cleanup
rm -f "$STATE_FILE" "$STUB_LOG"
echo ""
echo "Results: ${PASSED} passed, ${FAILED} failed"
[ "$FAILED" -eq 0 ]
