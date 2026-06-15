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
# Point the state dir at a temp dir BEFORE sourcing: scheduler.sh derives STATE_FILE
# and RECHECK_STAMP_FILE from it (and mkdir-s it), so tests must not touch the real
# /var/lib/dark-factory.
SCHEDULER_STATE_DIR=$(mktemp -d /tmp/sched-test-statedir-XXXXXX)
export SCHEDULER_STATE_DIR
STATE_FILE=$(mktemp /tmp/sched-test-state-XXXXXX.json)
echo '{}' > "$STATE_FILE"
export STATE_FILE
# Stub credentials to satisfy the validation block (which runs before SCHEDULER_SOURCE_ONLY guard)
export GH_TOKEN="${GH_TOKEN:-stub-token}"
export CLAUDE_CODE_OAUTH_TOKEN="${CLAUDE_CODE_OAUTH_TOKEN:-stub-token}"
# Set all config-driven vars explicitly: read_config runs after SCHEDULER_SOURCE_ONLY guard
# so these values won't be populated by config.yaml during test sourcing.
export POLL_INTERVAL=60
export MAX_RETRIES=3
export RATE_LIMIT_FLOOR=200
export FACTORY_WIP_LIMIT=1
export MAIN_RED_RECHECK_ENABLED=true
export MAIN_RED_RECHECK_MINUTES=20
export REFINE_WIP_LIMIT=2
export DIRECT_TO_PR_LABEL=direct-to-pr
export SPEC_GRACE_MINUTES=30
export PLAN_GRACE_MINUTES=30
export CONFLICT_RESOLUTION_ENABLED=true
export DISPATCH_CEILING_ENABLED=true
export ABOVE_CEILING_LABEL=above-ceiling
export ABOVE_CEILING_KEYWORDS="migration|migrate|performance|perf|architectur|refactor"
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
assert_eq "gh issue edit adds factory-regression" \
  "1" "$(grep -c 'issue edit 99.*factory-regression' "$STUB_LOG" || echo 0)"
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
assert_eq "dispatch does not pass --no-build (invalid flag for 'compose run')" \
  "0" "$(grep -c -- '--no-build' "$STUB_LOG" || true)"

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
# H: Entry trigger — direct-to-pr admits Backlog items
# ==========================================
echo ""
echo "--- H: Entry trigger ---"

ITEM_DTP_ONLY='{"content":{"number":30},"labels":["direct-to-pr"],"status":"Backlog"}'
ITEM_RFA_ONLY='{"content":{"number":31},"labels":["ready-for-agent"],"status":"Backlog"}'
ITEM_NEITHER='{"content":{"number":32},"labels":["needs-triage"],"status":"Backlog"}'
ITEM_BOTH='{"content":{"number":33},"labels":["direct-to-pr","ready-for-agent"],"status":"Backlog"}'

# H1: direct-to-pr alone → passes entry gate
(has_opt_in_refine_label "$ITEM_DTP_ONLY" || has_direct_to_pr_label "$ITEM_DTP_ONLY") \
  && assert_eq "H1: direct-to-pr admits item" "0" "0" \
  || assert_eq "H1: direct-to-pr admits item" "0" "1"

# H2: ready-for-agent alone → still passes (unchanged)
(has_opt_in_refine_label "$ITEM_RFA_ONLY" || has_direct_to_pr_label "$ITEM_RFA_ONLY") \
  && assert_eq "H2: ready-for-agent still admits item" "0" "0" \
  || assert_eq "H2: ready-for-agent still admits item" "0" "1"

# H3: neither → blocked
(has_opt_in_refine_label "$ITEM_NEITHER" || has_direct_to_pr_label "$ITEM_NEITHER") \
  && assert_eq "H3: neither label is blocked" "0" "1" \
  || assert_eq "H3: neither label is blocked" "0" "0"

# H4: both labels → passes (direct-to-pr wins, no double-dispatch risk)
(has_opt_in_refine_label "$ITEM_BOTH" || has_direct_to_pr_label "$ITEM_BOTH") \
  && assert_eq "H4: both labels passes gate once" "0" "0" \
  || assert_eq "H4: both labels passes gate once" "0" "1"

# ==========================================
# I: Plan auto-advance (direct-to-pr)
# ==========================================
echo ""
echo "--- I: Plan auto-advance ---"
echo '{}' > "$STATE_FILE"; > "$STUB_LOG"
REFINE_RUNNING=0
DISPATCHED=""

