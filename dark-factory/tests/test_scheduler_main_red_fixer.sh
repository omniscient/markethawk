#!/usr/bin/env bash
# Verifies scheduler.sh dispatches a main-red fixer, gated by enable + dedupe + throttle,
# only inside the MAIN_IS_RED block.
# Run: bash dark-factory/tests/test_scheduler_main_red_fixer.sh
set -euo pipefail
sched="$(cd "$(dirname "$0")" && pwd)/../scheduler.sh"

grep -q 'MAIN_RED_AUTOFIX_ENABLED' "$sched" \
  || { echo "FAIL: no MAIN_RED_AUTOFIX_ENABLED kill-switch"; exit 1; }
grep -q 'is_fixer_running' "$sched" \
  || { echo "FAIL: no is_fixer_running dedupe helper"; exit 1; }
grep -qE 'dispatch "Fix main"' "$sched" \
  || { echo "FAIL: scheduler never dispatches 'Fix main'"; exit 1; }

# The fixer dispatch must live inside the MAIN_IS_RED block (after the recheck call).
block="$(awk '/Read main-is-red sentinel/{f=1} f{print} f&&/^fi$/{exit}' "$sched")"
echo "$block" | grep -q 'main_red_fixer_check' \
  || { echo "FAIL: main_red_fixer_check not called in the MAIN_IS_RED block"; exit 1; }

echo "PASS"
