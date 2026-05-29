#!/usr/bin/env bash
# Regression guard for the cost-report comment endpoint in entrypoint.sh.
#
# Bug: post_cost_report() read and PATCHed the cost-report comment via
#   /repos/{owner}/{repo}/issues/{ISSUE_NUM}/comments/{COMMENT_ID}
# That path 404s — GitHub's single-comment endpoint omits the issue number
#   /repos/{owner}/{repo}/issues/comments/{COMMENT_ID}
# The 404 was swallowed (2>/dev/null, 2>&1), so the comment was created once and never
# updated (frozen on its first run, prior-run history lost). Verified live: the bad path
# returns 404, the canonical path returns the comment.
#
# Behavioral testing of post_cost_report is impractical (it shells out to archon + gh +
# bc), so this is a static guard: the single-comment endpoint must NOT carry an issue
# number. The list/create endpoint (/issues/{n}/comments, no trailing id) is fine.
#
# Run: bash dark-factory/tests/test_cost_report_endpoint.sh
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENTRYPOINT="${SCRIPT_DIR}/../entrypoint.sh"
FAIL=0

# A single-comment op = the path ends in .../comments/<something>. Such a path must never
# include the issue number segment (issues/$ISSUE_NUM/comments/<id>).
if grep -nE 'issues/\$\{?ISSUE_NUM\}?/comments/[^"]' "$ENTRYPOINT"; then
  echo "  FAIL: single-comment endpoint includes the issue number (404s — see above lines)"
  FAIL=1
else
  echo "  PASS: no issue-number-prefixed single-comment endpoint"
fi

# And the canonical single-comment endpoint should be present (read + PATCH).
CANON=$(grep -cE 'issues/comments/\$\{?COMMENT_ID\}?' "$ENTRYPOINT")
if [ "$CANON" -ge 2 ]; then
  echo "  PASS: canonical /issues/comments/{id} endpoint used (${CANON} occurrences)"
else
  echo "  FAIL: expected >=2 uses of /issues/comments/{id} (read + PATCH), found ${CANON}"
  FAIL=1
fi

echo ""
[ "$FAIL" -eq 0 ] && echo "OK" || echo "FAILED"
[ "$FAIL" -eq 0 ]
