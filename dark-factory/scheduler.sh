#!/usr/bin/env bash
set -euo pipefail

# --- Configuration ---
POLL_INTERVAL="${POLL_INTERVAL:-60}"
SKIP_LABELS="needs-discussion,epic"
MAX_RETRIES="${MAX_RETRIES:-3}"
STATE_FILE="/tmp/scheduler-state.json"
RATE_LIMIT_FLOOR="${RATE_LIMIT_FLOOR:-200}"

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
STATUS_BACKLOG="f75ad846"
STATUS_REFINED="0c79ebe5"

# Refinement pipeline configuration
REFINE_WIP_LIMIT="${REFINE_WIP_LIMIT:-2}"
REFINE_SKIP_LABELS="needs-discussion,epic,spec-pending-review,plan-pending-review"

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

# --- Rate limit guard ---
check_rate_limit() {
  local rate_json
  rate_json=$(gh api rate_limit --jq '.resources.graphql' 2>/dev/null) || return 0
  local remaining reset_at
  remaining=$(echo "$rate_json" | jq -r '.remaining')
  reset_at=$(echo "$rate_json" | jq -r '.reset')
  if [ "$remaining" -le "$RATE_LIMIT_FLOOR" ]; then
    local now
    now=$(date +%s)
    local wait=$((reset_at - now + 5))
    if [ "$wait" -gt 0 ]; then
      echo "[$(date -u +%FT%TZ)] rate_limit remaining=${remaining} sleeping=${wait}s until_reset"
      sleep "$wait"
    fi
  fi
}

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
  docker ps --no-trunc --format '{{.Command}}' 2>/dev/null | grep -q "#${issue_num}" && return 0
  return 1
}

count_factory_running() {
  docker ps --format '{{.Names}}' 2>/dev/null | grep -c 'markethawk-dark-factory-run-' || true
}

count_refine_running() {
  docker ps --no-trunc --format '{{.Command}}' 2>/dev/null | grep -cE 'Refine issue|Plan issue' || true
}

has_refine_skip_label() {
  local item="$1"
  local labels
  labels=$(echo "$item" | jq -r '.labels[]?' 2>/dev/null)
  IFS=',' read -ra SKIP_ARRAY <<< "$REFINE_SKIP_LABELS"
  for skip in "${SKIP_ARRAY[@]}"; do
    if echo "$labels" | grep -qi "$skip"; then
      return 0
    fi
  done
  return 1
}

has_new_comment_after_report() {
  local issue_num="$1"
  local report_marker="$2"
  local comments
  comments=$(gh issue view "$issue_num" --repo "${OWNER}/markethawk" --json comments -q '.comments' 2>/dev/null) || { echo "no"; return; }

  local report_idx
  report_idx=$(echo "$comments" | jq "map(.body) | to_entries | map(select(.value | test(\"$report_marker\"))) | last | .key // -1")

  if [ "$report_idx" = "-1" ]; then
    echo "no"
    return
  fi

  local total
  total=$(echo "$comments" | jq 'length')
  local next_idx=$((report_idx + 1))
  if [ "$next_idx" -lt "$total" ]; then
    echo "yes"
  else
    echo "no"
  fi
}

# --- Dispatch ---
dispatch() {
  local command="$1"
  echo "Dispatching: $command"
  docker compose -f /workspace/project/docker-compose.yml --profile factory run -d --rm dark-factory "$command"
}

# --- Board state ---
fetch_board_items() {
  local raw
  raw=$(gh api graphql -f query='
    query {
      node(id: "'"$PROJECT_ID"'") {
        ... on ProjectV2 {
          items(first: 50) {
            nodes {
              fieldValueByName(name: "Status") {
                ... on ProjectV2ItemFieldSingleSelectValue { name }
              }
              content {
                ... on Issue {
                  number
                  title
                  labels(first: 10) { nodes { name } }
                }
              }
            }
          }
        }
      }
    }
  ')
  echo "$raw" | jq '{items: [.data.node.items.nodes[]
    | select(.content.number != null)
    | {content: {number: .content.number, title: .content.title, type: "Issue"},
       labels: [.content.labels.nodes[].name],
       status: .fieldValueByName.name}]}'
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
  body=$(gh issue view "$issue_num" --repo "${OWNER}/markethawk" --json body -q '.body' 2>/dev/null) || return 0
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

