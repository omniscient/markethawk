#!/usr/bin/env bash
# Integration test: write_memory_entry() in gate_lib.sh delegates to memory_write.py.
# Tests that the delegation produces entries with scope:/path: tags (new behaviour).
set -euo pipefail

REPO_ROOT=$(git rev-parse --show-toplevel)
source "${REPO_ROOT}/dark-factory/scripts/gate_lib.sh"

PASS=0; FAIL=0

assert() {
  local desc="$1" result="$2"
  if [ "$result" = "0" ]; then
    echo "PASS: $desc"; PASS=$((PASS+1))
  else
    echo "FAIL: $desc"; FAIL=$((FAIL+1))
  fi
}

TMP=$(mktemp -d)
trap "rm -rf $TMP" EXIT

# ── Test 1: entry written with scope:/path: tags ─────────────────────────────
MD="$TMP/dark-factory-ops.md"
printf "# Dark Factory Ops\n\n---\n<!-- PROVISIONAL -->\n" > "$MD"

write_memory_entry "$MD" "dark-factory/scripts/" "avoid bad pattern" "conformance" "648"

assert "[AVOID] entry written" \
  "$(grep -q '\[AVOID\]' "$MD" && echo 0 || echo 1)"
assert "scope: tag present" \
  "$(grep -q 'scope:dark-factory' "$MD" && echo 0 || echo 1)"
assert "agent: tag present" \
  "$(grep -q 'agent:conformance' "$MD" && echo 0 || echo 1)"
assert "path: tag present" \
  "$(grep -q 'path:dark-factory/scripts/' "$MD" && echo 0 || echo 1)"
assert "entry is before --- delimiter" \
  "$(awk '/\[AVOID\]/{a=NR} /^---$/{b=NR} END{exit !(a<b)}' "$MD" && echo 0 || echo 1)"

# ── Test 2: normalized dedup skips second write ──────────────────────────────
write_memory_entry "$MD" "dark-factory/scripts/" "avoid bad pattern" "conformance" "648"
ENTRY_COUNT=$(grep -c '\[AVOID\]' "$MD" || true)
assert "dedup skips second identical write (count=1)" \
  "$([ "$ENTRY_COUNT" -eq 1 ] && echo 0 || echo 1)"

# ── Test 3: index.jsonl created next to the markdown ────────────────────────
assert "index.jsonl created" \
  "$([ -f "$TMP/index.jsonl" ] && echo 0 || echo 1)"

# ── Test 4: index.jsonl record is valid JSON with agent_id field ─────────────
INDEX_CHECK_VALID=$(python3 - "$TMP/index.jsonl" <<'PYEOF' && echo 0 || echo 1
import json, sys
json.loads(open(sys.argv[1]).readline())
PYEOF
)
assert "index.jsonl record is valid JSON" "$INDEX_CHECK_VALID"

INDEX_CHECK_AGENT=$(python3 - "$TMP/index.jsonl" <<'PYEOF' && echo 0 || echo 1
import json, sys
r = json.loads(open(sys.argv[1]).readline())
exit(0 if r['agent_id'] == 'conformance' else 1)
PYEOF
)
assert "index.jsonl agent_id is conformance" "$INDEX_CHECK_AGENT"

# ── Test 5: route_memory_file() still works (bash function unchanged) ─────────
ROUTE_RESULT=$(route_memory_file 'dark-factory/scripts/foo.sh')
assert "route_memory_file dark-factory/ → dark-factory-ops.md" \
  "$([ "$ROUTE_RESULT" = '.archon/memory/dark-factory-ops.md' ] && echo 0 || echo 1)"

echo ""
echo "Results: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
