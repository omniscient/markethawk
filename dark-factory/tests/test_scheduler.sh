#!/usr/bin/env bash
# Unit tests for scheduler.sh helpers.
# Run: bash dark-factory/tests/test_scheduler.sh
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SCHED="$SCRIPT_DIR/../scheduler.sh"

# ---- Stubs ----
STUB_LOG=$(mktemp /tmp/sched-test-stubs-XXXXXX.log)
gh()               { echo "gh $*"               >> "$STUB_LOG"; return 0; }
docker()           { echo "docker $*"           >> "$STUB_LOG"; return 0; }
set_board_status() { echo "set_board_status $*" >> "$STUB_LOG"; return 0; }
export -f gh docker set_board_status

# ---- Source scheduler helpers only ----
STATE_FILE=$(mktemp /tmp/sched-test-state-XXXXXX.json)
echo '{}' > "$STATE_FILE"
export STATE_FILE
# Stub credentials to satisfy the validation block (which runs before SCHEDULER_SOURCE_ONLY guard)
export GH_TOKEN="${GH_TOKEN:-stub-token}"
export CLAUDE_CODE_OAUTH_TOKEN="${CLAUDE_CODE_OAUTH_TOKEN:-stub-token}"
SCHEDULER_SOURCE_ONLY=1 source "$SCHED"

# Re-stub set_board_status — scheduler.sh defines its own, overriding the export above
set_board_status() { echo "set_board_status $*" >> "$STUB_LOG"; return 0; }

# ---- Runner ----
PASSED=0; FAILED=0
assert_eq() {
  local desc="$1" expected="$2" actual="$3"
  if [ "$expected" = "$actual" ]; then
    echo "  PASS: $desc"; PASSED=$((PASSED+1))
  else
    echo "  FAIL: $desc — expected='$expected' got='$actual'" >&2; FAILED=$((FAILED+1))
  fi
}

# ==========================================
# A: Retry helpers (should pass immediately)
# ==========================================
echo "--- A: Retry helpers ---"
echo '{}' > "$STATE_FILE"

assert_eq "unknown key returns 0"       "0" "$(get_retry_count "42:refine")"
increment_retry "42:refine"
assert_eq "after 1 increment"           "1" "$(get_retry_count "42:refine")"
increment_retry "42:refine"
assert_eq "after 2 increments"          "2" "$(get_retry_count "42:refine")"
reset_retry "42:refine"
assert_eq "after reset"                 "0" "$(get_retry_count "42:refine")"
increment_retry "42"
assert_eq "bare key independent"        "1" "$(get_retry_count "42")"
assert_eq ":refine unaffected by bare"  "0" "$(get_retry_count "42:refine")"

# ==========================================
# B: trip_to_blocked (fails until Task 5)
# ==========================================
echo ""
echo "--- B: trip_to_blocked ---"
echo '{}' > "$STATE_FILE"; > "$STUB_LOG"

increment_retry "99:plan"
increment_retry "99:plan"
increment_retry "99:plan"

trip_to_blocked "99" "plan" "test reason"

assert_eq "set_board_status called" \
  "1" "$(grep -c 'set_board_status 99' "$STUB_LOG" || echo 0)"
assert_eq "gh issue edit adds needs-discussion" \
  "1" "$(grep -c 'issue edit 99.*needs-discussion' "$STUB_LOG" || echo 0)"
assert_eq "gh issue comment posted" \
  "1" "$(grep -c 'issue comment 99' "$STUB_LOG" || echo 0)"
assert_eq ":plan counter reset after trip" \
  "0" "$(get_retry_count "99:plan")"

echo '{}' > "$STATE_FILE"; > "$STUB_LOG"
increment_retry "88:refine"
trip_to_blocked "88" "refine" "test"
assert_eq ":refine counter reset" "0" "$(get_retry_count "88:refine")"

echo '{}' > "$STATE_FILE"; > "$STUB_LOG"
increment_retry "77"
trip_to_blocked "77" "implement" "test"
assert_eq "bare implement counter reset" "0" "$(get_retry_count "77")"

