#!/usr/bin/env bash
# Regression tests for the preview environment differentiator.
# Tests the preview-up guard logic and validate skip path.
# Run: bash dark-factory/tests/test_preview_differentiator.sh
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ARTIFACTS_DIR=$(mktemp -d /tmp/preview-diff-test-XXXXXX)
trap 'rm -rf "$ARTIFACTS_DIR"' EXIT

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

assert_contains() {
  local desc="$1" needle="$2" haystack="$3"
  if echo "$haystack" | grep -qF "$needle"; then
    echo "  PASS: $desc"; PASSED=$((PASSED+1))
  else
    echo "  FAIL: $desc — expected to find '$needle' in output" >&2; FAILED=$((FAILED+1))
  fi
}

assert_not_contains() {
  local desc="$1" needle="$2" haystack="$3"
  if echo "$haystack" | grep -qF "$needle"; then
    echo "  FAIL: $desc — did not expect '$needle' in output" >&2; FAILED=$((FAILED+1))
  else
    echo "  PASS: $desc"; PASSED=$((PASSED+1))
  fi
}

# =====================================================================
# A: preview-up guard — the core gated executor logic
# Simulate the guard block from preview-up with various NEEDS_PREVIEW values
# =====================================================================
echo "--- A: preview-up guard ---"

run_guard() {
  local needs_preview="$1" skip_reason="${2:-test reason}"
  local artifacts="$ARTIFACTS_DIR/guard_$1"
  mkdir -p "$artifacts"
  # Simulate the guard block
  OUTPUT=$(
    NEEDS_PREVIEW="$needs_preview"
    SKIP_REASON="$skip_reason"
    ISSUE="99"
    ARTIFACTS_DIR="$artifacts"
    if [ "$NEEDS_PREVIEW" = "false" ]; then
      echo "Preview differentiator: skipping preview for issue #${ISSUE}"
      echo "Reason: ${SKIP_REASON}"
      {
        echo "export PREVIEW_SKIPPED=true"
        echo "export PREVIEW_SKIP_REASON=\"${SKIP_REASON}\""
        echo "export PREVIEW_FRONTEND=\"\""
        echo "export PREVIEW_BACKEND=\"\""
        echo "export PREVIEW_NET=\"\""
      } > "$ARTIFACTS_DIR/preview_env.sh"
      echo "PREVIEW_SKIPPED=true"
      echo "PREVIEW_SKIP_REASON=${SKIP_REASON}"
      exit 0
    fi
    echo "BUILDING_PREVIEW"
  )
  RC=$?
  echo "$OUTPUT"
}

# needs_preview=false → should skip
OUT=$(run_guard "false" "docs-only change")
assert_contains "false → outputs PREVIEW_SKIPPED=true" "PREVIEW_SKIPPED=true" "$OUT"
assert_not_contains "false → does not build preview" "BUILDING_PREVIEW" "$OUT"

# Check preview_env.sh was written correctly for skip case
ENV_FILE="$ARTIFACTS_DIR/guard_false/preview_env.sh"
assert_eq "preview_env.sh exists after skip" "0" "$(test -f "$ENV_FILE" && echo 0 || echo 1)"
if [ -f "$ENV_FILE" ]; then
  SKIPPED_VAL=$(grep 'PREVIEW_SKIPPED' "$ENV_FILE" | head -1 | grep -o 'true\|false')
  assert_eq "preview_env.sh has PREVIEW_SKIPPED=true" "true" "$SKIPPED_VAL"
fi

# needs_preview=true → should build
OUT=$(run_guard "true" "code changed")
assert_contains "true → proceeds to build" "BUILDING_PREVIEW" "$OUT"
assert_not_contains "true → does not skip" "PREVIEW_SKIPPED=true" "$OUT"

# needs_preview=garbled → fail-safe: should build (not skip on uncertainty)
OUT=$(run_guard "garbled_value" "uncertain")
assert_contains "garbled → fail-safe builds" "BUILDING_PREVIEW" "$OUT"
assert_not_contains "garbled → does not skip" "PREVIEW_SKIPPED=true" "$OUT"

# needs_preview='' (empty) → fail-safe: should build
OUT=$(run_guard "" "empty classifier output")
assert_contains "empty → fail-safe builds" "BUILDING_PREVIEW" "$OUT"
assert_not_contains "empty → does not skip" "PREVIEW_SKIPPED=true" "$OUT"

# =====================================================================
# B: validate skip path — when PREVIEW_SKIPPED=true, endpoint tests skipped
# =====================================================================
echo ""
echo "--- B: validate skip path (preview_env.sh parsing) ---"

# Write a skip-mode preview_env.sh
SKIP_ENV="$ARTIFACTS_DIR/skip_preview_env.sh"
cat > "$SKIP_ENV" <<'EOF'
export PREVIEW_SKIPPED=true
export PREVIEW_SKIP_REASON="docs-only change — no runtime impact"
export PREVIEW_FRONTEND=""
export PREVIEW_BACKEND=""
export PREVIEW_NET=""
EOF

