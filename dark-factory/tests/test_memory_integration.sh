#!/usr/bin/env bash
# Smoke test: memory_retrieve.py integrates correctly with all 4 Dark Factory phases.
# Asserts exit 0 for each phase, validates phase→source filter, and confirms
# the --issue flag passes through cleanly.
# Run manually: bash dark-factory/tests/test_memory_integration.sh
set -euo pipefail

REPO_ROOT=$(git rev-parse --show-toplevel)
SCRIPT="${REPO_ROOT}/dark-factory/scripts/memory_retrieve.py"
MEMORY_DIR="${REPO_ROOT}/.archon/memory"

PASS=0; FAIL=0

assert() {
  local desc="$1" result="$2"
  if [ "$result" = "0" ]; then
    echo "PASS: $desc"; PASS=$((PASS+1))
  else
    echo "FAIL: $desc"; FAIL=$((FAIL+1))
  fi
}

# ── Phase exit-0 tests ────────────────────────────────────────────────────

for phase in refine plan implement validate; do
  python3 "$SCRIPT" --phase "$phase" --memory-dir "$MEMORY_DIR" > /dev/null 2>&1; rc=$?
  assert "phase=$phase exits 0 (no --files)" "$([ "$rc" -eq 0 ] && echo 0 || echo 1)"
done

# ── --issue flag passes cleanly ──────────────────────────────────────────

for phase in refine plan implement validate; do
  python3 "$SCRIPT" --phase "$phase" --issue 652 --memory-dir "$MEMORY_DIR" > /dev/null 2>&1; rc=$?
  assert "phase=$phase with --issue 652 exits 0" "$([ "$rc" -eq 0 ] && echo 0 || echo 1)"
done

# ── validate phase returns only conformance-sourced entries ───────────────
#
# Build a temp memory dir with one conformance entry and one implement entry.
# --phase validate must surface the conformance one and suppress the implement one.
# Use dark-factory-ops.md (an area file) not codebase-patterns.md (a global file
# exempt from the source filter).

TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

# Minimal codebase-patterns.md so the script has a global file to scan
cat > "$TMP/codebase-patterns.md" << 'MEMEOF'
# Codebase Patterns
MEMEOF

cat > "$TMP/dark-factory-ops.md" << 'MEMEOF'
# Dark Factory Ops
- [PATTERN] conformance lesson <!-- issue:#1 date:2026-01-01 expires:2099-01-01 source:conformance -->
- [PATTERN] implement lesson <!-- issue:#2 date:2026-01-01 expires:2099-01-01 source:implement -->
MEMEOF

VALIDATE_OUT=$(python3 "$SCRIPT" --phase validate --memory-dir "$TMP" 2>/dev/null || true)

assert "validate returns conformance-sourced entry" \
  "$(echo "$VALIDATE_OUT" | grep -q 'conformance lesson' && echo 0 || echo 1)"

assert "validate suppresses implement-sourced entry" \
  "$(echo "$VALIDATE_OUT" | grep -q 'implement lesson' && echo 1 || echo 0)"

# ── implement phase returns only implement-sourced entries ────────────────

IMPL_OUT=$(python3 "$SCRIPT" --phase implement --memory-dir "$TMP" 2>/dev/null || true)

assert "implement returns implement-sourced entry" \
  "$(echo "$IMPL_OUT" | grep -q 'implement lesson' && echo 0 || echo 1)"

assert "implement suppresses conformance-sourced entry" \
  "$(echo "$IMPL_OUT" | grep -q 'conformance lesson' && echo 1 || echo 0)"

# ── --files path-filter passes cleanly ───────────────────────────────────

rc=0
python3 "$SCRIPT" \
  --phase implement \
  --files ".archon/commands/dark-factory-implement.md
dark-factory/scripts/memory_retrieve.py" \
  --memory-dir "$MEMORY_DIR" > /dev/null 2>&1 && rc=0 || rc=$?
assert "phase=implement with --files exits 0" "$([ "$rc" -eq 0 ] && echo 0 || echo 1)"

# ── global files (codebase-patterns.md, architecture.md) exempt from source filter ──

cat > "$TMP/architecture.md" << 'MEMEOF'
# Architecture
- [PATTERN] architecture lesson no source tag <!-- issue:#3 date:2026-01-01 expires:2099-01-01 -->
MEMEOF

ARCH_OUT=$(python3 "$SCRIPT" --phase validate --memory-dir "$TMP" 2>/dev/null || true)

assert "global architecture.md entries pass validate source filter" \
  "$(echo "$ARCH_OUT" | grep -q 'architecture lesson' && echo 0 || echo 1)"

echo ""
echo "Results: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
