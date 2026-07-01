#!/usr/bin/env bash
set -euo pipefail

# --- Configuration (non-policy infrastructure) ---
# ready-for-human marks a ticket a human has taken over; the factory must leave it alone
# everywhere (dispatch, retry, rescue, and the orphaned-in-progress sweep) — an In-progress
# ready-for-human ticket has no container because a HUMAN is on it, not because a run died.
SKIP_LABELS="needs-discussion,epic,ready-for-human"
SCHEDULER_STATE_DIR="${SCHEDULER_STATE_DIR:-/var/lib/dark-factory}"
STATE_FILE="${SCHEDULER_STATE_DIR}/scheduler-state.json"
RECHECK_STAMP_FILE="${SCHEDULER_STATE_DIR}/main-red-last-recheck"

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
FACTORY_CORE_CLI="${FACTORY_CORE_CLI:-/workspace/project/dark-factory/scripts/factory_core/cli.py}"

# Refinement pipeline (env-only: REFINE_MAX_RETRIES is not in config.yaml by design)
REFINE_SKIP_LABELS="needs-discussion,epic,spec-pending-review,plan-pending-review"
REFINE_MAX_RETRIES="${REFINE_MAX_RETRIES:-3}"

# --- Config YAML resolution ---
# Ordered search: bind-mounted repo (local dev / deletion test) → baked image (production).
CONFIG_YAML_PATHS=(
  "/workspace/project/.claude/skills/refinement/config.yaml"
  "/opt/refinement-skills/config.yaml"
)

resolve_config_yaml() {
  local p
  for p in "${CONFIG_YAML_PATHS[@]}"; do
    [ -f "$p" ] && echo "$p" && return 0
  done
  echo "ERROR: config.yaml not found — searched: ${CONFIG_YAML_PATHS[*]}" >&2
  return 1
}

# Read all policy knobs from config.yaml; log when an env var overrides the config value.
# Must be called in the main exec path (after SCHEDULER_SOURCE_ONLY guard) — not at source
# time — so test sourcing never triggers config resolution.
read_config() {
  local cfg
  cfg=$(resolve_config_yaml) || { echo "FATAL: cannot read config.yaml" >&2; exit 1; }

  _set_cfg() {
    local var="$1" yq_expr="$2"
    local cfg_val
    cfg_val=$(yq "$yq_expr" "$cfg" 2>/dev/null || true)
    [ "${cfg_val:-null}" = "null" ] && cfg_val=""
    # ${!var+x} expands to "x" if var is set (even empty), empty if unset — safe under set -u
    if [ -n "${!var+x}" ]; then
      local env_val="${!var}"
      if [ "$env_val" != "$cfg_val" ]; then
        echo "[config] ${var}=${env_val} (env override; config has '${cfg_val}')" >&2
      fi
      # Keep existing env value
    else
      export "${var}=${cfg_val}"
    fi
  }

  _set_cfg POLL_INTERVAL              '.scheduler.poll_interval'
  _set_cfg MAX_RETRIES                '.scheduler.max_retries'
  _set_cfg RATE_LIMIT_FLOOR           '.scheduler.rate_limit_floor'
  _set_cfg FACTORY_WIP_LIMIT          '.scheduler.factory_wip_limit'
  _set_cfg MAIN_RED_RECHECK_ENABLED   '.scheduler.main_red_recheck_enabled'
  _set_cfg MAIN_RED_RECHECK_MINUTES   '.scheduler.main_red_recheck_minutes'
  _set_cfg BLOCKED_RESCUE_ENABLED     '.scheduler.blocked_rescue_enabled'
  _set_cfg REFINE_WIP_LIMIT           '.refine.wip_limit'
  _set_cfg DIRECT_TO_PR_LABEL         '.direct_to_pr.label'
  _set_cfg SPEC_GRACE_MINUTES         '.direct_to_pr.spec_grace_minutes'
  _set_cfg PLAN_GRACE_MINUTES         '.direct_to_pr.plan_grace_minutes'
  _set_cfg CONFLICT_RESOLUTION_ENABLED '.conflict_resolution.enabled'
  _set_cfg DISPATCH_CEILING_ENABLED   '.dispatch_ceiling.enabled'
  _set_cfg ABOVE_CEILING_LABEL        '.dispatch_ceiling.label'
  _set_cfg ABOVE_CEILING_KEYWORDS     '.dispatch_ceiling.keywords'
  _set_cfg EPIC_AUTOPILOT_ENABLED          '.epic_autopilot.enabled'
  _set_cfg EPIC_AUTOPILOT_MODEL            '.epic_autopilot.model'
  _set_cfg EPIC_AUTOPILOT_DAILY_CAP        '.epic_autopilot.daily_cap'
  _set_cfg EPIC_AUTOPILOT_CONFIDENCE_FLOOR '.epic_autopilot.confidence_floor'
  _set_cfg EPIC_AUTOPILOT_OPT_OUT_LABEL    '.epic_autopilot.opt_out_label'
  _set_cfg EPIC_AUTOPILOT_HOLD_TTL_HOURS    '.epic_autopilot.hold_ttl_hours'
  _set_cfg EPIC_AUTOPILOT_SIZE_CEILING      '.epic_autopilot.size_ceiling'
  _set_cfg EPIC_AUTOPILOT_START_EPICS       '.epic_autopilot.start_epics'
  _set_cfg EPIC_AUTOPILOT_SENSITIVE_KEYWORDS '.epic_autopilot.sensitive_keywords'
  _set_cfg MAIN_RED_AUTOFIX_ENABLED        '.main_red_autofix.enabled'
  _set_cfg MAIN_RED_AUTOFIX_MODEL          '.main_red_autofix.model'
  _set_cfg MAIN_RED_AUTOFIX_MAX_ATTEMPTS   '.main_red_autofix.max_attempts'
  _set_cfg MAIN_RED_AUTOFIX_THROTTLE_MIN   '.main_red_autofix.throttle_minutes'

  echo "[config] loaded from ${cfg}"
}

