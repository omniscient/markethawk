#!/usr/bin/env bash
# Test: savings row and fallbacks are extracted correctly from a context-budget.json v2 artifact.
set -euo pipefail

TMPDIR=$(mktemp -d)
trap 'rm -rf "$TMPDIR"' EXIT

# Create a synthetic v2 budget artifact
cat > "$TMPDIR/context-budget.json" <<'EOF'
{
  "schema_version": 2,
  "baseline_input_tokens": 20000,
  "estimated_input_tokens": 14000,
  "savings_tokens": 6000,
  "savings_pct": 30.0,
  "fallback_events": [],
  "sections": {
    "architecture_md": {
      "status": "included_slice",
      "tokens": 2000,
      "baseline_tokens": 8000,
      "fallback": false,
      "fallback_reason": null
    }
  }
}
EOF

# Test: schema_version is 2
SCHEMA_VER=$(jq -r '.schema_version // 1' "$TMPDIR/context-budget.json")
[ "$SCHEMA_VER" = "2" ] || { echo "FAIL: schema_version expected 2, got $SCHEMA_VER"; exit 1; }

# Test: savings extraction
SAVINGS_TOKENS=$(jq -r '.savings_tokens // 0' "$TMPDIR/context-budget.json")
SAVINGS_PCT=$(jq -r '.savings_pct // 0' "$TMPDIR/context-budget.json")
[ "$SAVINGS_TOKENS" = "6000" ] || { echo "FAIL: savings_tokens expected 6000, got $SAVINGS_TOKENS"; exit 1; }
[ "$SAVINGS_PCT" = "30" ] || [ "$SAVINGS_PCT" = "30.0" ] || { echo "FAIL: savings_pct expected 30 or 30.0, got $SAVINGS_PCT"; exit 1; }

# Test: baseline_input_tokens present
BASELINE=$(jq -r '.baseline_input_tokens // "MISSING"' "$TMPDIR/context-budget.json")
[ "$BASELINE" = "20000" ] || { echo "FAIL: baseline_input_tokens expected 20000, got $BASELINE"; exit 1; }

# Test: fallback_events empty → no fallbacks line
FALLBACK_COUNT=$(jq -r '(.fallback_events // []) | length' "$TMPDIR/context-budget.json")
[ "$FALLBACK_COUNT" = "0" ] || { echo "FAIL: expected 0 fallback_events, got $FALLBACK_COUNT"; exit 1; }

# Test: fallback_events with entries → correct text rendering
cat > "$TMPDIR/context-budget-fallback.json" <<'EOF'
{
  "schema_version": 2,
  "baseline_input_tokens": 20000,
  "estimated_input_tokens": 20000,
  "savings_tokens": 0,
  "savings_pct": 0,
  "fallback_events": [
    {"section": "architecture_md", "reason": "safety_keyword:performance"}
  ],
  "sections": {}
}
EOF
FALLBACKS=$(jq -r '
  "**Fallbacks:** " + ([ (.fallback_events // [])[] | "\(.section): \(.reason)" ] | join(", "))
' "$TMPDIR/context-budget-fallback.json" 2>/dev/null || true)
[ "$FALLBACKS" = "**Fallbacks:** architecture_md: safety_keyword:performance" ] || {
  echo "FAIL: expected fallbacks text, got: $FALLBACKS"; exit 1;
}

echo "PASS: savings row extraction tests"