# --- Comment interpretation ---
get_new_comments() {
  local issue_num="$1"
  local comments
  comments=$(gh issue view "$issue_num" --repo "${OWNER}/markethawk" --json comments -q '.comments' 2>/dev/null) || { echo "[]"; return; }

  local factory_idx
  factory_idx=$(echo "$comments" | jq 'map(.body) | to_entries | map(select(.value | test("Posted by MarketHawk Dark Factory"))) | last | .key // -1')

  if [ "$factory_idx" = "-1" ]; then
    echo "$comments"
    return
  fi

  local start_idx=$((factory_idx + 1))
  local total
  total=$(echo "$comments" | jq 'length')
  if [ "$start_idx" -ge "$total" ]; then
    echo "[]"
    return
  fi

  echo "$comments" | jq --argjson s "$start_idx" '.[$s:]'
}

classify_comments() {
  local issue_num="$1"
  local title="$2"
  local comments_json="$3"

  local comment_text
  comment_text=$(echo "$comments_json" | jq -r '.[] | "[\(.author.login)] \(.body)"')

  local prompt
  prompt="You are a PR comment classifier. Read the comments below and decide
the intent. Reply with exactly one word: MERGE, CONTINUE, or SKIP.

MERGE — the reviewer approves the PR (e.g. \"looks good\", \"ship it\",
\"approved\", \"LGTM\", thumbs up, ready to merge)
CONTINUE — the reviewer wants changes, asks questions about the implementation,
raises concerns, or requests any action (e.g. \"fix the tests\",
\"can you rename X\", \"is this fixable?\", \"should we do X or Y?\",
\"this needs error handling\", any feedback that needs a response)
SKIP — the comment is purely from a bot or automated system, with no
human-authored content requiring action

When in doubt between CONTINUE and SKIP, choose CONTINUE.

PR #${issue_num}: ${title}
Comments since last factory run:
${comment_text}"

  local result
  result=$(echo "$prompt" | claude -p --model haiku 2>&1)
  local exit_code=$?
  local cleaned
  cleaned=$(echo "$result" | tr -d '[:space:]' | tr '[:lower:]' '[:upper:]')

  if [ "$exit_code" -ne 0 ] || [ -z "$cleaned" ]; then
    echo "  classify_comments #${issue_num}: API error (exit=$exit_code), defaulting to SKIP" >&2
    echo "SKIP"
    return
  fi

  case "$cleaned" in
    MERGE|CONTINUE|SKIP)
      echo "  classify_comments #${issue_num}: verdict=${cleaned}" >&2
      echo "$cleaned"
      ;;
    *)
      echo "  classify_comments #${issue_num}: unexpected response '${cleaned}', defaulting to SKIP" >&2
      echo "SKIP"
      ;;
  esac
}

# --- Fetch WIP limits once at startup (cached until restart) ---
WIP_DATA=$(fetch_wip_limits)
MAX_IN_PROGRESS=$(get_column_limit "$WIP_DATA" "$STATUS_IN_PROGRESS")
MAX_IN_REVIEW=$(get_column_limit "$WIP_DATA" "$STATUS_IN_REVIEW")
echo "WIP limits: in_progress=${MAX_IN_PROGRESS} in_review=${MAX_IN_REVIEW}"

# --- Main loop ---
echo "Backlog scheduler started (poll every ${POLL_INTERVAL}s)"

