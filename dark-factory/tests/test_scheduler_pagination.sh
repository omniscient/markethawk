#!/usr/bin/env bash
# Unit test for ProjectV2 pagination in scheduler.sh.
# Run: bash dark-factory/tests/test_scheduler_pagination.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SCHED="$SCRIPT_DIR/../scheduler.sh"

docker() { return 0; }
export -f docker

export GH_TOKEN="${GH_TOKEN:-stub-token}"
export CLAUDE_CODE_OAUTH_TOKEN="${CLAUDE_CODE_OAUTH_TOKEN:-stub-token}"
export SCHEDULER_SOURCE_ONLY=1
export SCHEDULER_STATE_DIR="$(mktemp -d /tmp/sched-page-test-statedir-XXXXXX)"
export FACTORY_CORE_CLI="$PWD/dark-factory/scripts/factory_core/cli.py"

STUB_LOG="$(mktemp /tmp/sched-page-test-gh-XXXXXX.log)"

gh() {
  echo "gh $*" >> "$STUB_LOG"
  if echo "$*" | grep -q 'after: "CUR1"'; then
    cat <<'JSON'
{"data":{"node":{"items":{"pageInfo":{"hasNextPage":false,"endCursor":null},"nodes":[{"fieldValueByName":{"name":"Backlog"},"content":{"number":102,"title":"second page issue","labels":{"nodes":[{"name":"ready-for-agent"}]}}}]}}}}
JSON
  else
    cat <<'JSON'
{"data":{"node":{"items":{"pageInfo":{"hasNextPage":true,"endCursor":"CUR1"},"nodes":[{"fieldValueByName":{"name":"Backlog"},"content":{"number":101,"title":"first page issue","labels":{"nodes":[{"name":"ready-for-agent"}]}}}]}}}}
JSON
  fi
}
export -f gh

source "$SCHED"

BOARD_PAGE_RESULT="$(fetch_board_items)"

cleanup() {
  rm -f "$STUB_LOG"
  rm -rf "$SCHEDULER_STATE_DIR"
}
trap cleanup EXIT

if [ "$(echo "$BOARD_PAGE_RESULT" | jq '.items | length')" != "2" ]; then
  echo "FAIL: expected two items across paginated ProjectV2 pages" >&2
  echo "$BOARD_PAGE_RESULT" >&2
  exit 1
fi

if [ "$(grep -c 'items(first: 100' "$STUB_LOG" || true)" != "2" ]; then
  echo "FAIL: expected every ProjectV2 page request to use first: 100" >&2
  cat "$STUB_LOG" >&2
  exit 1
fi

if [ "$(grep -c 'after: "CUR1"' "$STUB_LOG" || true)" != "1" ]; then
  echo "FAIL: expected second ProjectV2 request to include cursor CUR1" >&2
  cat "$STUB_LOG" >&2
  exit 1
fi

echo "PASS: fetch_board_items paginates ProjectV2 items"
