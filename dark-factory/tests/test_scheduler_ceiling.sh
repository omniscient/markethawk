#!/usr/bin/env bash
# Verifies scheduler.sh raised the dispatch ceiling to L and maps the epic_started outcome.
# Run: bash dark-factory/tests/test_scheduler_ceiling.sh
set -euo pipefail
sched="$(cd "$(dirname "$0")" && pwd)/../scheduler.sh"

# get_size_label must recognise XL (not just S/M/L)
grep -qE 'XL|xl' <(awk '/^get_size_label\(\)/{f=1} f{print} f&&/^}/{exit}' "$sched") \
  || { echo "FAIL: get_size_label does not recognise XL"; exit 1; }

# is_above_ceiling must park XL (not L)
block="$(awk '/^is_above_ceiling\(\)/{f=1} f{print} f&&/^}/{exit}' "$sched")"
echo "$block" | grep -qE 'XL\)' \
  || { echo "FAIL: is_above_ceiling does not special-case XL"; exit 1; }
echo "$block" | grep -qE '^[[:space:]]*L\)[[:space:]]*return 0' \
  && { echo "FAIL: is_above_ceiling still parks L unconditionally"; exit 1; }

# is_below_ceiling must treat L as below ceiling (timer-advance applies to S and L)
grep -qE 'S\|L\|""\)' <(awk '/^is_below_ceiling\(\)/{f=1} f{print} f&&/^}/{exit}' "$sched") \
  || { echo "FAIL: is_below_ceiling does not include L"; exit 1; }

# Priority-6 must map epic_started → DISPATCHED on the same line
grep -qE 'autopilot=epic_started.*DISPATCHED|DISPATCHED.*autopilot=epic_started' "$sched" \
  || { echo "FAIL: scheduler does not map epic_started to DISPATCHED on the same line"; exit 1; }

echo "PASS"