_ITEM_DTP_PPR='{"content":{"number":40},"labels":["direct-to-pr","plan-pending-review"],"status":"Refined"}'
_ITEM_NODTP_PPR='{"content":{"number":41},"labels":["plan-pending-review"],"status":"Refined"}'

# I1: flag + human comment → re-plan
has_new_comment_after_report() { echo "yes"; }
dispatch() { echo "dispatch $*" >> "$STUB_LOG"; return 0; }
export -f has_new_comment_after_report dispatch

plan_advance_check 40 "$_ITEM_DTP_PPR"
assert_eq "I1: re-plan: remove-label called" \
  "1" "$(grep -c -- '--remove-label plan-pending-review' "$STUB_LOG" || echo 0)"
assert_eq "I1: re-plan: Plan dispatched" \
  "1" "$(grep -c 'dispatch Plan issue #40' "$STUB_LOG" || echo 0)"

> "$STUB_LOG"
# I2: flag + no comment + elapsed ≥ grace → advance to Ready
has_new_comment_after_report() { echo "no"; }
export PLAN_GRACE_MINUTES=30
elapsed_minutes_since_marker() { echo "35"; }
export -f has_new_comment_after_report elapsed_minutes_since_marker

plan_advance_check 40 "$_ITEM_DTP_PPR"
assert_eq "I2: advance: remove-label called" \
  "1" "$(grep -c -- '--remove-label plan-pending-review' "$STUB_LOG" || echo 0)"
assert_eq "I2: advance: set_board_status READY" \
  "1" "$(grep -c "set_board_status 40 ${STATUS_READY}" "$STUB_LOG" || echo 0)"

> "$STUB_LOG"
# I3: flag + no comment + elapsed < grace → no action
elapsed_minutes_since_marker() { echo "10"; }
export -f elapsed_minutes_since_marker

plan_advance_check 40 "$_ITEM_DTP_PPR"
assert_eq "I3: within-window: no set_board_status" \
  "0" "$(grep -c 'set_board_status' "$STUB_LOG" || true)"
assert_eq "I3: within-window: no dispatch" \
  "0" "$(grep -c 'dispatch' "$STUB_LOG" || true)"

> "$STUB_LOG"
# I4: no flag → no auto-advance (regression guard)
elapsed_minutes_since_marker() { echo "99"; }
export -f elapsed_minutes_since_marker

plan_advance_check 41 "$_ITEM_NODTP_PPR"
assert_eq "I4: no-flag regression: no advance" \
  "0" "$(grep -c 'set_board_status' "$STUB_LOG" || true)"

> "$STUB_LOG"
# I5: flag + needs-discussion → suppressed (no advance, even with elapsed ≥ grace)
_ITEM_DTP_PPR_ND='{"content":{"number":42},"labels":["direct-to-pr","plan-pending-review","needs-discussion"],"status":"Refined"}'
elapsed_minutes_since_marker() { echo "99"; }
export -f elapsed_minutes_since_marker

plan_advance_check 42 "$_ITEM_DTP_PPR_ND"
assert_eq "I5: needs-discussion suppresses plan advance" \
  "0" "$(grep -c 'set_board_status' "$STUB_LOG" || true)"
assert_eq "I5: needs-discussion suppresses plan dispatch" \
  "0" "$(grep -c 'dispatch' "$STUB_LOG" || true)"

# Restore
has_new_comment_after_report() { echo "no"; }
elapsed_minutes_since_marker() { echo ""; }
dispatch() { echo "dispatch $*" >> "$STUB_LOG"; return 0; }
export -f has_new_comment_after_report elapsed_minutes_since_marker dispatch

# ==========================================
# J: End-gate auto-merge (direct-to-pr)
# ==========================================
echo ""
echo "--- J: End-gate auto-merge ---"
echo '{}' > "$STATE_FILE"; > "$STUB_LOG"
DISPATCHED=""

_ITEM_DTP_REVIEW='{"content":{"number":50},"labels":["direct-to-pr"],"status":"In review"}'
_ITEM_NODTP_REVIEW='{"content":{"number":51},"labels":[],"status":"In review"}'

