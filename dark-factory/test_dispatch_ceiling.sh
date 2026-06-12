#!/usr/bin/env bash
# Test harness for dispatch ceiling helpers (issue #339)
set -euo pipefail
PASS=0; FAIL=0

assert_eq() {
  local label="$1" got="$2" expected="$3"
  if [ "$got" = "$expected" ]; then
    echo "PASS: $label"; PASS=$((PASS+1))
  else
    echo "FAIL: $label — got='$got' expected='$expected'"; FAIL=$((FAIL+1))
  fi
}
assert_rc() {
  local label="$1" expected_rc="$2"; shift 2
  local rc=0; "$@" || rc=$?
  if [ "$rc" = "$expected_rc" ]; then
    echo "PASS: $label"; PASS=$((PASS+1))
  else
    echo "FAIL: $label — got rc=$rc expected rc=$expected_rc"; FAIL=$((FAIL+1))
  fi
}

# --- Env defaults required by helpers ---
DISPATCH_CEILING_ENABLED="true"
ABOVE_CEILING_LABEL="above-ceiling"
ABOVE_CEILING_KEYWORDS="migration|migrate|performance|perf|architectur|refactor"

# --- Helpers under test (sourced inline for isolation) ---
get_size_label() {
  echo "$1" | jq -r '.labels[]?' 2>/dev/null | grep -oi 'size: [SML]' | awk '{print $2}' | head -1
}
is_above_ceiling() {
  local item="$1" title size
  title=$(echo "$item" | jq -r '.content.title // ""' 2>/dev/null)
  size=$(get_size_label "$item")
  case "$size" in
    L) return 0 ;;
    M) echo "$title" | grep -qiE "${ABOVE_CEILING_KEYWORDS}" && return 0 || return 1 ;;
    *) return 1 ;;
  esac
}
has_above_ceiling_label() {
  echo "$1" | jq -r '.labels[]?' 2>/dev/null | grep -qi "^${ABOVE_CEILING_LABEL}$"
}
is_below_ceiling() {
  local size; size=$(get_size_label "$1")
  case "$size" in S|"") return 0 ;; *) return 1 ;; esac
}

# --- Mock items ---
ITEM_S='{"labels":["size: S","priority: must-have"],"content":{"title":"Fix login bug"}}'
ITEM_M='{"labels":["size: M","priority: must-have"],"content":{"title":"Add new chart"}}'
ITEM_M_MIGRATION='{"labels":["size: M"],"content":{"title":"Run database migration for users table"}}'
ITEM_M_PERF='{"labels":["size: M"],"content":{"title":"Improve performance of scanner query"}}'
ITEM_M_ARCH='{"labels":["size: M"],"content":{"title":"Architectural refactor of provider layer"}}'
ITEM_L='{"labels":["size: L"],"content":{"title":"Big architectural feature"}}'
ITEM_NO_SIZE='{"labels":["priority: must-have"],"content":{"title":"No size label here"}}'
ITEM_ABOVE_LABELED='{"labels":["above-ceiling","size: L"],"content":{"title":"Perf work"}}'

# --- get_size_label ---
assert_eq "get_size_label: S"    "$(get_size_label "$ITEM_S")" "S"
assert_eq "get_size_label: M"    "$(get_size_label "$ITEM_M")" "M"
assert_eq "get_size_label: L"    "$(get_size_label "$ITEM_L")" "L"
assert_eq "get_size_label: none" "$(get_size_label "$ITEM_NO_SIZE")" ""

# --- is_above_ceiling ---
assert_rc "is_above_ceiling: S → false"              1 is_above_ceiling "$ITEM_S"
assert_rc "is_above_ceiling: M no keyword → false"   1 is_above_ceiling "$ITEM_M"
assert_rc "is_above_ceiling: M+migration → true"     0 is_above_ceiling "$ITEM_M_MIGRATION"
assert_rc "is_above_ceiling: M+perf → true"          0 is_above_ceiling "$ITEM_M_PERF"
assert_rc "is_above_ceiling: M+architectur → true"   0 is_above_ceiling "$ITEM_M_ARCH"
assert_rc "is_above_ceiling: L → true"               0 is_above_ceiling "$ITEM_L"
assert_rc "is_above_ceiling: no size → false"        1 is_above_ceiling "$ITEM_NO_SIZE"

# --- has_above_ceiling_label ---
assert_rc "has_above_ceiling_label: absent → false"  1 has_above_ceiling_label "$ITEM_M"
assert_rc "has_above_ceiling_label: present → true"  0 has_above_ceiling_label "$ITEM_ABOVE_LABELED"

# --- is_below_ceiling ---
assert_rc "is_below_ceiling: S → true"               0 is_below_ceiling "$ITEM_S"
assert_rc "is_below_ceiling: no size → true"         0 is_below_ceiling "$ITEM_NO_SIZE"
assert_rc "is_below_ceiling: M → false"              1 is_below_ceiling "$ITEM_M"
assert_rc "is_below_ceiling: L → false"              1 is_below_ceiling "$ITEM_L"

# --- P2 gate simulation ---
p2_gate_outcome() {
  local item="$1"
  if [ "${DISPATCH_CEILING_ENABLED:-true}" = "true" ] && is_above_ceiling "$item"; then
    has_above_ceiling_label "$item" && echo "already_labeled_skip" || echo "block_and_label"
  else
    echo "dispatch"
  fi
}
assert_eq "P2 gate: S → dispatch"            "$(p2_gate_outcome "$ITEM_S")"            "dispatch"
assert_eq "P2 gate: M no kw → dispatch"      "$(p2_gate_outcome "$ITEM_M")"            "dispatch"
assert_eq "P2 gate: M+migration → block"     "$(p2_gate_outcome "$ITEM_M_MIGRATION")"  "block_and_label"
assert_eq "P2 gate: L → block"               "$(p2_gate_outcome "$ITEM_L")"            "block_and_label"
assert_eq "P2 gate: L already labeled → skip" "$(p2_gate_outcome "$ITEM_ABOVE_LABELED")" "already_labeled_skip"

# --- P3 guard simulation ---
p3_guard_outcome() {
  has_above_ceiling_label "$1" && echo "skip" || echo "retry"
}
assert_eq "P3 guard: normal blocked → retry"         "$(p3_guard_outcome "$ITEM_M")"           "retry"
assert_eq "P3 guard: above-ceiling labeled → skip"   "$(p3_guard_outcome "$ITEM_ABOVE_LABELED")" "skip"

# --- plan_advance_check suppression ---
plan_advance_ceiling_outcome() {
  local item="$1"
  if [ "${DISPATCH_CEILING_ENABLED:-true}" = "true" ] && ! is_below_ceiling "$item"; then
    echo "suppressed"
  else
    echo "allowed"
  fi
}
assert_eq "plan_advance: S → allowed"       "$(plan_advance_ceiling_outcome "$ITEM_S")"          "allowed"
assert_eq "plan_advance: no size → allowed" "$(plan_advance_ceiling_outcome "$ITEM_NO_SIZE")"    "allowed"
assert_eq "plan_advance: M → suppressed"    "$(plan_advance_ceiling_outcome "$ITEM_M")"          "suppressed"
assert_eq "plan_advance: M+kw → suppressed" "$(plan_advance_ceiling_outcome "$ITEM_M_MIGRATION")" "suppressed"
assert_eq "plan_advance: L → suppressed"    "$(plan_advance_ceiling_outcome "$ITEM_L")"          "suppressed"

echo ""
echo "Results: $PASS passed, $FAIL failed"
[ "$FAIL" = "0" ] || exit 1