# Simulate the validate branch logic
source "$SKIP_ENV"
assert_eq "PREVIEW_SKIPPED sourced correctly" "true" "$PREVIEW_SKIPPED"
assert_eq "PREVIEW_BACKEND is empty when skipped" "" "$PREVIEW_BACKEND"
assert_eq "PREVIEW_NET is empty when skipped" "" "$PREVIEW_NET"

# Simulate the network disconnect guard
DISCONNECT_RAN=""
if [ "$PREVIEW_SKIPPED" != "true" ]; then
  DISCONNECT_RAN="yes"
fi
assert_eq "network disconnect skipped when PREVIEW_SKIPPED=true" "" "$DISCONNECT_RAN"

# Write a normal (non-skipped) preview_env.sh
NORMAL_ENV="$ARTIFACTS_DIR/normal_preview_env.sh"
cat > "$NORMAL_ENV" <<'EOF'
export PREVIEW_SKIPPED=false
export PREVIEW_FRONTEND="http://localhost:10333"
export PREVIEW_BACKEND="http://mh-preview-99-backend-1:8000"
export PREVIEW_NET="mh-preview-99_preview-network"
EOF

source "$NORMAL_ENV"
assert_eq "PREVIEW_SKIPPED false sourced correctly" "false" "$PREVIEW_SKIPPED"
assert_eq "PREVIEW_BACKEND populated when not skipped" "http://mh-preview-99-backend-1:8000" "$PREVIEW_BACKEND"

DISCONNECT_RAN=""
if [ "$PREVIEW_SKIPPED" != "true" ]; then
  DISCONNECT_RAN="yes"
fi
assert_eq "network disconnect runs when not skipped" "yes" "$DISCONNECT_RAN"

# =====================================================================
# C: push-and-pr preview section rendering
# =====================================================================
echo ""
echo "--- C: push-and-pr preview section rendering ---"

# Skipped case
PREVIEW_SKIPPED="true"
PREVIEW_SKIP_REASON="docs-only change — no runtime impact"
PREVIEW_FRONTEND=""
PREVIEW_BACKEND=""
if [ "$PREVIEW_SKIPPED" = "true" ]; then
  PREVIEW_SECTION="_No preview environment — this change does not affect the running app (${PREVIEW_SKIP_REASON})._"
else
  PREVIEW_SECTION="- Frontend: ${PREVIEW_FRONTEND}"$'\n'"- Backend API: ${PREVIEW_BACKEND}/docs"
fi
assert_contains "skipped → PR preview section has no-preview note" "No preview environment" "$PREVIEW_SECTION"
assert_not_contains "skipped → PR section has no Frontend URL" "Frontend:" "$PREVIEW_SECTION"

# Not-skipped case
PREVIEW_SKIPPED="false"
PREVIEW_FRONTEND="http://localhost:10333"
PREVIEW_BACKEND="http://mh-preview-99-backend-1:8000"
if [ "$PREVIEW_SKIPPED" = "true" ]; then
  PREVIEW_SECTION="_No preview environment — this change does not affect the running app._"
else
  PREVIEW_SECTION="- Frontend: ${PREVIEW_FRONTEND}"$'\n'"- Backend API: ${PREVIEW_BACKEND}/docs"
fi
assert_contains "not-skipped → PR preview section has Frontend URL" "Frontend:" "$PREVIEW_SECTION"
assert_not_contains "not-skipped → PR section has no no-preview note" "No preview environment" "$PREVIEW_SECTION"

# =====================================================================
# D: report preview section rendering
# =====================================================================
echo ""
echo "--- D: report preview section rendering ---"

# Skipped case
PREVIEW_SKIPPED="true"
PREVIEW_SKIP_REASON="docs-only — no runtime impact"
if [ "$PREVIEW_SKIPPED" = "true" ]; then
  PREVIEW_SECTION="_No preview environment — this change does not affect the running app (${PREVIEW_SKIP_REASON})._"
else
  PREVIEW_SECTION="| Service | URL |"
fi
assert_contains "report skipped → no-preview note" "No preview environment" "$PREVIEW_SECTION"
assert_not_contains "report skipped → no table" "| Service |" "$PREVIEW_SECTION"

# Not-skipped case
PREVIEW_SKIPPED="false"
PREVIEW_SLOT="03"
PREVIEW_FRONTEND="http://localhost:10333"
PREVIEW_BACKEND="http://mh-preview-99-backend-1:8000"
if [ "$PREVIEW_SKIPPED" = "true" ]; then
  PREVIEW_SECTION="_No preview environment._"
else
  PREVIEW_SECTION="| Service | URL |
|---------|-----|
| Frontend | ${PREVIEW_FRONTEND} |
| Backend API | ${PREVIEW_BACKEND} |"
fi
assert_contains "report not-skipped → table rendered" "| Service |" "$PREVIEW_SECTION"
assert_not_contains "report not-skipped → no no-preview note" "No preview environment" "$PREVIEW_SECTION"

# =====================================================================
# Summary
# =====================================================================
echo ""
echo "============================="
echo "Results: ${PASSED} passed, ${FAILED} failed"
echo "============================="
[ "$FAILED" -eq 0 ] && exit 0 || exit 1