# J1: flag + APPROVED → Close dispatched
get_pr_for_issue() { echo "99"; }
gh() {
  case "$*" in
    *"pr view"*) echo "APPROVED" ;;
    *) echo "gh $*" >> "$STUB_LOG" ;;
  esac
  return 0
}
dispatch() { echo "dispatch $*" >> "$STUB_LOG"; return 0; }
export -f get_pr_for_issue gh dispatch

end_gate_check 50 "$_ITEM_DTP_REVIEW"
assert_eq "J1: APPROVED → Close dispatched" \
  "1" "$(grep -c 'dispatch Close issue #50' "$STUB_LOG" || echo 0)"

> "$STUB_LOG"
# J2: flag + CHANGES_REQUESTED → Continue dispatched
gh() {
  case "$*" in
    *"pr view"*) echo "CHANGES_REQUESTED" ;;
    *) echo "gh $*" >> "$STUB_LOG" ;;
  esac
  return 0
}
export -f gh

end_gate_check 50 "$_ITEM_DTP_REVIEW"
assert_eq "J2: CHANGES_REQUESTED → Continue dispatched" \
  "1" "$(grep -c 'dispatch Continue issue #50' "$STUB_LOG" || echo 0)"

> "$STUB_LOG"
# J3: flag + no actionable review → no dispatch (fall through)
gh() {
  case "$*" in
    *"pr view"*) echo "" ;;
    *) echo "gh $*" >> "$STUB_LOG" ;;
  esac
  return 0
}
export -f gh

end_gate_check 50 "$_ITEM_DTP_REVIEW" || true
assert_eq "J3: no review → no dispatch" \
  "0" "$(grep -c 'dispatch' "$STUB_LOG" || true)"

> "$STUB_LOG"
# J4: no flag → no end-gate dispatch (regression guard)
gh() {
  case "$*" in
    *"pr view"*) echo "APPROVED" ;;
    *) echo "gh $*" >> "$STUB_LOG" ;;
  esac
  return 0
}
export -f gh

end_gate_check 51 "$_ITEM_NODTP_REVIEW" || true
assert_eq "J4: no-flag: no end-gate dispatch" \
  "0" "$(grep -c 'dispatch Close' "$STUB_LOG" || true)"

# Restore
gh() { echo "gh $*" >> "$STUB_LOG"; return 0; }
get_pr_for_issue() { echo ""; }
dispatch() { echo "dispatch $*" >> "$STUB_LOG"; return 0; }
export -f gh get_pr_for_issue dispatch

# ==========================================
# K: Priority 1.5 — conflict gate
# ==========================================
echo ""
echo "--- K: Priority 1.5 conflict gate ---"
echo '{}' > "$STATE_FILE"; > "$STUB_LOG"
DISPATCHED=""

_ITEM_REVIEW_A='{"content":{"number":60},"labels":[],"status":"In review"}'
_ITEM_REVIEW_B='{"content":{"number":61},"labels":[],"status":"In review"}'
_ITEM_REVIEW_C='{"content":{"number":62},"labels":["needs-discussion"],"status":"In review"}'

# K1: CONFLICTING → dispatch Deconflict
get_pr_for_issue() { echo "200"; }
check_pr_mergeable() { echo "CONFLICTING"; }
is_issue_running() { return 1; }
dispatch() { echo "dispatch $*" >> "$STUB_LOG"; return 0; }
export -f get_pr_for_issue check_pr_mergeable is_issue_running dispatch

CONFLICT_RESOLUTION_ENABLED=true
CI_BLOCKED=""

# Simulate the P1.5 loop body for one item
ISSUE=$(get_issue_number "$_ITEM_REVIEW_A")
has_skip_label "$_ITEM_REVIEW_A" && SKIP=1 || SKIP=0
assert_eq "K1: no-skip-label item passes gate" "0" "$SKIP"

PR_NUM=$(get_pr_for_issue "$ISSUE")
MERGEABLE=$(check_pr_mergeable "$PR_NUM")
case "$MERGEABLE" in
  CONFLICTING)
    if ! is_issue_running "$ISSUE"; then
      if dispatch "Deconflict issue #${ISSUE}"; then
        DISPATCHED="Deconflict issue #${ISSUE}"
      fi
    fi
    ;;
esac
assert_eq "K1: CONFLICTING → Deconflict dispatched" \
  "1" "$(grep -c 'dispatch Deconflict issue #60' "$STUB_LOG" || echo 0)"

> "$STUB_LOG"; DISPATCHED=""