# ==========================================
# C: dispatch() exit-code capture (fails until Task 3)
# ==========================================
echo ""
echo "--- C: dispatch() exit-code capture ---"
> "$STUB_LOG"

_orig_docker() { echo "docker $*" >> "$STUB_LOG"; return 0; }
docker() {
  echo "docker $*" >> "$STUB_LOG"
  echo "$*" | grep -q "compose.*run" && return 42
  return 0
}
export -f docker

EXIT_CODE=0
dispatch "Fix issue #1" || EXIT_CODE=$?
assert_eq "dispatch returns non-zero exit code" "42" "$EXIT_CODE"
assert_eq "dispatch uses --no-build" \
  "1" "$(grep -c -- '--no-build' "$STUB_LOG" || echo 0)"

docker() { echo "docker $*" >> "$STUB_LOG"; return 0; }
export -f docker

# ==========================================
# D: Opt-in label gate (fails until Task 8)
# ==========================================
echo ""
echo "--- D: Opt-in label gate ---"

ITEM_WITH='{"content":{"number":1},"labels":["ready-for-agent","needs-triage"],"status":"Backlog"}'
ITEM_WITHOUT='{"content":{"number":2},"labels":["needs-triage"],"status":"Backlog"}'

has_opt_in_refine_label "$ITEM_WITH"    \
  && assert_eq "item WITH label passes gate"    "0" "0" \
  || assert_eq "item WITH label passes gate"    "0" "1"
has_opt_in_refine_label "$ITEM_WITHOUT" \
  && assert_eq "item WITHOUT label blocked"     "0" "1" \
  || assert_eq "item WITHOUT label blocked"     "0" "0"

# ==========================================
# E: has_direct_to_pr_label
# ==========================================
echo ""
echo "--- E: has_direct_to_pr_label ---"

ITEM_DTP='{"content":{"number":10},"labels":["enhancement","direct-to-pr"],"status":"Backlog"}'
ITEM_NO_DTP='{"content":{"number":11},"labels":["enhancement","ready-for-agent"],"status":"Backlog"}'

has_direct_to_pr_label "$ITEM_DTP" \
  && assert_eq "item WITH direct-to-pr returns true" "0" "0" \
  || assert_eq "item WITH direct-to-pr returns true" "0" "1"

has_direct_to_pr_label "$ITEM_NO_DTP" \
  && assert_eq "item WITHOUT direct-to-pr returns false" "0" "1" \
  || assert_eq "item WITHOUT direct-to-pr returns false" "0" "0"

# ==========================================
# F: elapsed_minutes_since_marker
# ==========================================
echo ""
echo "--- F: elapsed_minutes_since_marker ---"

# Compute a timestamp 35 minutes in the past
_MARKER_EPOCH=$(( $(date -u +%s) - 35*60 ))
_MARKER_TS=$(date -u -d "@${_MARKER_EPOCH}" +%Y-%m-%dT%H:%M:%SZ)

gh() {
  printf '[{"body":"Refinement Pipeline — Plan Generated","createdAt":"%s"}]\n' "$_MARKER_TS"
}
export -f gh

_ELAPSED=$(elapsed_minutes_since_marker "55" "Refinement Pipeline")
[ -n "$_ELAPSED" ] && [ "$_ELAPSED" -ge 34 ] \
  && assert_eq "elapsed ≥ 34 for 35-min-old marker" "0" "0" \
  || assert_eq "elapsed ≥ 34 for 35-min-old marker" "0" "1"

# No matching comment → returns ""
gh() { printf '[{"body":"some other comment","createdAt":"%s"}]\n' "$_MARKER_TS"; }
export -f gh
_ELAPSED2=$(elapsed_minutes_since_marker "55" "Refinement Pipeline")
assert_eq "no matching marker returns empty" "" "$_ELAPSED2"

# Restore original gh stub
gh() { echo "gh $*" >> "$STUB_LOG"; return 0; }
export -f gh

# ==========================================
# G: Spec auto-advance (direct-to-pr)
# ==========================================
echo ""
echo "--- G: Spec auto-advance ---"
echo '{}' > "$STATE_FILE"; > "$STUB_LOG"
# Initialize variables that the main loop sets but tests don't have
REFINE_RUNNING=0
DISPATCHED=""

