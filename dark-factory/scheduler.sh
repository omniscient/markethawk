#!/usr/bin/env bash
set -euo pipefail

# --- Configuration ---
POLL_INTERVAL="${POLL_INTERVAL:-30}"
SKIP_LABELS="needs-discussion,epic"
MAX_RETRIES="${MAX_RETRIES:-3}"
STATE_FILE="/tmp/scheduler-state.json"

# Board constants
PROJECT_NUMBER=1
OWNER="omniscient"
PROJECT_ID="PVT_kwHOAAFds84BWh4w"
STATUS_FIELD="PVTSSF_lAHOAAFds84BWh4wzhR1VaA"
STATUS_READY="61e4505c"
STATUS_IN_PROGRESS="47fc9ee4"
STATUS_IN_REVIEW="df73e18b"
STATUS_BLOCKED="93d87b2f"
STATUS_DONE="98236657"

# --- Validate required environment ---
if [ -z "${GH_TOKEN:-}" ]; then
  echo "ERROR: GH_TOKEN is not set. Add it to .archon/.env" >&2
  exit 1
fi
if [ -z "${CLAUDE_CODE_OAUTH_TOKEN:-}" ] && [ -z "${ANTHROPIC_API_KEY:-}" ]; then
  echo "ERROR: Set CLAUDE_CODE_OAUTH_TOKEN or ANTHROPIC_API_KEY in .archon/.env" >&2
  exit 1
fi

# Initialize retry state
if [ ! -f "$STATE_FILE" ]; then
  echo '{}' > "$STATE_FILE"
fi

# --- Retry tracking ---
get_retry_count() {
  local issue_num="$1"
  jq -r --arg n "$issue_num" '.[$n] // 0' "$STATE_FILE"
}

increment_retry() {
  local issue_num="$1"
  local current
  current=$(get_retry_count "$issue_num")
  local new_count=$((current + 1))
  local tmp
  tmp=$(mktemp)
  jq --arg n "$issue_num" --argjson c "$new_count" '.[$n] = $c' "$STATE_FILE" > "$tmp" && mv "$tmp" "$STATE_FILE"
}

reset_retry() {
  local issue_num="$1"
  local tmp
  tmp=$(mktemp)
  jq --arg n "$issue_num" 'del(.[$n])' "$STATE_FILE" > "$tmp" && mv "$tmp" "$STATE_FILE"
}

# --- Duplicate dispatch prevention ---
is_issue_running() {
  local issue_num="$1"
  docker ps --format '{{.Command}}' 2>/dev/null | grep -q "#${issue_num}" && return 0
  return 1
}

# --- Dispatch ---
dispatch() {
  local command="$1"
  echo "Dispatching: $command"
  docker compose -f /workspace/project/docker-compose.yml --profile factory run -d --rm dark-factory "$command"
}

# --- Board state ---
fetch_board_items() {
  gh project item-list "$PROJECT_NUMBER" --owner "$OWNER" --format json --limit 200
}

get_items_by_status() {
  local items="$1"
  local status_name="$2"
  echo "$items" | jq -c "[.items[] | select(.status == \"$status_name\") | select(.content.type == \"Issue\")]"
}

has_skip_label() {
  local item="$1"
  local labels
  labels=$(echo "$item" | jq -r '.labels[]?' 2>/dev/null)
  IFS=',' read -ra SKIP_ARRAY <<< "$SKIP_LABELS"
  for skip in "${SKIP_ARRAY[@]}"; do
    if echo "$labels" | grep -qi "$skip"; then
      return 0
    fi
  done
  return 1
}

get_issue_number() {
  local item="$1"
  echo "$item" | jq -r '.content.number'
}

# --- WIP limits ---
fetch_wip_limits() {
  local result
  result=$(gh api graphql -f query='
    query {
      node(id: "'"$PROJECT_ID"'") {
        ... on ProjectV2 {
          field(name: "Status") {
            ... on ProjectV2SingleSelectField {
              options { id name description }
            }
          }
        }
      }
    }
  ' 2>/dev/null) || true
  echo "$result"
}

get_column_limit() {
  local wip_data="$1"
  local option_id="$2"
  local desc
  desc=$(echo "$wip_data" | jq -r --arg id "$option_id" \
    '.data.node.field.options[] | select(.id == $id) | .description // ""' 2>/dev/null)
  if echo "$desc" | grep -qoP 'limit:\s*\K\d+'; then
    echo "$desc" | grep -oP 'limit:\s*\K\d+'
  else
    echo "999"
  fi
}

# --- Dependency checking ---
dependencies_met() {
  local issue_num="$1"
  local board_items="$2"
  local body
  body=$(gh issue view "$issue_num" --json body -q '.body' 2>/dev/null) || return 0
  local deps
  deps=$(echo "$body" | grep -oP 'Depends on:\s*#\K\d+' || true)
  if [ -z "$deps" ]; then
    return 0
  fi
  while IFS= read -r dep_num; do
    local dep_status
    dep_status=$(echo "$board_items" | jq -r ".items[] | select(.content.number == $dep_num) | .status" 2>/dev/null)
    if [ "$dep_status" != "Done" ]; then
      return 1
    fi
  done <<< "$deps"
  return 0
}