# --- Validate required environment ---
if [ -z "${GH_TOKEN:-}" ]; then
  echo "ERROR: GH_TOKEN is not set. Add it to .archon/.env" >&2
  exit 1
fi
if [ -z "${CLAUDE_CODE_OAUTH_TOKEN:-}" ] && [ -z "${ANTHROPIC_API_KEY:-}" ]; then
  echo "ERROR: Set CLAUDE_CODE_OAUTH_TOKEN or ANTHROPIC_API_KEY in .archon/.env" >&2
  exit 1
fi

# --- Provision the dispatch env file ---
# The dispatch runs `docker compose -f /opt/dark-factory/docker-compose.yml run dark-factory`,
# whose service declares `env_file: .archon/.env (required: true)` — which the compose CLI
# resolves to /opt/dark-factory/.archon/.env relative to the baked compose file. Secrets are
# never baked into the image, so materialize that file at startup from the bind-mounted repo.
# (Regressed by #104/#155 when docker-compose.yml moved to the required env_file format.)
if [ -f /workspace/project/.archon/.env ]; then
  mkdir -p /opt/dark-factory/.archon
  cp /workspace/project/.archon/.env /opt/dark-factory/.archon/.env
  echo "Provisioned dispatch env file at /opt/dark-factory/.archon/.env from bind mount"
else
  echo "WARNING: /workspace/project/.archon/.env not found — dispatched runs will fail env_file resolution" >&2
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

# --- Retry tracking (thin adapters — logic lives in factory_core/breaker.py) ---
get_retry_count() {
  STATE_FILE="$STATE_FILE" python3 "$FACTORY_CORE_CLI" breaker-get --key "$1"
}

increment_retry() {
  STATE_FILE="$STATE_FILE" python3 "$FACTORY_CORE_CLI" breaker-incr --key "$1"
}

reset_retry() {
  STATE_FILE="$STATE_FILE" python3 "$FACTORY_CORE_CLI" breaker-reset --key "$1"
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

# True when the running factory-container count ($1) has reached FACTORY_WIP_LIMIT.
factory_at_capacity() {
  [ "$1" -ge "$FACTORY_WIP_LIMIT" ]
}

# True when a "Recheck main" container is already running (dedupe — recheck runs
# carry no "#N", so is_issue_running cannot see them).
is_recheck_running() {
  docker ps --no-trunc --format '{{.Command}}' 2>/dev/null | grep -q 'Recheck main' && return 0
  return 1
}

# True when the recheck throttle window has elapsed (or no recheck happened yet).
# Throttled via the stamp file's mtime — survives scheduler restarts on the state volume.
recheck_due() {
  [ -f "$RECHECK_STAMP_FILE" ] || return 0
  local last now
  last=$(stat -c %Y "$RECHECK_STAMP_FILE" 2>/dev/null || echo 0)
  now=$(date +%s)
  [ $(( now - last )) -ge $(( MAIN_RED_RECHECK_MINUTES * 60 )) ]
}

# --- Main-red self-clear: throttled "Recheck main" dispatch (#365) ---
# The main-is-red sentinel pauses implementation dispatches, but the only code that
# CLEARS it is _smoke_on_green() inside a dispatched container — and those dispatches
# are exactly what the sentinel blocks. Without this, the latch is one-way: main goes
# green and the factory stays paused until a human comments on an in-review PR.
# Callers guarantee a free factory slot (runs after the capacity guard).
main_red_recheck_check() {
  [ "$MAIN_RED_RECHECK_ENABLED" = "true" ] || return 0
  is_recheck_running && return 0
  recheck_due || return 0
  if dispatch "Recheck main"; then
    DISPATCHED="Recheck main"
    touch "$RECHECK_STAMP_FILE"
    echo "[$(date -u +%FT%TZ)] main_red_recheck=dispatched interval=${MAIN_RED_RECHECK_MINUTES}m"
  fi
}

FIXER_STAMP_FILE="${SCHEDULER_STATE_DIR}/main-red-fixer-last-run"

is_fixer_running() {
  docker ps --no-trunc --format '{{.Command}}' 2>/dev/null | grep -q 'Fix main' && return 0
  return 1
}

fixer_due() {
  [ -f "$FIXER_STAMP_FILE" ] || return 0
  local last now
  last=$(stat -c %Y "$FIXER_STAMP_FILE" 2>/dev/null || echo 0)
  now=$(date +%s)
  [ $(( now - last )) -ge $(( ${MAIN_RED_AUTOFIX_THROTTLE_MIN:-15} * 60 )) ]
}

main_red_fixer_check() {
  [ "${MAIN_RED_AUTOFIX_ENABLED:-false}" = "true" ] || return 0
  is_fixer_running && return 0
  fixer_due || return 0
  if dispatch "Fix main"; then
    DISPATCHED="Fix main"
    touch "$FIXER_STAMP_FILE"
    echo "[$(date -u +%FT%TZ)] main_red_fixer=dispatched"
  fi
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

has_opt_in_refine_label() {
  local item="$1"
  local labels
  labels=$(echo "$item" | jq -r '.labels[]?' 2>/dev/null)
  echo "$labels" | grep -qi "ready-for-agent"
}

has_direct_to_pr_label() {
  local item="$1"
  echo "$item" | jq -r '.labels[]?' 2>/dev/null | grep -qi "$DIRECT_TO_PR_LABEL"
}

# --- Dispatch ceiling classification (#339) ---
# Returns "S", "M", "L", or "" from the item's labels
get_size_label() {
  echo "$1" | jq -r '.labels[]?' 2>/dev/null | grep -oiE 'size: ?(xl|[sml])' | awk '{print toupper($NF)}' | head -1
}

# True (returns 0) if item is above the dispatch ceiling: size XL always, or size M
# when the title matches an ABOVE_CEILING_KEYWORDS pattern (escalation only — the
# keyword heuristic never demotes).
is_above_ceiling() {
  local item="$1" title size
  title=$(echo "$item" | jq -r '.content.title // ""' 2>/dev/null)
  size=$(get_size_label "$item")
  case "$size" in
    XL) return 0 ;;
    M) echo "$title" | grep -qiE "${ABOVE_CEILING_KEYWORDS}" && return 0 || return 1 ;;
    *) return 1 ;;
  esac
}

