#!/usr/bin/env bash
# Verifies the scheduler.sh Priority-6 autopilot hook exists and is correctly guarded.
# Run: bash dark-factory/tests/test_scheduler_autopilot_guard.sh
set -euo pipefail
sched="$(cd "$(dirname "$0")" && pwd)/../scheduler.sh"

grep -q 'epic-autopilot --once' "$sched" \
  || { echo "FAIL: scheduler.sh does not call the epic-autopilot CLI"; exit 1; }
grep -q 'EPIC_AUTOPILOT_ENABLED' "$sched" \
  || { echo "FAIL: scheduler.sh autopilot block missing the enabled kill-switch"; exit 1; }

# The Priority-6 block must be gated by DISPATCHED-empty (starved) AND main-green.
block="$(awk '/Priority 6: Epic Autopilot/{f=1} f{print} f&&/^  fi$/{exit}' "$sched")"
echo "$block" | grep -q 'z "\$DISPATCHED"' \
  || { echo "FAIL: autopilot not guarded by DISPATCHED-empty (starved)"; exit 1; }
echo "$block" | grep -q 'MAIN_IS_RED.*false' \
  || { echo "FAIL: autopilot not guarded by main-green"; exit 1; }

echo "PASS"
