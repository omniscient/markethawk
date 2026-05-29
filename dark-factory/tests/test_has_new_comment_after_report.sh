#!/usr/bin/env bash
# Regression test for has_new_comment_after_report() in scheduler.sh.
#
# Bug (issue #124): the dark factory posts its cost-report comment AFTER the spec on the
# success path. has_new_comment_after_report() found the last "Posted by MarketHawk
# Refinement Pipeline" comment (the spec) and returned "yes" if ANY comment followed it —
# so the bot-authored cost report was mistaken for human feedback and a duplicate spec run
# was dispatched. Only genuine human comments after the spec should return "yes".
#
# Run: bash dark-factory/tests/test_has_new_comment_after_report.sh
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCHEDULER="${SCRIPT_DIR}/../scheduler.sh"

# scheduler.sh validates these at top level; provide dummies so sourcing succeeds.
export GH_TOKEN="test-token"
export CLAUDE_CODE_OAUTH_TOKEN="test-oauth"
export SCHEDULER_SOURCE_ONLY=1

# shellcheck source=/dev/null
source "$SCHEDULER"
set +e  # scheduler.sh sets -e; don't let an assertion failure abort the run

# --- gh stub: return the JSON in $MOCK_COMMENTS for `gh issue view ... --json comments` ---
MOCK_COMMENTS='[]'
gh() {
  case "$*" in
    *"issue view"*) printf '%s' "$MOCK_COMMENTS" ;;
    *) return 0 ;;
  esac
}

REPORT_MARKER="Posted by MarketHawk Refinement Pipeline"
PASS=0
FAIL=0

# Footers used by the comment factories, kept verbatim so the test breaks if they drift.
SCHED_FOOTER="*Posted by MarketHawk Backlog Scheduler*"
SPEC_FOOTER="*Posted by MarketHawk Refinement Pipeline*"
COST_FOOTER="*Updated by MarketHawk Dark Factory*"

# Build a GitHub-shaped comments array from the body strings passed as arguments.
# Uses jq --args (NOT process substitution, which is broken under MSYS bash).
mock_comments() {
  jq -n '$ARGS.positional | map({body: ., author: {login: "omniscient"}})' --args "$@"
}

assert_eq() {
  local name="$1" expected="$2" actual="$3"
  if [ "$expected" = "$actual" ]; then
    echo "  PASS: $name"
    PASS=$((PASS + 1))
  else
    echo "  FAIL: $name (expected '$expected', got '$actual')"
    FAIL=$((FAIL + 1))
  fi
}

# Scenario A — issue #124 exactly: spec, then cost report. No human feedback => "no".
MOCK_COMMENTS=$(mock_comments \
  "🧠 Starting brainstorming and spec generation.
---
${SCHED_FOOTER}" \
  "## Refinement Pipeline — Spec Generated
The spec body.
---
${SPEC_FOOTER}" \
  "<!-- dark-factory-cost-report -->
## Dark Factory — Cost Report
---
${COST_FOOTER}")
assert_eq "cost report after spec is NOT human feedback" "no" "$(has_new_comment_after_report 124 "$REPORT_MARKER")"

# Scenario B — a genuine human comment after the spec => "yes".
MOCK_COMMENTS=$(mock_comments \
  "## Refinement Pipeline — Spec Generated
---
${SPEC_FOOTER}" \
  "Please use a port range starting at 20000 instead.")
assert_eq "human comment after spec IS feedback" "yes" "$(has_new_comment_after_report 124 "$REPORT_MARKER")"

# Scenario C — cost report AND a later human comment => "yes" (human still counts).
MOCK_COMMENTS=$(mock_comments \
  "## Refinement Pipeline — Spec Generated
---
${SPEC_FOOTER}" \
  "<!-- dark-factory-cost-report -->
---
${COST_FOOTER}" \
  "Looks good but rename the helper.")
assert_eq "human comment after cost report IS feedback" "yes" "$(has_new_comment_after_report 124 "$REPORT_MARKER")"

# Scenario D — spec only, nothing after => "no".
MOCK_COMMENTS=$(mock_comments \
  "## Refinement Pipeline — Spec Generated
---
${SPEC_FOOTER}")
assert_eq "spec with no following comment" "no" "$(has_new_comment_after_report 124 "$REPORT_MARKER")"

# Scenario E — no spec marker present at all => "no".
MOCK_COMMENTS=$(mock_comments "Just a stray comment, no spec yet.")
assert_eq "no spec marker" "no" "$(has_new_comment_after_report 124 "$REPORT_MARKER")"

echo ""
echo "Passed: $PASS  Failed: $FAIL"
[ "$FAIL" -eq 0 ]