# True if item already carries the above-ceiling label (board-fetch snapshot)
has_above_ceiling_label() {
  echo "$1" | jq -r '.labels[]?' 2>/dev/null | grep -qi "^${ABOVE_CEILING_LABEL}$"
}

# True if item is S- or L-size, or has no size label (unlabelled is treated as S per spec)
is_below_ceiling() {
  local size
  size=$(get_size_label "$1")
  case "$size" in S|L|"") return 0 ;; *) return 1 ;; esac
}

# Returns minutes elapsed since the last comment matching $marker_re on the given issue.
# Returns "" if no matching comment exists or if the timestamp cannot be parsed.
elapsed_minutes_since_marker() {
  local issue_num="$1"
  local marker_re="$2"
  local comments
  comments=$(gh issue view "$issue_num" --repo "${OWNER}/markethawk" \
    --json comments -q '.comments' 2>/dev/null) || { echo ""; return; }
  local created_at
  created_at=$(echo "$comments" | jq -r --arg m "$marker_re" \
    '[.[] | select(.body | test($m))] | last | .createdAt // ""')
  [ -z "$created_at" ] && { echo ""; return; }
  local marker_epoch now_epoch
  marker_epoch=$(date -u -d "$created_at" +%s 2>/dev/null) || { echo ""; return; }
  now_epoch=$(date -u +%s)
  echo $(( (now_epoch - marker_epoch) / 60 ))
}

spec_advance_check() {
  local issue_num="$1"
  local item="$2"
  has_skip_label "$item" && return 0
  local has_new
  has_new=$(has_new_comment_after_report "$issue_num" "Posted by MarketHawk Refinement Pipeline")
  if [ "$has_new" = "yes" ]; then
    reset_retry "${issue_num}:refine"
    gh issue edit "$issue_num" --repo "${OWNER}/markethawk" \
      --remove-label "spec-pending-review" 2>/dev/null || true
    gh issue comment "$issue_num" --repo "${OWNER}/markethawk" --body \
"🔄 **Refinement Pipeline** — Re-running with new feedback.

---
*Posted by MarketHawk Backlog Scheduler*" 2>/dev/null || true
    if dispatch "Refine issue #${issue_num}"; then
      DISPATCHED="Refine issue #${issue_num}"
      REFINE_RUNNING=$((REFINE_RUNNING + 1))
    fi
    return 0
  fi
  if has_direct_to_pr_label "$item"; then
    local elapsed
    elapsed=$(elapsed_minutes_since_marker "$issue_num" "Posted by MarketHawk Refinement Pipeline")
    if [ -n "$elapsed" ] && [ "$elapsed" -ge "$SPEC_GRACE_MINUTES" ]; then
      echo "[$(date -u +%FT%TZ)] spec_auto_advance issue=#${issue_num} elapsed=${elapsed}m grace=${SPEC_GRACE_MINUTES}m action=advance_to_refined"
      gh issue edit "$issue_num" --repo "${OWNER}/markethawk" \
        --remove-label "spec-pending-review" 2>/dev/null || true
      set_board_status "$issue_num" "$STATUS_REFINED" || true
    else
      echo "[$(date -u +%FT%TZ)] spec_grace_window issue=#${issue_num} elapsed=${elapsed:-unknown}m grace=${SPEC_GRACE_MINUTES}m action=waiting"
    fi
  fi
}

plan_advance_check() {
  local issue_num="$1"
  local item="$2"
  has_skip_label "$item" && return 0
  local has_new
  has_new=$(has_new_comment_after_report "$issue_num" "Posted by MarketHawk Refinement Pipeline")
  if [ "$has_new" = "yes" ]; then
    reset_retry "${issue_num}:plan"
    gh issue edit "$issue_num" --repo "${OWNER}/markethawk" \
      --remove-label "plan-pending-review" 2>/dev/null || true
    gh issue comment "$issue_num" --repo "${OWNER}/markethawk" --body \
"🔄 **Refinement Pipeline** — Re-running plan with new feedback.

---
*Posted by MarketHawk Backlog Scheduler*" 2>/dev/null || true
    if dispatch "Plan issue #${issue_num}"; then
      DISPATCHED="Plan issue #${issue_num}"
      REFINE_RUNNING=$((REFINE_RUNNING + 1))
    fi
    return 0
  fi
  # Dispatch ceiling (#339): timer-based advance applies only to S-size items. M and L
  # require explicit human plan approval; the human-feedback path above is untouched.
  if [ "${DISPATCH_CEILING_ENABLED:-true}" = "true" ] && ! is_below_ceiling "$item"; then
    return 0
  fi
  if has_direct_to_pr_label "$item"; then
    local elapsed
    elapsed=$(elapsed_minutes_since_marker "$issue_num" "Posted by MarketHawk Refinement Pipeline")
    if [ -n "$elapsed" ] && [ "$elapsed" -ge "$PLAN_GRACE_MINUTES" ]; then
      echo "[$(date -u +%FT%TZ)] plan_auto_advance issue=#${issue_num} elapsed=${elapsed}m grace=${PLAN_GRACE_MINUTES}m action=advance_to_ready"
      gh issue edit "$issue_num" --repo "${OWNER}/markethawk" \
        --remove-label "plan-pending-review" 2>/dev/null || true
      set_board_status "$issue_num" "$STATUS_READY" || true
    else
      echo "[$(date -u +%FT%TZ)] plan_grace_window issue=#${issue_num} elapsed=${elapsed:-unknown}m grace=${PLAN_GRACE_MINUTES}m action=waiting"
    fi
  fi
}

