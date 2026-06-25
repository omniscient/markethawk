#!/usr/bin/env bash
# Verifies entrypoint.sh routes "Fix main" to the fixer, disambiguated from INTENT=fix,
# and BEFORE the smoke gate can red-exit.
# Run: bash dark-factory/tests/test_entrypoint_fix_main.sh
set -euo pipefail
ep="$(cd "$(dirname "$0")" && pwd)/../entrypoint.sh"

grep -q 'fix-main' "$ep" \
  || { echo "FAIL: no fix-main intent override"; exit 1; }
grep -q 'main-red-fix --once' "$ep" \
  || { echo "FAIL: entrypoint does not invoke the main-red-fix CLI"; exit 1; }

# The fix-main route must appear BEFORE the smoke-gate invocation (so the gate's
# red-exit-0 cannot abort the fixer). Compare line numbers.
route_ln=$(grep -n 'INTENT" = "fix-main"' "$ep" | head -1 | cut -d: -f1)
smoke_ln=$(grep -n 'run_smoke_gate\|smoke_gate.sh' "$ep" | head -1 | cut -d: -f1)
[ -n "$route_ln" ] && [ -n "$smoke_ln" ] && [ "$route_ln" -lt "$smoke_ln" ] \
  || { echo "FAIL: fix-main route ($route_ln) not before smoke gate ($smoke_ln)"; exit 1; }

echo "PASS"