while true; do
  DISPATCHED=""

  # Guard: only one factory container at a time (Claude Max rate limit)
  FACTORY_RUNNING=$(count_factory_running)
  if [ "$FACTORY_RUNNING" -gt 0 ]; then
    echo "[$(date -u +%FT%TZ)] skip=factory_running count=${FACTORY_RUNNING}"
    sleep "$POLL_INTERVAL"
    continue
  fi

  # Guard against rate limit exhaustion (REST call, doesn't cost GraphQL points)
  check_rate_limit

  # Fetch board state
  BOARD_ITEMS=$(fetch_board_items 2>/dev/null) || { echo "[$(date -u +%FT%TZ)] error=gh_api_failed"; sleep "$POLL_INTERVAL"; continue; }

  IN_REVIEW=$(get_items_by_status "$BOARD_ITEMS" "In review")
  BLOCKED=$(get_items_by_status "$BOARD_ITEMS" "Blocked")
  READY=$(get_items_by_status "$BOARD_ITEMS" "Ready")
  IN_PROGRESS=$(get_items_by_status "$BOARD_ITEMS" "In progress")

  BACKLOG=$(get_items_by_status "$BOARD_ITEMS" "Backlog")
  REFINED=$(get_items_by_status "$BOARD_ITEMS" "Refined")

  IN_PROGRESS_COUNT=$(echo "$IN_PROGRESS" | jq 'length')
  IN_REVIEW_COUNT=$(echo "$IN_REVIEW" | jq 'length')
  BACKLOG_COUNT=$(echo "$BACKLOG" | jq 'length')
  REFINED_COUNT=$(echo "$REFINED" | jq 'length')
  REFINE_RUNNING=$(count_refine_running)

  # --- Priority 0: Backlog items (refinement) ---
  while IFS= read -r item; do
    [ -n "$DISPATCHED" ] && break
    ISSUE=$(get_issue_number "$item")

    # Handle spec-pending-review items first (before skip-label check would filter them)
    ITEM_LABELS=$(echo "$item" | jq -r '.labels[]?' 2>/dev/null)
    if echo "$ITEM_LABELS" | grep -qi "spec-pending-review"; then
      if ! is_issue_running "$ISSUE" && [ "$REFINE_RUNNING" -lt "$REFINE_WIP_LIMIT" ]; then
        HAS_NEW=$(has_new_comment_after_report "$ISSUE" "Posted by MarketHawk Refinement Pipeline")
        if [ "$HAS_NEW" = "yes" ]; then
          gh issue edit "$ISSUE" --repo "${OWNER}/markethawk" --remove-label "spec-pending-review" 2>/dev/null || true
          gh issue comment "$ISSUE" --repo "${OWNER}/markethawk" --body "🔄 **Refinement Pipeline** — Re-running with new feedback.

---
*Posted by MarketHawk Backlog Scheduler*" 2>/dev/null || true
          dispatch "Refine issue #${ISSUE}"
          DISPATCHED="Refine issue #${ISSUE}"
          REFINE_RUNNING=$((REFINE_RUNNING + 1))
        fi
      fi
      continue
    fi

    if has_refine_skip_label "$item"; then continue; fi
    if is_issue_running "$ISSUE"; then continue; fi
    if [ "$REFINE_RUNNING" -ge "$REFINE_WIP_LIMIT" ]; then break; fi

    gh issue comment "$ISSUE" --repo "${OWNER}/markethawk" --body "🧠 **Refinement Pipeline** — Starting brainstorming and spec generation.

---
*Posted by MarketHawk Backlog Scheduler*" 2>/dev/null || true
    dispatch "Refine issue #${ISSUE}"
    DISPATCHED="Refine issue #${ISSUE}"
    REFINE_RUNNING=$((REFINE_RUNNING + 1))
  done < <(echo "$BACKLOG" | jq -c '.[]')

  # --- Priority 0.5: Refined items (plan generation) ---
  while IFS= read -r item; do
    [ -n "$DISPATCHED" ] && break
    ISSUE=$(get_issue_number "$item")
    if has_refine_skip_label "$item"; then continue; fi
    if is_issue_running "$ISSUE"; then continue; fi
    if [ "$REFINE_RUNNING" -ge "$REFINE_WIP_LIMIT" ]; then break; fi

    gh issue comment "$ISSUE" --repo "${OWNER}/markethawk" --body "📋 **Refinement Pipeline** — Starting plan generation and architect validation.

