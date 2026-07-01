#!/usr/bin/env bash
# Detect and excise files committed outside the allowed-prefixes scope.
# Usage: oos_excise.sh <allowed-prefixes> <commit-noun>
# Args:
#   <allowed-prefixes>  space-separated path prefixes that are in scope
#   <commit-noun>       noun for the excision commit message (e.g. "refine", "plan")
# Env:
#   ISSUE_NUM     (optional) issue number embedded in commit message
#   ARTIFACTS_DIR (required) directory where out-of-scope.md is written
# Stdout: names of excised files, one per line (log messages go to stderr)
# Side effects:
#   - reverts or removes each out-of-scope file
#   - creates a git commit (--allow-empty) recording the excision
#   - appends entries to $ARTIFACTS_DIR/out-of-scope.md
set -euo pipefail

ALLOWED_PREFIXES="${1:?Usage: oos_excise.sh <allowed-prefixes> <commit-noun>}"
COMMIT_NOUN="${2:?Usage: oos_excise.sh <allowed-prefixes> <commit-noun>}"
ISSUE_NUM="${ISSUE_NUM:-}"
ARTIFACTS_DIR="${ARTIFACTS_DIR:?ARTIFACTS_DIR must be set}"

OOS_FILES=$(git diff --name-only origin/main HEAD 2>/dev/null | while read -r f; do
  ALLOWED=false
  for prefix in $ALLOWED_PREFIXES; do
    case "$f" in "$prefix"*) ALLOWED=true; break;; esac
  done
  $ALLOWED || echo "$f"
done)

if [ -n "$OOS_FILES" ]; then
  echo "OOS gate: excising out-of-scope files: $OOS_FILES" >&2
  for f in $OOS_FILES; do
    if git show origin/main:"$f" > /dev/null 2>&1; then
      git checkout origin/main -- "$f" >/dev/null 2>&1
    else
      git rm -f --cached "$f" >/dev/null 2>&1; rm -f "$f"
    fi
  done
  git commit -m "chore: excise out-of-scope files from ${COMMIT_NOUN} run (#${ISSUE_NUM})" --allow-empty >/dev/null 2>&1
  mkdir -p "$ARTIFACTS_DIR"
  echo "$OOS_FILES" | while read -r f; do
    echo "- $f: removed by ${COMMIT_NOUN} OOS gate (should not have been created/modified)" >> "$ARTIFACTS_DIR/out-of-scope.md"
  done
  echo "$OOS_FILES"
fi