_ITEM_DTP_SPR='{"content":{"number":20},"labels":["direct-to-pr","spec-pending-review"],"status":"Backlog"}'
_ITEM_NODTP_SPR='{"content":{"number":21},"labels":["spec-pending-review"],"status":"Backlog"}'

# G1: flag + human comment → re-refine path (remove-label + dispatch Refine)
has_new_comment_after_report() { echo "yes"; }
elapsed_minutes_since_marker() { echo "99"; }
dispatch() { echo "dispatch $*" >> "$STUB_LOG"; return 0; }
export -f has_new_comment_after_report elapsed_minutes_since_marker dispatch

spec_advance_check 20 "$_ITEM_DTP_SPR"
assert_eq "G1: re-refine: remove-label called" \
  "1" "$(grep -c -- '--remove-label spec-pending-review' "$STUB_LOG" || echo 0)"
assert_eq "G1: re-refine: Refine dispatched" \
  "1" "$(grep -c 'dispatch Refine issue #20' "$STUB_LOG" || echo 0)"

> "$STUB_LOG"
# G2: flag + no comment + elapsed ≥ grace → advance (remove-label + set_board_status REFINED)
has_new_comment_after_report() { echo "no"; }
export SPEC_GRACE_MINUTES=30
elapsed_minutes_since_marker() { echo "35"; }
export -f has_new_comment_after_report elapsed_minutes_since_marker

spec_advance_check 20 "$_ITEM_DTP_SPR"
assert_eq "G2: advance: remove-label called" \
  "1" "$(grep -c -- '--remove-label spec-pending-review' "$STUB_LOG" || echo 0)"
assert_eq "G2: advance: set_board_status REFINED" \
  "1" "$(grep -c "set_board_status 20 ${STATUS_REFINED}" "$STUB_LOG" || echo 0)"

> "$STUB_LOG"
# G3: flag + no comment + elapsed < grace → no action
elapsed_minutes_since_marker() { echo "10"; }
export -f elapsed_minutes_since_marker

spec_advance_check 20 "$_ITEM_DTP_SPR"
assert_eq "G3: within-window: no set_board_status" \
  "0" "$(grep -c 'set_board_status' "$STUB_LOG" || true)"
assert_eq "G3: within-window: no dispatch" \
  "0" "$(grep -c 'dispatch' "$STUB_LOG" || true)"

> "$STUB_LOG"
# G4: no flag → no auto-advance (regression guard)
elapsed_minutes_since_marker() { echo "99"; }
export -f elapsed_minutes_since_marker

spec_advance_check 21 "$_ITEM_NODTP_SPR"
assert_eq "G4: no-flag regression: no advance" \
  "0" "$(grep -c 'set_board_status' "$STUB_LOG" || true)"

> "$STUB_LOG"
# G5: flag + needs-discussion → suppressed (no advance, even with elapsed ≥ grace)
_ITEM_DTP_SPR_ND='{"content":{"number":22},"labels":["direct-to-pr","spec-pending-review","needs-discussion"],"status":"Backlog"}'
elapsed_minutes_since_marker() { echo "99"; }
export -f elapsed_minutes_since_marker

spec_advance_check 22 "$_ITEM_DTP_SPR_ND"
assert_eq "G5: needs-discussion suppresses spec advance" \
  "0" "$(grep -c 'set_board_status' "$STUB_LOG" || true)"
assert_eq "G5: needs-discussion suppresses spec dispatch" \
  "0" "$(grep -c 'dispatch' "$STUB_LOG" || true)"

# Restore stubs
has_new_comment_after_report() { echo "no"; }
elapsed_minutes_since_marker() { echo ""; }
dispatch() { echo "dispatch $*" >> "$STUB_LOG"; return 0; }
export -f has_new_comment_after_report elapsed_minutes_since_marker dispatch

# ==========================================
# Cleanup
# ==========================================
rm -f "$STATE_FILE" "$STUB_LOG"
echo ""
echo "Results: ${PASSED} passed, ${FAILED} failed"
[ "$FAILED" -eq 0 ]
