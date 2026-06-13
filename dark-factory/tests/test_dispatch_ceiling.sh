#!/usr/bin/env bash
# Unit tests for the dispatch ceiling (issue #339): size/type classification helpers,
# Priority 2 ceiling gate, Priority 3 guard, and plan_advance_check suppression.
# Run: bash dark-factory/tests/test_dispatch_ceiling.sh
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SCHED="$SCRIPT_DIR/../scheduler.sh"

# ---- Stubs ----
STUB_LOG=$(mktemp /tmp/sched-ceiling-stubs-XXXXXX.log)
gh()               { echo "gh $*"               >> "$STUB_LOG"; return 0; }
docker()           { echo "docker $*"           >> "$STUB_LOG"; return 0; }
set_board_status() { echo "set_board_status $*" >> "$STUB_LOG"; return 0; }
export -f gh docker set_board_status

# ---- Source scheduler helpers only ----
SCHEDULER_STATE_DIR=$(mktemp -d /tmp/sched-ceiling-statedir-XXXXXX)
export SCHEDULER_STATE_DIR
STATE_FILE=$(mktemp /tmp/sched-ceiling-state-XXXXXX.json)
echo '{}' > "$STATE_FILE"
export STATE_FILE
export GH_TOKEN="${GH_TOKEN:-stub-token}"
export CLAUDE_CODE_OAUTH_TOKEN="${CLAUDE_CODE_OAUTH_TOKEN:-stub-token}"
# Set all config-driven vars explicitly: read_config runs after SCHEDULER_SOURCE_ONLY guard
export POLL_INTERVAL=60 MAX_RETRIES=3 RATE_LIMIT_FLOOR=200 FACTORY_WIP_LIMIT=1
export MAIN_RED_RECHECK_ENABLED=true MAIN_RED_RECHECK_MINUTES=20 REFINE_WIP_LIMIT=2
export DIRECT_TO_PR_LABEL=direct-to-pr SPEC_GRACE_MINUTES=30 PLAN_GRACE_MINUTES=30
export CONFLICT_RESOLUTION_ENABLED=true DISPATCH_CEILING_ENABLED=true
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
assert_true() {
  local desc="$1"; shift
  if "$@"; then assert_eq "$desc" "0" "0"; else assert_eq "$desc" "0" "1"; fi
}
assert_false() {
  local desc="$1"; shift
  if "$@"; then assert_eq "$desc" "0" "1"; else assert_eq "$desc" "0" "0"; fi
}

# ---- Mock items ----
ITEM_S='{"content":{"number":1,"title":"Fix login bug"},"labels":["size: S","priority: must-have"],"status":"Ready"}'
ITEM_M='{"content":{"number":2,"title":"Add new chart panel"},"labels":["size: M","priority: must-have"],"status":"Ready"}'
ITEM_M_MIGRATION='{"content":{"number":3,"title":"Run database migration for users table"},"labels":["size: M"],"status":"Ready"}'
ITEM_M_PERF='{"content":{"number":4,"title":"Improve performance of scanner query"},"labels":["size: M"],"status":"Ready"}'
ITEM_M_ARCH='{"content":{"number":5,"title":"Architectural refactor of provider layer"},"labels":["size: M"],"status":"Ready"}'
ITEM_L='{"content":{"number":6,"title":"Big new feature"},"labels":["size: L"],"status":"Ready"}'
ITEM_NO_SIZE='{"content":{"number":7,"title":"No size label here"},"labels":["priority: must-have"],"status":"Ready"}'
ITEM_ABOVE_LABELED='{"content":{"number":8,"title":"Perf work"},"labels":["above-ceiling","size: L"],"status":"Blocked"}'

# ==========================================
# N: get_size_label
# ==========================================
echo "--- N: get_size_label ---"
assert_eq "S item → S"            "S" "$(get_size_label "$ITEM_S")"
assert_eq "M item → M"            "M" "$(get_size_label "$ITEM_M")"
assert_eq "L item → L"            "L" "$(get_size_label "$ITEM_L")"
assert_eq "no size label → empty" ""  "$(get_size_label "$ITEM_NO_SIZE")"

