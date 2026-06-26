#!/usr/bin/env bash
# Test: run_post_mortem() writes failure telemetry to ARTIFACTS_DIR,
# with zero git operations — no worktree, no push, no commit.
# Issue #521
# Run: bash dark-factory/tests/test_431_telemetry_isolation.sh
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# ── Stubs ────────────────────────────────────────────────────────────────────
export GH_TOKEN="stub-token"
export CLAUDE_CODE_OAUTH_TOKEN="stub-token"

GIT_LOG=$(mktemp /tmp/521-git-XXXXXX.log)

git() {
  echo "git $*" >> "$GIT_LOG"
  return 0
}
export -f git

gh() { echo "stub-title"; return 0; }
export -f gh

docker() { return 0; }
export -f docker

claude() { echo "Stub post-mortem text for test."; return 0; }
export -f claude

# ── Source entrypoint (guard prevents clone + main execution) ─────────────
ENTRYPOINT_SOURCE_ONLY=1 source "$SCRIPT_DIR/../entrypoint.sh"

# Reset strict error handling from entrypoint — test context manages its own flow
trap - ERR
set +e
set +u
set +o pipefail

# Reset git log: sourcing entrypoint runs top-level git config calls; we only
# want to count git operations from run_post_mortem itself.
> "$GIT_LOG"

# ── Test fixture ──────────────────────────────────────────────────────────
CLONE_DIR=$(mktemp -d /tmp/521-clone-XXXXXX)

# Set ARTIFACTS_DIR to a temp directory (simulates the global per-run dir)
ARTIFACTS_DIR=$(mktemp -d /tmp/521-artifacts-XXXXXX)
export ARTIFACTS_DIR

JSONL_IN_ARTIFACTS="${ARTIFACTS_DIR}/factory-failures.jsonl"

ISSUE_NUM=521
INTENT=fix

# ── Run ───────────────────────────────────────────────────────────────────
run_post_mortem 1 ""

# ── Assertions ────────────────────────────────────────────────────────────
PASSED=0; FAILED=0
assert_eq() {
  local desc="$1" expected="$2" actual="$3"
  if [ "$expected" = "$actual" ]; then
    echo "  PASS: $desc"; PASSED=$((PASSED + 1))
  else
    echo "  FAIL: $desc — expected='$expected' got='$actual'" >&2
    FAILED=$((FAILED + 1))
  fi
}
assert_true() {
  local desc="$1" condition="$2"
  if eval "$condition"; then
    echo "  PASS: $desc"; PASSED=$((PASSED + 1))
  else
    echo "  FAIL: $desc — condition false: $condition" >&2
    FAILED=$((FAILED + 1))
  fi
}

echo "=== #521: Telemetry isolation — ARTIFACTS_DIR write, zero git operations ==="
echo ""

GIT_CALL_COUNT=$(wc -l < "$GIT_LOG" 2>/dev/null || echo "0")
assert_eq "no git operations called" "0" "$GIT_CALL_COUNT"

assert_true "factory-failures.jsonl exists in ARTIFACTS_DIR" "[ -f '$JSONL_IN_ARTIFACTS' ]"

LINE_COUNT=$(wc -l < "$JSONL_IN_ARTIFACTS" 2>/dev/null || echo "0")
assert_eq "exactly one JSONL line written" "1" "$LINE_COUNT"

# Use stdin redirection so Python does not need to resolve the Unix tmp path
# (avoids Git Bash /tmp path incompatibility with Windows Python).
VALID_JSON=$(python3 -c "import json,sys; json.loads(sys.stdin.read())" < "$JSONL_IN_ARTIFACTS" 2>/dev/null && echo "ok" || echo "invalid")
assert_eq "JSONL line is valid JSON" "ok" "$VALID_JSON"

ISSUE_FIELD=$(python3 -c "import json,sys; d=json.loads(sys.stdin.read()); print(d.get('issue','missing'))" < "$JSONL_IN_ARTIFACTS" 2>/dev/null || echo "missing")
assert_eq "issue field matches ISSUE_NUM" "521" "$ISSUE_FIELD"

# ── Cleanup ───────────────────────────────────────────────────────────────
rm -f "$GIT_LOG"
rm -rf "$CLONE_DIR" "$ARTIFACTS_DIR"

echo ""
echo "Results: ${PASSED} passed, ${FAILED} failed"
[ "$FAILED" -eq 0 ]