# K2: UNKNOWN → no dispatch
check_pr_mergeable() { echo "UNKNOWN"; }
export -f check_pr_mergeable

ISSUE=$(get_issue_number "$_ITEM_REVIEW_B")
PR_NUM=$(get_pr_for_issue "$ISSUE")
MERGEABLE=$(check_pr_mergeable "$PR_NUM")
case "$MERGEABLE" in
  CONFLICTING)
    dispatch "Deconflict issue #${ISSUE}" || true
    ;;
  UNKNOWN)
    : # skip
    ;;
esac
assert_eq "K2: UNKNOWN → no dispatch" \
  "0" "$(grep -c 'dispatch' "$STUB_LOG" || true)"

> "$STUB_LOG"; DISPATCHED=""

# K3: MERGEABLE → no dispatch
check_pr_mergeable() { echo "MERGEABLE"; }
export -f check_pr_mergeable

ISSUE=$(get_issue_number "$_ITEM_REVIEW_A")
PR_NUM=$(get_pr_for_issue "$ISSUE")
MERGEABLE=$(check_pr_mergeable "$PR_NUM")
case "$MERGEABLE" in
  CONFLICTING)
    dispatch "Deconflict issue #${ISSUE}" || true
    ;;
esac
assert_eq "K3: MERGEABLE → no dispatch" \
  "0" "$(grep -c 'dispatch' "$STUB_LOG" || true)"

> "$STUB_LOG"; DISPATCHED=""

# K4: skip label → no dispatch even if CONFLICTING
check_pr_mergeable() { echo "CONFLICTING"; }
export -f check_pr_mergeable

ISSUE=$(get_issue_number "$_ITEM_REVIEW_C")
has_skip_label "$_ITEM_REVIEW_C" \
  && assert_eq "K4: needs-discussion is a skip label" "0" "0" \
  || assert_eq "K4: needs-discussion is a skip label" "0" "1"

if ! has_skip_label "$_ITEM_REVIEW_C"; then
  dispatch "Deconflict issue #${ISSUE}" || true
fi
assert_eq "K4: skip label suppresses deconflict dispatch" \
  "0" "$(grep -c 'dispatch' "$STUB_LOG" || true)"

> "$STUB_LOG"; DISPATCHED=""

# K5: CONFLICT_RESOLUTION_ENABLED=false → entire P1.5 block skipped
check_pr_mergeable() { echo "CONFLICTING"; }
export -f check_pr_mergeable

CONFLICT_RESOLUTION_ENABLED=false
if [ "${CONFLICT_RESOLUTION_ENABLED:-true}" = "true" ]; then
  dispatch "Deconflict issue #60" || true
fi
assert_eq "K5: kill-switch disables conflict gate" \
  "0" "$(grep -c 'dispatch' "$STUB_LOG" || true)"
CONFLICT_RESOLUTION_ENABLED=true

> "$STUB_LOG"; DISPATCHED=""

# K6: is_issue_running → no duplicate dispatch
is_issue_running() { return 0; }
export -f is_issue_running

ISSUE=$(get_issue_number "$_ITEM_REVIEW_A")
if ! is_issue_running "$ISSUE"; then
  dispatch "Deconflict issue #${ISSUE}" || true
fi
assert_eq "K6: running issue skipped" \
  "0" "$(grep -c 'dispatch' "$STUB_LOG" || true)"

# K7: check_pr_mergeable returns correct format
check_pr_mergeable() {
  local pr_num="$1"
  gh pr view "$pr_num" --repo "omniscient/markethawk" --json mergeable --jq '.mergeable' 2>/dev/null || echo "UNKNOWN"
}
gh() {
  case "$*" in
    *"pr view"*) echo "CONFLICTING" ;;
    *) echo "gh $*" >> "$STUB_LOG" ;;
  esac
  return 0
}
export -f check_pr_mergeable gh

_RESULT=$(check_pr_mergeable "99")
assert_eq "K7: check_pr_mergeable returns value from gh" "CONFLICTING" "$_RESULT"

> "$STUB_LOG"; DISPATCHED=""

# K8: P1.5-1 — increment_retry recorded after CONFLICTING dispatch
echo '{}' > "$STATE_FILE"
check_pr_mergeable() { echo "CONFLICTING"; }
is_issue_running() { return 1; }
export -f check_pr_mergeable is_issue_running

