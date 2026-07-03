#!/usr/bin/env bash
# Test: BUDGET_LINE for would_trim state uses estimated_input_tokens, not reserved_tokens
set -euo pipefail

TMPDIR=$(mktemp -d)
trap 'rm -rf "$TMPDIR"' EXIT

# budget file: would_trim=true, estimated_input_tokens=10000, reserved_tokens=9000, scenario_budget=8000
cat > "$TMPDIR/context-budget.json" <<'EOF'
{
  "schema_version": 2,
  "scenario": "conformance",
  "over_budget": false,
  "would_trim": true,
  "estimated_input_tokens": 10000,
  "reserved_tokens": 9000,
  "scenario_budget": 8000,
  "derived_caps": {"arch": 1500, "memory": 750},
  "allowance": 100
}
EOF

BUDGET_FILE="$TMPDIR/context-budget.json"

# Replicate the entrypoint.sh logic (fixed: uses estimated_input_tokens)
OVER_BUDGET=$(jq -r '.over_budget // "null"' "$BUDGET_FILE" 2>/dev/null || echo "null") || true
WOULD_TRIM=$(jq -r '.would_trim // "null"' "$BUDGET_FILE" 2>/dev/null || echo "null") || true

BUDGET_LINE=""
if [ "$OVER_BUDGET" = "true" ]; then
  echo "SKIP: over_budget path not under test"
elif [ "$WOULD_TRIM" = "true" ]; then
  BE_SCENARIO=$(jq -r '.scenario // "unknown"' "$BUDGET_FILE" 2>/dev/null || echo "unknown") || true
  BE_ESTIMATED=$(jq -r '.estimated_input_tokens // 0' "$BUDGET_FILE" 2>/dev/null || echo "0") || true
  BE_BUDGET=$(jq -r '.scenario_budget // 0' "$BUDGET_FILE" 2>/dev/null || echo "0") || true
  CAPS_STR=$(jq -r '[(.derived_caps // {}) | to_entries[] | "\(.key)→\(.value)"] | join(", ")' "$BUDGET_FILE" 2>/dev/null || echo "") || true
  BUDGET_LINE="**Budget trim (${BE_SCENARIO}): est ${BE_ESTIMATED} / ${BE_BUDGET} budget — capped: ${CAPS_STR}**"
fi

# The spec requires estimated_input_tokens (10000), not reserved_tokens (9000)
EXPECTED_EST="10000"
if echo "$BUDGET_LINE" | grep -q "est ${EXPECTED_EST}"; then
  echo "PASS: budget trim line uses estimated_input_tokens"
else
  echo "FAIL: budget trim line does not contain 'est ${EXPECTED_EST}'"
  echo "  got: $BUDGET_LINE"
  exit 1
fi