# ==========================================
# O: is_above_ceiling
# ==========================================
echo ""
echo "--- O: is_above_ceiling ---"
assert_false "S → below"                       is_above_ceiling "$ITEM_S"
assert_false "M without keyword → not above"   is_above_ceiling "$ITEM_M"
assert_true  "M + migration keyword → above"   is_above_ceiling "$ITEM_M_MIGRATION"
assert_true  "M + performance keyword → above" is_above_ceiling "$ITEM_M_PERF"
assert_true  "M + architectural keyword → above" is_above_ceiling "$ITEM_M_ARCH"
assert_true  "L → always above"                is_above_ceiling "$ITEM_L"
assert_false "no size label → treated as S"    is_above_ceiling "$ITEM_NO_SIZE"

# ==========================================
# P: has_above_ceiling_label / is_below_ceiling
# ==========================================
echo ""
echo "--- P: has_above_ceiling_label / is_below_ceiling ---"
assert_false "label absent → false"  has_above_ceiling_label "$ITEM_M"
assert_true  "label present → true"  has_above_ceiling_label "$ITEM_ABOVE_LABELED"
assert_true  "S → below ceiling"           is_below_ceiling "$ITEM_S"
assert_true  "no size → below ceiling"     is_below_ceiling "$ITEM_NO_SIZE"
assert_false "M → not below ceiling"       is_below_ceiling "$ITEM_M"
assert_false "L → not below ceiling"       is_below_ceiling "$ITEM_L"

# ==========================================
# Q: Priority 2 ceiling gate (mirrors the inserted loop code)
# ==========================================
echo ""
echo "--- Q: Priority 2 ceiling gate ---"

# Mirrors the gate inserted in the Priority 2 loop so the branch logic is exercised
# with the real helpers. Outcomes: dispatch | block_and_label | already_labeled_skip
p2_gate_outcome() {
  local item="$1"
  local ISSUE
  ISSUE=$(get_issue_number "$item")
  if [ "${DISPATCH_CEILING_ENABLED:-true}" = "true" ] && is_above_ceiling "$item"; then
    if ! has_above_ceiling_label "$item"; then
      gh issue edit "$ISSUE" --repo "${OWNER}/markethawk" --add-label "$ABOVE_CEILING_LABEL" 2>/dev/null || true
      set_board_status "$ISSUE" "$STATUS_BLOCKED" || true
      echo "block_and_label"
    else
      echo "already_labeled_skip"
    fi
    return 0
  fi
  echo "dispatch"
}

DISPATCH_CEILING_ENABLED=true
> "$STUB_LOG"
assert_eq "S → dispatch"                    "dispatch"             "$(p2_gate_outcome "$ITEM_S")"
assert_eq "M without keyword → dispatch"    "dispatch"             "$(p2_gate_outcome "$ITEM_M")"
assert_eq "M + keyword → block and label"   "block_and_label"      "$(p2_gate_outcome "$ITEM_M_MIGRATION")"
assert_eq "L → block and label"             "block_and_label"      "$(p2_gate_outcome "$ITEM_L")"
assert_eq "already labeled → silent skip"   "already_labeled_skip" "$(p2_gate_outcome "$ITEM_ABOVE_LABELED")"
assert_eq "block path adds the label" \
  "1" "$(grep -c "issue edit 3.*--add-label above-ceiling" "$STUB_LOG" || echo 0)"
assert_eq "block path moves board to Blocked" \
  "1" "$(grep -c "set_board_status 3 ${STATUS_BLOCKED}" "$STUB_LOG" || echo 0)"

DISPATCH_CEILING_ENABLED=false
assert_eq "kill-switch off: L → dispatch"   "dispatch" "$(p2_gate_outcome "$ITEM_L")"
DISPATCH_CEILING_ENABLED=true

# ==========================================
# R: Priority 3 guard
# ==========================================
echo ""
echo "--- R: Priority 3 guard ---"
assert_false "normal blocked item → retried"        has_above_ceiling_label "$ITEM_M"
assert_true  "above-ceiling blocked item → skipped" has_above_ceiling_label "$ITEM_ABOVE_LABELED"

