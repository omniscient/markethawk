#!/usr/bin/env bash
# Unit test for route_memory_file() — the path routing table for gate-stage memory writes.
# This test is self-contained: it defines and tests the function in isolation.
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

route_memory_file() {
  local FILE="$1"
  case "$FILE" in
    backend/app/*)            echo ".archon/memory/backend-patterns.md" ;;
    frontend/src/*)           echo ".archon/memory/frontend-patterns.md" ;;
    .archon/*|dark-factory/*) echo ".archon/memory/dark-factory-ops.md" ;;
    ARCHITECTURE.md)          echo ".archon/memory/architecture.md" ;;
    *)                        echo ".archon/memory/codebase-patterns.md" ;;
  esac
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

echo ""
echo "Results: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