ISSUE=$(get_issue_number "$_ITEM_REVIEW_A")
PR_NUM=$(get_pr_for_issue "$ISSUE")
MERGEABLE=$(check_pr_mergeable "$PR_NUM")
case "$MERGEABLE" in
  CONFLICTING)
    if ! is_issue_running "$ISSUE"; then
      increment_retry "${ISSUE}:resolve" || true
      dispatch "Deconflict issue #${ISSUE}" || true
    fi
    ;;
esac
assert_eq "K8: increment_retry recorded after CONFLICTING dispatch" \
  "1" "$(get_retry_count "60:resolve")"

> "$STUB_LOG"; DISPATCHED=""

# K9: P1.5-5 — trip_to_blocked called at MAX_RETRIES
echo "{\"60:resolve\": $MAX_RETRIES}" > "$STATE_FILE"

ISSUE=$(get_issue_number "$_ITEM_REVIEW_A")
RETRIES=$(get_retry_count "${ISSUE}:resolve")
if [ "$RETRIES" -ge "$MAX_RETRIES" ]; then
  trip_to_blocked "$ISSUE" "resolve" "retry limit of ${MAX_RETRIES} reached for conflict resolution"
else
  dispatch "Deconflict issue #${ISSUE}" || true
fi
assert_eq "K9: set_board_status Blocked logged" \
  "1" "$(grep -c "set_board_status 60 ${STATUS_BLOCKED}" "$STUB_LOG" || echo 0)"
assert_eq "K9: no dispatch on trip" \
  "0" "$(grep -c 'dispatch' "$STUB_LOG" || true)"
assert_eq "K9: retry counter reset to 0" \
  "0" "$(get_retry_count "60:resolve")"

# Restore stubs
gh() { echo "gh $*" >> "$STUB_LOG"; return 0; }
get_pr_for_issue() { echo ""; }
is_issue_running() { return 1; }
check_pr_mergeable() { echo "UNKNOWN"; }
dispatch() { echo "dispatch $*" >> "$STUB_LOG"; return 0; }
export -f gh get_pr_for_issue is_issue_running check_pr_mergeable dispatch

# ==========================================
# L: factory_at_capacity / FACTORY_WIP_LIMIT
# ==========================================
echo ""
echo "--- L: factory_at_capacity ---"

assert_eq "L0: FACTORY_WIP_LIMIT=1 (test-provided)" "1" "${FACTORY_WIP_LIMIT:-}"

FACTORY_WIP_LIMIT=1
factory_at_capacity 0 \
  && assert_eq "L1: 0 running, limit 1 → below capacity" "0" "1" \
  || assert_eq "L1: 0 running, limit 1 → below capacity" "0" "0"
factory_at_capacity 1 \
  && assert_eq "L2: 1 running, limit 1 → at capacity" "0" "0" \
  || assert_eq "L2: 1 running, limit 1 → at capacity" "0" "1"

FACTORY_WIP_LIMIT=2
factory_at_capacity 1 \
  && assert_eq "L3: 1 running, limit 2 → below capacity" "0" "1" \
  || assert_eq "L3: 1 running, limit 2 → below capacity" "0" "0"
factory_at_capacity 2 \
  && assert_eq "L4: 2 running, limit 2 → at capacity" "0" "0" \
  || assert_eq "L4: 2 running, limit 2 → at capacity" "0" "1"
factory_at_capacity 3 \
  && assert_eq "L5: 3 running, limit 2 → at capacity" "0" "0" \
  || assert_eq "L5: 3 running, limit 2 → at capacity" "0" "1"

FACTORY_WIP_LIMIT=1

# ==========================================
# M: Main-red recheck self-clear (#365)
# ==========================================
echo ""
echo "--- M: main-red recheck self-clear ---"
> "$STUB_LOG"
DISPATCHED=""

dispatch() { echo "dispatch $*" >> "$STUB_LOG"; return 0; }
is_recheck_running() { return 1; }
export -f dispatch is_recheck_running

# M1: no stamp → due
rm -f "$RECHECK_STAMP_FILE"
recheck_due \
  && assert_eq "M1: no stamp → due" "0" "0" \
  || assert_eq "M1: no stamp → due" "0" "1"

# M2: fresh stamp → throttled
touch "$RECHECK_STAMP_FILE"
recheck_due \
  && assert_eq "M2: fresh stamp → throttled" "0" "1" \
  || assert_eq "M2: fresh stamp → throttled" "0" "0"