end_gate_check() {
  local issue_num="$1"
  local item="$2"
  has_direct_to_pr_label "$item" || return 1
  local pr_num
  pr_num=$(get_pr_for_issue "$issue_num")
  [ -z "$pr_num" ] && return 1
  local review_state
  review_state=$(gh pr view "$pr_num" --repo "${OWNER}/markethawk" --json reviews \
    --jq '[.reviews[] | select(.state == "APPROVED" or .state == "CHANGES_REQUESTED")] | last | .state // ""' \
    2>/dev/null) || review_state=""
  case "$review_state" in
    APPROVED)
      echo "[$(date -u +%FT%TZ)] end_gate issue=#${issue_num} pr=#${pr_num} state=APPROVED action=Close"
      if dispatch "Close issue #${issue_num}"; then
        DISPATCHED="Close issue #${issue_num}"
      fi
      return 0
      ;;
    CHANGES_REQUESTED)
      echo "[$(date -u +%FT%TZ)] end_gate issue=#${issue_num} pr=#${pr_num} state=CHANGES_REQUESTED action=Continue"
      if ! is_issue_running "$issue_num"; then
        if dispatch "Continue issue #${issue_num}"; then
          DISPATCHED="Continue issue #${issue_num}"
          reset_retry "$issue_num"
        fi
      fi
      return 0
      ;;
    *)
      return 1
      ;;
  esac
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
  local bot_re="Posted by MarketHawk Refinement Pipeline|Posted by MarketHawk Backlog Scheduler|Posted by MarketHawk Dark Factory|Updated by MarketHawk Dark Factory|dark-factory-cost-report|Posted by MarketHawk Epic Autopilot"

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
# `docker compose run` never builds inline (it has no --build by default); the startup
# probe ensures the image exists. Note: --no-build is NOT a valid flag for `run` (it is
# `up`/`create`-only) and passing it makes every dispatch fail with "unknown flag".
dispatch() {
  local command="$1"
  local exit_code=0
  echo "[$(date -u +%FT%TZ)] dispatch command=\"${command}\""
  docker compose -f /opt/dark-factory/docker-compose.yml --profile factory run \
    -d --rm dark-factory "$command" || exit_code=$?
  if [ "$exit_code" -ne 0 ]; then
    echo "[$(date -u +%FT%TZ)] dispatch_error command=\"${command}\" exit=${exit_code}" >&2
  fi
  return "$exit_code"
}

# --- Move an issue to a board status (thin adapter — logic lives in factory_core/board.py) ---
set_board_status() {
  python3 "$FACTORY_CORE_CLI" board-move --issue "$1" --status "$2"
}

# --- Universal circuit-breaker (thin adapter — logic lives in factory_core/breaker.py) ---
# Usage: trip_to_blocked <issue_num> <phase: implement|plan|refine|resolve> <reason>
trip_to_blocked() {
  local issue_num="$1"
  local phase="$2"
  local reason="${3:-repeated dispatch failure}"
  echo "[$(date -u +%FT%TZ)] circuit_breaker=trip issue=#${issue_num} phase=${phase}"
  STATE_FILE="$STATE_FILE" python3 "$FACTORY_CORE_CLI" \
    breaker-trip --issue "$issue_num" --phase "$phase" --reason "$reason"
}

