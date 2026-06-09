#!/usr/bin/env bash
# Unit test for load_memory() — path-tag filtering in Phase 1 LOAD.
# Tests POSIX-compatible extraction (sed) and prefix matching (grep -q).
set -euo pipefail

PASS=0; FAIL=0

assert() {
  local desc="$1" result="$2"
  if [ "$result" = "0" ]; then
    echo "PASS: $desc"; PASS=$((PASS+1))
  else
    echo "FAIL: $desc"; FAIL=$((FAIL+1))
  fi
}

AFFECTED="backend/app/routers/scanner.py"

load_memory() {
  local MEMFILE="$1"
  [ -f "$MEMFILE" ] || return
  while IFS= read -r line; do
    if echo "$line" | grep -q 'path:'; then
      PATH_TAG=$(echo "$line" | sed 's/.*path:\([^ >]*\).*/\1/')
      if [ -z "$AFFECTED" ] || echo "$AFFECTED" | grep -q "^${PATH_TAG}"; then
        echo "$line"
      fi
    else
      echo "$line"
    fi
  done < "$MEMFILE"
}

TMPFILE=$(mktemp /tmp/test_load_memory_XXXXXX.md)
cat > "$TMPFILE" << 'MEMEOF'
- [PATTERN] Always included — no path tag
- [AVOID] Backend only <!-- issue:#1 date:2026-01-01 expires:2026-12-01 source:conformance path:backend/app/ -->
- [AVOID] Frontend only <!-- issue:#2 date:2026-01-01 expires:2026-12-01 source:conformance path:frontend/src/ -->
MEMEOF

OUTPUT=$(load_memory "$TMPFILE")
rm -f "$TMPFILE"

assert "entry without path: tag is always included" \
  "$(echo "$OUTPUT" | grep -q 'Always included' && echo 0 || echo 1)"

assert "backend-path entry included when affected file matches prefix" \
  "$(echo "$OUTPUT" | grep -q 'Backend only' && echo 0 || echo 1)"

assert "frontend-path entry excluded when no affected file matches prefix" \
  "$(echo "$OUTPUT" | grep -q 'Frontend only' && echo 1 || echo 0)"

# Test: empty AFFECTED includes all entries (new branch / pre-impl fallback)
AFFECTED=""
TMPFILE2=$(mktemp /tmp/test_load_memory_XXXXXX.md)
echo '- [AVOID] Path-tagged entry <!-- path:frontend/src/ -->' > "$TMPFILE2"
OUTPUT2=$(load_memory "$TMPFILE2")
rm -f "$TMPFILE2"

assert "empty AFFECTED includes all path-tagged entries (new branch)" \
  "$(echo "$OUTPUT2" | grep -q 'Path-tagged entry' && echo 0 || echo 1)"

# Test: PROVISIONAL section entries pass through unfiltered (filtering is for [AVOID]/[PATTERN])
AFFECTED="backend/app/services/scanner.py"
TMPFILE3=$(mktemp /tmp/test_load_memory_XXXXXX.md)
cat > "$TMPFILE3" << 'MEMEOF'
- [PATTERN] Always loaded <!-- no path tag -->
- [PROVISIONAL] Runtime observation <!-- evidence:docker-exec path:backend/app/ -->
MEMEOF
OUTPUT3=$(load_memory "$TMPFILE3")
rm -f "$TMPFILE3"

assert "PROVISIONAL entry with matching path is included" \
  "$(echo "$OUTPUT3" | grep -q 'Runtime observation' && echo 0 || echo 1)"

# Test: deep path prefix still matches
AFFECTED="backend/app/routers/scanner.py
frontend/src/pages/Scanner/index.tsx"
TMPFILE4=$(mktemp /tmp/test_load_memory_XXXXXX.md)
cat > "$TMPFILE4" << 'MEMEOF'
- [AVOID] Backend broad prefix <!-- path:backend/ -->
- [AVOID] Frontend exact path <!-- path:frontend/src/pages/ -->
- [AVOID] No-match entry <!-- path:dark-factory/ -->
MEMEOF
OUTPUT4=$(load_memory "$TMPFILE4")
rm -f "$TMPFILE4"

assert "broad backend/ prefix matches deep routers/ path" \
  "$(echo "$OUTPUT4" | grep -q 'Backend broad prefix' && echo 0 || echo 1)"

assert "exact frontend/src/pages/ prefix matches Scanner page" \
  "$(echo "$OUTPUT4" | grep -q 'Frontend exact path' && echo 0 || echo 1)"

assert "dark-factory/ prefix excluded when no affected file matches" \
  "$(echo "$OUTPUT4" | grep -q 'No-match entry' && echo 1 || echo 0)"

echo ""
echo "Results: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
