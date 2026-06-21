#!/usr/bin/env bash
# Verifies the epic_autopilot config section + scheduler.sh read_config wiring.
# Run (needs yq): bash dark-factory/tests/test_epic_autopilot_config.sh
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
cfg="$HERE/../../.claude/skills/refinement/config.yaml"
sched="$HERE/../scheduler.sh"

val=$(yq '.epic_autopilot.enabled' "$cfg")
[ "$val" = "false" ] || { echo "FAIL: epic_autopilot.enabled should default false, got '$val'"; exit 1; }

cap=$(yq '.epic_autopilot.daily_cap' "$cfg")
[ "$cap" = "5" ] || { echo "FAIL: epic_autopilot.daily_cap should be 5, got '$cap'"; exit 1; }

model=$(yq '.epic_autopilot.model' "$cfg")
[ "$model" = "claude-opus-4-8" ] || { echo "FAIL: epic_autopilot.model should be claude-opus-4-8, got '$model'"; exit 1; }

floor=$(yq '.epic_autopilot.confidence_floor' "$cfg")
[ "$floor" = "0.7" ] || { echo "FAIL: epic_autopilot.confidence_floor should be 0.7, got '$floor'"; exit 1; }

# scheduler.sh read_config wires the knobs
grep -qE 'EPIC_AUTOPILOT_ENABLED[[:space:]]+.\.epic_autopilot\.enabled.' "$sched" \
  || { echo "FAIL: scheduler.sh read_config missing EPIC_AUTOPILOT_ENABLED wiring"; exit 1; }
grep -qE 'EPIC_AUTOPILOT_DAILY_CAP[[:space:]]+.\.epic_autopilot\.daily_cap.' "$sched" \
  || { echo "FAIL: scheduler.sh read_config missing EPIC_AUTOPILOT_DAILY_CAP wiring"; exit 1; }

echo "PASS"