# ==========================================
# S: plan_advance_check suppression (real function, stubbed collaborators)
# ==========================================
echo ""
echo "--- S: plan_advance_check ceiling suppression ---"
echo '{}' > "$STATE_FILE"
REFINE_RUNNING=0
DISPATCHED=""
export PLAN_GRACE_MINUTES=30

_ITEM_S_PPR='{"content":{"number":70,"title":"Small fix"},"labels":["size: S","direct-to-pr","plan-pending-review"],"status":"Refined"}'
_ITEM_M_PPR='{"content":{"number":71,"title":"Add new chart panel"},"labels":["size: M","direct-to-pr","plan-pending-review"],"status":"Refined"}'
_ITEM_L_PPR='{"content":{"number":72,"title":"Big new feature"},"labels":["size: L","direct-to-pr","plan-pending-review"],"status":"Refined"}'

has_new_comment_after_report() { echo "no"; }
elapsed_minutes_since_marker() { echo "99"; }
dispatch() { echo "dispatch $*" >> "$STUB_LOG"; return 0; }
export -f has_new_comment_after_report elapsed_minutes_since_marker dispatch

# S1: S item past grace → advances to Ready (unchanged behaviour)
> "$STUB_LOG"
plan_advance_check 70 "$_ITEM_S_PPR"
assert_eq "S1: S-size advances to Ready" \
  "1" "$(grep -c "set_board_status 70 ${STATUS_READY}" "$STUB_LOG" || echo 0)"

# S2: M item past grace → suppressed (requires explicit human approval)
> "$STUB_LOG"
plan_advance_check 71 "$_ITEM_M_PPR"
assert_eq "S2: M-size grace-advance suppressed" \
  "0" "$(grep -c 'set_board_status' "$STUB_LOG" || true)"

# S3: L item past grace → suppressed
> "$STUB_LOG"
plan_advance_check 72 "$_ITEM_L_PPR"
assert_eq "S3: L-size grace-advance suppressed" \
  "0" "$(grep -c 'set_board_status' "$STUB_LOG" || true)"

# S4: human feedback on an M item → re-plan still dispatched (feedback path not suppressed)
> "$STUB_LOG"
has_new_comment_after_report() { echo "yes"; }
export -f has_new_comment_after_report
plan_advance_check 71 "$_ITEM_M_PPR"
assert_eq "S4: M-size human feedback still re-plans" \
  "1" "$(grep -c 'dispatch Plan issue #71' "$STUB_LOG" || echo 0)"
has_new_comment_after_report() { echo "no"; }
export -f has_new_comment_after_report

# S5: kill-switch off → M item past grace advances again
> "$STUB_LOG"
DISPATCH_CEILING_ENABLED=false
plan_advance_check 71 "$_ITEM_M_PPR"
assert_eq "S5: kill-switch restores M grace-advance" \
  "1" "$(grep -c "set_board_status 71 ${STATUS_READY}" "$STUB_LOG" || echo 0)"
DISPATCH_CEILING_ENABLED=true

# S6: spec_advance_check is NOT ceiling-gated — M item spec still auto-advances
> "$STUB_LOG"
export SPEC_GRACE_MINUTES=30
_ITEM_M_SPR='{"content":{"number":73,"title":"Add new chart panel"},"labels":["size: M","direct-to-pr","spec-pending-review"],"status":"Backlog"}'
spec_advance_check 73 "$_ITEM_M_SPR"
assert_eq "S6: M-size spec advance unaffected by ceiling" \
  "1" "$(grep -c "set_board_status 73 ${STATUS_REFINED}" "$STUB_LOG" || echo 0)"

# ==========================================
# Cleanup
# ==========================================
rm -f "$STATE_FILE" "$STUB_LOG"
rm -rf "$SCHEDULER_STATE_DIR"
echo ""
echo "Results: ${PASSED} passed, ${FAILED} failed"
[ "$FAILED" -eq 0 ]
