#!/usr/bin/env bash
# Unit tests for agent_roles.sh — verifies all 13 constants and MEMORY_PROJECT.
set -euo pipefail

REPO_ROOT=$(git rev-parse --show-toplevel)
source "${REPO_ROOT}/dark-factory/scripts/agent_roles.sh"

PASS=0; FAIL=0

assert() {
  local desc="$1" result="$2"
  if [ "$result" = "0" ]; then
    echo "PASS: $desc"; PASS=$((PASS+1))
  else
    echo "FAIL: $desc"; FAIL=$((FAIL+1))
  fi
}

assert "MEMORY_PROJECT=markethawk" \
  "$([ "${MEMORY_PROJECT:-}" = 'markethawk' ] && echo 0 || echo 1)"

assert "AGENT_ID_FACTORY_DIRECTOR=factory-director" \
  "$([ "${AGENT_ID_FACTORY_DIRECTOR:-}" = 'factory-director' ] && echo 0 || echo 1)"

assert "AGENT_ID_INTAKE_TRIAGE=intake-triage-agent" \
  "$([ "${AGENT_ID_INTAKE_TRIAGE:-}" = 'intake-triage-agent' ] && echo 0 || echo 1)"

assert "AGENT_ID_REFINEMENT=refinement-agent" \
  "$([ "${AGENT_ID_REFINEMENT:-}" = 'refinement-agent' ] && echo 0 || echo 1)"

assert "AGENT_ID_PLANNING=planning-agent" \
  "$([ "${AGENT_ID_PLANNING:-}" = 'planning-agent' ] && echo 0 || echo 1)"

assert "AGENT_ID_IMPLEMENTATION=implementation-agent" \
  "$([ "${AGENT_ID_IMPLEMENTATION:-}" = 'implementation-agent' ] && echo 0 || echo 1)"

assert "AGENT_ID_VALIDATION=validation-agent" \
  "$([ "${AGENT_ID_VALIDATION:-}" = 'validation-agent' ] && echo 0 || echo 1)"

assert "AGENT_ID_CODE_REVIEW=code-review-agent" \
  "$([ "${AGENT_ID_CODE_REVIEW:-}" = 'code-review-agent' ] && echo 0 || echo 1)"

assert "AGENT_ID_SECURITY=security-agent" \
  "$([ "${AGENT_ID_SECURITY:-}" = 'security-agent' ] && echo 0 || echo 1)"

assert "AGENT_ID_DECONFLICT=deconflict-agent" \
  "$([ "${AGENT_ID_DECONFLICT:-}" = 'deconflict-agent' ] && echo 0 || echo 1)"

assert "AGENT_ID_CI_RESCUE=ci-rescue-agent" \
  "$([ "${AGENT_ID_CI_RESCUE:-}" = 'ci-rescue-agent' ] && echo 0 || echo 1)"

assert "AGENT_ID_MERGE_GATE=merge-gate-agent" \
  "$([ "${AGENT_ID_MERGE_GATE:-}" = 'merge-gate-agent' ] && echo 0 || echo 1)"

assert "AGENT_ID_COST_TELEMETRY=cost-telemetry-agent" \
  "$([ "${AGENT_ID_COST_TELEMETRY:-}" = 'cost-telemetry-agent' ] && echo 0 || echo 1)"

assert "AGENT_ID_HUMAN_LIAISON=human-liaison-agent" \
  "$([ "${AGENT_ID_HUMAN_LIAISON:-}" = 'human-liaison-agent' ] && echo 0 || echo 1)"

echo ""
echo "Results: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
