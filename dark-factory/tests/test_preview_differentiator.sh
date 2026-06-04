#!/usr/bin/env bash
# Regression tests for the preview-environment differentiator (issue #178).
# Run: bash dark-factory/tests/test_preview_differentiator.sh
set -uo pipefail

PASSED=0; FAILED=0
ARTIFACTS_DIR=$(mktemp -d /tmp/test-differentiator-XXXXXX)
trap 'rm -rf "$ARTIFACTS_DIR"' EXIT

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
  if echo "$haystack" | grep -q "$needle"; then
    echo "  PASS: $desc"; PASSED=$((PASSED+1))
  else
    echo "  FAIL: $desc — '$needle' not found in output" >&2; FAILED=$((FAILED+1))
  fi
}

assert_not_contains() {
  local desc="$1" needle="$2" haystack="$3"
  if ! echo "$haystack" | grep -q "$needle"; then
    echo "  PASS: $desc"; PASSED=$((PASSED+1))
  else
    echo "  FAIL: $desc — '$needle' found but should be absent" >&2; FAILED=$((FAILED+1))
  fi
}

# ============================================================
# A: preview-up guard logic
# ============================================================
echo "--- A: preview-up guard logic ---"

run_guard() {
  local needs_preview="$1" skip_reason="${2:-test reason}"
  local artifacts="$ARTIFACTS_DIR/guard_test_$$_${needs_preview}"
  mkdir -p "$artifacts"

  DOCKER_CALLED=0
  docker() { DOCKER_CALLED=1; echo "docker $*"; }

  NEEDS_PREVIEW="$needs_preview"
  SKIP_REASON="$skip_reason"

  if [ "$NEEDS_PREVIEW" = "false" ]; then
    ISSUE="99"
    mkdir -p "$artifacts"
    printf 'export PREVIEW_SKIPPED=true\nexport PREVIEW_SKIP_REASON="%s"\nexport PREVIEW_FRONTEND=""\nexport PREVIEW_BACKEND=""\nexport PREVIEW_NET=""\n' "${SKIP_REASON}" > "$artifacts/preview_env.sh"
    echo "PREVIEW_SKIPPED=true"
    echo "PREVIEW_SKIP_REASON=${SKIP_REASON}"
    GUARD_EXIT=0
  else
    GUARD_EXIT=1
  fi

  echo "DOCKER_CALLED=$DOCKER_CALLED"
  echo "GUARD_EXIT=$GUARD_EXIT"
  echo "ENV_FILE=$artifacts/preview_env.sh"
}

# A1: explicit false → skip
OUT=$(run_guard "false" "all files are markdown")
ENV_FILE=$(echo "$OUT" | grep '^ENV_FILE=' | cut -d= -f2-)
assert_contains "A1: PREVIEW_SKIPPED=true written to env file"    "PREVIEW_SKIPPED=true"    "$(cat "$ENV_FILE" 2>/dev/null)"
assert_not_contains "A1: docker not called"                       "DOCKER_CALLED=1"          "$OUT"
assert_contains     "A1: stdout emits PREVIEW_SKIPPED=true"       "PREVIEW_SKIPPED=true"     "$OUT"

# A2: explicit true → fall through to build
OUT2=$(run_guard "true" "touches backend/app")
assert_eq "A2: fell through to build path" "1" "$(echo "$OUT2" | grep -c 'GUARD_EXIT=1')"

# A3: garbled value → fall through (fail-safe)
OUT3=$(run_guard "garbled_value" "classifier error")
assert_eq "A3: garbled falls through" "1" "$(echo "$OUT3" | grep -c 'GUARD_EXIT=1')"

# A4: empty string → fall through
OUT4=$(run_guard "" "empty")
assert_eq "A4: empty string falls through" "1" "$(echo "$OUT4" | grep -c 'GUARD_EXIT=1')"

# ============================================================
# B: validate skip-path — sourcing preview_env.sh
# ============================================================
echo ""
echo "--- B: validate skip-path assertions ---"

SKIP_ARTIFACTS="$ARTIFACTS_DIR/validate_skip"
mkdir -p "$SKIP_ARTIFACTS"
printf 'export PREVIEW_SKIPPED=true\nexport PREVIEW_SKIP_REASON="docs-only change"\nexport PREVIEW_FRONTEND=""\nexport PREVIEW_BACKEND=""\nexport PREVIEW_NET=""\n' > "$SKIP_ARTIFACTS/preview_env.sh"

source "$SKIP_ARTIFACTS/preview_env.sh"
assert_eq "B1: PREVIEW_SKIPPED sourced correctly" "true"  "$PREVIEW_SKIPPED"
assert_eq "B2: PREVIEW_BACKEND empty when skipped" ""     "$PREVIEW_BACKEND"
assert_eq "B3: PREVIEW_NET empty when skipped"    ""      "$PREVIEW_NET"

SKIP_NOTE=$(printf "Endpoint tests skipped — no preview environment (%s)." "$PREVIEW_SKIP_REASON")
assert_contains "B4: skip note contains reason" "docs-only change" "$SKIP_NOTE"

# ============================================================
# C: PR body and report — preview section conditional
# ============================================================
echo ""
echo "--- C: PR body / report preview section ---"

PREVIEW_SKIP_REASON="all files are markdown docs"
PREVIEW_BODY_SKIP=$(printf "_No preview environment — this change does not affect the running app (%s)._" "${PREVIEW_SKIP_REASON}")
assert_contains     "C1: skip body contains reason" "markdown docs" "$PREVIEW_BODY_SKIP"
assert_not_contains "C1: skip body has no URL"      "Frontend:"     "$PREVIEW_BODY_SKIP"

PREVIEW_FRONTEND="http://localhost:10333"
PREVIEW_BACKEND="http://mh-preview-1-backend-1:8000"
PREVIEW_BODY_FULL="Frontend: ${PREVIEW_FRONTEND}
Backend API: ${PREVIEW_BACKEND}/docs"
assert_contains "C2: full body has frontend URL" "localhost:10333"        "$PREVIEW_BODY_FULL"
assert_contains "C2: full body has backend URL"  "mh-preview-1-backend-1" "$PREVIEW_BODY_FULL"

# ============================================================
# D: config.yaml preview block
# ============================================================
echo ""
echo "--- D: config.yaml preview block ---"
CONFIG=".claude/skills/refinement/config.yaml"
if [ -f "$CONFIG" ]; then
  assert_contains "D1: preview block present" "preview:" "$(cat "$CONFIG")"
  assert_contains "D2: enabled key present"   "enabled:" "$(cat "$CONFIG")"
  assert_contains "D3: model key present"     "model:"   "$(cat "$CONFIG")"
else
  echo "  SKIP: config file not found at $CONFIG (run from repo root)"
fi

# ============================================================
# Summary
# ============================================================
echo ""
echo "Results: $PASSED passed, $FAILED failed"
[ "$FAILED" -eq 0 ] && exit 0 || exit 1