---
*Posted by MarketHawk Backlog Scheduler*" 2>/dev/null || true
    dispatch "Plan issue #${ISSUE}"
    DISPATCHED="Plan issue #${ISSUE}"
    REFINE_RUNNING=$((REFINE_RUNNING + 1))
  done < <(echo "$REFINED" | jq -c '.[]')

  # --- Priority 1: In Review items with new comments ---
  while IFS= read -r item; do
    [ -n "$DISPATCHED" ] && break
    ISSUE=$(get_issue_number "$item")
    if has_skip_label "$item"; then continue; fi

    NEW_COMMENTS=$(get_new_comments "$ISSUE")
    COMMENT_COUNT=$(echo "$NEW_COMMENTS" | jq 'length')
    if [ "$COMMENT_COUNT" -eq 0 ]; then continue; fi

    TITLE=$(echo "$item" | jq -r '.content.title')
    VERDICT=$(classify_comments "$ISSUE" "$TITLE" "$NEW_COMMENTS")

    case "$VERDICT" in
      MERGE)
        dispatch "Close issue #${ISSUE}"
        DISPATCHED="Close issue #${ISSUE}"
        ;;
      CONTINUE)
        if ! is_issue_running "$ISSUE"; then
          dispatch "Continue issue #${ISSUE}"
          DISPATCHED="Continue issue #${ISSUE}"
          reset_retry "$ISSUE"
        fi
        ;;
      SKIP) ;;
    esac
  done < <(echo "$IN_REVIEW" | jq -c '.[]')

  # --- Priority 2: Blocked items (retry) ---
  while IFS= read -r item; do
    [ -n "$DISPATCHED" ] && break
    ISSUE=$(get_issue_number "$item")
    if has_skip_label "$item"; then continue; fi
    if is_issue_running "$ISSUE"; then continue; fi

    RETRIES=$(get_retry_count "$ISSUE")
    if [ "$RETRIES" -ge "$MAX_RETRIES" ]; then continue; fi

    increment_retry "$ISSUE"
    dispatch "Fix issue #${ISSUE}"
    DISPATCHED="Fix issue #${ISSUE}"
  done < <(echo "$BLOCKED" | jq -c '.[]')

  # --- Priority 3: Ready items (new work) ---
  while IFS= read -r item; do
    [ -n "$DISPATCHED" ] && break
    ISSUE=$(get_issue_number "$item")
    if has_skip_label "$item"; then continue; fi
    if [ "$IN_PROGRESS_COUNT" -ge "$MAX_IN_PROGRESS" ]; then break; fi
    if [ "$IN_REVIEW_COUNT" -ge "$MAX_IN_REVIEW" ]; then break; fi
    if ! dependencies_met "$ISSUE" "$BOARD_ITEMS"; then continue; fi
    if is_issue_running "$ISSUE"; then continue; fi

    dispatch "Fix issue #${ISSUE}"
    DISPATCHED="Fix issue #${ISSUE}"
  done < <(echo "$READY" | jq -c '.[]')

  # --- Log cycle summary ---
  BUDGET=$(gh api rate_limit --jq '.resources.graphql | "\(.used)/\(.limit)"' 2>/dev/null) || BUDGET="?"
  if [ -n "$DISPATCHED" ]; then
    echo "[$(date -u +%FT%TZ)] backlog=${BACKLOG_COUNT} refined=${REFINED_COUNT} in_progress=${IN_PROGRESS_COUNT}/${MAX_IN_PROGRESS} in_review=${IN_REVIEW_COUNT}/${MAX_IN_REVIEW} refine_running=${REFINE_RUNNING}/${REFINE_WIP_LIMIT} dispatched=\"${DISPATCHED}\" graphql=${BUDGET}"
  else
    echo "[$(date -u +%FT%TZ)] backlog=${BACKLOG_COUNT} refined=${REFINED_COUNT} in_progress=${IN_PROGRESS_COUNT}/${MAX_IN_PROGRESS} in_review=${IN_REVIEW_COUNT}/${MAX_IN_REVIEW} refine_running=${REFINE_RUNNING}/${REFINE_WIP_LIMIT} skip=nothing_to_do graphql=${BUDGET}"
  fi

  sleep "$POLL_INTERVAL"
done