# M3: stale stamp (older than MAIN_RED_RECHECK_MINUTES=20) → due
touch -d "25 minutes ago" "$RECHECK_STAMP_FILE"
recheck_due \
  && assert_eq "M3: stale stamp → due" "0" "0" \
  || assert_eq "M3: stale stamp → due" "0" "1"

# M4: due → dispatches "Recheck main", sets DISPATCHED, refreshes the stamp
rm -f "$RECHECK_STAMP_FILE"; DISPATCHED=""
main_red_recheck_check
assert_eq "M4: Recheck main dispatched" \
  "1" "$(grep -c 'dispatch Recheck main' "$STUB_LOG" || echo 0)"
assert_eq "M4: DISPATCHED set" "Recheck main" "$DISPATCHED"
[ -f "$RECHECK_STAMP_FILE" ] \
  && assert_eq "M4: stamp refreshed" "0" "0" \
  || assert_eq "M4: stamp refreshed" "0" "1"

# M5: stamp fresh from M4 → throttled, no dispatch
> "$STUB_LOG"; DISPATCHED=""
main_red_recheck_check
assert_eq "M5: throttled → no dispatch" \
  "0" "$(grep -c 'dispatch' "$STUB_LOG" || true)"

# M6: recheck container already running → no dispatch even when due
> "$STUB_LOG"; DISPATCHED=""
rm -f "$RECHECK_STAMP_FILE"
is_recheck_running() { return 0; }
export -f is_recheck_running
main_red_recheck_check
assert_eq "M6: running recheck → no dispatch" \
  "0" "$(grep -c 'dispatch' "$STUB_LOG" || true)"

# M7: kill switch off → no dispatch even when due
> "$STUB_LOG"; DISPATCHED=""
is_recheck_running() { return 1; }
export -f is_recheck_running
MAIN_RED_RECHECK_ENABLED=false
main_red_recheck_check
assert_eq "M7: kill switch → no dispatch" \
  "0" "$(grep -c 'dispatch' "$STUB_LOG" || true)"
MAIN_RED_RECHECK_ENABLED=true

# Restore stubs
is_recheck_running() { return 1; }
dispatch() { echo "dispatch $*" >> "$STUB_LOG"; return 0; }
export -f is_recheck_running dispatch

# ==========================================
# N: dependencies_met() — off-board fallback
# ==========================================
echo ""
echo "--- N: dependencies_met ---"
> "$STUB_LOG"

# Shared stub variables for this section
_N_BODY=""
_N_DEP200_STATE=""
_N_DEP200_GH_EXIT=0
_N_DEP201_STATE=""

# gh stub: routes by issue number; body call → _N_BODY; state call → per-dep state var
gh() {
  echo "gh $*" >> "$STUB_LOG"
  if echo "$*" | grep -qE "view 100"; then
    printf '%s\n' "$_N_BODY"; return 0
  fi
  if echo "$*" | grep -qE "view 201"; then
    printf '%s\n' "$_N_DEP201_STATE"; return 0
  fi
  if echo "$*" | grep -qE "view 200"; then
    printf '%s\n' "$_N_DEP200_STATE"; return $_N_DEP200_GH_EXIT
  fi
  return 0
}
export -f gh

_BOARD_EMPTY='{"items":[]}'
_BOARD_200_DONE='{"items":[{"content":{"number":200},"status":"Done"}]}'
_BOARD_200_WIP='{"items":[{"content":{"number":200},"status":"In Progress"}]}'
_BOARD_200_DONE_201_ABSENT='{"items":[{"content":{"number":200},"status":"Done"}]}'

# N1: no deps in body → returns 0
_N_BODY="No dependencies here"
> "$STUB_LOG"
dependencies_met "100" "$_BOARD_EMPTY" && _N_RET=0 || _N_RET=1
assert_eq "N1: no deps → returns 0" "0" "$_N_RET"

# N2: dep Done on board → returns 0, no dep_gate log
_N_BODY="Depends on: #200"
> "$STUB_LOG"
dependencies_met "100" "$_BOARD_200_DONE" && _N_RET=0 || _N_RET=1
assert_eq "N2: dep Done on board → returns 0" "0" "$_N_RET"
assert_eq "N2: Done dep is silent (no dep_gate log)" \
  "0" "$(grep -c 'dep_gate' "$STUB_LOG" || true)"

