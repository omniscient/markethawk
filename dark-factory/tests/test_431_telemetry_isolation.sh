#!/usr/bin/env bash
# Test: run_post_mortem() writes failure telemetry via a git worktree on main,
# never touching the feature-branch CLONE_DIR.
# Issue #431
# Run: bash dark-factory/tests/test_431_telemetry_isolation.sh
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# ── Stubs ────────────────────────────────────────────────────────────────────
export GH_TOKEN="stub-token"
export CLAUDE_CODE_OAUTH_TOKEN="stub-token"

GIT_LOG=$(mktemp /tmp/431-git-XXXXXX.log)

git() {
  echo "git $*" >> "$GIT_LOG"
  local prev=""
  for arg in "$@"; do
    if [ "$prev" = "--detach" ]; then
      mkdir -p "${arg}/dark-factory/evals"
      echo '{"issue":1,"title":"prior","phase":"fix","exit_code":1,"postmortem":"prior","promoted_at":"2026-01-01T00:00:00Z"}' \
        > "${arg}/dark-factory/evals/factory-failures.jsonl"
      break
    fi
    prev="$arg"
  done
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

# Reset error handling set by entrypoint — test context manages its own flow
trap - ERR
set +e
set +o pipefail

# ── Test fixture ──────────────────────────────────────────────────────────
CLONE_DIR=$(mktemp -d /tmp/431-clone-XXXXXX)
JSONL_IN_CLONE="${CLONE_DIR}/dark-factory/evals/factory-failures.jsonl"
mkdir -p "$(dirname "$JSONL_IN_CLONE")"
echo '{"issue":1,"title":"prior","phase":"fix","exit_code":1,"postmortem":"prior","promoted_at":"2026-01-01T00:00:00Z"}' \
  > "$JSONL_IN_CLONE"

INITIAL_LINES=$(wc -l < "$JSONL_IN_CLONE")
INITIAL_MD5=$(md5sum "$JSONL_IN_CLONE" | awk '{print $1}')

ISSUE_NUM=431
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

echo "=== #431: Telemetry isolation — worktree on main, never touches CLONE_DIR ==="
echo ""

FINAL_MD5=$(md5sum "$JSONL_IN_CLONE" | awk '{print $1}')
assert_eq "CLONE_DIR jsonl not modified (md5)" "$INITIAL_MD5" "$FINAL_MD5"

FINAL_LINES=$(wc -l < "$JSONL_IN_CLONE")
assert_eq "CLONE_DIR jsonl line count unchanged" "$INITIAL_LINES" "$FINAL_LINES"

PUSH_TO_MAIN=$(grep 'push origin HEAD:main' "$GIT_LOG" 2>/dev/null | wc -l)
assert_eq "push targets HEAD:main exactly once" "1" "$PUSH_TO_MAIN"

PUSH_TO_BRANCH=$(grep 'push origin' "$GIT_LOG" 2>/dev/null | grep -v 'HEAD:main' | wc -l)
assert_eq "no direct push to feature branch" "0" "$PUSH_TO_BRANCH"

WORKTREE_ADD=$(grep 'worktree add' "$GIT_LOG" 2>/dev/null | wc -l)
assert_eq "worktree add called" "1" "$WORKTREE_ADD"

WORKTREE_REMOVE=$(grep 'worktree remove' "$GIT_LOG" 2>/dev/null | wc -l)
assert_eq "worktree remove called" "1" "$WORKTREE_REMOVE"

FETCH_MAIN=$(grep 'fetch origin main' "$GIT_LOG" 2>/dev/null | wc -l)
assert_eq "git fetch origin main called" "1" "$FETCH_MAIN"

# ── Cleanup ───────────────────────────────────────────────────────────────
rm -f "$GIT_LOG"
rm -rf "$CLONE_DIR"

echo ""
echo "Results: ${PASSED} passed, ${FAILED} failed"
[ "$FAILED" -eq 0 ]