# --- Mergeable status for a PR: CONFLICTING, MERGEABLE, or UNKNOWN ---
# UNKNOWN means GitHub hasn't finished computing mergeability — callers must skip.
# --repo is required because the scheduler runs outside a git checkout.
check_pr_mergeable() {
  local pr_num="$1"
  local result
  result=$(gh pr view "$pr_num" --repo "${OWNER}/markethawk" --json mergeable \
    --jq '.mergeable' 2>/dev/null) || true
  echo "${result:-UNKNOWN}"
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
  local cursor="" has_next="true" nodes="[]"
  while [ "$has_next" = "true" ]; do
    local after_arg="" raw
    [ -n "$cursor" ] && after_arg=', after: "'"$cursor"'"'
    raw=$(gh api graphql -f query='
      query {
        node(id: "'"$PROJECT_ID"'") {
          ... on ProjectV2 {
            items(first: 100'"$after_arg"') {
              pageInfo { hasNextPage endCursor }
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
    nodes=$(echo "$raw" | jq -c --argjson nodes "$nodes" '$nodes + (.data.node.items.nodes // [])')
    has_next=$(echo "$raw" | jq -r '.data.node.items.pageInfo.hasNextPage // false')
    cursor=$(echo "$raw" | jq -r '.data.node.items.pageInfo.endCursor // ""')
    if [ "$has_next" = "true" ] && [ -z "$cursor" ]; then
      echo "ERROR: GitHub ProjectV2 pageInfo indicated another page but returned no cursor" >&2
      return 1
    fi
  done
  echo "$nodes" | jq '{items: [.[]
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
    if [ -z "$dep_status" ]; then
      # Dep not found on board (archived or beyond fetch window) — fall back to issue state
      local dep_state
      local dep_gh_exit=0
      dep_state=$(gh issue view "$dep_num" --repo "${OWNER}/markethawk" --json state -q '.state' 2>/dev/null) || dep_gh_exit=$?
      if [ "$dep_state" = "CLOSED" ]; then
        echo "[$(date -u +%FT%TZ)] dep_gate issue=#${issue_num} dep=#${dep_num} resolved=closed_off_board"
        continue
      fi
      if [ "$dep_gh_exit" -ne 0 ] || [ -z "$dep_state" ]; then
        echo "[$(date -u +%FT%TZ)] dep_gate issue=#${issue_num} dep=#${dep_num} blocked_by=#${dep_num} dep_status=unknown"
      else
        echo "[$(date -u +%FT%TZ)] dep_gate issue=#${issue_num} dep=#${dep_num} blocked_by=#${dep_num} dep_status=off_board"
      fi
      return 1
    fi
    if [ "$dep_status" != "Done" ]; then
      echo "[$(date -u +%FT%TZ)] dep_gate issue=#${issue_num} blocked_by=#${dep_num} dep_status=${dep_status}"
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

# --- Load policy knobs from config.yaml (env overrides logged when active) ---
read_config

# --- ERR trap: log unhandled exits for post-mortem diagnosis ---
# dispatch() callers are all guarded with `if dispatch ...; then`; this backstop
# identifies any command that slips through. The scheduler exits on unhandled ERR
# (set -e); durable retry state on the named volume ensures circuit-breakers
# accumulate correctly across the restart-unless-stopped restart cycle.
_sched_err_trap() {
  local code=$? line=${BASH_LINENO[0]}
  echo "[$(date -u +%FT%TZ)] SCHED_UNHANDLED_ERR line=${line} exit=${code}" >&2
}
trap '_sched_err_trap' ERR

# --- Fetch WIP limits once at startup (cached until restart) ---
WIP_DATA=$(fetch_wip_limits)
MAX_IN_PROGRESS=$(get_column_limit "$WIP_DATA" "$STATUS_IN_PROGRESS")
MAX_IN_REVIEW=$(get_column_limit "$WIP_DATA" "$STATUS_IN_REVIEW")
echo "WIP limits: in_progress=${MAX_IN_PROGRESS} in_review=${MAX_IN_REVIEW} factory=${FACTORY_WIP_LIMIT}"

# --- Startup probe: verify factory image is available locally ---
# `docker compose run` does not build inline by default, so a missing image causes every
# dispatch to fail immediately. Exit here with actionable instructions rather than entering a loop
# where every dispatch fails and the circuit-breaker trips in N cycles.
FACTORY_IMAGE="${FACTORY_IMAGE:-ghcr.io/omniscient/markethawk-dark-factory:${IMAGE_TAG:-latest}}"
echo "[$(date -u +%FT%TZ)] probe=image_check image=${FACTORY_IMAGE}"
if ! docker image inspect "$FACTORY_IMAGE" >/dev/null 2>&1; then
  echo "[$(date -u +%FT%TZ)] probe=image_missing — attempting docker pull"
  if ! docker pull "$FACTORY_IMAGE"; then
    echo "[$(date -u +%FT%TZ)] FATAL: image unavailable and pull failed." >&2
    echo "  Fix GHCR auth (docker login ghcr.io) or build the image locally:" >&2
    echo "  docker compose --profile factory build dark-factory" >&2
    echo "  Then restart the scheduler." >&2
    # Sleep before exit to throttle restart-unless-stopped restart loops
    sleep 60
    exit 1
  fi
  echo "[$(date -u +%FT%TZ)] probe=image_pulled image=${FACTORY_IMAGE}"
else
  echo "[$(date -u +%FT%TZ)] probe=image_ok image=${FACTORY_IMAGE}"
fi

# --- Startup: warn if stale preview containers exist (non-blocking) ---
STALE_PREVIEW_WARN_COUNT="${STALE_PREVIEW_WARN_COUNT:-3}"
# Validate that STALE_PREVIEW_WARN_COUNT is numeric; reset to default if not to avoid
# integer comparison errors under set -euo pipefail.
if ! [[ "$STALE_PREVIEW_WARN_COUNT" =~ ^[0-9]+$ ]]; then
  echo "[$(date -u +%FT%TZ)] WARNING: STALE_PREVIEW_WARN_COUNT='${STALE_PREVIEW_WARN_COUNT}' is not a non-negative integer; resetting to default 3." >&2
  STALE_PREVIEW_WARN_COUNT=3
fi
STALE_COUNT=$(docker ps -a --filter "name=mh-preview-" --format '{{.Names}}' 2>/dev/null | wc -l | tr -d ' ')
if [ "$STALE_COUNT" -gt "$STALE_PREVIEW_WARN_COUNT" ]; then
  echo "[$(date -u +%FT%TZ)] WARNING: $STALE_COUNT stale mh-preview-* containers found (threshold: ${STALE_PREVIEW_WARN_COUNT}). Run 'docker ps -a --filter name=mh-preview-' to inspect and clean up." >&2
fi

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

  # --- Priority 0.6: rescue Blocked items whose PR is already green + mergeable ---
  # Inverse of Priority 0. A ticket can sit in Blocked (CI gate, circuit-breaker trip,
  # orphaned-run sweep) while its PR is actually green and conflict-free. The Priority 3
  # retry loop below would re-dispatch "Continue" on it — re-running the whole pipeline,
  # burning the Max session window, re-hitting the same gate — until the retry counter
  # exhausts and trip_to_blocked parks it FOREVER with a mergeable PR stranded. Instead,
  # promote it to In review so the normal merge flow (human / "Close issue #N") takes it.
  # Dispatch-free (only sets board status + marks the PR ready + comments), so it runs
  # every cycle regardless of factory capacity, like Priority 0. RESCUED is consumed by
  # Priority 3 so a just-rescued issue is not retried in the same cycle.
  RESCUED=""
  if [ "${BLOCKED_RESCUE_ENABLED:-true}" = "true" ]; then
    while IFS= read -r item; do
      ISSUE=$(get_issue_number "$item")
      if has_skip_label "$item"; then continue; fi
      # Above-ceiling items are parked in Blocked by design (#339), not failed.
      if has_above_ceiling_label "$item"; then continue; fi
      if is_issue_running "$ISSUE"; then continue; fi
      RESCUE_OUT=$(python3 "$FACTORY_CORE_CLI" rescue-blocked --issue "$ISSUE" 2>/dev/null) || true
      if [ "$RESCUE_OUT" = "rescued" ]; then
        echo "[$(date -u +%FT%TZ)] blocked_rescue issue=#${ISSUE} action=promoted_to_in_review"
        RESCUED="${RESCUED} ${ISSUE} "
        reset_retry "$ISSUE" || true
      fi
    done < <(echo "$BLOCKED" | jq -c '.[]')
  fi

  # Guard: cap concurrent factory containers at FACTORY_WIP_LIMIT (Claude Max 5h-window
  # burn scales with concurrency — default 1, override in .archon/.env). Everything
  # below DISPATCHES factory work, so it waits for a free slot; the CI gate above has
  # already run regardless of factory activity.
  FACTORY_RUNNING=$(count_factory_running)
  if factory_at_capacity "$FACTORY_RUNNING"; then
    echo "[$(date -u +%FT%TZ)] skip=factory_at_capacity running=${FACTORY_RUNNING}/${FACTORY_WIP_LIMIT}"
    sleep "$POLL_INTERVAL"
    continue
  fi

  # --- Sweep: recover orphaned "In progress" items ---
  # We reach here whenever a factory slot is free (capacity guard above). An issue in
  # "In progress" whose container is alive is skipped by is_issue_running below; one
  # with no container was abandoned mid-run. The usual
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

  # --- Read main-is-red sentinel (written by smoke_gate.sh in dispatched containers) ---
  # When present, skip Priority 1.5/2/3 (implementation dispatches); 1/4/5 continue,
  # and a throttled "Recheck main" run gives the gate a chance to self-clear (#365).
  MAIN_IS_RED=false
  [ -f "${SCHEDULER_STATE_DIR}/main-is-red" ] && MAIN_IS_RED=true
  if [ "$MAIN_IS_RED" = "true" ]; then
    echo "[$(date -u +%FT%TZ)] main_red_gate=active action=skip_implement_dispatch"
    main_red_recheck_check
    main_red_fixer_check
  fi

  # --- Priority 1.5: In Review items with merge conflicts (proactive auto-resolve) ---
  # Runs every cycle after the factory guard. Scans in-review PRs for GitHub's
  # CONFLICTING mergeability state and dispatches a deconflict run before any
  # human comments are processed. Honors SKIP_LABELS, CI_BLOCKED, and is_issue_running.
  # UNKNOWN is skipped — GitHub hasn't computed mergeability yet.
  if [ "$MAIN_IS_RED" = "true" ]; then
    echo "[$(date -u +%FT%TZ)] main_red_gate=skip_deconflict"
  elif [ "${CONFLICT_RESOLUTION_ENABLED:-true}" = "true" ]; then
    while IFS= read -r item; do
      [ -n "$DISPATCHED" ] && break
      ISSUE=$(get_issue_number "$item")
      if has_skip_label "$item"; then continue; fi
      case "$CI_BLOCKED" in *" $ISSUE "*) continue ;; esac
      if is_issue_running "$ISSUE"; then continue; fi

      RETRIES=$(get_retry_count "${ISSUE}:resolve")
      if [ "$RETRIES" -ge "$MAX_RETRIES" ]; then
        trip_to_blocked "$ISSUE" "resolve" "retry limit of ${MAX_RETRIES} reached for conflict resolution"
        continue
      fi

      PR_NUM=$(get_pr_for_issue "$ISSUE")
      [ -z "$PR_NUM" ] && continue

      MERGEABLE=$(check_pr_mergeable "$PR_NUM")
      case "$MERGEABLE" in
        CONFLICTING)
          echo "[$(date -u +%FT%TZ)] conflict_gate issue=#${ISSUE} pr=#${PR_NUM} mergeable=CONFLICTING action=dispatch_deconflict"
          increment_retry "${ISSUE}:resolve" || true
          if dispatch "Deconflict issue #${ISSUE}"; then
            DISPATCHED="Deconflict issue #${ISSUE}"
          fi
          ;;
        UNKNOWN)
          echo "[$(date -u +%FT%TZ)] conflict_gate issue=#${ISSUE} pr=#${PR_NUM} mergeable=UNKNOWN action=skip"
          ;;
      esac
    done < <(echo "$IN_REVIEW" | jq -c '.[]')
  fi

  # --- Priority 1: In Review items with new comments (unblock existing work) ---
  while IFS= read -r item; do
    [ -n "$DISPATCHED" ] && break
    ISSUE=$(get_issue_number "$item")
    if has_skip_label "$item"; then continue; fi
    case "$CI_BLOCKED" in *" $ISSUE "*) continue ;; esac   # gated to Blocked this cycle

    if end_gate_check "$ISSUE" "$item"; then continue; fi

    NEW_COMMENTS=$(get_new_comments "$ISSUE")
    COMMENT_COUNT=$(echo "$NEW_COMMENTS" | jq 'length')
    if [ "$COMMENT_COUNT" -eq 0 ]; then continue; fi

    TITLE=$(echo "$item" | jq -r '.content.title')
    VERDICT=$(classify_comments "$ISSUE" "$TITLE" "$NEW_COMMENTS")

    case "$VERDICT" in
      MERGE)
        if dispatch "Close issue #${ISSUE}"; then
          DISPATCHED="Close issue #${ISSUE}"
        fi
        ;;
      CONTINUE)
        if ! is_issue_running "$ISSUE"; then
          if dispatch "Continue issue #${ISSUE}"; then
            DISPATCHED="Continue issue #${ISSUE}"
            reset_retry "$ISSUE"
          fi
        fi
        ;;
      SKIP) ;;
    esac
  done < <(echo "$IN_REVIEW" | jq -c '.[]')

  # --- Priority 2: Ready items (implement what's already refined+planned) ---
  if [ "$MAIN_IS_RED" = "true" ]; then
    echo "[$(date -u +%FT%TZ)] main_red_gate=skip_implement"
  else
    while IFS= read -r item; do
      [ -n "$DISPATCHED" ] && break
      ISSUE=$(get_issue_number "$item")
      if has_skip_label "$item"; then continue; fi
      if [ "$IN_PROGRESS_COUNT" -ge "$MAX_IN_PROGRESS" ]; then break; fi
      if [ "$IN_REVIEW_COUNT" -ge "$MAX_IN_REVIEW" ]; then break; fi
      if ! dependencies_met "$ISSUE" "$BOARD_ITEMS"; then continue; fi
      if is_issue_running "$ISSUE"; then continue; fi

      # Dispatch ceiling (#339): park above-ceiling work for human pairing. The label
      # check stops the comment/board-move from repeating every poll cycle — the label
      # persists and comes back in the next fetch_board_items snapshot.
      if [ "${DISPATCH_CEILING_ENABLED:-true}" = "true" ] && is_above_ceiling "$item"; then
        if ! has_above_ceiling_label "$item"; then
          echo "[$(date -u +%FT%TZ)] ceiling_gate issue=#${ISSUE} action=above_ceiling_blocked"
          gh issue edit "$ISSUE" --repo "${OWNER}/markethawk" \
            --add-label "$ABOVE_CEILING_LABEL" 2>/dev/null || true
          set_board_status "$ISSUE" "$STATUS_BLOCKED" || true
          gh issue comment "$ISSUE" --repo "${OWNER}/markethawk" --body \
