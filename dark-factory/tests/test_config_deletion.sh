#!/usr/bin/env bash
# Verifies that resolve_config_yaml() exits non-zero when config.yaml is absent.
# This is the "deletion test" for the single-config-interface requirement (#338):
# removing config.yaml must break consumers loudly.
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SCHED="$SCRIPT_DIR/../scheduler.sh"

PASSED=0; FAILED=0
_assert() {
  local desc="$1" expected="$2" actual="$3"
  if [ "$expected" = "$actual" ]; then
    echo "  PASS: $desc"; PASSED=$((PASSED+1))
  else
    echo "  FAIL: $desc — expected='$expected' got='$actual'" >&2; FAILED=$((FAILED+1))
  fi
}

# ---- Source scheduler helpers with SCHEDULER_SOURCE_ONLY=1 ----
SCHEDULER_STATE_DIR=$(mktemp -d /tmp/cfg-del-test-XXXXXX)
export SCHEDULER_STATE_DIR GH_TOKEN="${GH_TOKEN:-stub-token}" CLAUDE_CODE_OAUTH_TOKEN="${CLAUDE_CODE_OAUTH_TOKEN:-stub-token}"
# Set required config-driven vars so set -u is satisfied during sourcing
export POLL_INTERVAL=60 MAX_RETRIES=3 RATE_LIMIT_FLOOR=200 FACTORY_WIP_LIMIT=1
export MAIN_RED_RECHECK_ENABLED=true MAIN_RED_RECHECK_MINUTES=20 REFINE_WIP_LIMIT=2
export DIRECT_TO_PR_LABEL=direct-to-pr SPEC_GRACE_MINUTES=30 PLAN_GRACE_MINUTES=30
export CONFLICT_RESOLUTION_ENABLED=true DISPATCH_CEILING_ENABLED=true
export ABOVE_CEILING_LABEL=above-ceiling ABOVE_CEILING_KEYWORDS="migration|migrate"

SCHEDULER_SOURCE_ONLY=1 source "$SCHED"

# ---- T1: resolve_config_yaml exits non-zero with absent paths ----
echo "--- T1: resolve_config_yaml — absent config ---"
# Re-define CONFIG_YAML_PATHS to non-existent locations to simulate config deletion
CONFIG_YAML_PATHS=("/tmp/nonexistent-config-a-$$-1.yaml" "/tmp/nonexistent-config-a-$$-2.yaml")

if resolve_config_yaml >/dev/null 2>&1; then
  _assert "resolve_config_yaml fails when config absent" "nonzero" "0"
else
  _assert "resolve_config_yaml fails when config absent" "nonzero" "nonzero"
fi

# ---- T2: resolve_config_yaml succeeds when config exists ----
echo "--- T2: resolve_config_yaml — config present ---"
TMP_CFG=$(mktemp /tmp/cfg-del-test-yaml-XXXXXX.yaml)
CONFIG_YAML_PATHS=("$TMP_CFG")
FOUND=$(resolve_config_yaml 2>/dev/null || echo "")
_assert "resolve_config_yaml returns path when present" "$TMP_CFG" "$FOUND"
rm -f "$TMP_CFG"

# ---- Cleanup ----
rm -rf "$SCHEDULER_STATE_DIR"
echo ""
echo "Results: ${PASSED} passed, ${FAILED} failed"
[ "$FAILED" -eq 0 ]
