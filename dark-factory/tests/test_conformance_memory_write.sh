#!/usr/bin/env bash
# Unit test for route_memory_file() — sourced from gate_lib.sh.
set -euo pipefail

source "$(git rev-parse --show-toplevel)/dark-factory/scripts/gate_lib.sh"

PASS=0; FAIL=0

assert() {
  local desc="$1" result="$2"
  if [ "$result" = "0" ]; then
    echo "PASS: $desc"; PASS=$((PASS+1))
  else
    echo "FAIL: $desc"; FAIL=$((FAIL+1))
  fi
}

assert "backend/ routes to backend-patterns.md" \
  "$([ "$(route_memory_file 'backend/app/routers/scanner.py')" = '.archon/memory/backend-patterns.md' ] && echo 0 || echo 1)"

assert "backend models/ routes to backend-patterns.md" \
  "$([ "$(route_memory_file 'backend/app/models/scanner.py')" = '.archon/memory/backend-patterns.md' ] && echo 0 || echo 1)"

assert "frontend/ routes to frontend-patterns.md" \
  "$([ "$(route_memory_file 'frontend/src/components/Foo.tsx')" = '.archon/memory/frontend-patterns.md' ] && echo 0 || echo 1)"

assert ".archon/ routes to dark-factory-ops.md" \
  "$([ "$(route_memory_file '.archon/commands/dark-factory-plan.md')" = '.archon/memory/dark-factory-ops.md' ] && echo 0 || echo 1)"

assert "dark-factory/ routes to dark-factory-ops.md" \
  "$([ "$(route_memory_file 'dark-factory/scripts/foo.sh')" = '.archon/memory/dark-factory-ops.md' ] && echo 0 || echo 1)"

assert "ARCHITECTURE.md routes to architecture.md" \
  "$([ "$(route_memory_file 'ARCHITECTURE.md')" = '.archon/memory/architecture.md' ] && echo 0 || echo 1)"

assert "catch-all docs/ routes to codebase-patterns.md" \
  "$([ "$(route_memory_file 'docs/some/file.md')" = '.archon/memory/codebase-patterns.md' ] && echo 0 || echo 1)"

assert "catch-all root file routes to codebase-patterns.md" \
  "$([ "$(route_memory_file 'CLAUDE.md')" = '.archon/memory/codebase-patterns.md' ] && echo 0 || echo 1)"

# ---- write_memory_entry() tag tests (R1/R2) ----

# Test: written entry includes project:markethawk and agentId: from explicit 6th param
TMPWM1=$(mktemp /tmp/test_write_memory_XXXXXX.md)
printf '# Test\n' > "$TMPWM1"
AGENT_ID="" write_memory_entry "$TMPWM1" "dark-factory/scripts/" "Test avoidance text for 651" "test" "651" "planning-agent"

assert "written entry includes project:markethawk (explicit 6th param)" \
  "$(grep -q 'project:markethawk' "$TMPWM1" && echo 0 || echo 1)"

assert "written entry includes agentId:planning-agent (explicit 6th param)" \
  "$(grep -q 'agentId:planning-agent' "$TMPWM1" && echo 0 || echo 1)"

rm -f "$TMPWM1"

# Test: falls back to AGENT_ID env var when no 6th param
TMPWM2=$(mktemp /tmp/test_write_memory_XXXXXX.md)
printf '# Test\n' > "$TMPWM2"
AGENT_ID="refinement-agent" write_memory_entry "$TMPWM2" "dark-factory/" "Env var fallback text for 651" "test" "651"

assert "written entry includes agentId from AGENT_ID env var (no 6th param)" \
  "$(grep -q 'agentId:refinement-agent' "$TMPWM2" && echo 0 || echo 1)"

assert "written entry includes project:markethawk (env var fallback path)" \
  "$(grep -q 'project:markethawk' "$TMPWM2" && echo 0 || echo 1)"

rm -f "$TMPWM2"

# Test: defaults to "unknown" when neither 6th param nor AGENT_ID set
TMPWM3=$(mktemp /tmp/test_write_memory_XXXXXX.md)
printf '# Test\n' > "$TMPWM3"
AGENT_ID="" write_memory_entry "$TMPWM3" "dark-factory/" "Unknown agent text for 651" "test" "651"

assert "written entry defaults agentId to unknown when no 6th param and no env var" \
  "$(grep -q 'agentId:unknown' "$TMPWM3" && echo 0 || echo 1)"

rm -f "$TMPWM3"

echo ""
echo "Results: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