"## Scheduler — Above Dispatch Ceiling

This ticket has been classified as **above the autonomous dispatch ceiling** \
(size: XL, or size: M with a perf/architectural/migration title keyword).

Spec and plan are complete. **A human must pair on implementation.**

To proceed:
1. Remove the \`$ABOVE_CEILING_LABEL\` label.
2. Dispatch manually:
   \`\`\`bash
   docker compose --profile factory run --rm dark-factory \"Fix issue #${ISSUE}\"
   \`\`\`
   Or implement directly in a local worktree.

---
*Posted by MarketHawk Backlog Scheduler*" 2>/dev/null || true
        fi
        continue
      fi

      if dispatch "Fix issue #${ISSUE}"; then
        DISPATCHED="Fix issue #${ISSUE}"
      fi
    done < <(echo "$READY" | jq -c '.[]')
  fi

  # --- Priority 3: Blocked items (retry stuck work) ---
  if [ "$MAIN_IS_RED" = "true" ]; then
    echo "[$(date -u +%FT%TZ)] main_red_gate=skip_blocked_retry"
  else
    while IFS= read -r item; do
      [ -n "$DISPATCHED" ] && break
      ISSUE=$(get_issue_number "$item")
      if has_skip_label "$item"; then continue; fi
      # Promoted to In review by the Priority 0.6 rescue this cycle — don't re-dispatch
      # (its green PR is now in the merge flow; BLOCKED was snapshotted before the move).
      case "$RESCUED" in *" $ISSUE "*) continue ;; esac
      # Above-ceiling items in Blocked are parked by design (#339), not failed — the
      # retry loop must not auto-dispatch them.
      if has_above_ceiling_label "$item"; then continue; fi
      if is_issue_running "$ISSUE"; then continue; fi

      RETRIES=$(get_retry_count "$ISSUE")
      if [ "$RETRIES" -ge "$MAX_RETRIES" ]; then
        trip_to_blocked "$ISSUE" "implement" "retry limit of ${MAX_RETRIES} reached"
        continue
      fi

      increment_retry "$ISSUE"
      # Branch-aware: a blocked item that already has a PR (e.g. red CI gated above, or a
      # continue run that failed mid-way) must be CONTINUED to reuse the existing branch.
      # Dispatching "Fix" would start a fresh branch that collides with the PR on push.
      if [ -n "$(get_pr_for_issue "$ISSUE")" ]; then
        if dispatch "Continue issue #${ISSUE}"; then
          DISPATCHED="Continue issue #${ISSUE}"
        fi
      else
        if dispatch "Fix issue #${ISSUE}"; then
          DISPATCHED="Fix issue #${ISSUE}"
        fi
      fi
    done < <(echo "$BLOCKED" | jq -c '.[]')
  fi

  # --- Priority 4: Refined items (plan generation — advance refined work before pulling new backlog) ---
  while IFS= read -r item; do
    [ -n "$DISPATCHED" ] && break
    ISSUE=$(get_issue_number "$item")

    # Direct-to-PR plan auto-advance: handle before refine_skip_label blocks plan-pending-review
    if echo "$item" | jq -r '.labels[]?' 2>/dev/null | grep -qi "plan-pending-review" \
       && has_direct_to_pr_label "$item"; then
      if ! is_issue_running "$ISSUE" && [ "$REFINE_RUNNING" -lt "$REFINE_WIP_LIMIT" ]; then
        plan_advance_check "$ISSUE" "$item"
      fi
      continue
    fi

    if has_refine_skip_label "$item"; then continue; fi
    if is_issue_running "$ISSUE"; then continue; fi
    if [ "$REFINE_RUNNING" -ge "$REFINE_WIP_LIMIT" ]; then break; fi

    RETRIES=$(get_retry_count "${ISSUE}:plan")
    if [ "$RETRIES" -ge "$REFINE_MAX_RETRIES" ]; then
      trip_to_blocked "$ISSUE" "plan" "retry limit of ${REFINE_MAX_RETRIES} reached"
      continue
    fi

    increment_retry "${ISSUE}:plan"
    gh issue comment "$ISSUE" --repo "${OWNER}/markethawk" --body "📋 **Refinement Pipeline** — Starting plan generation and architect validation.

---
*Posted by MarketHawk Backlog Scheduler*" 2>/dev/null || true
    if dispatch "Plan issue #${ISSUE}"; then
      DISPATCHED="Plan issue #${ISSUE}"
      REFINE_RUNNING=$((REFINE_RUNNING + 1))
    fi
  done < <(echo "$REFINED" | jq -c '.[]')

  # --- Priority 5: Backlog items (refinement — prepare future work) ---
  while IFS= read -r item; do
    [ -n "$DISPATCHED" ] && break
    ISSUE=$(get_issue_number "$item")

    # Handle spec-pending-review items first (before skip-label check would filter them)
    ITEM_LABELS=$(echo "$item" | jq -r '.labels[]?' 2>/dev/null)
    if echo "$ITEM_LABELS" | grep -qi "spec-pending-review"; then
      if ! is_issue_running "$ISSUE" && [ "$REFINE_RUNNING" -lt "$REFINE_WIP_LIMIT" ]; then
        spec_advance_check "$ISSUE" "$item"
      fi
      continue
    fi

    if has_refine_skip_label "$item"; then continue; fi
    # Opt-in gate: only auto-refine Backlog items labelled ready-for-agent.
    # Unlabelled items are left for triage — humans add the label when the issue is ready.
    if ! has_opt_in_refine_label "$item" && ! has_direct_to_pr_label "$item"; then continue; fi
    if is_issue_running "$ISSUE"; then continue; fi
    if [ "$REFINE_RUNNING" -ge "$REFINE_WIP_LIMIT" ]; then break; fi

    RETRIES=$(get_retry_count "${ISSUE}:refine")
    if [ "$RETRIES" -ge "$REFINE_MAX_RETRIES" ]; then
      trip_to_blocked "$ISSUE" "refine" "retry limit of ${REFINE_MAX_RETRIES} reached"
      continue
    fi

    increment_retry "${ISSUE}:refine"
    gh issue comment "$ISSUE" --repo "${OWNER}/markethawk" --body "🧠 **Refinement Pipeline** — Starting brainstorming and spec generation.

---
*Posted by MarketHawk Backlog Scheduler*" 2>/dev/null || true
    if dispatch "Refine issue #${ISSUE}"; then
      DISPATCHED="Refine issue #${ISSUE}"
      REFINE_RUNNING=$((REFINE_RUNNING + 1))
    fi
  done < <(echo "$BACKLOG" | jq -c '.[]')

  # --- Priority 6: Epic Autopilot (starved self-unlock, #571) ---
  # Runs ONLY when this cycle dispatched nothing (starved), main is green, and it is
  # enabled. Reviews the refined, below-ceiling children of in-progress epics with Opus
  # and advances the low-risk ones via direct-to-pr. Fail-soft: never abort the loop.
  if [ -z "$DISPATCHED" ] && [ "$MAIN_IS_RED" = "false" ] && [ "${EPIC_AUTOPILOT_ENABLED:-false}" = "true" ]; then
    AP_OUT=$(python3 "$FACTORY_CORE_CLI" epic-autopilot --once 2>&1) || true
    echo "[$(date -u +%FT%TZ)] ${AP_OUT}"
    case "$AP_OUT" in *"autopilot=advanced"*|*"autopilot=epic_started"*) DISPATCHED="$AP_OUT" ;; esac
  fi

  # --- Log cycle summary ---
  BUDGET=$(gh api rate_limit --jq '.resources.graphql | "\(.used)/\(.limit)"' 2>/dev/null) || BUDGET="?"
  if [ -n "$DISPATCHED" ]; then
    echo "[$(date -u +%FT%TZ)] backlog=${BACKLOG_COUNT} refined=${REFINED_COUNT} in_progress=${IN_PROGRESS_COUNT}/${MAX_IN_PROGRESS} in_review=${IN_REVIEW_COUNT}/${MAX_IN_REVIEW} factory_running=${FACTORY_RUNNING}/${FACTORY_WIP_LIMIT} refine_running=${REFINE_RUNNING}/${REFINE_WIP_LIMIT} dispatched=\"${DISPATCHED}\" main_red=${MAIN_IS_RED} graphql=${BUDGET}"
  else
    echo "[$(date -u +%FT%TZ)] backlog=${BACKLOG_COUNT} refined=${REFINED_COUNT} in_progress=${IN_PROGRESS_COUNT}/${MAX_IN_PROGRESS} in_review=${IN_REVIEW_COUNT}/${MAX_IN_REVIEW} factory_running=${FACTORY_RUNNING}/${FACTORY_WIP_LIMIT} refine_running=${REFINE_RUNNING}/${REFINE_WIP_LIMIT} skip=nothing_to_do main_red=${MAIN_IS_RED} graphql=${BUDGET}"
  fi

  sleep "$POLL_INTERVAL"
done
