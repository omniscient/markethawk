#!/usr/bin/env bash
set -euo pipefail

# --- Configuration ---
POLL_INTERVAL="${POLL_INTERVAL:-60}"
SKIP_LABELS="needs-discussion,epic"
MAX_RETRIES="${MAX_RETRIES:-3}"
SCHEDULER_STATE_DIR="${SCHEDULER_STATE_DIR:-/var/lib/dark-factory}"
STATE_FILE="${SCHEDULER_STATE_DIR}/scheduler-state.json"
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
REFINE_MAX_RETRIES="${REFINE_MAX_RETRIES:-3}"

# --- Validate required environment ---
if [ -z "${GH_TOKEN:-}" ]; then
  echo "ERROR: GH_TOKEN is not set. Add it to .archon/.env" >&2
  exit 1
fi
if [ -z "${CLAUDE_CODE_OAUTH_TOKEN:-}" ] && [ -z "${ANTHROPIC_API_KEY:-}" ]; then
  echo "ERROR: Set CLAUDE_CODE_OAUTH_TOKEN or ANTHROPIC_API_KEY in .archon/.env" >&2
  exit 1
fi

# Create state directory (named volume creates the mountpoint but not subdirectories).
mkdir -p "$SCHEDULER_STATE_DIR"

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

  # A comment counts as reviewer feedback only if it appears AFTER the last spec report
  # AND is not one of our own automated comments. The dark factory posts its cost report
  # after the spec on the success path (entrypoint.sh post_cost_report), and the scheduler
  # posts pipeline-status comments — none are feedback, so re-running the spec on them
  # loops the pipeline (issue #124: cost report -> spurious second spec). Match on
  # footer/marker, NOT author: every comment is authored by the same PAT account.
  local bot_re="Posted by MarketHawk Refinement Pipeline|Posted by MarketHawk Backlog Scheduler|Posted by MarketHawk Dark Factory|Updated by MarketHawk Dark Factory|dark-factory-cost-report"

  local has_human
  has_human=$(echo "$comments" | jq --arg marker "$report_marker" --arg bot "$bot_re" '
    (to_entries | map(select(.value.body | test($marker))) | last | .key // -1) as $ridx
    | if $ridx == -1 then false
      else (to_entries | any(.key > $ridx and (.value.body | test($bot) | not)))
      end')

  if [ "$has_human" = "true" ]; then echo "yes"; else echo "no"; fi
}

# --- Dispatch ---
# Returns the docker compose exit code. Callers MUST use `if dispatch ...; then` —
# a bare call under set -e exits the daemon on non-zero.
# --no-build prevents inline image builds; the startup probe ensures the image exists.
dispatch() {
  local command="$1"
  local exit_code=0
  echo "[$(date -u +%FT%TZ)] dispatch command=\"${command}\""
  docker compose -f /opt/dark-factory/docker-compose.yml --profile factory run \
    -d --rm --no-build dark-factory "$command" || exit_code=$?
  if [ "$exit_code" -ne 0 ]; then
    echo "[$(date -u +%FT%TZ)] dispatch_error command=\"${command}\" exit=${exit_code}" >&2
  fi
  return "$exit_code"
}

# --- Move an issue to a board status (used by the orphaned-in-progress sweep) ---
set_board_status() {
  local issue_num="$1"
  local option_id="$2"
  local item_id
  item_id=$(gh project item-list "$PROJECT_NUMBER" --owner "$OWNER" --format json --limit 200 2>/dev/null \
    | jq -r ".items[] | select(.content.number == $issue_num and .content.type == \"Issue\") | .id")
  if [ -n "$item_id" ]; then
    gh project item-edit --project-id "$PROJECT_ID" --id "$item_id" \
      --field-id "$STATUS_FIELD" --single-select-option-id "$option_id" >/dev/null 2>&1 || true
  fi
}

# --- PR lookup: open PR number for an issue's feature branch ("" if none) ---
# Matches the branch convention used throughout the workflow: feat/issue-<N>-<slug>.
# `--repo` is REQUIRED: the scheduler runs at /workspace (not a git checkout — the repo
# is mounted read-only at /workspace/project), so gh cannot infer the repo and a bare
# `gh pr list` fails with "not a git repository". Trailing `|| true` keeps a gh failure
# from aborting the loop under `set -e` (callers assign the result with $(...), which
# would otherwise propagate gh's non-zero exit).
get_pr_for_issue() {
  gh pr list --repo "${OWNER}/markethawk" --search "head:feat/issue-${1}-" --json number --jq '.[0].number // empty' 2>/dev/null || true
}

# --- CI status: JSON array of definitively-failing checks (bucket == "fail") for a PR ---
# Robust to gh's non-zero exit on failing/pending checks and to "no checks reported"
# (gh then prints EMPTY stdout): capture stdout (kept even on non-zero exit), require it
# to be a real JSON array via `jq -e` (empty/invalid input -> exit 4/2 -> fall back to []),
# then filter. `jq empty` is NOT enough — it succeeds on empty input (zero JSON values).
# Do NOT use $(cmd || echo '[]') — on a non-zero exit that appends [] after real JSON.
failing_checks_for_pr() {
  local pr_num="$1"
  local checks
  # --repo required for the same reason as get_pr_for_issue (scheduler runs outside a checkout).
  checks=$(gh pr checks "$pr_num" --repo "${OWNER}/markethawk" --json name,bucket,link 2>/dev/null) || true
  echo "$checks" | jq -e 'type == "array"' >/dev/null 2>&1 || checks='[]'
  echo "$checks" | jq -c '[.[] | select(.bucket == "fail")]'
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

# When sourced for testing (SCHEDULER_SOURCE_ONLY=1) stop here: the helper functions
# and constants above are now defined, but the startup probes and poll loop below must
# not run (they would call gh and block forever in `while true`).
if [ "${SCHEDULER_SOURCE_ONLY:-0}" = "1" ]; then
  return 0
fi

# --- Fetch WIP limits once at startup (cached until restart) ---
WIP_DATA=$(fetch_wip_limits)
MAX_IN_PROGRESS=$(get_column_limit "$WIP_DATA" "$STATUS_IN_PROGRESS")
MAX_IN_REVIEW=$(get_column_limit "$WIP_DATA" "$STATUS_IN_REVIEW")
echo "WIP limits: in_progress=${MAX_IN_PROGRESS} in_review=${MAX_IN_REVIEW}"

# --- Main loop ---
echo "Backlog scheduler started (poll every ${POLL_INTERVAL}s)"

while true; do
  DISPATCHED=""

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

  # --- Priority 0: In Review items with failing CI (gate red PRs out of review) ---
  # Runs on EVERY cycle, independent of the factory-concurrency guard below: a PR with
  # red CI must not sit in review (a human could approve/merge it) just because the
  # factory happens to be busy. This only sets board status + posts a comment (it never
  # dispatches a factory container), so it is safe to run while a factory run is active.
  # The branch-aware Blocked retry below later continues the existing PR branch and
  # re-runs validate (pytest) to fix the failures. Cheap, so we gate every red ticket
  # this cycle — no DISPATCHED/break.
  CI_BLOCKED=""   # space-padded list of issues gated this cycle (Priority 1 skips them)
  while IFS= read -r item; do
    ISSUE=$(get_issue_number "$item")
    if has_skip_label "$item"; then continue; fi

    PR_NUM=$(get_pr_for_issue "$ISSUE")
    [ -z "$PR_NUM" ] && continue

    FAILED=$(failing_checks_for_pr "$PR_NUM")
    FAIL_COUNT=$(echo "$FAILED" | jq 'length')
    [ "$FAIL_COUNT" -eq 0 ] && continue

    echo "[$(date -u +%FT%TZ)] ci_gate issue=#${ISSUE} pr=#${PR_NUM} failing=${FAIL_COUNT} action=move_to_blocked"
    set_board_status "$ISSUE" "$STATUS_BLOCKED"

    FAIL_LIST=$(echo "$FAILED" | jq -r '.[] | "- [\(.name)](\(.link))"')
    gh issue comment "$ISSUE" --repo "${OWNER}/markethawk" --body "## Dark Factory — CI Failing, Moved to Blocked

PR #${PR_NUM} has failing CI checks, so this ticket has been moved out of **In review** to **Blocked**. The factory will retry automatically, continue the existing PR branch, and attempt to fix the failures.

**Failing checks:**
${FAIL_LIST}

---
*Posted by MarketHawk Backlog Scheduler*" 2>/dev/null || true

    CI_BLOCKED="${CI_BLOCKED} ${ISSUE} "
  done < <(echo "$IN_REVIEW" | jq -c '.[]')

  # Guard: only one factory container at a time (Claude Max rate limit). Everything
  # below DISPATCHES factory work, so it waits for the current run; the CI gate above
  # has already run regardless of factory activity.
  FACTORY_RUNNING=$(count_factory_running)
  if [ "$FACTORY_RUNNING" -gt 0 ]; then
    echo "[$(date -u +%FT%TZ)] skip=factory_running count=${FACTORY_RUNNING}"
    sleep "$POLL_INTERVAL"
    continue
  fi

  # --- Sweep: recover orphaned "In progress" items ---
  # We only reach here when no factory container is running (FACTORY_RUNNING guard
  # above), so any issue still in "In progress" was abandoned mid-run. The usual
  # failure path (entrypoint on_failure -> Blocked) cannot fire for untrappable
  # deaths — host reboot, OOM/SIGKILL — so those issues would otherwise sit stuck
  # forever and silently consume a WIP slot. Route them into the Blocked retry path,
  # exactly what on_failure would have done. (Skip-labels let a human park an item.)
  while IFS= read -r item; do
    ISSUE=$(get_issue_number "$item")
    if has_skip_label "$item"; then continue; fi
    if is_issue_running "$ISSUE"; then continue; fi
    echo "[$(date -u +%FT%TZ)] sweep=orphaned_in_progress issue=#${ISSUE} action=move_to_blocked"
    set_board_status "$ISSUE" "$STATUS_BLOCKED"
    gh issue comment "$ISSUE" --repo "${OWNER}/markethawk" --body "## Dark Factory — Orphaned Run Recovered

This issue was left in **In progress** with no running factory container — the run died without its error handler executing (e.g. a host restart or OOM/SIGKILL). The scheduler has moved it to **Blocked** so it will be retried automatically.

---
*Posted by MarketHawk Backlog Scheduler*" 2>/dev/null || true
  done < <(echo "$IN_PROGRESS" | jq -c '.[]')

  # --- Priority 1: In Review items with new comments (unblock existing work) ---
  while IFS= read -r item; do
    [ -n "$DISPATCHED" ] && break
    ISSUE=$(get_issue_number "$item")
    if has_skip_label "$item"; then continue; fi
    case "$CI_BLOCKED" in *" $ISSUE "*) continue ;; esac   # gated to Blocked this cycle

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

  # --- Priority 2: Ready items (implement what's already refined+planned) ---
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

  # --- Priority 3: Blocked items (retry stuck work) ---
  while IFS= read -r item; do
    [ -n "$DISPATCHED" ] && break
    ISSUE=$(get_issue_number "$item")
    if has_skip_label "$item"; then continue; fi
    if is_issue_running "$ISSUE"; then continue; fi

    RETRIES=$(get_retry_count "$ISSUE")
    if [ "$RETRIES" -ge "$MAX_RETRIES" ]; then continue; fi

    increment_retry "$ISSUE"
    # Branch-aware: a blocked item that already has a PR (e.g. red CI gated above, or a
    # continue run that failed mid-way) must be CONTINUED to reuse the existing branch.
    # Dispatching "Fix" would start a fresh branch that collides with the PR on push.
    if [ -n "$(get_pr_for_issue "$ISSUE")" ]; then
      dispatch "Continue issue #${ISSUE}"
      DISPATCHED="Continue issue #${ISSUE}"
    else
      dispatch "Fix issue #${ISSUE}"
      DISPATCHED="Fix issue #${ISSUE}"
    fi
  done < <(echo "$BLOCKED" | jq -c '.[]')

  # --- Priority 4: Refined items (plan generation — advance refined work before pulling new backlog) ---
  while IFS= read -r item; do
    [ -n "$DISPATCHED" ] && break
    ISSUE=$(get_issue_number "$item")
    if has_refine_skip_label "$item"; then continue; fi
    if is_issue_running "$ISSUE"; then continue; fi
    if [ "$REFINE_RUNNING" -ge "$REFINE_WIP_LIMIT" ]; then break; fi

    RETRIES=$(get_retry_count "${ISSUE}:plan")
    if [ "$RETRIES" -ge "$REFINE_MAX_RETRIES" ]; then
      gh issue edit "$ISSUE" --repo "${OWNER}/markethawk" --add-label needs-discussion 2>/dev/null || true
      gh issue comment "$ISSUE" --repo "${OWNER}/markethawk" --body "## Refinement Pipeline — Retries Exhausted

The scheduler has attempted plan generation **${RETRIES} time(s)** and cannot recover automatically. The issue has been labelled \`needs-discussion\` to pause automation.

**To resume automation:**
1. Investigate the failure comments above.
2. Fix the root cause (update the issue body, fix a dependency, or resolve the blocking error).
3. Remove the \`needs-discussion\` label — the scheduler will resume automatically.

\`\`\`bash
# Or retry manually:
docker compose --profile factory run --rm dark-factory \"Plan issue #${ISSUE}\"
\`\`\`

---
*Posted by MarketHawk Backlog Scheduler*" 2>/dev/null || true
      continue
    fi

    increment_retry "${ISSUE}:plan"
    gh issue comment "$ISSUE" --repo "${OWNER}/markethawk" --body "📋 **Refinement Pipeline** — Starting plan generation and architect validation.

---
*Posted by MarketHawk Backlog Scheduler*" 2>/dev/null || true
    dispatch "Plan issue #${ISSUE}"
    DISPATCHED="Plan issue #${ISSUE}"
    REFINE_RUNNING=$((REFINE_RUNNING + 1))
  done < <(echo "$REFINED" | jq -c '.[]')

  # --- Priority 5: Backlog items (refinement — prepare future work) ---
  while IFS= read -r item; do
    [ -n "$DISPATCHED" ] && break
    ISSUE=$(get_issue_number "$item")

    # Handle spec-pending-review items first (before skip-label check would filter them)
    ITEM_LABELS=$(echo "$item" | jq -r '.labels[]?' 2>/dev/null)
    if echo "$ITEM_LABELS" | grep -qi "spec-pending-review"; then
      if ! is_issue_running "$ISSUE" && [ "$REFINE_RUNNING" -lt "$REFINE_WIP_LIMIT" ]; then
        HAS_NEW=$(has_new_comment_after_report "$ISSUE" "Posted by MarketHawk Refinement Pipeline")
        if [ "$HAS_NEW" = "yes" ]; then
          reset_retry "${ISSUE}:refine"
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

    RETRIES=$(get_retry_count "${ISSUE}:refine")
    if [ "$RETRIES" -ge "$REFINE_MAX_RETRIES" ]; then
      gh issue edit "$ISSUE" --repo "${OWNER}/markethawk" --add-label needs-discussion 2>/dev/null || true
      gh issue comment "$ISSUE" --repo "${OWNER}/markethawk" --body "## Refinement Pipeline — Retries Exhausted

The scheduler has attempted refinement **${RETRIES} time(s)** and cannot recover automatically. The issue has been labelled \`needs-discussion\` to pause automation.

**To resume automation:**
1. Investigate the failure comments above.
2. Fix the root cause (update the issue body, fix a dependency, or resolve the blocking error).
3. Remove the \`needs-discussion\` label — the scheduler will resume automatically.

\`\`\`bash
# Or retry manually:
docker compose --profile factory run --rm dark-factory \"Refine issue #${ISSUE}\"
\`\`\`

---
*Posted by MarketHawk Backlog Scheduler*" 2>/dev/null || true
      continue
    fi

    increment_retry "${ISSUE}:refine"
    gh issue comment "$ISSUE" --repo "${OWNER}/markethawk" --body "🧠 **Refinement Pipeline** — Starting brainstorming and spec generation.

---
*Posted by MarketHawk Backlog Scheduler*" 2>/dev/null || true
    dispatch "Refine issue #${ISSUE}"
    DISPATCHED="Refine issue #${ISSUE}"
    REFINE_RUNNING=$((REFINE_RUNNING + 1))
  done < <(echo "$BACKLOG" | jq -c '.[]')

  # --- Log cycle summary ---
  BUDGET=$(gh api rate_limit --jq '.resources.graphql | "\(.used)/\(.limit)"' 2>/dev/null) || BUDGET="?"
  if [ -n "$DISPATCHED" ]; then
    echo "[$(date -u +%FT%TZ)] backlog=${BACKLOG_COUNT} refined=${REFINED_COUNT} in_progress=${IN_PROGRESS_COUNT}/${MAX_IN_PROGRESS} in_review=${IN_REVIEW_COUNT}/${MAX_IN_REVIEW} refine_running=${REFINE_RUNNING}/${REFINE_WIP_LIMIT} dispatched=\"${DISPATCHED}\" graphql=${BUDGET}"
  else
    echo "[$(date -u +%FT%TZ)] backlog=${BACKLOG_COUNT} refined=${REFINED_COUNT} in_progress=${IN_PROGRESS_COUNT}/${MAX_IN_PROGRESS} in_review=${IN_REVIEW_COUNT}/${MAX_IN_REVIEW} refine_running=${REFINE_RUNNING}/${REFINE_WIP_LIMIT} skip=nothing_to_do graphql=${BUDGET}"
  fi

  sleep "$POLL_INTERVAL"
done