# N3: dep non-Done on board → returns 1, logs dep_gate
_N_BODY="Depends on: #200"
> "$STUB_LOG"
_N_OUTPUT=$(dependencies_met "100" "$_BOARD_200_WIP" 2>&1) && _N_RET=0 || _N_RET=1
assert_eq "N3: non-Done dep → returns 1" "1" "$_N_RET"
assert_eq "N3: non-Done dep → dep_gate logged" \
  "1" "$(echo "$_N_OUTPUT" | grep -c 'dep_gate' || true)"

# N4: dep off-board, gh state=CLOSED → returns 0, logs resolved=closed_off_board
_N_BODY="Depends on: #200"
_N_DEP200_STATE="CLOSED"
_N_DEP200_GH_EXIT=0
> "$STUB_LOG"
_N_OUTPUT=$(dependencies_met "100" "$_BOARD_EMPTY" 2>&1) && _N_RET=0 || _N_RET=1
assert_eq "N4: off-board CLOSED dep → returns 0" "0" "$_N_RET"
assert_eq "N4: off-board CLOSED → logs resolved=closed_off_board" \
  "1" "$(echo "$_N_OUTPUT" | grep -c 'resolved=closed_off_board' || true)"

# N5: dep off-board, gh state=OPEN → returns 1, logs dep_status=off_board
_N_BODY="Depends on: #200"
_N_DEP200_STATE="OPEN"
_N_DEP200_GH_EXIT=0
> "$STUB_LOG"
_N_OUTPUT=$(dependencies_met "100" "$_BOARD_EMPTY" 2>&1) && _N_RET=0 || _N_RET=1
assert_eq "N5: off-board OPEN dep → returns 1" "1" "$_N_RET"
assert_eq "N5: off-board OPEN → logs dep_status=off_board" \
  "1" "$(echo "$_N_OUTPUT" | grep -c 'dep_status=off_board' || true)"

# N6: dep off-board, gh state call fails/empty → returns 1 (safe direction)
_N_BODY="Depends on: #200"
_N_DEP200_STATE=""
_N_DEP200_GH_EXIT=1
> "$STUB_LOG"
dependencies_met "100" "$_BOARD_EMPTY" && _N_RET=0 || _N_RET=1
assert_eq "N6: off-board gh-failure dep → returns 1 (safe)" "1" "$_N_RET"

# N7: two deps — first Done on board, second off-board OPEN → returns 1
_N_BODY="$(printf 'Depends on: #200\nDepends on: #201')"
_N_DEP200_STATE=""
_N_DEP200_GH_EXIT=0
_N_DEP201_STATE="OPEN"
> "$STUB_LOG"
dependencies_met "100" "$_BOARD_200_DONE_201_ABSENT" && _N_RET=0 || _N_RET=1
assert_eq "N7: two deps, second off-board OPEN → returns 1" "1" "$_N_RET"

# N8: two deps — first Done on board, second off-board CLOSED → returns 0
_N_BODY="$(printf 'Depends on: #200\nDepends on: #201')"
_N_DEP200_STATE=""
_N_DEP200_GH_EXIT=0
_N_DEP201_STATE="CLOSED"
> "$STUB_LOG"
dependencies_met "100" "$_BOARD_200_DONE_201_ABSENT" && _N_RET=0 || _N_RET=1
assert_eq "N8: two deps, second off-board CLOSED → returns 0" "0" "$_N_RET"

# N9: body fetch fails → returns 0 (pre-existing behaviour)
# Override gh so body call for issue 100 returns non-zero
gh() {
  echo "gh $*" >> "$STUB_LOG"
  if echo "$*" | grep -qE "view 100"; then
    return 1
  fi
  return 0
}
export -f gh
> "$STUB_LOG"
dependencies_met "100" "$_BOARD_EMPTY" && _N_RET=0 || _N_RET=1
assert_eq "N9: body fetch fails → returns 0" "0" "$_N_RET"

# Restore global gh stub
gh() { echo "gh $*" >> "$STUB_LOG"; return 0; }
export -f gh

# ==========================================
# Cleanup
# ==========================================
rm -f "$STATE_FILE" "$STUB_LOG"
rm -rf "$SCHEDULER_STATE_DIR"
echo ""
echo "Results: ${PASSED} passed, ${FAILED} failed"
[ "$FAILED" -eq 0 ]
